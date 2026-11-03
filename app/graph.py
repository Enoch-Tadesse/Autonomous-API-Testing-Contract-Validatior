"""Graph wiring. Phase 2 has only the routers; build_graph() comes in phase 3.

Routers are pure functions of state, so they are unit tested without an LLM.
The first matching rule wins, and rule 1 is always the budget guard.
"""

from app.config import budget_exhausted


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
