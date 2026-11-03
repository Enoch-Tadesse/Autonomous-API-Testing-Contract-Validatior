"""What every tool receives and returns."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolContext:
    base_url: str
    allow_mutating: bool = False
    timeout_s: float = 10.0
    http_transport: Any = None
    web_transport: Any = None
    auth_token: str = ""
    tavily_api_key: str = ""
    workspace_dir: str = "./workspace"
    endpoints: list[dict] = field(default_factory=list)


def ok(**data) -> dict:
    return {"ok": True, "error": None, **data}


def fail(error: str, **data) -> dict:
    return {"ok": False, "error": error, **data}
