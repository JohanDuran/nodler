import { useEffect, useState } from "react";
import { api, errorText } from "../api";
import type { Project, Workflow } from "../types";

const blank = (): Project => ({
  id: "", name: "", repo: "", board_owner: "@me", board_number: 1, local_path: "", base_branch: "main",
  setup_command: "", test_command: "", workflow_id: "default", context: "", enabled: true,
});

interface Check { name: string; ok: boolean; detail: string }

export default function Projects() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [edit, setEdit] = useState<Project | null>(null);
  const [isNew, setIsNew] = useState(false);
  const [checks, setChecks] = useState<Check[] | null>(null);
  const [msg, setMsg] = useState<{ kind: string; text: string } | null>(null);

  const reload = async () => setProjects(await api.get<Project[]>("/projects"));
  useEffect(() => { reload(); api.get<Workflow[]>("/workflows").then(setWorkflows); }, []);
  const set = (patch: Partial<Project>) => setEdit((p) => (p ? { ...p, ...patch } : p));

  const save = async () => {
    if (!edit) return;
    try {
      await api.put(`/projects/${edit.id}`, edit);
      await reload(); setIsNew(false); setMsg({ kind: "ok", text: "Saved." });
      runCheck(edit.id);
    } catch (e) { setMsg({ kind: "err", text: errorText(e) }); }
  };

  const runCheck = async (id: string) => {
    setChecks(null);
    try { setChecks(await api.post<Check[]>(`/projects/${id}/check`)); }
    catch (e) { setMsg({ kind: "err", text: errorText(e) }); }
  };

  const remove = async () => {
    if (!edit || !confirm(`Remove project '${edit.name}' from nodler? (Nothing on GitHub is deleted.)`)) return;
    await api.del(`/projects/${edit.id}`); setEdit(null); reload();
  };

  return (
    <div className="grid two">
      <div className="card">
        <div className="row between"><h2 style={{ margin: 0 }}>Projects</h2>
          <button className="small" onClick={() => { setEdit(blank()); setIsNew(true); setChecks(null); setMsg(null); }}>+ New</button></div>
        <div className="list" style={{ marginTop: 12 }}>
          {projects.length === 0 && <p className="muted">No projects yet.</p>}
          {projects.map((p) => (
            <button key={p.id} className={edit?.id === p.id && !isNew ? "active" : ""}
              onClick={() => { setEdit(structuredClone(p)); setIsNew(false); setMsg(null); runCheck(p.id); }}>
              <b>{p.name}</b> {!p.enabled && <span className="badge warn">disabled</span>}
              <div className="muted mono" style={{ fontSize: 12 }}>{p.repo} · board #{p.board_number}</div>
            </button>
          ))}
        </div>
      </div>

      {edit ? (
        <div className="card">
          {msg && <div className={`notice ${msg.kind === "err" ? "err" : ""}`}>{msg.text}</div>}
          <div className="row" style={{ alignItems: "flex-start" }}>
            <label className="field" style={{ flex: 1 }}>Id {isNew ? "" : "(fixed)"}
              <input value={edit.id} disabled={!isNew} onChange={(e) => set({ id: e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, "") })} /></label>
            <label className="field" style={{ flex: 2 }}>Name
              <input value={edit.name} onChange={(e) => set({ name: e.target.value })} /></label>
          </div>
          <label className="field">Repository (owner/name)
            <input className="mono" placeholder="JohanDuran/my-app" value={edit.repo} onChange={(e) => set({ repo: e.target.value.trim() })} /></label>
          <div className="row" style={{ alignItems: "flex-start" }}>
            <label className="field" style={{ flex: 2 }}>Board owner (user/org, or @me)
              <input className="mono" value={edit.board_owner} onChange={(e) => set({ board_owner: e.target.value.trim() })} /></label>
            <label className="field" style={{ flex: 1 }}>Board number
              <input type="number" value={edit.board_number} onChange={(e) => set({ board_number: Number(e.target.value) })} /></label>
          </div>
          <label className="field">Local clone path
            <input className="mono" placeholder="C:\Users\you\Projects\my-app" value={edit.local_path} onChange={(e) => set({ local_path: e.target.value })} /></label>
          <div className="row" style={{ alignItems: "flex-start" }}>
            <label className="field" style={{ flex: 1 }}>Base branch
              <input className="mono" value={edit.base_branch} onChange={(e) => set({ base_branch: e.target.value.trim() })} /></label>
            <label className="field" style={{ flex: 2 }}>Test command (run by nodler, empty = none)
              <input className="mono" placeholder="uv run pytest" value={edit.test_command} onChange={(e) => set({ test_command: e.target.value })} /></label>
          </div>
          <label className="field">Setup command (runs once in each new card worktree, e.g. npm ci)
            <input className="mono" placeholder="npm ci" value={edit.setup_command} onChange={(e) => set({ setup_command: e.target.value })} /></label>
          <label className="field">Workflow
            <select value={edit.workflow_id} onChange={(e) => set({ workflow_id: e.target.value })}>
              {workflows.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
            </select></label>
          <label className="field">Project context for every agent (stack, conventions, constraints)
            <textarea value={edit.context} onChange={(e) => set({ context: e.target.value })} /></label>
          <div className="checks"><label>
            <input type="checkbox" checked={edit.enabled} onChange={(e) => set({ enabled: e.target.checked })} /> Enabled (the worker processes this board)
          </label></div>
          <div className="row" style={{ marginTop: 12 }}>
            <button className="primary" onClick={save} disabled={!edit.id || !edit.repo || !edit.local_path}>Save</button>
            {!isNew && <button onClick={() => runCheck(edit.id)}>Re-check</button>}
            {!isNew && <button className="danger" onClick={remove}>Remove</button>}
          </div>

          {!isNew && (
            <>
              <h3>Setup check</h3>
              {checks === null ? <p className="muted">Checking…</p> : (
                <table><tbody>
                  {checks.map((c) => (
                    <tr key={c.name}><td className={c.ok ? "ok" : "err"}>{c.ok ? "✓" : "✗"}</td><td>{c.name}</td>
                      <td className="muted mono" style={{ fontSize: 12 }}>{c.detail}</td></tr>
                  ))}
                </tbody></table>
              )}
            </>
          )}
        </div>
      ) : <div className="card muted">Select a project, or add one.</div>}
    </div>
  );
}
