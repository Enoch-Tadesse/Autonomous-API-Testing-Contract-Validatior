"""The only place the agent talks to a language model.

Nodes call `await llm.structured(OutputModel, prompt)` and get an instance of
OutputModel back. FakeLLM returns queued answers (or a safe default) so the
whole graph runs in tests without an API key.
"""

import os
from typing import Any, Literal

from pydantic import BaseModel, Field


# ---------- structured outputs ----------

class RequestSpec(BaseModel):
    method: str = "GET"
    path: str
    query: dict[str, Any] = {}
    headers: dict[str, str] = {}
    body: Any = None


class ExtraTask(BaseModel):
    endpoint: str = Field(description='e.g. "GET /v1/restaurants/nearby"')
    objective: str
    request: RequestSpec
    expected_status: list[int]


class PlanOrder(BaseModel):
    order: list[str] = Field(default=[], description="task ids, riskiest first")
    extra_tasks: list[ExtraTask] = Field(default=[], max_length=5)
    rationale: str


class FixedRequest(BaseModel):
    request: RequestSpec | None = Field(default=None, description="the repaired request, or null to keep it")
    rationale: str


class Critique(BaseModel):
    issue: Literal["api_defect", "test_error", "infra_failure", "ambiguous", "ok"]
    feedback: str
    action: Literal["next", "retry", "rerun", "ask_user"]
    rationale: str


class Summary(BaseModel):
    text: str


# ---------- fake model for tests and offline runs ----------

DEFAULTS = {
    "PlanOrder": lambda: PlanOrder(rationale="fake LLM: keep the generated order"),
    "FixedRequest": lambda: FixedRequest(rationale="fake LLM: no repair suggested"),
    "Critique": lambda: Critique(issue="ambiguous", feedback="fake LLM cannot classify this",
                                 action="next", rationale="fake LLM: move on"),
    "Summary": lambda: Summary(text="Summary written by the fake LLM."),
}


class FakeLLM:
    """Returns queued answers per output model, then safe defaults. Records every call."""

    def __init__(self, answers: dict[str, list[BaseModel]] | None = None):
        self.answers = {k: list(v) for k, v in (answers or {}).items()}
        self.calls: list[tuple[str, str]] = []

    async def structured(self, schema: type[BaseModel], prompt: str) -> BaseModel:
        name = schema.__name__
        self.calls.append((name, prompt))
        queue = self.answers.get(name)
        return queue.pop(0) if queue else DEFAULTS[name]()


def make_llm(fake: bool = False):
    """FakeLLM when asked for (or when no model is configured). The real model arrives in phase 4."""
    if fake or not os.environ.get("AGENT_MODEL"):
        return FakeLLM()
    raise NotImplementedError("The real model is wired up in phase 4. Use --fake-llm for now.")
