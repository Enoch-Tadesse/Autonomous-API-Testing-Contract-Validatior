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


async def test_one_run_uses_all_five_tools(monkeypatch, tmp_path):
    """read_file (project notes), web_search -> rag_search (undocumented case), http_request (tests),
    run_python (pagination check over two fetched pages)."""
    monkeypatch.setenv("SEEDED_BUGS", "")
    monkeypatch.setenv("FAULTS", "")
    fault_counters.clear()
    config = RunConfig(base_url="http://target", interactive=False)
    graph = build_graph(InMemorySaver())
    cfg = {"configurable": {"thread_id": "tools"}, "recursion_limit": recursion_limit(config.model_dump())}
    deps = Deps(llm=FakeLLM(), http_transport=httpx.ASGITransport(app=target_app), backoff_scale=0,
                reports_dir=str(tmp_path), tavily_api_key="")
    spec = Path("target_api/openapi_undocumented.yaml").read_text()
    state = await graph.ainvoke(initial_state("tools", spec, config), cfg, context=deps)

    attempted = {e["tool"] for e in state["evidence"]}
    fell_back = [e for e in state["decision_log"] if e["decision"] == "fallback" and "web_search" in e["reason"]]
    assert {"http_request", "read_file", "rag_search", "run_python"} <= attempted and fell_back

    check = next(t for t in state["tasks"] if t["kind"] == "consistency")
    assert check["outcome"] == "pass"            # the clean API paginates correctly
    plan = next(e for e in state["decision_log"] if e["decision"] == "plan")
    assert "using the project notes" in plan["reason"]


async def test_page_overlap_is_only_caught_by_the_run_python_check(monkeypatch, tmp_path):
    state = await run_agent(monkeypatch, tmp_path, bugs="BUG_PAGE_OVERLAP")

    findings = merge_findings(state["findings"])
    assert [f["class"] for f in findings] == ["pagination"]      # every single-response test still passes
    assert findings[0]["status"] == "suspected"
    assert "items on both page 1 and page 2" in findings[0]["actual"]

    check = next(t for t in state["tasks"] if t["kind"] == "consistency")
    assert check["outcome"] == "defect"
    tools = {e["id"]: e["tool"] for e in state["evidence"]}
    assert sorted(tools[i] for i in findings[0]["evidence_ids"]) == ["http_request", "http_request", "run_python"]
