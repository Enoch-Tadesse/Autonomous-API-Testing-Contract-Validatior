"""The only place the agent talks to a language model.

Nodes call `await llm.structured(OutputModel, prompt)` and get an instance of
OutputModel back. ChatLLM wraps the real model (init_chat_model, AGENT_MODEL
from .env). FakeLLM returns queued answers (or a safe default) so the whole
graph runs in tests without an API key.
"""

import json
import os
from typing import Any, Literal

from pydantic import BaseModel, Field


# ---------- structured outputs ----------
# Kept to simple types (lists of name/value pairs, JSON body as text) so every
# provider's structured-output mode accepts the schema.

class Pair(BaseModel):
    name: str
    value: str


class RequestSpec(BaseModel):
    method: str = "GET"
    path: str = Field(description="path only, e.g. /v1/restaurants/nearby")
    query: list[Pair] = []
    headers: list[Pair] = []
    body_json: str | None = Field(default=None, description="JSON body as text, or null")

    def to_request(self) -> dict[str, Any]:
        return {
            "method": self.method.upper(), "path": self.path,
            "query": {p.name: p.value for p in self.query},
            "headers": {p.name: p.value for p in self.headers},
            "body": parse_json(self.body_json),
        }


def parse_json(text: str | None) -> Any:
    try:
        return json.loads(text) if text else None
    except ValueError:
        return None


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


class ChatLLM:
    """The real model. Any error falls back to the safe default so one bad call never kills a run."""

    def __init__(self, model):
        self.model = model
        self.calls: list[tuple[str, str]] = []

    async def structured(self, schema: type[BaseModel], prompt: str) -> BaseModel:
        self.calls.append((schema.__name__, prompt))
        try:
            answer = await self.model.with_structured_output(schema).ainvoke(prompt)
        except Exception as e:  # network, quota, schema or parsing errors
            default = DEFAULTS[schema.__name__]()
            note = f"LLM call failed ({type(e).__name__}: {str(e)[:120]}), used the safe default"
            return default.model_copy(update={"rationale": note}) if hasattr(default, "rationale") else default
        if answer is None:
            return DEFAULTS[schema.__name__]()
        return answer


def make_llm(fake: bool = False):
    """FakeLLM when asked for or when AGENT_MODEL is empty, otherwise the configured model.

    AGENT_MODEL is "<model>" (Gemini via google_genai) or "<provider>:<model>".
    """
    name = os.environ.get("AGENT_MODEL", "").strip()
    if fake or not name:
        return FakeLLM()
    from langchain.chat_models import init_chat_model

    provider, _, model = name.rpartition(":")
    provider = provider or "google_genai"
    kwargs: dict[str, Any] = {"temperature": 0}
    if provider == "google_genai":
        kwargs["api_key"] = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    return ChatLLM(init_chat_model(model, model_provider=provider, **kwargs))
