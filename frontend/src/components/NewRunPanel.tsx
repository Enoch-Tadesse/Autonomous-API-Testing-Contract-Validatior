import { useEffect, useState } from "react";
import { AlertTriangle, Check, Loader2, Rocket } from "lucide-react";
import { api } from "../lib/api";
import { go } from "../lib/router";
import { BUGS, FAULTS, PRESETS, type Preset } from "../lib/catalog";
import type { DemoInfo, DemoSpec } from "../lib/types";

function Toggle({ id, title, detail, checked, onChange }: {
  id: string;
  title: string;
  detail: string;
  checked: boolean;
  onChange: (on: boolean) => void;
}) {
  return (
    <label className={`toggle ${checked ? "checked" : ""}`}>
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span className="box" aria-hidden><Check size={13} strokeWidth={3} /></span>
      <span className="grow">
        <span className="t-title" style={{ display: "block" }}>{title}</span>
        <span className="t-detail">{detail}</span>
      </span>
      <span className="t-id hide-sm">{id}</span>
    </label>
  );
}

const SPEC_CHOICES: [string, string][] = [["standard", "Standard"], ["undocumented", "Undocumented"], ["custom", "Paste"]];

export default function NewRunPanel({ info }: { info: DemoInfo | null }) {
  const [specs, setSpecs] = useState<DemoSpec[]>([]);
  const [specId, setSpecId] = useState("standard");
  const [customSpec, setCustomSpec] = useState("");
  const [bugs, setBugs] = useState<string[]>(PRESETS[0].bugs);
  const [faults, setFaults] = useState<string[]>(PRESETS[0].faults);
  const [interactive, setInteractive] = useState(false);
  const [preset, setPreset] = useState<string | null>(PRESETS[0].name);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.specs().then(setSpecs).catch((e: Error) => setError(e.message));
  }, []);

  const applyPreset = (p: Preset) => {
    setPreset(p.name);
    setSpecId(p.spec);
    setBugs(p.bugs);
    setFaults(p.faults);
    setInteractive(p.interactive);
  };
  const flip = (list: string[], id: string, on: boolean) => (on ? [...list, id] : list.filter((x) => x !== id));
  const custom = () => setPreset(null);

  const start = async () => {
    setError("");
    const spec = specId === "custom" ? customSpec : specs.find((s) => s.id === specId)?.text ?? "";
    if (!spec.trim()) {
      setError("Paste an OpenAPI document (YAML or JSON) first.");
      return;
    }
    setBusy(true);
    try {
      const switches = [...bugs, ...faults].map((x) => x.replace(/^(BUG|FAULT)_/, "").toLowerCase());
      const label = preset ?? (switches.join(" + ") || "clean API");
      const { run_id } = await api.start({
        spec,
        label,
        base_url: info?.target_url ?? "http://localhost:9000",
        config: { interactive },
        target: { bugs, faults },
      });
      go(`/run/${run_id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };

  return (
    <section className="card" aria-labelledby="new-run-title">
      <div className="card-header">
        <h2 id="new-run-title" className="card-title"><Rocket size={16} aria-hidden /> New run</h2>
        <span className="subtle mono" style={{ fontSize: 11.5 }}>{info?.target_url ?? ""}</span>
      </div>
      <div className="card-pad">
        <div className="field">
          <span className="field-label">Scenario</span>
          <div className="presets" role="group" aria-label="Scenario presets">
            {PRESETS.map((p) => (
              <button key={p.name} type="button" className="preset" aria-pressed={preset === p.name} onClick={() => applyPreset(p)}>
                <strong>{p.name}</strong>
                <span>{p.blurb}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="field">
          <span className="field-label" id="spec-label">OpenAPI spec</span>
          <div className="segmented" role="group" aria-labelledby="spec-label">
            {SPEC_CHOICES.map(([id, label]) => (
              <button key={id} type="button" aria-pressed={specId === id} onClick={() => { setSpecId(id); custom(); }}>
                {label}
              </button>
            ))}
          </div>
          {specId === "custom" ? (
            <>
              <label htmlFor="spec-text" className="helper">YAML or JSON. Requests still go to the target URL above.</label>
              <textarea id="spec-text" className="spec" value={customSpec} spellCheck={false}
                onChange={(e) => setCustomSpec(e.target.value)} placeholder={"openapi: 3.1.0\npaths: ..."} />
            </>
          ) : (
            <span className="helper">{specs.find((s) => s.id === specId)?.label ?? "Loading specs…"}</span>
          )}
        </div>

        <div className="field">
          <span className="field-label">
            Seeded bugs <span className="subtle" style={{ fontWeight: 400 }}>{bugs.length} on</span>
          </span>
          <div className="toggles">
            {Object.entries(BUGS).map(([id, b]) => (
              <Toggle key={id} id={id} title={b.title} detail={b.detail} checked={bugs.includes(id)}
                onChange={(on) => { setBugs(flip(bugs, id, on)); custom(); }} />
            ))}
          </div>
        </div>

        <div className="field">
          <span className="field-label">
            Faults <span className="subtle" style={{ fontWeight: 400 }}>{faults.length} on</span>
          </span>
          <div className="toggles">
            {Object.entries(FAULTS).map(([id, f]) => (
              <Toggle key={id} id={id} title={f.title} detail={f.detail} checked={faults.includes(id)}
                onChange={(on) => { setFaults(flip(faults, id, on)); custom(); }} />
            ))}
          </div>
        </div>

        <div className="field">
          <div className="switch-row">
            <span>
              <span className="field-label" id="interactive-label">Ask me when unsure</span>
              <span className="helper">Pause on undocumented cases and wait for your answer.</span>
            </span>
            <button type="button" role="switch" className="switch" aria-checked={interactive}
              aria-labelledby="interactive-label" onClick={() => { setInteractive(!interactive); custom(); }} />
          </div>
        </div>

        {error && (
          <div className="alert tone-red" role="alert" style={{ marginBottom: 16 }}>
            <AlertTriangle size={16} aria-hidden style={{ flex: "none", marginTop: 2 }} /> {error}
          </div>
        )}

        <button type="button" className="btn btn-primary btn-block" onClick={start} disabled={busy || !specs.length}>
          {busy ? <Loader2 size={18} className="spin" aria-hidden /> : <Rocket size={18} aria-hidden />}
          {busy ? "Starting…" : "Launch run"}
        </button>
        <p className="helper" style={{ textAlign: "center", margin: "10px 0 0" }}>
          {info?.model
            ? `Uses ${info.model.split(":").pop()} · about 2 model calls per run`
            : "No model configured: the scripted fake LLM is used"}
        </p>
      </div>
    </section>
  );
}
