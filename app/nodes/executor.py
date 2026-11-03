"""Executor: run the current task's tool, safely, and store the evidence.

1. retry   -> ask the LLM to repair the request using the newest critique
2. safety  -> base URL allowlist, mutating methods, per-endpoint call cap (no network call if blocked)
3. call    -> transient failures (timeout, 502/503/504) retried with backoff
4. fallback-> when retries are used up and FALLBACKS has a substitute, switch tool
5. record  -> redact, truncate, store evidence, update counters
"""

import asyncio
import copy

from langgraph.runtime import Runtime

from app.config import Deps
from app.llm import FixedRequest
from app.nodes.common import copy_tasks, describe_request, find, latest_critique, log
from app.prompts import fix_request_prompt
from app.redact import redact, redact_body
from app.tools import FALLBACKS, call_tool, fallback_args
from app.tools.base import ToolContext
from app.tools.http_request import MAX_CALLS_PER_ENDPOINT, HttpArgs, is_transient, safety_problem

MAX_BODY = 4096


def backoff_seconds(n: int) -> float:
    return min(0.5 * 2 ** n, 4)


def tool_context(state: dict, deps: Deps) -> ToolContext:
    c = state["config"]
    return ToolContext(
        base_url=state["base_url"], allow_mutating=c["allow_mutating"], timeout_s=c["request_timeout_s"],
        http_transport=deps.http_transport, web_transport=deps.web_transport, auth_token=deps.auth_token,
        tavily_api_key=deps.tavily_api_key, workspace_dir=deps.workspace_dir, endpoints=state.get("endpoints", []),
    )


async def executor(state: dict, runtime: Runtime[Deps]) -> dict:
    deps = runtime.context
    tasks = copy_tasks(state)
    task = find(tasks, state["current_task_id"])
    tool, args = state["tool_name"], copy.deepcopy(state.get("tool_args") or task["request"])
    retries = dict(state.get("retries", {}))
    entries: list[dict] = []

    def note(decision: str, reason: str):
        entries.append(log(state, "executor", decision, reason, len(entries)))

    task["attempts"] += 1
    mode = state.get("action")
    if mode == "retry":
        key = f"{task['id']}:{tool}"
        retries[key] = retries.get(key, 0) + 1
        critique = latest_critique(state, task["id"]) or {}
        body = (find_evidence(state, critique.get("evidence_id")) or {}).get("response", {}).get("body", "")
        fix = await deps.llm.structured(FixedRequest, fix_request_prompt(task, critique, body))
        if fix.request is not None:
            args = keep_tested_value(fix.request.to_request(), task["request"], task["param"])
            task["request"] = args
        note("repair_request", f"retry {retries[key]}: {fix.rationale}")

    ctx = tool_context(state, deps)
    blocked = gate(tool, args, ctx, state, task)
    if blocked:
        note("blocked", blocked)
        result, calls, used_tool = {"ok": False, "error": f"blocked: {blocked}", "blocked": True}, 0, tool
        transient = []
    else:
        result, calls, transient = await call_with_retries(tool, args, ctx, state["config"], deps.backoff_scale)
        used_tool = tool
        if not result["ok"] and FALLBACKS.get(tool):
            used_tool = FALLBACKS[tool]
            note("fallback", f"{tool} failed ({result['error']}), switching to {used_tool}")
            args = fallback_args(args)
            result, extra_calls, _ = await call_with_retries(used_tool, args, ctx, state["config"], deps.backoff_scale)
            calls += extra_calls

    evidence = make_evidence(state, task, used_tool, args, result, transient) if calls else None
    failures = dict(state.get("tool_failures", {}))
    if calls:
        failures[used_tool] = 0 if result["ok"] else failures.get(used_tool, 0) + 1

    label = "rerun" if mode == "rerun" else "call"
    outcome = result.get("status") or result.get("error") or "ok"
    chain = " -> ".join(transient + [str(outcome)])
    target = describe_request(args) if used_tool == "http_request" else str(args)[:80]
    if not blocked:
        note(f"{label}_{used_tool}", f"{target} -> {chain}" + (f" ({evidence['id']})" if evidence else ""))

    return {
        "tasks": tasks,
        "tool_args": args,
        "last_result": {
            "tool": used_tool, "ok": result["ok"], "error": result.get("error"), "status": result.get("status"),
            "blocked": bool(blocked), "evidence_id": evidence["id"] if evidence else None,
            "transient_retries": len(transient), "fallback_used": used_tool != tool,
        },
        "evidence": [evidence] if evidence else [],
        "retries": retries,
        "tool_failures": failures,
        "steps": state.get("steps", 0) + 1,
        "tool_calls": state.get("tool_calls", 0) + calls,
        "decision_log": entries,
    }


def keep_tested_value(fixed: dict, original: dict, param: str | None) -> dict:
    """A repair may change anything except the value under test (and it keeps the auth header)."""
    if param:
        if param in original.get("query", {}):
            fixed["query"][param] = original["query"][param]
        else:
            fixed["query"].pop(param, None)
    if "Authorization" in original.get("headers", {}):
        fixed["headers"]["Authorization"] = original["headers"]["Authorization"]
    return fixed


def gate(tool: str, args: dict, ctx: ToolContext, state: dict, task: dict) -> str | None:
    """Reason to block an http_request before it is sent, or None."""
    if tool != "http_request":
        return None
    try:
        problem = safety_problem(HttpArgs(**args), ctx)
    except Exception as e:  # malformed args are not sent either
        return f"bad request arguments: {e}"
    if problem:
        return problem
    used = sum(1 for e in state.get("evidence", []) if e["tool"] == "http_request" and e["endpoint"] == task["endpoint"])
    if used >= MAX_CALLS_PER_ENDPOINT:
        return f"{MAX_CALLS_PER_ENDPOINT} calls already made to {task['endpoint']} this run"
    return None


async def call_with_retries(tool: str, args: dict, ctx: ToolContext, config: dict, backoff_scale: float):
    """Returns (result, number of calls, outcomes of the transient failures that were retried)."""
    calls, transient = 0, []
    limit = config["max_retries_per_tool"]
    while True:
        result = await call_tool(tool, args, ctx)
        calls += 1
        if tool == "http_request":
            retryable = is_transient(result)
        else:
            retryable = (result.get("error") or "").startswith("timeout")
        if not retryable or len(transient) >= limit:
            return result, calls, transient
        await asyncio.sleep(backoff_seconds(len(transient)) * backoff_scale)
        transient.append(f"{result.get('status') or result.get('error')} -> retry {len(transient) + 1}/{limit}")


def make_evidence(state: dict, task: dict, tool: str, args: dict, result: dict, transient: list[str]) -> dict:
    number = len(state.get("evidence", [])) + 1
    if tool == "http_request":
        response = {"status": result.get("status"), "headers": redact(result.get("headers", {})),
                    "body": redact_body(result.get("body") or "")[:MAX_BODY], "error": result.get("error")}
    else:
        response = {"ok": result["ok"], "error": result.get("error"), "output": redact(result.get("output"))}
    return {
        "id": f"e_{number:03d}", "task_id": task["id"], "endpoint": task["endpoint"], "tool": tool,
        "request": redact(args), "response": response, "transient_retries": len(transient),
    }


def find_evidence(state: dict, evidence_id: str | None) -> dict | None:
    return next((e for e in state.get("evidence", []) if e["id"] == evidence_id), None)
