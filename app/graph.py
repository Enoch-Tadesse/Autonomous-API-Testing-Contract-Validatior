"""Graph wiring: five nodes, routers and compile.

Routers are pure functions of state, so they are unit tested without an LLM.
The first matching rule wins, and rule 1 is always the budget guard.
"""

import time
import uuid

from langgraph.graph import END, START, StateGraph

from app.config import Deps, RunConfig, budget_exhausted
from app.nodes.ask_user import ask_user
from app.nodes.executor import executor
from app.nodes.planner import planner
from app.nodes.reporter import reporter
from app.nodes.validator import validator
from app.state import AgentState


def after_planner(state: dict) -> str:
    if budget_exhausted(state):
        return "reporter"
    # The planner sets current_task_id to the task it picked, or None when no task is pending.
    if not state.get("current_task_id"):
        return "reporter"
    return "executor"


def after_executor(state: dict) -> str:
    if budget_exhausted(state):
        return "reporter"
    return "validator"


def after_validator(state: dict) -> str:
    if budget_exhausted(state):
        return "reporter"
    action = state.get("action", "next")
    if action in ("retry", "rerun"):
        return "executor"
    if action == "ask_user":
        return "ask_user"
    if action == "replan" and state.get("replans", 0) < state["config"]["max_replans"]:
        return "planner"
    return "planner"  # "next": the planner picks the next task, or sends the run to the reporter


def build_graph(checkpointer):
    g = StateGraph(AgentState, context_schema=Deps)
    g.add_node("planner", planner)
    g.add_node("executor", executor)
    g.add_node("validator", validator)
    g.add_node("ask_user", ask_user)
    g.add_node("reporter", reporter)

    g.add_edge(START, "planner")
    g.add_conditional_edges("planner", after_planner, ["executor", "reporter"])
    g.add_conditional_edges("executor", after_executor, ["validator", "reporter"])
    g.add_conditional_edges("validator", after_validator, ["executor", "planner", "ask_user", "reporter"])
    g.add_edge("ask_user", "planner")
    g.add_edge("reporter", END)
    return g.compile(checkpointer=checkpointer)


def new_run_id() -> str:
    return f"run_{uuid.uuid4().hex[:8]}"


def initial_state(run_id: str, spec_text: str, config: RunConfig) -> dict:
    return {
        "run_id": run_id, "base_url": config.base_url, "config": config.model_dump(), "started_at": time.time(),
        "spec_text": spec_text, "tasks": [], "current_task_id": None, "retries": {}, "tool_failures": {},
        "steps": 0, "tool_calls": 0, "replans": 0, "status": "running", "stop_reason": None,
        "pending_question": None, "action": "start",
    }
