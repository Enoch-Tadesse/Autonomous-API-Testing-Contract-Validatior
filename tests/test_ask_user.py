"""An endpoint with no documented error response pauses the run; resuming with an answer lets it finish."""

from pathlib import Path

import httpx
import yaml
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.config import Deps, RunConfig, recursion_limit
from app.graph import build_graph, initial_state
from app.llm import FakeLLM
from target_api.main import app as target_app


def favorites_only_spec_without_401() -> str:
    spec = yaml.safe_load(Path("target_api/openapi.yaml").read_text())
    spec["paths"] = {"/v1/favorites": spec["paths"]["/v1/favorites"]}
    del spec["paths"]["/v1/favorites"]["get"]["responses"]["401"]
    return yaml.safe_dump(spec)


async def test_ambiguous_case_pauses_and_resumes(monkeypatch, tmp_path):
    monkeypatch.delenv("SEEDED_BUGS", raising=False)
    monkeypatch.delenv("FAULTS", raising=False)
    config = RunConfig(base_url="http://target", interactive=True)
    graph = build_graph(InMemorySaver())
    cfg = {"configurable": {"thread_id": "ask"}, "recursion_limit": recursion_limit(config.model_dump())}
    deps = Deps(llm=FakeLLM(), http_transport=httpx.ASGITransport(app=target_app), backoff_scale=0,
                reports_dir=str(tmp_path))

    paused = await graph.ainvoke(initial_state("ask", favorites_only_spec_without_401(), config), cfg, context=deps)
    question = paused["__interrupt__"][0].value["question"]
    assert "without a bearer token" in question
    assert (await graph.aget_state(cfg)).values["status"] == "awaiting_input"

    done = await graph.ainvoke(Command(resume="It should return 401"), cfg, context=deps)

    assert "__interrupt__" not in done
    assert done["status"] == "complete"
    no_auth = next(t for t in done["tasks"] if t["kind"] == "no_auth")
    assert no_auth["expected_status"] == [401] and no_auth["outcome"] == "pass"
    assert done["clarifications"][0]["answer"] == "It should return 401"
