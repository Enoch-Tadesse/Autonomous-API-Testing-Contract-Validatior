"""Phase 1 tests: the target API matches its contract, and bugs/faults switch on by env var."""

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from target_api.main import app, load_openapi

SPEC = load_openapi()
NEARBY = "/v1/restaurants/nearby"
GOOD_QUERY = {"lat": 9.03, "lng": 38.75, "radius": 5000}
AUTH = {"Authorization": "Bearer test-token"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("SEEDED_BUGS", raising=False)
    monkeypatch.delenv("FAULTS", raising=False)
    with TestClient(app) as c:
        c.post("/__admin/reset")
        yield c


def assert_matches(spec_path: str, response):
    """The status is documented for this path and the body fits the documented schema."""
    documented = SPEC["paths"][spec_path]["get"]["responses"]
    assert str(response.status_code) in documented
    schema_ref = documented[str(response.status_code)]["content"]["application/json"]["schema"]
    schema = {**schema_ref, "components": SPEC["components"]}
    errors = list(Draft202012Validator(schema).iter_errors(response.json()))
    assert not errors, [e.message for e in errors]


def test_no_bugs_endpoints_follow_contract(client):
    ok = client.get(NEARBY, params=GOOD_QUERY)
    assert ok.status_code == 200
    assert ok.json()["total"] > 0
    assert_matches("/v1/restaurants/nearby", ok)

    for bad in [{"lat": 9.03}, {**GOOD_QUERY, "radius": "abc"}, {**GOOD_QUERY, "radius": 0},
                {**GOOD_QUERY, "radius": 50001}, {**GOOD_QUERY, "lat": 91}]:
        r = client.get(NEARBY, params=bad)
        assert r.status_code == 400, bad
        assert_matches("/v1/restaurants/nearby", r)

    assert_matches("/v1/favorites", client.get("/v1/favorites", headers=AUTH))
    no_token = client.get("/v1/favorites")
    assert no_token.status_code == 401
    assert_matches("/v1/favorites", no_token)


def bug_symptom(client, bug_id: str) -> bool:
    """True when the behavior described for bug_id is visible."""
    if bug_id == "BUG_RADIUS_MIN":
        return client.get(NEARBY, params={**GOOD_QUERY, "radius": 0}).status_code == 200
    if bug_id == "BUG_DISTANCE_STRING":
        results = client.get(NEARBY, params=GOOD_QUERY).json()["results"]
        return isinstance(results[0]["distance"], str)
    if bug_id == "BUG_MISSING_LNG_500":
        return client.get(NEARBY, params={"lat": 9.03}).status_code == 500
    if bug_id == "BUG_AUTH_BYPASS":
        return client.get("/v1/favorites").status_code == 200
    raise ValueError(bug_id)


BUGS = ["BUG_RADIUS_MIN", "BUG_DISTANCE_STRING", "BUG_MISSING_LNG_500", "BUG_AUTH_BYPASS"]


@pytest.mark.parametrize("bug_id", BUGS)
def test_each_bug_only_when_enabled(client, monkeypatch, bug_id):
    others = [b for b in BUGS if b != bug_id]
    monkeypatch.setenv("SEEDED_BUGS", ",".join(others))
    assert not bug_symptom(client, bug_id)

    monkeypatch.setenv("SEEDED_BUGS", bug_id)
    assert bug_symptom(client, bug_id)


def test_fault_503_then_ok(client, monkeypatch):
    monkeypatch.setenv("FAULTS", "FAULT_503_THEN_OK")
    statuses = [client.get(NEARBY, params=GOOD_QUERY).status_code for _ in range(4)]
    assert statuses == [503, 503, 200, 200]

    client.post("/__admin/reset")
    assert client.get(NEARBY, params=GOOD_QUERY).status_code == 503
