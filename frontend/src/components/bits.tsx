import { Fragment, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { RunStatus } from "../lib/types";

const STATUS: Record<RunStatus, { label: string; tone: string; live?: boolean }> = {
  running: { label: "Running", tone: "tone-blue", live: true },
  awaiting_input: { label: "Waiting for you", tone: "tone-cyan", live: true },
  complete: { label: "Complete", tone: "tone-green" },
  partial: { label: "Partial", tone: "tone-amber" },
  error: { label: "Error", tone: "tone-red" },
};

export function StatusBadge({ status }: { status: RunStatus }) {
  const s = STATUS[status] ?? STATUS.error;
  return (
    <span className={`pill ${s.tone}`}>
      <span className={`dot ${s.live ? "pulse" : ""}`} aria-hidden />
      {s.label}
    </span>
  );
}

export const OUTCOME_TONE: Record<string, string> = {
  pass: "tone-green",
  defect: "tone-red",
  inconclusive: "tone-amber",
  unknown: "tone-grey",
};

export function EvidenceLink({ id, onOpen }: { id: string; onOpen: (id: string) => void }) {
  return (
    <button type="button" className="ev-link" onClick={() => onOpen(id)} aria-label={`Open evidence ${id}`}>
      {id}
    </button>
  );
}

const EVIDENCE_ID = /\b(e_\d{3,})\b/g;

/** Plain text with every evidence id (e_001) turned into a clickable link. */
export function Linkified({ text, onOpen }: { text: string; onOpen: (id: string) => void }) {
  const parts = text.split(EVIDENCE_ID);
  return (
    <>
      {parts.map((part, i) =>
        i % 2 === 1 ? <EvidenceLink key={i} id={part} onOpen={onOpen} /> : <Fragment key={i}>{part}</Fragment>,
      )}
    </>
  );
}

/** Markdown (reports, eval) where citations like [e_007] open the evidence panel. */
export function Markdown({ source, onEvidence }: { source: string; onEvidence?: (id: string) => void }) {
  const withLinks = onEvidence ? source.replace(/\[(e_\d{3,})\]/g, "[$1](#ev:$1)") : source;
  return (
    <div className="md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children }) => {
            if (href?.startsWith("#ev:") && onEvidence) {
              const id = href.slice(4);
              return <EvidenceLink id={id} onOpen={onEvidence} />;
            }
            return <a href={href} target={href?.startsWith("#") ? undefined : "_blank"} rel="noreferrer">{children}</a>;
          },
        }}
      >
        {withLinks}
      </ReactMarkdown>
    </div>
  );
}

export function Empty({ icon, title, children }: { icon: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <div className="empty-icon" aria-hidden>{icon}</div>
      <strong style={{ color: "var(--fg)" }}>{title}</strong>
      {children && <span style={{ fontSize: 13.5 }}>{children}</span>}
    </div>
  );
}

export function timeAgo(seconds: number | null): string {
  if (!seconds) return "";
  const diff = Math.max(0, Date.now() / 1000 - seconds);
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
  return new Date(seconds * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
