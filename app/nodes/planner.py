"""Planner (meta-tool: plan / to-do list).

The only node that adds, reorders or cancels tasks.
  first visit  -> generate tasks from the spec, one LLM call to order them and add extras
  after ask    -> apply the user's answer to the task that raised the question
  replan visit -> add neighbor tasks around confirmed defects
  every visit  -> pick the next pending task
"""

import re

from langgraph.runtime import Runtime

from app.config import Deps
from app.llm import PlanOrder
from app.nodes.common import copy_tasks, find, log
from app.prompts import plan_prompt
from app.spec import base_request, generate_tasks, list_endpoints, load_spec
from app.tools import FALLBACKS, UNAVAILABLE_AFTER, fallback_args

MAX_EXTRA_TASKS = 5
RANGE_KINDS = ("below_min", "above_max")


async def planner(state: dict, runtime: Runtime[Deps]) -> dict:
    update: dict = {"decision_log": []}
    tasks = copy_tasks(state)
    endpoints = state.get("endpoints")

    def note(decision: str, reason: str):
        update["decision_log"].append(log(state, "planner", decision, reason, len(update["decision_log"])))

    if not tasks:
        endpoints = list_endpoints(load_spec(state["spec_text"]))
        tasks = generate_tasks(endpoints)
        plan = await runtime.context.llm.structured(PlanOrder, plan_prompt(tasks, endpoints))
        tasks = apply_plan(tasks, plan, endpoints)
        update["endpoints"] = endpoints
        note("plan", f"{len(tasks)} tasks for {len(endpoints)} endpoints. {plan.rationale}")

    elif state.get("clarifications") and (task := find(tasks, state.get("current_task_id"))) and \
            task["status"] == "in_progress":
        answer = state["clarifications"][-1]["answer"]
        note("apply_answer", apply_answer(task, str(answer), endpoints))

    elif state.get("action") == "replan" and state.get("replans", 0) < state["config"]["max_replans"]:
        added = add_followups(tasks, endpoints)
        update["replans"] = state.get("replans", 0) + 1
        ids = ", ".join(t["id"] for t in added) or "none"
        note("replan", f"added {len(added)} neighbor tasks around confirmed defects ({ids})")

    update.update(pick_next(tasks, state, note))
    update["tasks"] = tasks
    update["action"] = "start"
    return update


def apply_plan(tasks: list[dict], plan: PlanOrder, endpoints: list[dict]) -> list[dict]:
    """Reorder by the LLM's order (unknown ids ignored, unlisted tasks keep their place at the end) and add extras."""
    by_id = {t["id"]: t for t in tasks}
    ordered = [by_id.pop(i) for i in plan.order if i in by_id]
    ordered += [t for t in tasks if t["id"] in by_id]

    known = {e["key"]: e for e in endpoints}
    for extra in plan.extra_tasks[:MAX_EXTRA_TASKS]:
        endpoint = known.get(extra.endpoint)
        request = extra.request.to_request()
        # Extras must target their own endpoint and expect only documented status codes.
        expected = [c for c in extra.expected_status if c in endpoint["responses"]] if endpoint else []
        if endpoint is None or request["path"] != endpoint["path"] or not expected:
            continue
        if endpoint["secured"] and "Authorization" not in request["headers"]:
            request["headers"]["Authorization"] = base_request(endpoint)["headers"]["Authorization"]
        ordered.append(new_task(ordered, endpoint, "extra", extra.objective, request, expected))
    return ordered


def new_task(tasks: list[dict], endpoint: dict, kind: str, objective: str, request: dict,
             expected: list[int], param: str | None = None, parent_id: str | None = None) -> dict:
    next_number = max(int(t["id"][2:]) for t in tasks) + 1 if tasks else 1
    return {
        "id": f"t_{next_number:03d}", "endpoint": endpoint["key"], "kind": kind, "tool": "http_request",
        "param": param, "objective": objective, "request": request, "expected_status": expected,
        "expected_schema": endpoint["responses"].get(expected[0]) if expected else None,
        "status": "pending", "outcome": "unknown", "attempts": 0, "parent_id": parent_id,
    }


