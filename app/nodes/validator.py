"""Validator (meta-tool: critique). Runs after every executor step.

Raw output goes through the deterministic checks first, then rules classify it:
  all checks pass                              -> ok             -> next
  documented expectation violated              -> api_defect     -> rerun, then replan once reproduced
  400 caused by a different parameter          -> test_error     -> retry
  timeout / connection error / 502-504         -> infra_failure  -> next (inconclusive)
  no documented expectation                    -> ambiguous      -> ask_user, or next when not interactive
Only when no rule fits is the LLM asked for a Critique. It can never confirm a finding.
"""

import json
import re

from langgraph.runtime import Runtime

from app.checks import failed, run_checks
from app.config import Deps
from app.llm import Critique
from app.nodes.common import copy_tasks, describe_request, find, latest_critique, log
from app.nodes.executor import find_evidence
from app.prompts import critique_prompt
from app.tools.http_request import TRANSIENT_STATUSES

QUOTED_NAME = re.compile(r"'(\w+)'")


def verdict(issue: str, action: str, outcome: str, reason: str, finding: dict | None = None) -> dict:
    return {"issue": issue, "action": action, "outcome": outcome, "reason": reason, "finding": finding}


async def validator(state: dict, runtime: Runtime[Deps]) -> dict:
    tasks = copy_tasks(state)
    task = find(tasks, state["current_task_id"])
    result = state["last_result"]
    evidence = find_evidence(state, result.get("evidence_id"))
    checks: list[dict] = []

    if result.get("blocked"):
        v = verdict("blocked", "next", "inconclusive", f"call blocked by the safety gate: {result['error']}")
    elif result["tool"] != "http_request":
        v = (verdict("ok", "next", "pass", f"{result['tool']} returned a result") if result["ok"] else
             verdict("infra_failure", "next", "inconclusive", f"{result['tool']} failed: {result['error']}"))
    else:
        checks = run_checks(task, evidence["response"])
        v = classify(state, task, evidence, checks)
        if v is None:
            v = await ask_llm(runtime.context, state, task, evidence, checks)

    v = enforce_limits(state, task, v)
    update = {
        "tasks": tasks,
        "action": v["action"],
        "critiques": [{"task_id": task["id"], "evidence_id": result.get("evidence_id"), "issue": v["issue"],
                       "feedback": v["reason"], "action": v["action"], "checks": checks,
                       "signature": signature(evidence, checks)}],
        "findings": [v["finding"]] if v["finding"] else [],
        "decision_log": [log(state, "validator", f"{v['issue']}:{v['action']}", v["reason"])],
    }
    if v["action"] in ("next", "replan"):
        task.update(status="done", outcome=v["outcome"])
    if v["action"] == "ask_user":
        update["pending_question"] = question_for(task)
        update["status"] = "awaiting_input"
    return update


# ---------- rules ----------

def classify(state: dict, task: dict, evidence: dict, checks: list[dict]) -> dict | None:
    response = evidence["response"]
    status = response.get("status")
    fails = failed(checks)
    previous = latest_critique(state, task["id"])
    is_rerun = previous is not None and previous["action"] == "rerun"

    if response.get("error") or status in TRANSIENT_STATUSES:
        reason = f"{response.get('error') or f'HTTP {status}'} after retries, the API did not answer"
        return verdict("infra_failure", "next", "inconclusive", reason)

    if not task["expected_status"]:
        action = "ask_user" if state["config"]["interactive"] else "next"
        return verdict("ambiguous", action, "inconclusive", "no documented response for this case")

    if not fails:
        if is_rerun:
            first = find_evidence(state, previous["evidence_id"])
            finding = make_finding(task, first, previous["checks"], "suspected", [first["id"], evidence["id"]])
            return verdict("ok", "next", "defect", "rerun passed, so the earlier failure is only suspected", finding)
        return verdict("ok", "next", "pass", "all checks passed")

    if is_test_error(task, response, fails):
        return verdict("test_error", "retry", "inconclusive",
                       f"400 blames another parameter, not the tested '{task['param']}'. Repair the request")

    if is_unclear(task, status):
        return None

    detail = "; ".join(f"{c['name']}: {c['detail']}" for c in fails)
    if already_confirmed(state, finding_key(task, evidence, checks)) or task["parent_id"]:
        finding = make_finding(task, evidence, checks, "suspected", [evidence["id"]])
        return verdict("api_defect", "next", "defect", f"same defect class as a known finding. {detail}", finding)
    if is_rerun:
        both = [previous["evidence_id"], evidence["id"]]
        if previous["signature"] == signature(evidence, checks):
            finding = make_finding(task, evidence, checks, "confirmed", both)
            return verdict("api_defect", "replan", "defect", f"defect reproduced twice, replan around it. {detail}", finding)
        finding = make_finding(task, evidence, checks, "suspected", both)
        return verdict("api_defect", "next", "defect", f"rerun failed differently, marked suspected. {detail}", finding)
    return verdict("api_defect", "rerun", "defect", f"{detail}. Rerun to confirm")


