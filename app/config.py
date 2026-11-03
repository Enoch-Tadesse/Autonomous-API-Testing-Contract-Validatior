"""Run configuration and budget helpers."""

import time

from pydantic import BaseModel


class RunConfig(BaseModel):
    base_url: str
    interactive: bool = True
    allow_mutating: bool = False
    max_steps: int = 50
    max_tool_calls: int = 60
    max_retries_per_tool: int = 2
    max_attempts_per_task: int = 3
    max_replans: int = 3
    max_seconds: int = 300
    request_timeout_s: float = 10.0


def budget_exhausted(state: dict) -> str | None:
    """Name of the first budget that has run out, or None if the run may continue."""
    c = state["config"]
    elapsed = time.time() - state.get("started_at", time.time())
    if state.get("steps", 0) >= c["max_steps"]:
        return "step_budget"
    if state.get("tool_calls", 0) >= c["max_tool_calls"]:
        return "tool_call_budget"
    if elapsed >= c["max_seconds"]:
        return "time_budget"
    return None


def recursion_limit(config: dict) -> int:
    """LangGraph backstop. The budget guard always fires before this is reached."""
    return config["max_steps"] * 3 + 20
