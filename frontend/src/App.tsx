import { useState } from "react";
import { Activity, FlaskConical, LayoutDashboard, ListChecks, Moon, ShieldCheck, Sun } from "lucide-react";
import { useRoute } from "./lib/router";
import { usePoll } from "./lib/usePoll";
import { api } from "./lib/api";
import type { DemoInfo } from "./lib/types";
import Overview from "./components/Overview";
import RunView from "./components/RunView";
import RunsPage from "./components/RunsPage";
import EvalPage from "./components/EvalPage";

type Theme = "dark" | "light";

function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(() => (document.documentElement.dataset.theme as Theme) || "dark");
  const toggle = () => {
    const next: Theme = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("theme", next);
    } catch {
      /* private mode */
    }
    setTheme(next);
  };
  return [theme, toggle];
}

function ModelPill({ info }: { info: DemoInfo | null }) {
  if (!info) return <span className="pill">connecting…</span>;
  if (!info.model) {
    return (
      <span className="pill tone-amber" title="AGENT_MODEL is not set in .env, runs use the scripted fake LLM">
        <span className="dot" /> fake LLM
      </span>
    );
  }
  const near = info.llm_calls >= info.daily_quota_hint - 4;
  const name = info.model.split(":").pop();
  return (
    <span
      className={`pill ${info.llm_failures ? "tone-amber" : "tone-green"}`}
      title={`${info.llm_calls} model calls since the service started (free tier: ~${info.daily_quota_hint}/day). ` +
        `${info.llm_failures} failed calls used safe defaults.` +
        (info.last_llm_error ? `\nLast error: ${info.last_llm_error}` : "")}
    >
      <span className="dot" /> {name}
      <span className={near ? "" : "subtle"} style={{ fontFamily: "var(--font-mono)" }}>
        · {info.llm_calls}/{info.daily_quota_hint}
      </span>
    </span>
  );
}

export default function App() {
  const route = useRoute();
  const [theme, toggleTheme] = useTheme();
  const [info, setInfo] = useState<DemoInfo | null>(null);
  const [apiDown, setApiDown] = useState(false);

  usePoll(async () => {
    try {
      setInfo(await api.info());
      setApiDown(false);
    } catch {
      setApiDown(true);
    }
  }, 4000, true);

  const nav = [
    { href: "#/", label: "Overview", icon: LayoutDashboard, active: route.page === "overview" },
    { href: "#/runs", label: "Runs", icon: ListChecks, active: route.page === "runs" || route.page === "run" },
    { href: "#/eval", label: "Evaluation", icon: FlaskConical, active: route.page === "eval" },
  ];

  return (
    <div className="shell">
      <header className="topbar">
        <a href="#/" className="brand" style={{ color: "inherit", textDecoration: "none" }} aria-label="Contract Agent home">
          <span className="brand-mark"><ShieldCheck size={18} aria-hidden /></span>
          <span>contract<span style={{ color: "var(--accent)" }}>.agent</span></span>
        </a>
        <nav className="nav" aria-label="Main">
          {nav.map(({ href, label, icon: Icon, active }) => (
            <a key={href} href={href} className="nav-link" aria-current={active ? "page" : undefined}>
              <Icon size={16} aria-hidden />
              <span className="nav-label">{label}</span>
            </a>
          ))}
        </nav>
        <div className="topbar-right">
          {apiDown ? (
            <span className="pill tone-red" role="status"><Activity size={13} aria-hidden /> service offline</span>
          ) : (
            <ModelPill info={info} />
          )}
          <button className="btn btn-ghost btn-icon" onClick={toggleTheme}
            aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}>
            {theme === "dark" ? <Sun size={18} aria-hidden /> : <Moon size={18} aria-hidden />}
          </button>
        </div>
      </header>
      <main className="main">
        {route.page === "overview" && <Overview theme={theme} info={info} />}
        {route.page === "runs" && <RunsPage />}
        {route.page === "run" && <RunView key={route.id} id={route.id} />}
        {route.page === "eval" && <EvalPage />}
      </main>
    </div>
  );
}
