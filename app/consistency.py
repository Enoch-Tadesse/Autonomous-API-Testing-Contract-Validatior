"""Cross-request checks that need computation: the run_python tool runs them over saved responses.

Pagination: fetch page 1 and page 2 of a list endpoint, then a small generated script checks that
no item appears on both pages, that the pages do not hold more items than `total`, and that the
order (by `distance`, when present) holds within and across pages.
"""

import json

from app.spec import base_request, set_param

PAGE_PARAM = "page"


def find_list_field(schema: dict | None) -> str | None:
    """Name of the first array property in a response schema, e.g. "results"."""
    for name, prop in (schema or {}).get("properties", {}).items():
        if prop.get("type") == "array":
            return name
    return None


def pagination_tasks(endpoints: list[dict], existing: list[dict], new_task) -> list[dict]:
    """For each endpoint with an integer `page` query parameter and a list response: page 1, page 2, then the check."""
    tasks: list[dict] = []
    for ep in endpoints:
        page = next((p for p in ep["parameters"] if p["name"] == PAGE_PARAM and p["in"] == "query"
                     and p.get("schema", {}).get("type") == "integer"), None)
        ok = sorted(c for c in ep["responses"] if 200 <= c < 300)
        if page is None or not ok or not find_list_field(ep["responses"][ok[0]]):
            continue
        fetched = []
        for number in (1, 2):
            request = base_request(ep)
            # Widen optional numeric filters (e.g. radius) to their maximum so there is more than one page.
            for p in ep["parameters"]:
                schema = p.get("schema", {})
                if p["name"] != PAGE_PARAM and not p.get("required") and "maximum" in schema:
                    set_param(request, p, schema["maximum"])
            set_param(request, page, number)
            task = new_task(existing + tasks, ep, "pagination", f"fetch page {number} for the pagination check", request, ok)
            tasks.append(task)
            fetched.append(task["id"])
        check = new_task(existing + tasks, ep, "consistency", "no duplicates, total and ordering across pages",
                         {"check": "pagination"}, [])
        check.update(tool="run_python", depends_on=fetched, expected_schema=None)
        tasks.append(check)
    return tasks


def pagination_script(bodies: list[dict], list_field: str) -> str:
    """Python source that checks two pages and prints {"checked": [...], "problems": [...]} as JSON."""
    data = json.dumps({"pages": bodies, "field": list_field})
    return f'''import json
data = json.loads({data!r})
pages, field = data["pages"], data["field"]
items = [p.get(field) or [] for p in pages]
problems, checked = [], []

ids = [[i.get("id") for i in page] for page in items]
both = sorted(set(ids[0]) & set(ids[1]) - {{None}})
checked.append("no item on both pages")
if both:
    problems.append(f"items on both page 1 and page 2: {{both}}")

total = pages[0].get("total")
if isinstance(total, int):
    checked.append("item count within total")
    if sum(len(page) for page in items) > total:
        problems.append(f"{{sum(len(page) for page in items)}} items on two pages but total is {{total}}")

def distances(page):
    out = []
    for item in page:
        try:
            out.append(float(item["distance"]))
        except (KeyError, TypeError, ValueError):
            return None
    return out

d1, d2 = distances(items[0]), distances(items[1])
if d1 is not None and d2 is not None:
    checked.append("sorted by distance across pages")
    if d1 != sorted(d1) or d2 != sorted(d2) or (d1 and d2 and d1[-1] > d2[0]):
        problems.append("results are not sorted by distance across pages")

print(json.dumps({{"checked": checked, "problems": problems,
                  "page_sizes": [len(page) for page in items]}}))
'''


def read_script_output(output: str) -> dict | None:
    """The JSON line the check script printed, or None if it printed something else."""
    try:
        result = json.loads(output.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None
    return result if isinstance(result, dict) and "problems" in result else None
