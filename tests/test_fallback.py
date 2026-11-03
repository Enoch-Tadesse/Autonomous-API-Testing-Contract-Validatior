"""The executor switches to the FALLBACKS tool when a tool fails."""

from langgraph.runtime import Runtime

from app.config import Deps, RunConfig
from app.llm import FakeLLM
from app.nodes.executor import executor


async def test_web_search_without_key_falls_back_to_rag_search():
    task = {"id": "t_001", "endpoint": "docs", "kind": "extra", "tool": "web_search", "param": None,
            "objective": "look up 401 meaning", "request": {"query": "bearer token 401"}, "expected_status": [],
            "expected_schema": None, "status": "in_progress", "outcome": "unknown", "attempts": 0, "parent_id": None}
    state = {"config": RunConfig(base_url="http://target").model_dump(), "base_url": "http://target",
             "tasks": [task], "current_task_id": "t_001", "tool_name": "web_search",
             "tool_args": task["request"], "decision_log": [], "evidence": []}
    deps = Deps(llm=FakeLLM(), tavily_api_key="", backoff_scale=0)

    update = await executor(state, Runtime(context=deps))

    assert update["last_result"]["fallback_used"] and update["last_result"]["tool"] == "rag_search"
    assert update["last_result"]["ok"]
    assert update["tool_failures"]["rag_search"] == 0
    assert any(e["decision"] == "fallback" for e in update["decision_log"])
