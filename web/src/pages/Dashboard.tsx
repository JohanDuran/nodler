import { useEffect, useState } from "react";
import { ago, api, duration } from "../api";
import type { Run, WorkerState } from "../types";
import { LogView } from "./Runs";

export default function Dashboard() {
  const [state, setState] = useState<WorkerState | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const [s, r] = await Promise.all([api.get<WorkerState>("/state"), api.get<Run[]>("/runs?limit=8")]);
        if (alive) { setState(s); setRuns(r); }
      } catch { /* server restarting */ }
    };
    load();
    const id = setInterval(load, 2000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  const control = async (action: string) => setState(await api.post<WorkerState>(`/worker/${action}`));

  if (!state) return <p className="muted">Connecting…</p>;
  const limited = state.paused_until && state.paused_until * 1000 > Date.now();
  return (
    <div className="grid">
      <div className="card">
        <div className="row between">
          <div>
            <h2 style={{ margin: 0 }}>
              Worker:{" "}
              {state.paused ? <span className="warn">paused</span>
                : limited ? <span className="warn">waiting for usage limit reset ({new Date(state.paused_until! * 1000).toLocaleTimeString()})</span>
                : state.current ? <span className="ok">working</span>
                : <span className="ok">idle, watching boards</span>}
            </h2>
            <div className="muted">Last board check: {ago(state.last_tick)}</div>
          </div>
          <div className="row">
            {state.paused
              ? <button className="primary" onClick={() => control("resume")}>Resume</button>
              : <button onClick={() => control("pause")}>Pause</button>}
            <button onClick={() => control("poke")} disabled={state.paused}>Check boards now</button>
          </div>
        </div>
        {state.api_key_in_env && (
          <div className="notice err" style={{ marginTop: 12 }}>
            ANTHROPIC_API_KEY is set in nodler's environment, so runs would be billed to the API instead of your Claude plan.
          </div>
        )}
        {state.last_error && <div className="notice err" style={{ marginTop: 12 }}>{state.last_error}</div>}
        {state.warnings.map((w) => <div key={w} className="notice warn" style={{ marginTop: 12 }}>{w}</div>)}
      </div>

      {state.current && (
        <div className="card">
          <h2>
            Now: #{state.current.issue} {state.current.card}{" "}
            <span className="muted">· {state.current.status} · {state.current.worker} · {duration(state.current.started_at, null)}</span>
          </h2>
          <LogView log={state.current.log} follow />
        </div>
      )}

      <div className="card">
        <h2>Recent runs</h2>
        {runs.length === 0 ? <p className="muted">No runs yet. Add a project, then move an issue to a queued status on its board.</p> : (
          <table>
            <thead><tr><th>When</th><th>Card</th><th>Worker</th><th>Outcome</th><th>Duration</th></tr></thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.id} className="clickable" onClick={() => (window.location.hash = "runs")}>
                  <td>{ago(r.started_at)}</td>
                  <td>#{r.issue_number}</td>
                  <td>{r.worker}</td>
                  <td className={r.error ? "err" : ""}>{r.outcome ?? "running…"}</td>
                  <td>{duration(r.started_at, r.finished_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
