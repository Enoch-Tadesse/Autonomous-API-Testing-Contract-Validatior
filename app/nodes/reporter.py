"""Reporter: build the final report from state only.

1. Findings, coverage and statistics come from state. No fact comes from LLM memory.
2. One LLM call writes the summary. If it cites an id that does not exist, a template sentence is used.
3. Citation check: a finding whose evidence ids are not all in state["evidence"] goes to "Unsupported".
4. The markdown report is written to data/reports/{run_id}.md.
"""

import re
from collections import Counter
from pathlib import Path

from langgraph.runtime import Runtime

from app.config import Deps, budget_exhausted
from app.llm import Summary
from app.nodes.common import log
from app.prompts import summary_prompt

STATUS_RANK = {"suspected": 0, "confirmed": 1}
CITED_ID = re.compile(r"\b(?:F\d+|e_\d{3,}|t_\d{3,})\b")


def merge_findings(findings: list[dict]) -> list[dict]:
    """One finding per key: evidence ids combined, strongest status kept, ids F1, F2, ..."""
    merged: dict[str, dict] = {}
    for f in findings:
        if f["key"] not in merged:
            merged[f["key"]] = {**f, "evidence_ids": list(f["evidence_ids"])}
            continue
        m = merged[f["key"]]
        m["evidence_ids"] += [e for e in f["evidence_ids"] if e not in m["evidence_ids"]]
        if STATUS_RANK[f["status"]] > STATUS_RANK[m["status"]]:
            m.update(status=f["status"], actual=f["actual"], repro=f["repro"], task_id=f["task_id"])
    ordered = sorted(merged.values(), key=lambda f: -STATUS_RANK[f["status"]])
    return [{**f, "id": f"F{i}"} for i, f in enumerate(ordered, 1)]


