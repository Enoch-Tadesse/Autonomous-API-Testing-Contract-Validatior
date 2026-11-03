"""Each of the five tools called once, plus the safety limits and the fallback switch."""

import json

import httpx

from app.tools import call_tool
from app.tools.base import ToolContext
from app.tools.http_request import HttpArgs, safety_problem
from target_api.main import app as target_app


def ctx(tmp_path=None, **kw) -> ToolContext:
    base = {"base_url": "http://target", "http_transport": httpx.ASGITransport(app=target_app),
            "workspace_dir": str(tmp_path or "workspace"), "auth_token": "test-token"}
    return ToolContext(**(base | kw))


async def test_http_request_fills_in_token():
    args = {"path": "/v1/favorites", "headers": {"Authorization": "Bearer {{AUTH_TOKEN}}"}}
    result = await call_tool("http_request", args, ctx())
    assert result["ok"] and result["status"] == 200


def test_http_safety_gate():
    c = ctx()
    assert safety_problem(HttpArgs(path="http://evil.example/x"), c)
    assert safety_problem(HttpArgs(method="DELETE", path="/v1/favorites"), c)
    assert safety_problem(HttpArgs(method="DELETE", path="/v1/favorites"), ctx(allow_mutating=True)) is None


async def test_web_search_with_stubbed_tavily():
    def tavily(request):
        assert json.loads(request.content)["query"] == "HTTP 422 meaning"
        return httpx.Response(200, json={"results": [{"url": "https://x", "title": "t", "content": "422 means..."}]})

    result = await call_tool("web_search", {"query": "HTTP 422 meaning"},
                             ctx(tavily_api_key="k", web_transport=httpx.MockTransport(tavily)))
    assert result["ok"] and result["output"][0]["url"] == "https://x"
    assert not (await call_tool("web_search", {"query": "x"}, ctx()))["ok"]   # no key -> fails, fallback applies


async def test_run_python_and_its_timeout():
    result = await call_tool("run_python", {"code": "print(len({1, 2, 2, 3}))"}, ctx())
    assert result["ok"] and result["output"].strip() == "3"
    slow = await call_tool("run_python", {"code": "while True: pass"}, ctx())
    assert not slow["ok"] and "timeout" in slow["error"]


async def test_rag_search_finds_workspace_doc_and_reports_empty():
    result = await call_tool("rag_search", {"query": "favorites bearer token 401"}, ctx())
    assert result["ok"] and "api_notes.md" in result["output"][0]["source"]
    assert (await call_tool("rag_search", {"query": "zzzz qqqq"}, ctx()))["error"] == "empty"


async def test_read_file_rejects_path_traversal(tmp_path):
    (tmp_path / "notes.txt").write_text("hello")
    assert (await call_tool("read_file", {"path": "notes.txt"}, ctx(tmp_path)))["output"] == "hello"
    assert not (await call_tool("read_file", {"path": "../../etc/passwd"}, ctx(tmp_path)))["ok"]
