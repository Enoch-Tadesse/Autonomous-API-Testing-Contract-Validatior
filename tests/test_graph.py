"""End-to-end runs of the whole graph with the fake LLM against target_api (in process)."""

from pathlib import Path

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.config import Deps, RunConfig, recursion_limit
from app.graph import build_graph, initial_state
from app.llm import FakeLLM
from app.nodes.reporter import merge_findings
from target_api.main import app as target_app, fault_counters

SPEC_TEXT = Path("target_api/openapi.yaml").read_text()


async def run_agent(monkeypatch, tmp_path, bugs="", faults="", **config_overrides):
    monkeypatch.setenv("SEEDED_BUGS", bugs)
    monkeypatch.setenv("FAULTS", faults)
    fault_counters.clear()
    config = RunConfig(base_url="http://target", interactive=False, **config_overrides)
    graph = build_graph(InMemorySaver())
    cfg = {"configurable": {"thread_id": "test"}, "recursion_limit": recursion_limit(config.model_dump())}
    deps = Deps(llm=FakeLLM(), http_transport=httpx.ASGITransport(app=target_app), backoff_scale=0,
                reports_dir=str(tmp_path))
    return await graph.ainvoke(initial_state("test", SPEC_TEXT, config), cfg, context=deps)


async def test_finds_radius_bug_end_to_end(monkeypatch, tmp_path):
    state = await run_agent(monkeypatch, tmp_path, bugs="BUG_RADIUS_MIN", faults="FAULT_503_THEN_OK")

    assert state["status"] == "complete"
    findings = merge_findings(state["findings"])
    radius = [f for f in findings if "|radius|" in f["key"]]
    assert len(radius) == 1 and radius[0]["status"] == "confirmed"
    evidence_ids = {e["id"] for e in state["evidence"]}
    assert len(radius[0]["evidence_ids"]) >= 2 and set(radius[0]["evidence_ids"]) <= evidence_ids

    decisions = [e["decision"] for e in state["decision_log"]]
    assert decisions.index("api_defect:rerun") < decisions.index("api_defect:replan") < decisions.index("replan")
    assert any("retry 1/2" in e["reason"] for e in state["decision_log"])   # the 503 fault was retried

    report = Path(state["report_path"]).read_text()
    assert "## Confirmed defects" in report and f"[{radius[0]['evidence_ids'][0]}]" in report


async def test_no_bugs_no_findings(monkeypatch, tmp_path):
    state = await run_agent(monkeypatch, tmp_path)
    assert state["status"] == "complete"
    assert state["findings"] == []


async def test_small_budget_stops_partial_without_recursion_error(monkeypatch, tmp_path):
    state = await run_agent(monkeypatch, tmp_path, max_steps=3)
    assert state["status"] == "partial"
    assert state["stop_reason"] == "step_budget"
    assert state["steps"] == 3
    assert "Partial run" in state["report_md"] and "step_budget" in state["report_md"]
