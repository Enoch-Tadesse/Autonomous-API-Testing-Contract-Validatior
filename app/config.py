"""Run configuration and budget helpers."""

import os
import time
from dataclasses import dataclass, field
from typing import Any

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


@dataclass
class Deps:
    """Run-time dependencies handed to every node through LangGraph's context.

    They live outside the state so they are never checkpointed, and tests can
    swap in a fake LLM or an in-process HTTP transport.
    """
    llm: Any                                    # anything with `async structured(schema, prompt)`
    http_transport: Any = None                  # httpx transport for http_request (tests use ASGITransport)
    web_transport: Any = None                   # httpx transport for web_search (tests stub it)
    auth_token: str = field(default_factory=lambda: os.environ.get("TARGET_API_TOKEN", "test-token"))
    tavily_api_key: str = field(default_factory=lambda: os.environ.get("TAVILY_API_KEY", ""))
    workspace_dir: str = field(default_factory=lambda: os.environ.get("WORKSPACE_DIR", "./workspace"))
    backoff_scale: float = 1.0                  # tests set 0 so transient retries do not sleep
