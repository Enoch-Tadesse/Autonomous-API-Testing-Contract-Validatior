import json

from app.redact import MASK, redact, redact_body

JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJl"


def test_authorization_header_and_token_field_are_hidden():
    data = {
        "headers": {"Authorization": "Bearer abc123", "Accept": "application/json"},
        "body": {"token": "abc123", "user": {"name": "sam", "password": "pw"}},
    }
    clean = redact(data)
    assert clean["headers"]["Authorization"] == MASK
    assert clean["headers"]["Accept"] == "application/json"
    assert clean["body"]["token"] == MASK
    assert clean["body"]["user"] == {"name": "sam", "password": MASK}
    assert "abc123" not in json.dumps(clean)


def test_jwt_and_bearer_strings_are_hidden():
    assert JWT not in redact({"note": f"got {JWT} back"})["note"]
    assert "abc123" not in redact_body("error: Bearer abc123 rejected")
    assert redact_body("The endpoint needs a Bearer token.") == "The endpoint needs a Bearer token."
    assert json.loads(redact_body(json.dumps({"access_token": "abc"})))["access_token"] == MASK
