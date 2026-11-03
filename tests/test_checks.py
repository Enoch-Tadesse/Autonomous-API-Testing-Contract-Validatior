import json

from app.checks import failed, run_checks

SCHEMA = {"type": "object", "required": ["distance"], "properties": {"distance": {"type": "number"}}}
TASK = {"kind": "normal", "expected_status": [200], "expected_schema": SCHEMA}
JSON_HEADERS = {"content-type": "application/json"}


def result(status=200, body=None, headers=JSON_HEADERS, error=None):
    return {"error": error, "status": status, "headers": headers,
            "body": json.dumps({"distance": 1.5}) if body is None else body}


def failed_names(task, res):
    return [c["name"] for c in failed(run_checks(task, res))]


def test_good_response_passes_everything():
    assert failed_names(TASK, result()) == []


def test_wrong_status_fails_status_check():
    assert failed_names(TASK, result(status=500)) == ["status_code"]


def test_bad_json_fails_json_parse():
    assert "json_parse" in failed_names(TASK, result(body="<html>oops"))


def test_schema_mismatch_fails_schema_check():
    assert failed_names(TASK, result(body=json.dumps({"distance": "1.5"}))) == ["schema"]


def test_out_of_range_accepted_fails_range_check():
    task = {**TASK, "kind": "below_min", "expected_status": [400], "expected_schema": None}
    assert failed_names(task, result(status=200)) == ["status_code", "range"]


def test_transport_error_stops_other_checks():
    checks = run_checks(TASK, result(status=None, body="", error="timeout"))
    assert [c["name"] for c in checks] == ["transport_ok"]
    assert checks[0]["passed"] is False
