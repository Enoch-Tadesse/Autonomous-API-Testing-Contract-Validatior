import { useEffect, useId, useState } from "react";

/** Renders a Mermaid diagram, re-themed when the app theme changes. Mermaid is loaded lazily. */
export default function Mermaid({ source, theme }: { source: string; theme: "dark" | "light" }) {
  const [svg, setSvg] = useState("");
  const [failed, setFailed] = useState(false);
  const id = useId().replace(/:/g, "");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const mermaid = (await import("mermaid")).default;
        const css = getComputedStyle(document.documentElement);
        const v = (name: string) => css.getPropertyValue(name).trim();
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: "strict",
          theme: "base",
          fontFamily: "JetBrains Mono, monospace",
          themeVariables: {
            darkMode: theme === "dark",
            background: v("--card"),
            primaryColor: v("--bg-elevated"),
            primaryTextColor: v("--fg"),
            primaryBorderColor: v("--accent"),
            lineColor: v("--fg-subtle"),
            secondaryColor: v("--muted"),
            tertiaryColor: v("--muted"),
            edgeLabelBackground: v("--card"),
            fontSize: "13px",
          },
          flowchart: { curve: "basis", padding: 14 },
        });
        const result = await mermaid.render(`arch-${id}-${theme}`, source);
        if (!cancelled) setSvg(result.svg);
      } catch {
        if (!cancelled) setFailed(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [source, theme, id]);

  if (failed) return <pre className="subtle" style={{ whiteSpace: "pre-wrap" }}>{source}</pre>;
  if (!svg) return <span className="subtle">Rendering diagram…</span>;
  // securityLevel "strict" sanitizes the SVG; the source is our own docs/architecture.mmd.
  return (
    <div
      role="img"
      aria-label="Agent architecture: planner, executor, validator, ask user and reporter nodes"
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}
