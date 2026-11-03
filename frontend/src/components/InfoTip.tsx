import { useEffect, useId, useState } from "react";
import { Info } from "lucide-react";

/**
 * An "i" in a circle that explains a section. Opens on hover, keyboard focus or tap (not hover-only),
 * closes on leave, blur or Escape. The panel is positioned against the nearest `.field-label`, so it
 * spans the field's width and never spills out of the card.
 */
export default function InfoTip({ label, title, lines, initiallyOpen = false }: {
  label: string;
  title: string;
  lines: string[];
  initiallyOpen?: boolean;
}) {
  const [open, setOpen] = useState(initiallyOpen);
  const id = useId();

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <span onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
      <button
        type="button"
        className="infotip"
        aria-label={`About ${label}`}
        aria-describedby={open ? id : undefined}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
      >
        <Info size={15} aria-hidden />
      </button>
      {open && (
        <span role="tooltip" id={id} className="tooltip fade-in">
          <strong className="tooltip-title">{title}</strong>
          <ul>
            {lines.map((line) => <li key={line}>{line}</li>)}
          </ul>
        </span>
      )}
    </span>
  );
}
