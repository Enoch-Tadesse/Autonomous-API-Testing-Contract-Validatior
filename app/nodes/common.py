"""Small helpers shared by the nodes."""

import copy


def log(state: dict, node: str, decision: str, reason: str, offset: int = 0) -> dict:
    """One decision_log entry. offset numbers several entries written by one node visit."""
    step = len(state.get("decision_log", [])) + 1 + offset
    return {"step": step, "node": node, "decision": decision, "reason": reason}


def copy_tasks(state: dict) -> list[dict]:
    """Nodes replace the whole task list, so they edit a copy."""
    return copy.deepcopy(state.get("tasks", []))


def find(tasks: list[dict], task_id: str | None) -> dict | None:
    return next((t for t in tasks if t["id"] == task_id), None)


def describe_request(request: dict) -> str:
    query = "&".join(f"{k}={v}" for k, v in request.get("query", {}).items())
    return f"{request.get('method', 'GET')} {request.get('path', '')}" + (f"?{query}" if query else "")


def latest_critique(state: dict, task_id: str) -> dict | None:
    return next((c for c in reversed(state.get("critiques", [])) if c["task_id"] == task_id), None)
