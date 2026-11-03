"""Mask secrets before data goes into state, evidence or the report."""

import json
import re
from typing import Any

MASK = "***"
SECRET_HEADERS = {"authorization", "cookie", "set-cookie", "x-api-key"}
SECRET_FIELD_WORDS = ("password", "token", "secret")
JWT = re.compile(r"eyJ[\w-]+\.[\w-]+\.[\w-]+")
BEARER = re.compile(r"(?i)\bbearer\s+[\w.~+/=-]+")


def is_secret_key(key: str) -> bool:
    k = key.lower()
    return k in SECRET_HEADERS or any(word in k for word in SECRET_FIELD_WORDS)


def redact_text(text: str) -> str:
    return BEARER.sub(f"Bearer {MASK}", JWT.sub(MASK, text))


def redact(value: Any) -> Any:
    """Return a copy with secret keys masked and JWT / bearer strings removed."""
    if isinstance(value, dict):
        return {k: MASK if isinstance(k, str) and is_secret_key(k) else redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_body(body: str) -> str:
    """Redact a response body. JSON bodies have their fields masked, others get the text rules."""
    try:
        data = json.loads(body)
    except ValueError:
        return redact_text(body)
    return json.dumps(redact(data))