def citation_check(findings: list[dict], evidence: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split findings into (supported, unsupported). Supported means every cited id exists."""
    known = {e["id"] for e in evidence}
    supported, unsupported = [], []
    for f in findings:
        ok = f["evidence_ids"] and all(e in known for e in f["evidence_ids"])
        (supported if ok else unsupported).append(f)
    return supported, unsupported


def statistics(state: dict) -> dict:
    decisions = Counter(e["decision"] for e in state.get("decision_log", []))
    transient = sum(e.get("transient_retries", 0) for e in state.get("evidence", []))
    return {
        "steps": state.get("steps", 0),
        "tool_calls": state.get("tool_calls", 0),
        "retries": sum(state.get("retries", {}).values()) + transient,
        "reruns": sum(n for d, n in decisions.items() if d.endswith(":rerun")),
        "replans": state.get("replans", 0),
        "fallbacks_used": decisions["fallback"],
        "questions_asked": len(state.get("clarifications", [])),
        "tasks": len(state.get("tasks", [])),
    }


def safe_summary(text: str, valid_ids: set[str], fallback: str) -> str:
    cited = set(CITED_ID.findall(text))
    return text.strip() if text.strip() and cited <= valid_ids else fallback


def template_summary(status: str, findings: list[dict], stats: dict) -> str:
    confirmed = [f["id"] for f in findings if f["status"] == "confirmed"]
    return (f"Run {status}: {stats['tasks']} tasks, {stats['tool_calls']} tool calls, "
            f"{len(confirmed)} confirmed defect(s){' (' + ', '.join(confirmed) + ')' if confirmed else ''} "
            f"and {len(findings) - len(confirmed)} suspected issue(s).")


async def reporter(state: dict, runtime: Runtime[Deps]) -> dict:
    stop = budget_exhausted(state)
    status = "partial" if stop else "complete"
    supported, unsupported = citation_check(merge_findings(state.get("findings", [])), state.get("evidence", []))
    stats = statistics(state)

    answer = await runtime.context.llm.structured(Summary, summary_prompt(stats, supported))
    valid_ids = {f["id"] for f in supported} | {e["id"] for e in state.get("evidence", [])} | \
                {t["id"] for t in state.get("tasks", [])}
    summary = safe_summary(answer.text, valid_ids, template_summary(status, supported, stats))

    markdown = render(state, status, stop, summary, supported, unsupported, stats)
    path = Path(runtime.context.reports_dir) / f"{state['run_id']}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown)

    cited = ", ".join(f"{f['id']} {f['status']} ({', '.join(f['evidence_ids'])})" for f in supported) or "no findings"
    reason = cited + (f"; stopped by {stop}" if stop else "") + (f"; {len(unsupported)} unsupported" if unsupported else "")
    return {
        "status": status,
        "stop_reason": stop,
        "report_path": str(path),
        "report_md": markdown,
        "decision_log": [log(state, "reporter", status.upper(), reason)],
    }


# ---------- markdown ----------

def cite(ids: list[str]) -> str:
    return " ".join(f"[{i}]" for i in ids)


def finding_lines(findings: list[dict]) -> list[str]:
    if not findings:
        return ["None."]
    return [f"- **{f['id']}** `{f['class']}` on `{f['endpoint']}`: expected {f['expected']}, got {f['actual']}. "
            f"Repro: `{f['repro']}` {cite(f['evidence_ids'])}" for f in findings]


def render(state, status, stop, summary, supported, unsupported, stats) -> str:
    tasks = state.get("tasks", [])
    critiques = {c["task_id"]: c for c in state.get("critiques", [])}  # last critique per task wins
    lines = [f"# API test report: {state['run_id']}", ""]
    if stop:
        lines += [f"> **Partial run.** Stopped by `{stop}`. Only the results below were verified.", ""]
    lines += [f"Target: `{state['base_url']}`  ", f"Status: **{status}**", "", "## Summary", "", summary, ""]

    lines += ["## Confirmed defects", "", *finding_lines([f for f in supported if f["status"] == "confirmed"]), ""]
    lines += ["## Suspected issues", "", *finding_lines([f for f in supported if f["status"] == "suspected"]), ""]
    if unsupported:
        lines += ["## Unsupported", "", "These findings cite evidence that does not exist, so they are not reported as results.", ""]
        lines += [f"- {f['id']} on `{f['endpoint']}` cites {', '.join(f['evidence_ids']) or 'nothing'}" for f in unsupported]
        lines += [""]

    lines += ["## Inconclusive tests", ""]
    inconclusive = [t for t in tasks if t["outcome"] == "inconclusive" or t["status"] in ("pending", "in_progress")]
    for t in inconclusive:
        why = critiques.get(t["id"], {}).get("feedback", "not run before the run stopped")
        lines.append(f"- `{t['id']}` {t['endpoint']} ({t['objective']}): {why}")
    lines += ["None." if not inconclusive else "", ""]

    lines += ["## Coverage by endpoint", "", "| Endpoint | Tasks | Pass | Defect | Inconclusive | Not run |",
              "|---|---|---|---|---|---|"]
    for endpoint in dict.fromkeys(t["endpoint"] for t in tasks):
        mine = [t for t in tasks if t["endpoint"] == endpoint]
        count = Counter(t["outcome"] for t in mine)
        lines.append(f"| `{endpoint}` | {len(mine)} | {count['pass']} | {count['defect']} | "
                     f"{count['inconclusive']} | {count['unknown']} |")
    lines += [""]

    lines += ["## Statistics", "", "| Metric | Value |", "|---|---|"]
    lines += [f"| {k.replace('_', ' ')} | {v} |" for k, v in stats.items()] + [""]

    lines += ["## Limitations", "",
              "- Only the operations in the OpenAPI file were tested; undocumented behavior is out of scope.",
              "- Expectations come from documented status codes and schemas; business rules are not checked.",
              "- Mutating requests are skipped unless `allow_mutating` is set."]
    if stop:
        lines.append(f"- The run hit its `{stop}`, so some tasks were not executed.")
    lines += [""]

    lines += ["## Evidence index", "", "| Id | Task | Request | Result |", "|---|---|---|---|"]
    for e in state.get("evidence", []):
        req = e["request"]
        target = f"{req.get('method', '')} {req.get('path', '')}" if e["tool"] == "http_request" else e["tool"]
        query = "&".join(f"{k}={v}" for k, v in req.get("query", {}).items()) if e["tool"] == "http_request" else ""
        result = e["response"].get("status") or e["response"].get("error") or "ok"
        lines.append(f"| {e['id']} | {e['task_id']} | `{target}{'?' + query if query else ''}` | {result} |")
    return "\n".join(lines) + "\n"
