"""Deterministic checks that run on every tool result before any LLM sees it.

Each check returns {name, passed, detail}. passed is None when the check does
not apply (for example a schema check when there is no schema to check against).

The HTTP result shape (produced by the http_request tool) is:
    {"error": str | None, "status": int | None, "headers": dict, "body": str}
"""

import json

from jsonschema import Draft202012Validator

INVALID_INPUT_KINDS = ("missing_param", "wrong_type", "below_min", "above_max")
RANGE_KINDS = ("below_min", "above_max")


def check(name: str, passed: bool | None, detail: str = "") -> dict:
    return {"name": name, "passed": passed, "detail": detail}


def transport_ok(result: dict) -> dict:
    if result.get("error"):
        return check("transport_ok", False, result["error"])
    return check("transport_ok", True, f"HTTP {result.get('status')}")


def non_empty(result: dict) -> dict:
    body = result.get("body") or ""
    return check("non_empty", bool(body.strip()), f"{len(body)} bytes")


def status_code(task: dict, result: dict) -> dict:
    expected = task["expected_status"]
    if not expected:
        return check("status_code", None, "no documented expectation")
    actual = result.get("status")
    return check("status_code", actual in expected, f"expected {expected}, got {actual}")


def json_parse(result: dict) -> dict:
    try:
        json.loads(result.get("body") or "")
    except ValueError as e:
        return check("json_parse", False, f"body is not JSON: {e}")
    return check("json_parse", True)


def content_type(result: dict) -> dict:
    headers = {k.lower(): v for k, v in (result.get("headers") or {}).items()}
    value = headers.get("content-type", "")
    return check("content_type", "application/json" in value, value or "missing")


def schema(task: dict, result: dict) -> dict:
    """Validate the body against the expected schema, only when the status was the expected one."""
    if not task.get("expected_schema"):
        return check("schema", None, "no schema documented")
    if result.get("status") not in task["expected_status"]:
        return check("schema", None, "status differs, schema not applicable")
    try:
        body = json.loads(result.get("body") or "")
    except ValueError:
        return check("schema", None, "body is not JSON")
    errors = list(Draft202012Validator(task["expected_schema"]).iter_errors(body))[:3]
    if errors:
        detail = "; ".join(f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}" for e in errors)
        return check("schema", False, detail)
    return check("schema", True)


def range_check(task: dict, result: dict) -> dict:
    """An out-of-range input must be rejected with a 4xx."""
    if task["kind"] not in RANGE_KINDS:
        return check("range", None, "not a range test")
    actual = result.get("status") or 0
    return check("range", 400 <= actual < 500, f"out-of-range input got HTTP {actual}")


def run_checks(task: dict, result: dict) -> list[dict]:
    """All checks for one HTTP result. If the transport failed, the rest are skipped."""
    first = transport_ok(result)
    if not first["passed"]:
        return [first]
    return [
        first,
        non_empty(result),
        status_code(task, result),
        json_parse(result),
        content_type(result),
        schema(task, result),
        range_check(task, result),
    ]


def failed(checks: list[dict]) -> list[dict]:
    return [c for c in checks if c["passed"] is False]
