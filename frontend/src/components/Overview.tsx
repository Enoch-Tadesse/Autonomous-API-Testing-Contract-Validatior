import { useEffect, useState } from "react";
import { ClipboardList, FileCheck2, Play, ScanSearch } from "lucide-react";
import { api } from "../lib/api";
import type { DemoInfo } from "../lib/types";
import Mermaid from "./Mermaid";
import NewRunPanel from "./NewRunPanel";

interface EvalNumbers {
  passed: string;
  detection: string;
  falsePositives: string;
  citations: string;
}

function parseEval(md: string): EvalNumbers {
  const pick = (re: RegExp) => md.match(re)?.[1] ?? "–";
  const passed = md.match(/\*\*(\d+)\/(\d+) scenarios passed/);
  return {
    passed: passed ? `${passed[1]}/${passed[2]}` : "–",
    detection: pick(/Bug detection rate (\d+%)/),
    falsePositives: pick(/false positives (\d+)/),
    citations: pick(/valid citations (\d+%)/),
  };
}

const STEPS = [
  { icon: ClipboardList, tone: "tone-violet", title: "Plan", text: "Turns the OpenAPI file into a to-do list of contract tests; the LLM orders them by risk." },
  { icon: Play, tone: "tone-blue", title: "Act", text: "Calls the API through guarded tools: allowlisted URLs, retries with backoff, fallbacks." },
  { icon: ScanSearch, tone: "tone-amber", title: "Validate", text: "Deterministic checks on every result, then rerun, retry, replan or ask a human." },
  { icon: FileCheck2, tone: "tone-green", title: "Report", text: "Findings only with evidence ids that exist. Unsupported claims are moved aside." },
];

export default function Overview({ theme, info }: { theme: "dark" | "light"; info: DemoInfo | null }) {
  const [diagram, setDiagram] = useState("");
  const [numbers, setNumbers] = useState<EvalNumbers | null>(null);

  useEffect(() => {
    api.architecture().then(setDiagram).catch(() => setDiagram(""));
    api.evaluation().then((md) => setNumbers(parseEval(md))).catch(() => setNumbers(null));
  }, []);

  const stats: [string, string][] = [
    [numbers?.passed ?? "–", "eval scenarios passed"],
    [numbers?.detection ?? "–", "bug detection"],
    [numbers?.falsePositives ?? "–", "false positives"],
    [numbers?.citations ?? "–", "valid citations"],
  ];

  return (
    <div className="overview fade-in">
      <div className="stack">
        <section className="card hero" aria-labelledby="hero-title">
          <span className="eyebrow">LangGraph agent · API contract testing</span>
          <h1 id="hero-title">
            Finds where an API <span className="hl">breaks its own contract</span>, and proves it.
          </h1>
          <p>
            Give it an OpenAPI file and a base URL. It plans tests, calls the API, validates every response, reruns to
            confirm defects, replans around them, and writes a report where every finding cites its evidence.
          </p>
          <div className="stats" aria-label="Latest evaluation">
            {stats.map(([value, label]) => (
              <div className="stat" key={label}>
                <div className="stat-value">{value}</div>
                <div className="stat-label">{label}</div>
              </div>
            ))}
          </div>
        </section>

        <section className="steps" aria-label="How it works">
          {STEPS.map(({ icon: Icon, tone, title, text }) => (
            <div className="step" key={title}>
              <div className={`step-icon ${tone}`}><Icon size={18} aria-hidden /></div>
              <h3>{title}</h3>
              <p>{text}</p>
            </div>
          ))}
        </section>

        <section className="card" aria-labelledby="arch-title">
          <div className="card-header">
            <h2 id="arch-title" className="card-title">Architecture</h2>
            <span className="subtle hide-sm" style={{ fontSize: 12.5 }}>
              StateGraph · conditional edges · InMemorySaver checkpointer
            </span>
          </div>
          <div className="diagram">
            {diagram ? <Mermaid source={diagram} theme={theme} /> : <span className="subtle">Loading…</span>}
          </div>
        </section>
      </div>

      <aside className="panel-sticky">
        <NewRunPanel info={info} />
      </aside>
    </div>
  );
}
