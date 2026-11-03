"""Planner (meta-tool: plan / to-do list).

The only node that adds, reorders or cancels tasks.
  first visit  -> generate tasks from the spec; if the workspace has project notes, read them first (read_file)
  plan visit   -> one LLM call, with the notes as context, to order tasks and add extras; add doc lookups
                  for undocumented cases and the cross-request pagination check (run_python)
  after ask    -> apply the user's answer to the task that raised the question
  replan visit -> add neighbor tasks around confirmed defects
  every visit  -> pick the next pending task whose inputs are ready
"""

import re
from pathlib import Path

from langgraph.runtime import Runtime

from app.config import Deps
from app.consistency import pagination_tasks
from app.llm import PlanOrder
from app.nodes.common import copy_tasks, find, log
from app.prompts import plan_prompt
from app.spec import base_request, generate_tasks, list_endpoints, load_spec
from app.tools import FALLBACKS, UNAVAILABLE_AFTER, fallback_args

MAX_EXTRA_TASKS = 5
RANGE_KINDS = ("below_min", "above_max")
NOTE_SUFFIXES = (".md", ".txt")
MAX_NOTE_FILES = 2


async def planner(state: dict, runtime: Runtime[Deps]) -> dict:
    update: dict = {"decision_log": []}
    tasks = copy_tasks(state)
    endpoints = state.get("endpoints")

    def note(decision: str, reason: str):
        update["decision_log"].append(log(state, "planner", decision, reason, len(update["decision_log"])))

    if not tasks:
        endpoints = list_endpoints(load_spec(state["spec_text"]))
        tasks = generate_tasks(endpoints)
        update["endpoints"] = endpoints
        docs = add_docs_tasks(tasks, runtime.context.workspace_dir)
        if docs:
            names = ", ".join(t["request"]["path"] for t in docs)
            note("read_docs", f"reading project notes ({names}) before planning, so the plan can use them")
        else:
            tasks = await make_plan(tasks, endpoints, "", runtime.context, note)
            update["planned"] = True

    elif not state.get("planned"):
        tasks = await make_plan(tasks, endpoints, notes_from(state, tasks), runtime.context, note)
        update["planned"] = True

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


async def make_plan(tasks: list[dict], endpoints: list[dict], notes: str, deps: Deps, note) -> list[dict]:
    """The one planning LLM call, then the tasks the plan always needs: doc lookups and cross-request checks."""
    pending = [t for t in tasks if t["status"] == "pending"]
    plan = await deps.llm.structured(PlanOrder, plan_prompt(pending, endpoints, notes))
    tasks = apply_plan(tasks, plan, endpoints)
    note("plan", f"{len(tasks)} tasks for {len(endpoints)} endpoints"
                 f"{', using the project notes' if notes else ''}. {plan.rationale}")

    lookups = add_doc_lookups(tasks)
    if lookups:
        note("add_lookup", f"{len(lookups)} case(s) have no documented response, searching docs first "
                           f"({', '.join(t['id'] for t in lookups)})")
    checks = pagination_tasks(endpoints, tasks, new_task)
    if checks:
        # Early in the list, so the per-endpoint call budget never squeezes them out.
        tasks[len(lookups):len(lookups)] = checks
        ids = [t["id"] for t in checks]
        note("add_check", f"pagination check: fetch pages ({', '.join(ids[:-1])}), then run_python compares them "
                          f"({ids[-1]})")
    return tasks


def add_docs_tasks(tasks: list[dict], workspace_dir: str) -> list[dict]:
    """A read_file task for each project note in the workspace (at most two), placed first."""
    workspace = Path(workspace_dir)
    files = sorted(p for p in workspace.glob("*") if p.suffix in NOTE_SUFFIXES and p.is_file()) if workspace.is_dir() else []
    docs = []
    for path in files[:MAX_NOTE_FILES]:
        task = new_task(tasks + docs, {"key": "workspace", "responses": {}}, "docs",
                        f"read project notes {path.name}", {"path": path.name}, [])
        task["tool"] = "read_file"
        docs.append(task)
    tasks[:0] = docs
    return docs


def notes_from(state: dict, tasks: list[dict]) -> str:
    """Text the docs tasks read (read_file output, or rag_search hits if it fell back)."""
    doc_ids = {t["id"] for t in tasks if t["kind"] == "docs"}
    parts = []
    for e in state.get("evidence", []):
        if e["task_id"] not in doc_ids:
            continue
        output = e["response"].get("output")
        if isinstance(output, str):
            parts.append(output)
        elif isinstance(output, list):
            parts += [hit.get("text", "") for hit in output if isinstance(hit, dict)]
    return "\n\n".join(p for p in parts if p).strip()


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
        "status": "pending", "outcome": "unknown", "attempts": 0, "parent_id": parent_id, "depends_on": [],
    }


def add_doc_lookups(tasks: list[dict]) -> list[dict]:
    """For each endpoint with undocumented cases, put a web_search task first. Its result helps the user answer."""
    lookups = []
    for endpoint in dict.fromkeys(t["endpoint"] for t in tasks if not t["expected_status"] and t["tool"] == "http_request"):
        unclear = [t["objective"] for t in tasks if t["endpoint"] == endpoint and not t["expected_status"]]
        path_words = endpoint.split(" ", 1)[1].replace("/", " ")
        query = f"{path_words} expected HTTP status code for {unclear[0]}"
        task = new_task(tasks, {"key": endpoint, "responses": {}}, "lookup", f"search docs: {unclear[0]}",
                        {"query": query}, [])
        task["tool"] = "web_search"
        lookups.append(task)
    tasks[:0] = lookups
    return lookups


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
        tested = {t["request"].get("query", {}).get(parent["param"]) for t in tasks if t["endpoint"] == parent["endpoint"]}
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
        inputs = [find(tasks, d) for d in task.get("depends_on") or []]
        if any(d is not None and d["status"] != "done" for d in inputs):
            continue  # its inputs (e.g. the pages to compare) are not fetched yet
        if any(d is None or d["outcome"] not in ("pass", "defect") for d in inputs):
            task.update(status="done", outcome="inconclusive")
            note("skip_task", f"{task['id']}: its inputs ({', '.join(task['depends_on'])}) did not produce a response")
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
