import { useEffect, useRef } from "react";
import { Bug, FileText, ListTodo, Microscope, ShieldAlert } from "lucide-react";
import type { Evidence, Finding, RunDetails } from "../lib/types";
import { Empty, EvidenceLink, Markdown, OUTCOME_TONE } from "./bits";

export type TabId = "findings" | "tasks" | "evidence" | "report";

const CLASS_LABEL: Record<string, string> = {
  validation: "input validation",
  schema: "response schema",
  server_error: "server error",
  auth: "authentication",
  contract: "contract",
};

function FindingCard({ f, onEvidence }: { f: Finding; onEvidence: (id: string) => void }) {
  return (
    <article className={`finding ${f.status}`}>
      <h3>
        <span className="mono">{f.id}</span>
        <span className={`pill ${f.status === "confirmed" ? "tone-red" : "tone-amber"}`}>{f.status}</span>
        <span className="pill">{CLASS_LABEL[f.class] ?? f.class}</span>
      </h3>
      <dl className="kv">
        <dt>endpoint</dt><dd className="mono">{f.endpoint}</dd>
        <dt>expected</dt><dd>{f.expected}</dd>
        <dt>actual</dt><dd>{f.actual}</dd>
        <dt>repro</dt><dd><code className="code">{f.repro}</code></dd>
        <dt>evidence</dt>
        <dd className="row wrap">{f.evidence_ids.map((id) => <EvidenceLink key={id} id={id} onOpen={onEvidence} />)}</dd>
      </dl>
    </article>
  );
}

function Findings({ details, onEvidence }: { details: RunDetails; onEvidence: (id: string) => void }) {
  if (!details.findings.length && !details.unsupported.length) {
    return <Empty icon={<ShieldAlert size={20} />} title="No findings yet">Confirmed defects appear here with their evidence.</Empty>;
  }
  return (
    <>
      {details.findings.map((f) => <FindingCard key={f.id} f={f} onEvidence={onEvidence} />)}
      {details.unsupported.length > 0 && (
        <>
          <p className="eyebrow" style={{ marginTop: 20 }}>Unsupported (cites missing evidence)</p>
          {details.unsupported.map((f) => <FindingCard key={f.id} f={f} onEvidence={onEvidence} />)}
        </>
      )}
    </>
  );
}

