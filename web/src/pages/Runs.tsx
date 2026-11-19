import { useEffect, useRef, useState } from "react";
import { ago, api, duration } from "../api";
import type { LogEntry, Run } from "../types";

export function LogView({ log, follow = false }: { log: LogEntry[]; follow?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (follow && ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [log.length, follow]);
  return (
    <div className="log" ref={ref}>
      {log.length === 0 && <div className="muted">No log entries.</div>}
      {log.map((e, i) => (
        <div key={i} className={e.type}>
          {e.type === "tool" ? `▸ ${e.name} ${e.input ?? ""}`
            : e.type === "result" ? `■ result: ${e.outcome ?? e.error ?? e.subtype} · ${e.turns ?? "?"} turns`
            : e.type === "rate_limit" ? `⏱ usage ${e.status} (${e.kind ?? ""}${e.utilization != null ? `, ${Math.round(Number(e.utilization) * 100)}%` : ""})`
            : e.text}
        </div>
      ))}
    </div>
  );
}

export default function Runs() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [selected, setSelected] = useState<Run | null>(null);

  useEffect(() => {
    api.get<Run[]>("/runs?limit=200").then(setRuns);
  }, []);

  const open = async (id: string) => setSelected(await api.get<Run>(`/runs/${id}`));

  return (
    <div className="grid" style={{ gridTemplateColumns: selected ? "minmax(0,1fr) minmax(0,1fr)" : "1fr" }}>
      <div className="card">
        <h2>Runs</h2>
        <table>
          <thead><tr><th>When</th><th>Card</th><th>Worker</th><th>Outcome</th><th>Took</th><th>Cost*</th></tr></thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.id} className={`clickable ${selected?.id === r.id ? "selected" : ""}`} onClick={() => open(r.id)}>
                <td>{ago(r.started_at)}</td>
                <td>#{r.issue_number}</td>
                <td>{r.worker}</td>
                <td className={r.error ? "err" : ""}>{r.outcome ?? "running…"}</td>
                <td>{duration(r.started_at, r.finished_at)}</td>
                <td className="muted">{r.cost_usd != null ? `$${r.cost_usd.toFixed(2)}` : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="muted" style={{ fontSize: 12 }}>*Equivalent API cost reported by Claude Code. On your Claude plan it counts against usage limits instead of being billed.</p>
      </div>
      {selected && (
        <div className="card">
          <div className="row between">
            <h2>Run {selected.id} · #{selected.issue_number} · {selected.worker}</h2>
            <button className="small" onClick={() => setSelected(null)}>Close</button>
          </div>
          <p>
            Outcome: <b>{selected.outcome ?? "—"}</b>
            {selected.target_status_id && <> → <b>{selected.target_status_id}</b></>}
          </p>
          {selected.error && <div className="notice err">{selected.error}</div>}
          {selected.summary && (<><h3>Summary</h3><div className="log">{selected.summary}</div></>)}
          <h3>Log</h3>
          <LogView log={selected.log} />
        </div>
      )}
    </div>
  );
}