# ---------- replan ----------

def add_followups(tasks: list[dict], endpoints: list[dict]) -> list[dict]:
    """For each confirmed range defect with no follow-ups yet, add 2-3 neighbor values right after it."""
    endpoints_by_key = {e["key"]: e for e in endpoints}
    has_children = {t["parent_id"] for t in tasks if t["parent_id"]}
    added = []
    for parent in list(tasks):
        if parent["outcome"] != "defect" or parent["parent_id"] or parent["id"] in has_children:
            continue
        if parent["kind"] not in RANGE_KINDS or not parent["param"]:
            continue
        endpoint = endpoints_by_key[parent["endpoint"]]
        position = tasks.index(parent) + 1
        tested = {t["request"]["query"].get(parent["param"]) for t in tasks if t["endpoint"] == parent["endpoint"]}
        for value in neighbor_values(parent, endpoint, tested):
            request = {**parent["request"], "query": {**parent["request"]["query"], parent["param"]: value}}
            kind = "below_min" if value < schema_of(endpoint, parent["param"]).get("minimum", value) else "above_max"
            child = new_task(tasks, endpoint, kind, f"follow-up: '{parent['param']}'={value}",
                             request, parent["expected_status"], parent["param"], parent["id"])
            tasks.insert(position, child)
            position += 1
            added.append(child)
    return added


def schema_of(endpoint: dict, param: str) -> dict:
    return next((p.get("schema", {}) for p in endpoint["parameters"] if p["name"] == param), {})


def neighbor_values(task: dict, endpoint: dict, tested: set) -> list:
    """Untested invalid values around the defect: just below min, further below, far below, just above max."""
    schema = schema_of(endpoint, task["param"])
    candidates = []
    if "minimum" in schema:
        low = schema["minimum"]
        candidates += [low - 1, low - 2, low - 101]
    if "maximum" in schema:
        candidates.append(schema["maximum"] + 1)
    fresh = []
    for value in candidates:
        if value not in tested and value not in fresh:
            fresh.append(value)
    return fresh[:3]


# ---------- ask-user answer ----------

def apply_answer(task: dict, answer: str, endpoints: list[dict]) -> str:
    """An answer with status codes makes them the expectation and re-queues the task. Anything else skips it."""
    codes = [int(c) for c in re.findall(r"\b[1-5]\d\d\b", answer)]
    if not codes:
        task.update(status="done", outcome="inconclusive")
        return f"user answer '{answer}' has no status code, {task['id']} marked inconclusive"
    endpoint = next(e for e in endpoints if e["key"] == task["endpoint"])
    task.update(expected_status=codes, expected_schema=endpoint["responses"].get(codes[0]),
                status="pending", attempts=0)
    return f"user expects {codes} for {task['id']}, task re-queued"


# ---------- pick ----------

def pick_next(tasks: list[dict], state: dict, note) -> dict:
    failures = state.get("tool_failures", {})
    for task in tasks:
        if task["status"] != "pending":
            continue
        tool, args = task["tool"], task["request"]
        if failures.get(tool, 0) >= UNAVAILABLE_AFTER:
            fallback = FALLBACKS.get(tool)
            if fallback is None or failures.get(fallback, 0) >= UNAVAILABLE_AFTER:
                task.update(status="done", outcome="inconclusive")
                note("skip_task", f"{task['id']}: {tool} is unavailable and has no working fallback")
                continue
            note("switch_tool", f"{task['id']}: {tool} is unavailable, using {fallback}")
            tool, args = fallback, fallback_args(args)
        task["status"] = "in_progress"
        note("pick_task", f"{task['id']} {task['kind']}: {task['objective']}")
        return {"current_task_id": task["id"], "tool_name": tool, "tool_args": args}
    note("no_tasks_left", "every task is done, handing over to the reporter")
    return {"current_task_id": None, "tool_name": None, "tool_args": {}}