function Tasks({ details }: { details: RunDetails }) {
  if (!details.tasks.length) return <Empty icon={<ListTodo size={20} />} title="Planning…" />;
  return (
    <table className="data">
      <thead><tr><th>Task</th><th>Kind</th><th>Objective</th><th>Expect</th><th>Outcome</th></tr></thead>
      <tbody>
        {details.tasks.map((t) => (
          <tr key={t.id}>
            <td className="mono">{t.id}{t.parent_id && <div className="subtle" style={{ fontSize: 11 }}>↳ {t.parent_id}</div>}</td>
            <td><span className="pill">{t.kind}</span></td>
            <td>{t.objective}<div className="subtle mono" style={{ fontSize: 11 }}>{t.endpoint}</div></td>
            <td className="mono">{t.expected_status.join(", ") || "?"}</td>
            <td>
              {t.status === "in_progress" ? <span className="pill tone-blue"><span className="dot pulse" />running</span>
                : <span className={`pill ${OUTCOME_TONE[t.outcome]}`}>{t.status === "pending" ? "pending" : t.outcome}</span>}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function describe(e: Evidence): string {
  if (e.tool === "run_python") return `run_python: ${String(e.request.check ?? "snippet")} check over ${((e.request.inputs as string[]) ?? []).join(", ")}`;
  if (e.tool === "read_file") return `read_file: ${String(e.request.path ?? "")}`;
  if (e.tool !== "http_request") return `${e.tool}: ${JSON.stringify(e.request).slice(0, 80)}`;
  const q = Object.entries(e.request.query ?? {}).map(([k, v]) => `${k}=${v}`).join("&");
  return `${e.request.method ?? "GET"} ${e.request.path ?? ""}${q ? `?${q}` : ""}`;
}

function pretty(body: unknown): string {
  if (typeof body !== "string") return JSON.stringify(body, null, 2);
  try {
    return JSON.stringify(JSON.parse(body), null, 2);
  } catch {
    return body;
  }
}

function EvidenceTab({ details, selected, onSelect }: {
  details: RunDetails; selected: string | null; onSelect: (id: string) => void;
}) {
  const detailRef = useRef<HTMLDivElement>(null);
  const current = details.evidence.find((e) => e.id === selected);
  useEffect(() => {
    detailRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [selected]);

  if (!details.evidence.length) return <Empty icon={<Microscope size={20} />} title="No evidence yet" />;
  return (
    <>
      {current && (
        <div className="evidence-detail fade-in" ref={detailRef}>
          <div className="row wrap" style={{ justifyContent: "space-between" }}>
            <strong className="mono">{current.id} · {current.task_id}</strong>
            <span className="row">
              {current.transient_retries > 0 && <span className="pill tone-amber">{current.transient_retries} retries</span>}
              <span className={`pill ${statusTone(current)}`}>{current.response.status ?? current.response.error ?? "ok"}</span>
            </span>
          </div>
          <div className="mono" style={{ marginTop: 8, fontSize: 12.5 }}>{describe(current)}</div>
          <p className="eyebrow" style={{ margin: "12px 0 0" }}>Response (redacted, max 4 KB)</p>
          <pre>{pretty(current.response.body ?? current.response.output ?? current.response.error ?? "")}</pre>
        </div>
      )}
      <table className="data" style={{ marginTop: current ? 16 : 0 }}>
        <thead><tr><th>Id</th><th>Task</th><th>Request</th><th>Result</th></tr></thead>
        <tbody>
          {details.evidence.map((e) => (
            <tr key={e.id} className={`clickable ${e.id === selected ? "selected" : ""}`} onClick={() => onSelect(e.id)}
              tabIndex={0} onKeyDown={(k) => (k.key === "Enter" || k.key === " ") && onSelect(e.id)}>
              <td className="mono">{e.id}</td>
              <td className="mono subtle">{e.task_id}</td>
              <td className="mono" style={{ fontSize: 12 }}>{describe(e)}</td>
              <td><span className={`pill ${statusTone(e)}`}>{e.response.status ?? e.response.error ?? "ok"}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function statusTone(e: Evidence): string {
  const s = e.response.status;
  if (s == null) return e.response.ok === false || e.response.error ? "tone-amber" : "tone-green";
  if (s >= 500) return "tone-red";
  if (s >= 400) return "tone-blue";
  return "tone-green";
}

export default function ResultTabs({ tab, setTab, details, report, selected, onEvidence }: {
  tab: TabId;
  setTab: (t: TabId) => void;
  details: RunDetails | null;
  report: string;
  selected: string | null;
  onEvidence: (id: string) => void;
}) {
  const tabs: { id: TabId; label: string; icon: typeof Bug; count?: number }[] = [
    { id: "findings", label: "Findings", icon: Bug, count: details?.findings.length },
    { id: "tasks", label: "Tasks", icon: ListTodo, count: details?.tasks.length },
    { id: "evidence", label: "Evidence", icon: Microscope, count: details?.evidence.length },
    { id: "report", label: "Report", icon: FileText },
  ];
  return (
    <section className="card">
      <div className="tabs" role="tablist" aria-label="Run results">
        {tabs.map(({ id, label, icon: Icon, count }) => (
          <button key={id} role="tab" id={`tab-${id}`} aria-selected={tab === id} aria-controls={`panel-${id}`}
            className="tab" onClick={() => setTab(id)}>
            <Icon size={15} aria-hidden /> {label}
            {count !== undefined && <span className="count">{count}</span>}
          </button>
        ))}
      </div>
      <div className="tab-body" role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
        {!details ? <span className="subtle">Loading…</span>
          : tab === "findings" ? <Findings details={details} onEvidence={onEvidence} />
          : tab === "tasks" ? <Tasks details={details} />
          : tab === "evidence" ? <EvidenceTab details={details} selected={selected} onSelect={onEvidence} />
          : report ? <Markdown source={report} onEvidence={onEvidence} />
          : <Empty icon={<FileText size={20} />} title="Report not ready">It is written when the run completes.</Empty>}
      </div>
    </section>
  );
}
