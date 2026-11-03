import { useEffect, useState } from "react";
import { FlaskConical } from "lucide-react";
import { api } from "../lib/api";
import { Empty, Markdown } from "./bits";

export default function EvalPage() {
  const [md, setMd] = useState<string | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.evaluation().then(setMd).catch((e: Error) => setError(e.message));
  }, []);

  return (
    <section className="card fade-in" aria-labelledby="eval-title" style={{ maxWidth: 1080, margin: "0 auto" }}>
      <div className="card-header">
        <h1 id="eval-title" className="card-title" style={{ fontSize: 16 }}><FlaskConical size={18} aria-hidden /> Evaluation</h1>
        <code className="code">python -m eval.run_eval</code>
      </div>
      <div className="card-pad">
        {error ? <Empty icon={<FlaskConical size={20} />} title="No evaluation report">{error}</Empty>
          : md === null ? <span className="subtle">Loading…</span>
          : <Markdown source={md.replace(/^# Evaluation report\n/, "")} />}
      </div>
    </section>
  );
}
