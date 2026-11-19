import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Background, Controls, Handle, MarkerType, Position, ReactFlow,
  type Connection, type Edge, type Node, type NodeChange, type NodeProps,
} from "@xyflow/react";
import { api, errorText } from "../api";
import type { Agent, Catalog, Rule, Status, StatusKind, Transition, Workflow } from "../types";

interface Validation { errors: string[]; warnings: string[]; outcomes: Record<string, string[]> }
type NodeData = { status: Status; detail: string; loops: string[]; selected: boolean };

function StatusNode({ data }: NodeProps<Node<NodeData>>) {
  const s = data.status;
  return (
    <div className={`node k-${s.kind} ${data.selected ? "selected" : ""}`}>
      <Handle id="l" type="target" position={Position.Left} />
      <Handle id="bt" type="target" position={Position.Bottom} style={{ left: "35%" }} />
      <div className="name">{s.name}</div>
      <div className="sub">{data.detail}</div>
      {data.loops.map((o) => <div key={o} className="sub">↺ {o}</div>)}
      <Handle id="r" type="source" position={Position.Right} />
      <Handle id="bs" type="source" position={Position.Bottom} style={{ left: "65%" }} />
    </div>
  );
}
const nodeTypes = { status: StatusNode };

const uid = (p: string) => `${p}${Math.random().toString(36).slice(2, 8)}`;
const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || uid("s");

