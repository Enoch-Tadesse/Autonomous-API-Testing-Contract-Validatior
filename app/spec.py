"""OpenAPI -> endpoints -> generated test tasks, in plain Python.

Run it to see the tasks for a spec:
    python -m app.spec target_api/openapi.yaml
"""

import copy
import sys
from pathlib import Path
from typing import Any

import yaml

from app.state import Task

HTTP_METHODS = ("get", "post", "put", "patch", "delete")
AUTH_STATUSES = (401, 403)
# Secrets never go into a task. The http_request tool swaps this for the real token.
AUTH_PLACEHOLDER = "Bearer {{AUTH_TOKEN}}"


# ---------- parsing ----------

def load_spec(source: str | Path) -> dict:
    """Load an OpenAPI document from a Path or from YAML/JSON text (JSON is valid YAML)."""
    if isinstance(source, Path):
        source = source.read_text()
    spec = yaml.safe_load(source)
    return resolve_refs(spec, spec)


def resolve_refs(node: Any, root: dict) -> Any:
    """Replace every local {"$ref": "#/..."} with a copy of its target."""
    if isinstance(node, dict):
        if "$ref" in node:
            target = root
            for part in node["$ref"].removeprefix("#/").split("/"):
                target = target[part]
            return resolve_refs(copy.deepcopy(target), root)
        return {k: resolve_refs(v, root) for k, v in node.items()}
    if isinstance(node, list):
        return [resolve_refs(v, root) for v in node]
    return node


def list_endpoints(spec: dict) -> list[dict]:
    """One plain dict per operation, with documented responses keyed by int status."""
    global_security = spec.get("security", [])
    endpoints = []
    for path, item in spec.get("paths", {}).items():
        shared_params = item.get("parameters", [])
        for method in HTTP_METHODS:
            op = item.get(method)
            if op is None:
                continue
            responses = {}
            for code, resp in op.get("responses", {}).items():
                if str(code).isdigit():
                    schema = resp.get("content", {}).get("application/json", {}).get("schema")
                    responses[int(code)] = schema
            endpoints.append({
                "key": f"{method.upper()} {path}",
                "method": method.upper(),
                "path": path,
                "parameters": shared_params + op.get("parameters", []),
                "secured": bool(op.get("security", global_security)),
                "responses": responses,
            })
    return endpoints


# ---------- task generation ----------

def valid_value(schema: dict) -> Any:
    """A value that the schema accepts: example, default, middle of the range, or a simple stand-in."""
    if schema.get("examples"):
        return schema["examples"][0]
    for key in ("example", "default"):
        if key in schema:
            return schema[key]
    kind = schema.get("type", "string")
    if kind in ("integer", "number"):
        low, high = schema.get("minimum"), schema.get("maximum")
        if low is not None and high is not None:
            mid = (low + high) / 2
            return int(mid) if kind == "integer" else mid
        if low is not None:
            return low
        return 1
    if kind == "boolean":
        return True
    if schema.get("enum"):
        return schema["enum"][0]
    return "test"


def statuses(endpoint: dict, low: int, high: int, exclude=()) -> list[int]:
    return sorted(c for c in endpoint["responses"] if low <= c < high and c not in exclude)


def client_error_statuses(endpoint: dict) -> list[int]:
    """Documented 4xx codes for bad input (auth codes excluded). Empty = not documented."""
    return statuses(endpoint, 400, 500, exclude=AUTH_STATUSES)


def base_request(endpoint: dict) -> dict:
    """A request that should succeed: every required parameter set to a valid value."""
    request = {"method": endpoint["method"], "path": endpoint["path"], "query": {}, "headers": {}, "body": None}
    for p in endpoint["parameters"]:
        if p.get("required") or p["in"] == "path":
            set_param(request, p, valid_value(p.get("schema", {})))
    if endpoint["secured"]:
        request["headers"]["Authorization"] = AUTH_PLACEHOLDER
    return request


