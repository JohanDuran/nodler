import { useEffect, useState } from "react";
import { api, errorText } from "../api";
import type { Agent, Catalog } from "../types";

const blank = (): Agent => ({
  id: "", name: "", description: "", system_prompt: "", model: "sonnet", effort: null,
  tools: ["Read", "Glob", "Grep"], permission_mode: "dontAsk", max_turns: 60, workspace: "read",
  outcomes: [{ name: "done", description: "" }], post_checks: [], blocked_commands: [], include_diff: false,
});

const MODELS = ["opus", "sonnet", "haiku"];

export default function Agents() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [edit, setEdit] = useState<Agent | null>(null);
  const [isNew, setIsNew] = useState(false);
  const [msg, setMsg] = useState<{ kind: string; text: string } | null>(null);

  const reload = async () => setAgents(await api.get<Agent[]>("/agents"));
  useEffect(() => { reload(); api.get<Catalog>("/catalog").then(setCatalog); }, []);

  const set = (patch: Partial<Agent>) => setEdit((a) => (a ? { ...a, ...patch } : a));
  const toggle = (key: "tools" | "post_checks", v: string) =>
    setEdit((a) => a && { ...a, [key]: a[key].includes(v) ? a[key].filter((x) => x !== v) : [...a[key], v] });

  const save = async () => {
    if (!edit) return;
    try {
      const agent = { ...edit, id: edit.id.trim() };
      await api.put(`/agents/${agent.id}`, agent);
      await reload(); setIsNew(false);
      setMsg({ kind: "ok", text: "Saved. Agent changes apply to the next run." });
    } catch (e) { setMsg({ kind: "err", text: errorText(e) }); }
  };

  const remove = async () => {
    if (!edit || !confirm(`Delete agent '${edit.name}'?`)) return;
    try { await api.del(`/agents/${edit.id}`); setEdit(null); await reload(); }
    catch (e) { setMsg({ kind: "err", text: errorText(e) }); }
  };

  return (
    <div className="grid two">
      <div className="card">
        <div className="row between"><h2 style={{ margin: 0 }}>Agents</h2>
          <button className="small" onClick={() => { setEdit(blank()); setIsNew(true); setMsg(null); }}>+ New</button></div>
        <div className="list" style={{ marginTop: 12 }}>
          {agents.map((a) => (
            <button key={a.id} className={edit?.id === a.id && !isNew ? "active" : ""}
              onClick={() => { setEdit(structuredClone(a)); setIsNew(false); setMsg(null); }}>
              <b>{a.name}</b> <span className="muted">· {a.model ?? "default"} · {a.workspace}</span>
              <div className="muted" style={{ fontSize: 12 }}>{a.description}</div>
            </button>
          ))}
        </div>
      </div>

      {edit && catalog ? (
        <div className="card">
          {msg && <div className={`notice ${msg.kind === "err" ? "err" : ""}`}>{msg.text}</div>}
          <div className="row" style={{ alignItems: "flex-start" }}>
            <label className="field" style={{ flex: 1 }}>Id {isNew ? "" : "(fixed)"}
              <input value={edit.id} disabled={!isNew} placeholder="e.g. qa" onChange={(e) => set({ id: e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, "") })} /></label>
            <label className="field" style={{ flex: 2 }}>Name
              <input value={edit.name} onChange={(e) => set({ name: e.target.value })} /></label>
          </div>
          <label className="field">Description
            <input value={edit.description} onChange={(e) => set({ description: e.target.value })} /></label>
          <label className="field">Role prompt (system prompt)
            <textarea style={{ minHeight: 220 }} value={edit.system_prompt} onChange={(e) => set({ system_prompt: e.target.value })} /></label>

          <div className="row" style={{ alignItems: "flex-start" }}>
            <label className="field" style={{ flex: 1 }}>Model
              <input list="models" value={edit.model ?? ""} onChange={(e) => set({ model: e.target.value || null })} />
              <datalist id="models">{MODELS.map((m) => <option key={m} value={m} />)}</datalist></label>
            <label className="field" style={{ flex: 1 }}>Effort
              <select value={edit.effort ?? ""} onChange={(e) => set({ effort: e.target.value || null })}>
                <option value="">default</option>{["low", "medium", "high", "xhigh", "max"].map((x) => <option key={x}>{x}</option>)}
              </select></label>
            <label className="field" style={{ flex: 1 }}>Max turns
              <input type="number" value={edit.max_turns ?? ""} onChange={(e) => set({ max_turns: e.target.value ? Number(e.target.value) : null })} /></label>
          </div>

          <label className="field">Workspace
            <select value={edit.workspace} onChange={(e) => set({ workspace: e.target.value as Agent["workspace"] })}>
              <option value="write">write: works in the card's worktree and may change files</option>
              <option value="read">read: sees the card's worktree, may not change anything</option>
              <option value="none">none: no repository access</option>
            </select></label>

          <h3>Tools (hard limit: the agent can't see any other tool)</h3>
          <div className="checks">
            {catalog.tools.map((t) => (
              <label key={t}><input type="checkbox" checked={edit.tools.includes(t)} onChange={() => toggle("tools", t)} /> {t}</label>
            ))}
          </div>
          {edit.workspace !== "write" && edit.tools.some((t) => ["Edit", "Write", "Bash"].includes(t)) && (
            <div className="notice warn" style={{ marginTop: 8 }}>
              A {edit.workspace} agent with Edit/Write/Bash: edits are blocked by policy, and a post-check of "clean_worktree" will undo and flag any change.
            </div>
          )}

          <h3>Outcomes it can return</h3>
          {edit.outcomes.map((o, i) => (
            <div key={i} className="row" style={{ marginBottom: 6 }}>
              <input style={{ width: 170 }} className="mono" value={o.name}
                onChange={(e) => { const outcomes = [...edit.outcomes]; outcomes[i] = { ...o, name: e.target.value.replace(/\s/g, "_") }; set({ outcomes }); }} />
              <input style={{ flex: 1 }} placeholder="what it means" value={o.description}
                onChange={(e) => { const outcomes = [...edit.outcomes]; outcomes[i] = { ...o, description: e.target.value }; set({ outcomes }); }} />
              <button className="small danger" onClick={() => set({ outcomes: edit.outcomes.filter((_, j) => j !== i) })}>✕</button>
            </div>
          ))}
          <button className="small" onClick={() => set({ outcomes: [...edit.outcomes, { name: "", description: "" }] })}>+ Outcome</button>

          <h3>Post-checks (run by nodler after the agent finishes)</h3>
          <div className="checks">
            {Object.entries(catalog.post_checks).map(([k, d]) => (
              <label key={k} title={d}><input type="checkbox" checked={edit.post_checks.includes(k)} onChange={() => toggle("post_checks", k)} /> {k}</label>
            ))}
          </div>
          <p className="muted" style={{ fontSize: 12 }}>If a check fails, the outcome becomes <span className="mono">check_failed</span>, which you route in the workflow.</p>

          <h3>Context</h3>
          <div className="checks">
            <label><input type="checkbox" checked={edit.include_diff} onChange={(e) => set({ include_diff: e.target.checked })} /> Include the branch diff in the prompt</label>
          </div>
          <label className="field" style={{ marginTop: 10 }}>Extra blocked shell commands (comma separated; git push, gh … are always blocked)
            <input value={edit.blocked_commands.join(", ")}
              onChange={(e) => set({ blocked_commands: e.target.value.split(",").map((x) => x.trim()).filter(Boolean) })} /></label>

          <div className="row" style={{ marginTop: 12 }}>
            <button className="primary" onClick={save} disabled={!edit.id || !edit.name || !edit.outcomes.length}>Save</button>
            {!isNew && <button className="danger" onClick={remove}>Delete</button>}
          </div>
        </div>
      ) : <div className="card muted">Select an agent, or create a new one.</div>}
    </div>
  );
}
