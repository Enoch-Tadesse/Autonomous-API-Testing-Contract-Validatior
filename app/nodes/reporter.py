"""Reporter. Phase 3 version: final status plus merged findings, all from state.

The markdown report, LLM summary and citation check come in phase 4.
"""

from app.config import budget_exhausted
from app.nodes.common import log

STATUS_RANK = {"suspected": 0, "confirmed": 1}


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


async def reporter(state: dict) -> dict:
    stop = budget_exhausted(state)
    status = "partial" if stop else "complete"
    findings = merge_findings(state.get("findings", []))
    summary = ", ".join(f"{f['id']} {f['status']} ({', '.join(f['evidence_ids'])})" for f in findings) or "no findings"
    return {
        "status": status,
        "stop_reason": stop,
        "decision_log": [log(state, "reporter", status.upper(), summary + (f"; stopped by {stop}" if stop else ""))],
    }