export default function WorkflowEditor() {
  const [list, setList] = useState<Workflow[]>([]);
  const [wf, setWf] = useState<Workflow | null>(null);
  const [versions, setVersions] = useState<{ version: number }[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [check, setCheck] = useState<Validation>({ errors: [], warnings: [], outcomes: {} });
  const [selected, setSelected] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [message, setMessage] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const latest = versions[0]?.version;
  const readOnly = !!wf && latest !== undefined && wf.version !== latest;

  const load = useCallback(async (id: string, version?: number) => {
    const res = await api.get<{ workflow: Workflow; versions: { version: number }[] }>(
      `/workflows/${id}${version ? `?version=${version}` : ""}`,
    );
    setWf(res.workflow); setVersions(res.versions); setDirty(false); setSelected(null);
  }, []);

  useEffect(() => {
    (async () => {
      const [wfs, ags, cat] = await Promise.all([
        api.get<Workflow[]>("/workflows"), api.get<Agent[]>("/agents"), api.get<Catalog>("/catalog"),
      ]);
      setList(wfs); setAgents(ags); setCatalog(cat);
      if (wfs[0]) await load(wfs[0].id);
    })();
  }, [load]);

  // Server-side validation (also tells us which outcomes each status can produce).
  useEffect(() => {
    if (!wf) return;
    const t = setTimeout(() => {
      api.post<Validation>("/workflows/validate", wf).then(setCheck).catch(() => {});
    }, 250);
    return () => clearTimeout(t);
  }, [wf]);

  const update = (fn: (w: Workflow) => Workflow) => {
    if (readOnly) return;
    setWf((w) => (w ? fn(structuredClone(w)) : w));
    setDirty(true); setMessage(null);
  };

  const agentName = (id?: string | null) => agents.find((a) => a.id === id)?.name ?? id ?? "?";
  const statusName = (id: string | null) => wf?.statuses.find((s) => s.id === id)?.name ?? id ?? "?";

  const nodes: Node<NodeData>[] = useMemo(() => (wf?.statuses ?? []).map((s) => ({
    id: s.id, type: "status", position: { x: s.x, y: s.y },
    data: {
      status: s,
      selected: s.id === selected,
      detail: s.kind === "agent" ? `agent · ${agentName(s.agent_id)}` : s.kind === "action" ? `action · ${s.action}` : s.kind,
      loops: (wf?.transitions ?? []).filter((t) => t.source === s.id && t.target === s.id).map((t) => t.outcome),
    },
  })), [wf, selected, agents]); // eslint-disable-line react-hooks/exhaustive-deps

  const edges: Edge[] = useMemo(() => {
    const pos = new Map((wf?.statuses ?? []).map((s) => [s.id, s]));
    let back = 0;
    return (wf?.transitions ?? []).filter((t) => t.source !== t.target).map((t) => {
      const a = pos.get(t.source), b = pos.get(t.target);
      // Rework/escalation edges (going left or down) run underneath the nodes so they don't hide forward arrows.
      const under = !!a && !!b && (b.x < a.x - 20 || b.y > a.y + 60);
      return {
        id: t.id, source: t.source, target: t.target,
        sourceHandle: under ? "bs" : "r", targetHandle: under ? "bt" : "l",
        type: under ? "smoothstep" : "default",
        pathOptions: under ? { offset: 24 + 14 * (back++ % 4), borderRadius: 10 } : undefined,
        label: t.outcome + (t.effects.length ? ` ⚡${t.effects.join(",")}` : ""),
        labelBgPadding: [4, 2] as [number, number],
        markerEnd: { type: MarkerType.ArrowClosed },
        animated: under,
      };
    });
  }, [wf]);

  const onNodesChange = (changes: NodeChange[]) => {
    for (const c of changes) {
      if (c.type === "position" && c.position) {
        const { x, y } = c.position;
        update((w) => { const s = w.statuses.find((s) => s.id === c.id)!; s.x = Math.round(x); s.y = Math.round(y); return w; });
      }
    }
  };

  const onConnect = (c: Connection) => {
    if (!wf || !c.source || !c.target) return;
    const handled = new Set(wf.transitions.filter((t) => t.source === c.source).map((t) => t.outcome));
    const outcome = (check.outcomes[c.source] ?? []).find((o) => !handled.has(o));
    if (!outcome) {
      setMessage({ kind: "err", text: `Every outcome of '${statusName(c.source)}' already has a transition. Change one in the side panel.` });
      return;
    }
    update((w) => { w.transitions.push({ id: uid("t"), source: c.source!, target: c.target!, outcome, effects: [] }); return w; });
    setSelected(c.source);
  };

  const setTarget = (source: string, outcome: string, target: string) => update((w) => {
    const existing = w.transitions.find((t) => t.source === source && t.outcome === outcome);
    if (!target) w.transitions = w.transitions.filter((t) => t !== existing);
    else if (existing) existing.target = target;
    else w.transitions.push({ id: uid("t"), source, outcome, target, effects: [] });
    return w;
  });

  const toggleEffect = (t: Transition, effect: string) => update((w) => {
    const tr = w.transitions.find((x) => x.id === t.id)!;
    tr.effects = tr.effects.includes(effect) ? tr.effects.filter((e) => e !== effect) : [...tr.effects, effect];
    return w;
  });

  const addStatus = () => {
    const name = prompt("Name of the new status (must match a Status option on the board):");
    if (!name || !wf) return;
    let id = slug(name);
    if (wf.statuses.some((s) => s.id === id)) id = uid(id + "-");
    update((w) => { w.statuses.push({ id, name, kind: "human", x: 100, y: 320 }); return w; });
    setSelected(id);
  };

  const removeStatus = (id: string) => {
    if (!confirm(`Delete status '${statusName(id)}' and its transitions/rules?`)) return;
    update((w) => {
      w.statuses = w.statuses.filter((s) => s.id !== id);
      w.transitions = w.transitions.filter((t) => t.source !== id && t.target !== id);
      w.rules = w.rules.filter((r) => r.status !== id && r.target !== id);
      return w;
    });
    setSelected(null);
  };

  const save = async () => {
    if (!wf) return;
    try {
      const res = await api.put<{ workflow: Workflow; warnings: string[] }>(`/workflows/${wf.id}`, wf);
      await load(res.workflow.id);
      setList(await api.get<Workflow[]>("/workflows"));
      setMessage({ kind: "ok", text: `Saved as version ${res.workflow.version}. Cards already in progress keep the version they started with.` });
    } catch (e) {
      setMessage({ kind: "err", text: errorText(e) });
    }
  };

  const duplicate = async () => {
    if (!wf) return;
    const name = prompt("Name for the new workflow:", `${wf.name} (copy)`);
    if (!name) return;
    const copy = { ...structuredClone(wf), id: slug(name), name, version: 1 };
    try {
      await api.put(`/workflows/${copy.id}`, copy);
      setList(await api.get<Workflow[]>("/workflows"));
      await load(copy.id);
    } catch (e) { setMessage({ kind: "err", text: errorText(e) }); }
  };

  if (!wf || !catalog) return <p className="muted">Loading…</p>;
  const sel = wf.statuses.find((s) => s.id === selected) ?? null;

  return (
    <div className="wf">
      <div className="canvas">
        <div className="wf-toolbar">
          <select style={{ width: 220 }} value={wf.id} onChange={(e) => load(e.target.value)}>
            {list.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
          </select>
          <select style={{ width: 130 }} value={wf.version} onChange={(e) => load(wf.id, Number(e.target.value))}>
            {versions.map((v) => <option key={v.version} value={v.version}>v{v.version}{v.version === latest ? " (latest)" : ""}</option>)}
          </select>
          <button onClick={addStatus} disabled={readOnly}>+ Status</button>
          <button onClick={duplicate}>Duplicate</button>
          <button className="primary" onClick={save} disabled={readOnly || !dirty || check.errors.length > 0}>
            Save{dirty ? " *" : ""}
          </button>
          {readOnly && <span className="badge warn">old version · read-only</span>}
        </div>
        <ReactFlow
          nodes={nodes} edges={edges} nodeTypes={nodeTypes}
          onNodesChange={onNodesChange} onConnect={onConnect}
          onNodeClick={(_, n) => setSelected(n.id)} onPaneClick={() => setSelected(null)}
          onEdgeClick={(_, e) => setSelected(e.source)}
          nodesDraggable={!readOnly} nodesConnectable={!readOnly}
          fitView fitViewOptions={{ padding: 0.3 }}
        >
          <Background /><Controls />
        </ReactFlow>
      </div>

      <div className="side card">
        {message && <div className={`notice ${message.kind === "ok" ? "" : "err"}`}>{message.text}</div>}
        {check.errors.map((e) => <div key={e} className="notice err">{e}</div>)}
        {check.warnings.map((w) => <div key={w} className="notice warn">{w}</div>)}

        {sel ? (
          <StatusPanel
            status={sel} wf={wf} agents={agents} catalog={catalog} outcomes={check.outcomes[sel.id] ?? []}
            readOnly={readOnly} statusName={statusName}
            onChange={(fn) => update((w) => { fn(w.statuses.find((s) => s.id === sel.id)!); return w; })}
            onTarget={setTarget} onEffect={toggleEffect} onRemove={() => removeStatus(sel.id)}
          />
        ) : (
          <WorkflowPanel wf={wf} readOnly={readOnly} update={update} statusName={statusName} />
        )}
      </div>
    </div>
  );
}

function StatusPanel(props: {
  status: Status; wf: Workflow; agents: Agent[]; catalog: Catalog; outcomes: string[]; readOnly: boolean;
  statusName: (id: string | null) => string;
  onChange: (fn: (s: Status) => void) => void;
  onTarget: (source: string, outcome: string, target: string) => void;
  onEffect: (t: Transition, effect: string) => void;
  onRemove: () => void;
}) {
  const { status: s, wf, agents, catalog, outcomes, readOnly } = props;
  const worked = s.kind === "agent" || s.kind === "action";
  return (
    <>
      <div className="row between"><h2 style={{ margin: 0 }}>Status</h2>
        <button className="small danger" onClick={props.onRemove} disabled={readOnly}>Delete</button></div>
      <p className="muted" style={{ marginTop: 4 }}>The name must match a Status option on the GitHub board.</p>
      <label className="field">Name
        <input value={s.name} disabled={readOnly} onChange={(e) => props.onChange((x) => { x.name = e.target.value; })} />
      </label>
      <label className="field">Who works on cards here?
        <select value={s.kind} disabled={readOnly} onChange={(e) => props.onChange((x) => {
          x.kind = e.target.value as StatusKind;
          if (x.kind === "agent") x.agent_id = x.agent_id ?? agents[0]?.id; else x.agent_id = null;
          if (x.kind === "action") x.action = x.action ?? Object.keys(catalog.actions)[0]; else x.action = null;
        })}>
          <option value="agent">An agent</option>
          <option value="action">A built-in action (plain code)</option>
          <option value="human">A human (nodler doesn't touch it)</option>
          <option value="done">Nobody: finished</option>
        </select>
      </label>
      {s.kind === "agent" && (
        <label className="field">Agent
          <select value={s.agent_id ?? ""} disabled={readOnly} onChange={(e) => props.onChange((x) => { x.agent_id = e.target.value; })}>
            {agents.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
        </label>
      )}
      {s.kind === "action" && (
        <label className="field">Action
          <select value={s.action ?? ""} disabled={readOnly} onChange={(e) => props.onChange((x) => { x.action = e.target.value; })}>
            {Object.entries(catalog.actions).map(([k, v]) => <option key={k} value={k}>{k}: {v.description}</option>)}
          </select>
        </label>
      )}

      {worked && (
        <>
          <h3>When the outcome is… move the card to</h3>
          {outcomes.length === 0 && <p className="muted">This worker declares no outcomes.</p>}
          {outcomes.map((o) => {
            const t = wf.transitions.find((t) => t.source === s.id && t.outcome === o);
            return (
              <div key={o} className="outcome-row">
                <span className="mono">{o}</span>
                <select value={t?.target ?? ""} disabled={readOnly} onChange={(e) => props.onTarget(s.id, o, e.target.value)}>
                  <option value="">— fallback ({props.statusName(wf.fallback_status)})</option>
                  {wf.statuses.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
                </select>
                {t && (
                  <div className="effects checks">
                    {Object.entries(catalog.effects).map(([e, desc]) => (
                      <label key={e} title={desc}>
                        <input type="checkbox" checked={t.effects.includes(e)} disabled={readOnly} onChange={() => props.onEffect(t, e)} /> {e}
                      </label>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
          <p className="muted" style={{ fontSize: 12 }}>
            Effects run before the move: <b>open_pr</b> pushes the branch and opens/updates the PR, <b>post_review</b> posts the
            agent's summary on the PR, <b>comment</b> posts it on the issue. A failed run (crash) is handled by the error rules.
          </p>
        </>
      )}
    </>
  );
}

function WorkflowPanel({ wf, readOnly, update, statusName }: {
  wf: Workflow; readOnly: boolean; update: (fn: (w: Workflow) => Workflow) => void; statusName: (id: string | null) => string;
}) {
  const setRule = (id: string, patch: Partial<Rule>) =>
    update((w) => { Object.assign(w.rules.find((r) => r.id === id)!, patch); return w; });
  const human = wf.statuses.filter((s) => s.kind === "human");
  return (
    <>
      <h2>Workflow</h2>
      <p className="muted" style={{ marginTop: 0 }}>Click a status to edit it and wire its outcomes. Drag from a status's right handle to another to add a transition.</p>
      <label className="field">Name
        <input value={wf.name} disabled={readOnly} onChange={(e) => update((w) => { w.name = e.target.value; return w; })} />
      </label>
      <label className="field">Fallback status (unknown outcome or no transition)
        <select value={wf.fallback_status} disabled={readOnly} onChange={(e) => update((w) => { w.fallback_status = e.target.value; return w; })}>
          {(human.length ? human : wf.statuses).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
      </label>

      <h3>Rules</h3>
      {wf.rules.map((r) => (
        <div key={r.id} className="card" style={{ padding: 10, marginBottom: 8 }}>
          <div className="row">
            <select style={{ flex: 1 }} value={r.type} disabled={readOnly} onChange={(e) => setRule(r.id, { type: e.target.value as Rule["type"] })}>
              <option value="max_visits">Max times a card may enter</option>
              <option value="max_errors">Max consecutive run errors in</option>
            </select>
            <button className="small danger" disabled={readOnly}
              onClick={() => update((w) => { w.rules = w.rules.filter((x) => x.id !== r.id); return w; })}>✕</button>
          </div>
          <div className="row" style={{ marginTop: 6 }}>
            <select style={{ flex: 1 }} value={r.status ?? ""} disabled={readOnly} onChange={(e) => setRule(r.id, { status: e.target.value || null })}>
              <option value="">any status</option>
              {wf.statuses.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
            <input type="number" min={1} style={{ width: 70 }} value={r.limit} disabled={readOnly}
              onChange={(e) => setRule(r.id, { limit: Math.max(1, Number(e.target.value)) })} />
          </div>
          <div className="row" style={{ marginTop: 6 }}>
            <span className="muted">then move to</span>
            <select style={{ flex: 1 }} value={r.target} disabled={readOnly} onChange={(e) => setRule(r.id, { target: e.target.value })}>
              {wf.statuses.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </div>
          <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
            {r.type === "max_visits"
              ? `Entering ${r.status ? `'${statusName(r.status)}'` : "any status"} more than ${r.limit} times sends the card to '${statusName(r.target)}'.`
              : `After ${r.limit} errors in a row, the card goes to '${statusName(r.target)}'; before that it is retried.`}
          </div>
        </div>
      ))}
      <button disabled={readOnly} onClick={() => update((w) => {
        w.rules.push({ id: uid("r"), type: "max_visits", status: null, limit: 3, target: w.fallback_status });
        return w;
      })}>+ Rule</button>
    </>
  );
}
