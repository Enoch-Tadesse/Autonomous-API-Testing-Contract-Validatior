from pathlib import Path

from app.spec import generate_tasks, list_endpoints, load_spec

SPEC_PATH = Path("target_api/openapi.yaml")


def tasks_for_param(name):
    tasks = generate_tasks(list_endpoints(load_spec(SPEC_PATH)))
    return [t for t in tasks if name in t["objective"]]


def test_endpoints_parsed():
    endpoints = {e["key"]: e for e in list_endpoints(load_spec(SPEC_PATH))}
    assert set(endpoints) == {"GET /v1/restaurants/nearby", "GET /v1/favorites"}
    assert endpoints["GET /v1/favorites"]["secured"]
    assert not endpoints["GET /v1/restaurants/nearby"]["secured"]


def test_radius_tasks():
    cases = {}
    for t in tasks_for_param("'radius'"):
        value = t["request"]["query"].get("radius", "missing")
        cases[value] = (t["kind"], t["expected_status"])

    assert cases == {
        0: ("below_min", [400]),
        1: ("normal", [200]),
        50000: ("normal", [200]),
        50001: ("above_max", [400]),
        "missing": ("missing_param", [200]),   # optional, so the default applies
        "abc": ("wrong_type", [400]),
    }


def test_no_auth_task_and_schema_attached():
    tasks = generate_tasks(list_endpoints(load_spec(SPEC_PATH)))
    no_auth = [t for t in tasks if t["kind"] == "no_auth"]
    assert len(no_auth) == 1
    assert no_auth[0]["expected_status"] == [401]
    assert "Authorization" not in no_auth[0]["request"]["headers"]

    normal = tasks[0]
    assert normal["expected_schema"]["required"] == ["page", "total", "results"]
    assert "$ref" not in str(normal["expected_schema"])
