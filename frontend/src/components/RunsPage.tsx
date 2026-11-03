import { useState } from "react";
import { ChevronRight, ListChecks, Plus } from "lucide-react";
import { api } from "../lib/api";
import { usePoll } from "../lib/usePoll";
import type { RunSummary } from "../lib/types";
import { Empty, StatusBadge, timeAgo } from "./bits";

export default function RunsPage() {
  const [runs, setRuns] = useState<RunSummary[] | null>(null);

  usePoll(async () => {
    try {
      setRuns(await api.runs());
    } catch {
      setRuns([]);
    }
  }, 3000, true);

  return (
    <section className="card fade-in" aria-labelledby="runs-title">
      <div className="card-header">
        <h1 id="runs-title" className="card-title" style={{ fontSize: 16 }}><ListChecks size={18} aria-hidden /> Runs</h1>
        <a className="btn btn-primary" href="#/"><Plus size={16} aria-hidden /> New run</a>
      </div>
      {runs === null ? (
        <p className="card-pad subtle">Loading…</p>
      ) : runs.length === 0 ? (
        <Empty icon={<ListChecks size={20} />} title="No runs yet">Launch one from the Overview page.</Empty>
      ) : (
        <div className="runs-list">
          {runs.map((r) => {
            const switches = [...(r.target?.bugs ?? []), ...(r.target?.faults ?? [])];
            return (
              <a key={r.run_id} className="run-item" href={`#/run/${r.run_id}`}>
                <span className="mono" style={{ fontSize: 13 }}>{r.run_id}</span>
                <span className="grow">
                  <strong style={{ fontSize: 14 }}>{r.label}</strong>
                  <span className="row wrap" style={{ marginTop: 4 }}>
                    {switches.length ? switches.map((s) => <span key={s} className="pill mono" style={{ fontSize: 11 }}>{s}</span>)
                      : <span className="subtle" style={{ fontSize: 12.5 }}>no bugs or faults</span>}
                  </span>
                </span>
                <span className="row">
                  <span className="subtle hide-sm" style={{ fontSize: 12.5 }}>{timeAgo(r.created_at)}</span>
                  <StatusBadge status={r.status} />
                </span>
                <ChevronRight size={18} className="subtle hide-sm" aria-hidden />
              </a>
            );
          })}
        </div>
      )}
    </section>
  );
}
