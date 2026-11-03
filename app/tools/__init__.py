"""The five tools, their fallbacks and a single place to call them."""

from pydantic import ValidationError

from app.tools import http_request, rag_search, read_file, run_python, web_search
from app.tools.base import ToolContext, fail

# name -> (argument model, async run function)
TOOLS = {
    "http_request": (http_request.HttpArgs, http_request.run),
    "web_search": (web_search.WebSearchArgs, web_search.run),
    "run_python": (run_python.RunPythonArgs, run_python.run),
    "rag_search": (rag_search.RagSearchArgs, rag_search.run),
    "read_file": (read_file.ReadFileArgs, read_file.run),
}

FALLBACKS = {
    "web_search": "rag_search",
    "rag_search": "web_search",
    "run_python": None,
    "read_file": "rag_search",
    "http_request": None,       # no substitute: the task becomes inconclusive
}

UNAVAILABLE_AFTER = 5           # consecutive failures before the planner stops choosing a tool


def fallback_args(args: dict) -> dict:
    """Arguments for a search fallback, built from whatever the failed tool was given."""
    return {"query": args.get("query") or args.get("path") or ""}


async def call_tool(name: str, args: dict, ctx: ToolContext) -> dict:
    model, run = TOOLS[name]
    try:
        parsed = model(**args)
    except ValidationError as e:
        return fail(f"bad arguments: {e.errors()[0]['msg']}")
    return await run(parsed, ctx)
