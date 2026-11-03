"""Search: Tavily web search through plain httpx. Falls back to rag_search without a key."""

import httpx
from pydantic import BaseModel

from app.tools.base import ToolContext, fail, ok

TAVILY_URL = "https://api.tavily.com/search"


class WebSearchArgs(BaseModel):
    query: str
    max_results: int = 5


async def run(args: WebSearchArgs, ctx: ToolContext) -> dict:
    if not ctx.tavily_api_key:
        return fail("no TAVILY_API_KEY set")
    payload = {"query": args.query, "max_results": min(args.max_results, 5)}
    try:
        async with httpx.AsyncClient(transport=ctx.web_transport, timeout=ctx.timeout_s) as client:
            response = await client.post(TAVILY_URL, json=payload,
                                         headers={"Authorization": f"Bearer {ctx.tavily_api_key}"})
        response.raise_for_status()
        results = response.json().get("results", [])
    except (httpx.HTTPError, ValueError) as e:
        return fail(f"web_search failed: {type(e).__name__}")
    if not results:
        return fail("empty")
    hits = [{"url": r.get("url"), "title": r.get("title"), "snippet": (r.get("content") or "")[:500]}
            for r in results[:5]]
    return ok(output=hits)
