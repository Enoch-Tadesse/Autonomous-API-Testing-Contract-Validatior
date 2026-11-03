import { useEffect, useRef, useState } from "react";
import { Terminal } from "lucide-react";
import type { LogEntry } from "../lib/types";
import { Empty, Linkified } from "./bits";

interface Badge { label: string; tone: string }

/** The agentic moments worth highlighting in the trace. */
function badgeFor(e: LogEntry): Badge | null {
  if (e.node === "ask_user") return { label: "asked", tone: "tone-cyan" };
  if (e.node === "reporter") return { label: e.decision.toLowerCase(), tone: e.decision === "PARTIAL" ? "tone-amber" : "tone-green" };
  if (e.decision === "replan") return { label: "replan", tone: "tone-violet" };
  if (e.decision === "fallback") return { label: "fallback", tone: "tone-cyan" };
  if (e.decision === "blocked" || e.decision.startsWith("blocked")) return { label: "blocked", tone: "tone-red" };
  if (e.decision.endsWith(":rerun") || e.decision.startsWith("rerun_")) return { label: "rerun", tone: "tone-amber" };
  if (e.decision === "apply_answer") return { label: "answer", tone: "tone-cyan" };
  if (e.decision === "switch_tool" || e.decision === "skip_task") return { label: "tool switch", tone: "tone-cyan" };
  if (e.decision.endsWith(":replan")) return { label: "confirmed", tone: "tone-red" };
  if (e.decision.startsWith("api_defect")) return { label: "defect", tone: "tone-red" };
  if (e.decision.endsWith(":retry") || e.decision === "repair_request") return { label: "retry", tone: "tone-amber" };
  if (e.reason.includes("retry 1/")) return { label: "retry", tone: "tone-amber" };
  if (e.decision.startsWith("infra_failure")) return { label: "infra", tone: "tone-amber" };
  if (e.decision === "plan" || e.decision === "add_lookup" || e.decision === "add_check") return { label: "plan", tone: "tone-violet" };
  if (e.decision === "read_docs" || e.decision === "call_read_file") return { label: "docs", tone: "tone-cyan" };
  if (e.decision === "call_run_python") return { label: "compute", tone: "tone-violet" };
  if (e.decision.startsWith("llm_")) return { label: "llm critique", tone: "tone-blue" };
  return null;
}


export default function DecisionLog({ entries, live, onEvidence }: {
  entries: LogEntry[];
  live: boolean;
  onEvidence: (id: string) => void;
}) {
  const [keyOnly, setKeyOnly] = useState(true);
  const [follow, setFollow] = useState(true);
  const box = useRef<HTMLDivElement>(null);
  // "Key events" = the agentic moments (plan, retry, rerun, defect, replan, fallback, ask, report).
  const shown = keyOnly ? entries.filter((e) => badgeFor(e) !== null) : entries;

  useEffect(() => {
    if (follow && live && box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [shown.length, follow, live]);

  return (
    <section className="card" aria-labelledby="log-title">
      <div className="card-header">
        <h2 id="log-title" className="card-title">
          <Terminal size={16} aria-hidden /> Decision log
          <span className="subtle mono" style={{ fontWeight: 400, fontSize: 12 }}>{entries.length} entries</span>
        </h2>
        <div className="row">
          <label className="row subtle" style={{ fontSize: 12.5, cursor: "pointer" }}>
            <input type="checkbox" checked={keyOnly} onChange={(e) => setKeyOnly(e.target.checked)} /> key events
          </label>
          {live && (
            <label className="row subtle hide-sm" style={{ fontSize: 12.5, cursor: "pointer" }}>
              <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} /> follow
            </label>
          )}
        </div>
      </div>
      <div className="console" ref={box} aria-live="off">
        {shown.length === 0 ? (
          <Empty icon={<Terminal size={20} />} title="Waiting for the first step">The planner is reading the spec.</Empty>
        ) : (
          shown.map((e) => {
            const badge = badgeFor(e);
            return (
              <div key={e.step} className={`log-row ${badge ? "key" : ""}`}>
                <span className="log-step">{String(e.step).padStart(2, "0")}</span>
                <span className={`log-node node-${e.node}`}>{e.node === "ask_user" ? "ask" : e.node}</span>
                <span className="log-text">
                  {badge && <span className={`log-badge ${badge.tone}`}>{badge.label}</span>}
                  <span className="log-decision">{e.decision}</span>
                  <Linkified text={e.reason} onOpen={onEvidence} />
                </span>
              </div>
            );
          })
        )}
      </div>
    </section>
  );
}
