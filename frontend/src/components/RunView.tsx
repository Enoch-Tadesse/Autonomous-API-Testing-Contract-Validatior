import { useState } from "react";
import { ArrowLeft, Loader2, MessageCircleQuestion, Send, XCircle } from "lucide-react";
import { api } from "../lib/api";
import { usePoll } from "../lib/usePoll";
import type { LogEntry, RunDetails, RunStatusBody } from "../lib/types";
import { Linkified, StatusBadge } from "./bits";
import DecisionLog from "./DecisionLog";
import ResultTabs, { type TabId } from "./ResultTabs";

const FINAL = new Set(["complete", "partial", "error"]);
const QUICK_ANSWERS = ["401", "400", "skip"];

function QuestionCard({ id, question, onAnswered, onEvidence }: {
  id: string; question: string; onAnswered: () => void; onEvidence: (id: string) => void;
}) {
  const [answer, setAnswer] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");

  const send = async (text: string) => {
    if (!text.trim()) return;
    setSending(true);
    setError("");
    try {
      await api.resume(id, text.trim());
      onAnswered();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSending(false);
    }
  };

  return (
    <section className="question fade-in" role="region" aria-labelledby="question-title">
      <div className="step-icon tone-cyan" style={{ margin: 0, flex: "none" }}><MessageCircleQuestion size={18} aria-hidden /></div>
      <div className="grow">
        <h2 id="question-title" style={{ fontSize: 14 }}>The agent needs your input</h2>
        <p style={{ margin: "6px 0 0", color: "var(--fg-muted)" }}><Linkified text={question} onOpen={onEvidence} /></p>
        <form onSubmit={(e) => { e.preventDefault(); send(answer); }}>
          <label htmlFor="answer" className="sr-only" style={{ position: "absolute", left: -9999 }}>Your answer</label>
          <input id="answer" className="input grow" value={answer} onChange={(e) => setAnswer(e.target.value)}
            placeholder="e.g. 401, or skip" autoFocus autoComplete="off" />
          <button className="btn btn-primary" type="submit" disabled={sending || !answer.trim()}>
            {sending ? <Loader2 size={16} className="spin" aria-hidden /> : <Send size={16} aria-hidden />} Answer
          </button>
        </form>
        <div className="row wrap" style={{ marginTop: 10 }}>
          <span className="subtle" style={{ fontSize: 12.5 }}>Quick answers:</span>
          {QUICK_ANSWERS.map((a) => (
            <button key={a} type="button" className="btn btn-ghost" style={{ minHeight: 32, padding: "0 10px" }}
              disabled={sending} onClick={() => send(a)}>{a}</button>
          ))}
        </div>
        {error && <p role="alert" style={{ color: "var(--danger)", margin: "8px 0 0" }}>{error}</p>}
      </div>
    </section>
  );
}

export default function RunView({ id }: { id: string }) {
  const [status, setStatus] = useState<RunStatusBody | null>(null);
  const [log, setLog] = useState<LogEntry[]>([]);
  const [details, setDetails] = useState<RunDetails | null>(null);
  const [report, setReport] = useState("");
  const [notFound, setNotFound] = useState(false);
  const [tab, setTab] = useState<TabId>(() => {
    const wanted = new URLSearchParams(window.location.search).get("tab");
    return (["findings", "tasks", "evidence", "report"].includes(wanted ?? "") ? wanted : "findings") as TabId;
  });
  const [selected, setSelected] = useState<string | null>(null);

  const live = !status || !FINAL.has(status.status);

  usePoll(async () => {
    try {
      const [s, trace] = await Promise.all([api.status(id), api.trace(id)]);
      setStatus(s);
      setLog(trace);
      setNotFound(false);
    } catch {
      setNotFound(true);
    }
  }, 1000, live, [id]);

  usePoll(async () => {
    try {
      setDetails(await api.details(id));
      if (status && (status.status === "complete" || status.status === "partial")) setReport(await api.report(id));
    } catch {
      /* the next poll retries */
    }
  }, 2000, live, [id, status?.status]);

  const openEvidence = (evidenceId: string) => {
    setSelected(evidenceId);
    setTab("evidence");
  };

  if (notFound && !status) {
    return (
      <div className="card card-pad fade-in">
        <div className="row"><XCircle size={18} color="var(--danger)" aria-hidden /> <strong>Run {id} not found</strong></div>
        <p className="muted">Runs live in the service's memory, so they disappear when it restarts.</p>
        <a className="btn" href="#/"><ArrowLeft size={16} aria-hidden /> Start a new run</a>
      </div>
    );
  }

  const progress = status && status.tasks_total ? Math.round((status.tasks_done / status.tasks_total) * 100) : 0;
  const tiles: [string, string | number][] = [
    ["tasks", status ? `${status.tasks_done}/${status.tasks_total}` : "–"],
    ["steps", status?.steps ?? "–"],
    ["tool calls", status?.tool_calls ?? "–"],
    ["replans", status?.replans ?? "–"],
    ["findings", status?.findings ?? "–"],
  ];

  return (
    <div className="fade-in">
      <div className="run-header">
        <div className="grow">
          <a href="#/runs" className="nav-link" style={{ paddingLeft: 0, marginBottom: 4 }}><ArrowLeft size={15} aria-hidden /> All runs</a>
          <div className="row wrap">
            <h1 className="mono">{id}</h1>
            {status && <span role="status" aria-atomic="true"><StatusBadge status={status.status} /></span>}
            {status?.stop_reason && <span className="pill tone-amber">stopped by {status.stop_reason}</span>}
          </div>
          <div className="progress" aria-label={`${progress}% of tasks done`}><div style={{ width: `${progress}%` }} /></div>
        </div>
      </div>

      {status?.status === "error" && (
        <div className="alert tone-red" role="alert" style={{ marginBottom: 16 }}>
          <XCircle size={16} aria-hidden /> {status.error}
        </div>
      )}

      {status?.status === "awaiting_input" && status.pending_question && (
        <QuestionCard id={id} question={status.pending_question} onEvidence={openEvidence}
          onAnswered={() => setStatus({ ...status, status: "running", pending_question: null })} />
      )}

      <div className="tiles">
        {tiles.map(([label, value]) => (
          <div className="card tile" key={label}>
            <div className="stat-value">{value}</div>
            <div className="stat-label">{label}</div>
          </div>
        ))}
      </div>

      <div className="run-grid">
        <DecisionLog entries={log} live={live} onEvidence={openEvidence} />
        <ResultTabs tab={tab} setTab={setTab} details={details} report={report} selected={selected} onEvidence={openEvidence} />
      </div>
    </div>
  );
}
