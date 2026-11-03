"""Function calling: one HTTP request to the API under test."""

from typing import Any

import httpx
from pydantic import BaseModel

from app.spec import AUTH_PLACEHOLDER
from app.tools.base import ToolContext, fail, ok

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
TRANSIENT_STATUSES = {502, 503, 504}
MAX_CALLS_PER_ENDPOINT = 25


class HttpArgs(BaseModel):
    method: str = "GET"
    path: str
    query: dict[str, Any] = {}
    headers: dict[str, str] = {}
    body: Any = None


def build_url(base_url: str, path: str) -> str:
    return path if path.startswith(("http://", "https://")) else base_url.rstrip("/") + path


def safety_problem(args: HttpArgs, ctx: ToolContext) -> str | None:
    """Reason the call is not allowed, or None. Checked before any network traffic."""
    if not build_url(ctx.base_url, args.path).startswith(ctx.base_url.rstrip("/")):
        return f"URL outside the allowed base URL {ctx.base_url}"
    if args.method.upper() in MUTATING and not ctx.allow_mutating:
        return f"{args.method} needs allow_mutating=true"
    return None


def is_transient(result: dict) -> bool:
    return result.get("error") is not None or result.get("status") in TRANSIENT_STATUSES


def query_value(value: Any) -> str:
    return str(value).lower() if isinstance(value, bool) else str(value)


async def run(args: HttpArgs, ctx: ToolContext) -> dict:
    headers = {k: v.replace(AUTH_PLACEHOLDER, f"Bearer {ctx.auth_token}") for k, v in args.headers.items()}
    query = {k: query_value(v) for k, v in args.query.items()}
    try:
        async with httpx.AsyncClient(transport=ctx.http_transport, timeout=ctx.timeout_s) as client:
            response = await client.request(args.method.upper(), build_url(ctx.base_url, args.path),
                                            params=query, headers=headers,
                                            json=args.body if args.body is not None else None)
    except httpx.TimeoutException:
        return fail("timeout", status=None, headers={}, body="")
    except httpx.HTTPError as e:
        return fail(f"connection_error: {type(e).__name__}", status=None, headers={}, body="")
    result = ok(status=response.status_code, headers=dict(response.headers), body=response.text)
    if response.status_code in TRANSIENT_STATUSES:
        result.update(ok=False, error=f"HTTP {response.status_code}")
    return result