def is_test_error(task: dict, response: dict, fails: list[dict]) -> bool:
    """A 400 on a request we expected to succeed, whose error names a different parameter."""
    if response.get("status") != 400 or not task["param"] or 400 in task["expected_status"]:
        return False
    names = QUOTED_NAME.findall(response.get("body") or "")
    return bool(names) and task["param"] not in names


def is_unclear(task: dict, status: int | None) -> bool:
    """A 400 on a whole-request test we expected to pass: our request or the API could be wrong."""
    return status == 400 and not task["param"] and all(200 <= s < 300 for s in task["expected_status"])


def enforce_limits(state: dict, task: dict, v: dict) -> dict:
    c = state["config"]
    if v["action"] == "retry":
        used = state.get("retries", {}).get(f"{task['id']}:{state['tool_name']}", 0)
        if used >= c["max_retries_per_tool"] or task["attempts"] >= c["max_attempts_per_task"]:
            return {**v, "action": "next", "outcome": "inconclusive", "reason": v["reason"] + " (retries used up)"}
    if v["action"] == "rerun" and task["attempts"] >= c["max_attempts_per_task"]:
        return {**v, "action": "next", "outcome": "inconclusive", "reason": v["reason"] + " (attempts used up)"}
    if v["action"] == "ask_user" and not c["interactive"]:
        return {**v, "action": "next"}
    return v


async def ask_llm(deps: Deps, state: dict, task: dict, evidence: dict, checks: list[dict]) -> dict:
    body = evidence["response"].get("body") or ""
    critique = await deps.llm.structured(Critique, critique_prompt(task, checks, body))
    action = critique.action
    if critique.issue == "api_defect":
        # The LLM may only raise a suspicion; confirmation needs two deterministic failures.
        finding = make_finding(task, evidence, checks, "suspected", [evidence["id"]])
        return verdict("api_defect", "next", "defect", f"LLM: {critique.rationale}", finding)
    outcome = "pass" if critique.issue == "ok" else "inconclusive"
    return verdict(f"llm_{critique.issue}", action, outcome, f"LLM: {critique.rationale}")


# ---------- findings ----------

def defect_class(task: dict, evidence: dict, checks: list[dict]) -> str:
    names = {c["name"] for c in failed(checks)}
    status = evidence["response"].get("status") or 0
    if status >= 500:
        return "server_error"
    if task["kind"] == "no_auth":
        return "auth"
    if "range" in names or task["kind"] in ("missing_param", "wrong_type"):
        return "validation"
    if "schema" in names:
        return "schema"
    return "contract"


def finding_key(task: dict, evidence: dict, checks: list[dict]) -> str:
    """Findings with the same key are one defect. Schema defects are per endpoint, others per parameter."""
    cls = defect_class(task, evidence, checks)
    param = "-" if cls == "schema" else (task["param"] or "-")
    return f"{task['endpoint']}|{param}|{cls}"


def already_confirmed(state: dict, key: str) -> bool:
    return any(f["key"] == key and f["status"] == "confirmed" for f in state.get("findings", []))


def signature(evidence: dict | None, checks: list[dict]) -> str:
    status = (evidence or {}).get("response", {}).get("status")
    return f"{status}:{','.join(sorted(c['name'] for c in failed(checks)))}"


def make_finding(task: dict, evidence: dict, checks: list[dict], status: str, evidence_ids: list[str]) -> dict:
    """A finding built from the evidence that shows the violation. The reporter merges findings by key."""
    key = finding_key(task, evidence, checks)
    response = evidence["response"]
    details = "; ".join(c["detail"] for c in failed(checks))
    schema_note = " matching the documented schema" if task["expected_schema"] else ""
    return {
        "key": key,
        "endpoint": task["endpoint"],
        "task_id": task["id"],
        "class": key.split("|")[-1],
        "status": status,
        "expected": f"HTTP {'/'.join(map(str, task['expected_status']))}{schema_note}",
        "actual": f"HTTP {response.get('status')}" + (f" ({details})" if details else ""),
        "evidence_ids": evidence_ids,
        "repro": describe_request(evidence["request"]),
    }


def question_for(task: dict) -> str:
    return (f"{task['id']} {task['endpoint']}: {task['objective']}. The spec documents no response for this case. "
            "Which status code(s) should it return? Answer e.g. '400', or 'skip'.")