def set_param(request: dict, param: dict, value: Any) -> None:
    where = param["in"]
    if where == "query":
        request["query"][param["name"]] = value
    elif where == "header":
        request["headers"][param["name"]] = str(value)
    elif where == "path":
        request["path"] = request["path"].replace("{" + param["name"] + "}", str(value))


def drop_param(request: dict, param: dict) -> None:
    if param["in"] == "query":
        request["query"].pop(param["name"], None)
    elif param["in"] == "header":
        request["headers"].pop(param["name"], None)


def param_cases(endpoint: dict, param: dict) -> list[tuple[str, str, Any, list[int]]]:
    """(kind, objective, value, expected_status) for one parameter. value None means 'leave it out'."""
    schema = param.get("schema", {})
    name, kind = param["name"], schema.get("type", "string")
    ok, bad = statuses(endpoint, 200, 300), client_error_statuses(endpoint)
    step = 1 if kind == "integer" else 1.0
    cases = []

    # Leaving out an optional parameter is the same request as the normal case, so only required ones get a test.
    if param["in"] != "path" and param.get("required"):
        cases.append(("missing_param", f"omit required '{name}'", None, bad))
    if kind in ("integer", "number"):
        cases.append(("wrong_type", f"'{name}' as a non-numeric string", "abc", bad))
    if "minimum" in schema:
        low = schema["minimum"]
        cases.append(("normal", f"'{name}' at its minimum {low}", low, ok))
        cases.append(("below_min", f"'{name}' just below its minimum", low - step, bad))
    if "maximum" in schema:
        high = schema["maximum"]
        cases.append(("normal", f"'{name}' at its maximum {high}", high, ok))
        cases.append(("above_max", f"'{name}' just above its maximum", high + step, bad))
    return cases


def generate_tasks(endpoints: list[dict]) -> list[Task]:
    """Normal case, then per-parameter edge cases, then a no-token case for secured endpoints."""
    tasks: list[Task] = []

    def add(endpoint: dict, kind: str, objective: str, request: dict, expected: list[int], param: str | None = None):
        schema = endpoint["responses"].get(expected[0]) if expected else None
        tasks.append(Task(
            id=f"t_{len(tasks) + 1:03d}", endpoint=endpoint["key"], kind=kind, tool="http_request", param=param,
            objective=objective,
            request=request, expected_status=expected, expected_schema=schema,
            status="pending", outcome="unknown", attempts=0, parent_id=None,
        ))

    for ep in endpoints:
        add(ep, "normal", "valid request with required parameters", base_request(ep), statuses(ep, 200, 300))

        for param in ep["parameters"]:
            for kind, objective, value, expected in param_cases(ep, param):
                request = base_request(ep)
                if value is None:
                    drop_param(request, param)
                else:
                    set_param(request, param, value)
                add(ep, kind, objective, request, expected, param=param["name"])

        if ep["secured"]:
            request = base_request(ep)
            request["headers"].pop("Authorization")
            auth_codes = [c for c in statuses(ep, 400, 500) if c in AUTH_STATUSES]
            add(ep, "no_auth", "request without a bearer token", request, auth_codes)
    return tasks


def format_task(t: Task) -> str:
    query = "&".join(f"{k}={v}" for k, v in t["request"]["query"].items())
    url = t["request"]["path"] + (f"?{query}" if query else "")
    expected = ",".join(map(str, t["expected_status"])) or "??"
    token = " +token" if "Authorization" in t["request"]["headers"] else ""
    return f"{t['id']}  {t['kind']:<13} {t['request']['method']} {url}{token}  -> expect {expected}   ({t['objective']})"


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "target_api/openapi.yaml"
    endpoints = list_endpoints(load_spec(Path(path)))
    tasks = generate_tasks(endpoints)
    print(f"{len(endpoints)} endpoints, {len(tasks)} tasks\n")
    for task in tasks:
        print(format_task(task))
