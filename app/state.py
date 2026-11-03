"""AgentState and the small record types it holds.

Everything is plain JSON-friendly dicts and lists so the state is easy to
checkpoint and to return from FastAPI. There is no message list.
"""

from operator import add
from typing import Annotated, Any, Literal, TypedDict


class Task(TypedDict):
    id: str                       # "t_007"
    endpoint: str                 # "GET /v1/restaurants/nearby"
    kind: str                     # normal | missing_param | wrong_type | below_min | above_max | no_auth | extra
    tool: str                     # tool that runs this task, usually "http_request"
    param: str | None             # parameter under test, None for whole-request tasks
    objective: str
    request: dict[str, Any]       # method, path, query, headers, body (or the tool's args for other tools)
    expected_status: list[int]    # empty list = no documented expectation (ambiguous)
    expected_schema: dict | None
    status: Literal["pending", "in_progress", "done", "failed"]
    outcome: Literal["unknown", "pass", "defect", "inconclusive"]
    attempts: int
    parent_id: str | None         # set on follow-up tasks
    depends_on: list[str]         # tasks whose results this one needs (e.g. the pages a check compares)


class AgentState(TypedDict, total=False):
    run_id: str
    base_url: str
    config: dict                              # RunConfig as dict
    started_at: float                         # time.time() when the run started
    spec_text: str                            # the OpenAPI document (YAML or JSON text)
    endpoints: list[dict]                     # parsed from OpenAPI
    planned: bool                             # the planning LLM call has run (after reading project notes)
    tasks: list[Task]                         # the plan / to-do list (nodes replace the whole list)
    current_task_id: str | None
    tool_name: str | None
    tool_args: dict[str, Any]
    last_result: dict | None                  # raw result of the last tool call (status, error, evidence_id)
    evidence: Annotated[list[dict], add]      # {id, task_id, tool, request, response, checks}
    critiques: Annotated[list[dict], add]     # {task_id, issue, feedback, action}
    findings: Annotated[list[dict], add]      # {id, endpoint, class, status, expected, actual, evidence_ids, repro}
    decision_log: Annotated[list[dict], add]  # {step, node, decision, reason}
    clarifications: Annotated[list[dict], add]
    pending_question: str | None
    action: str                               # validator's verdict: next | retry | rerun | replan | ask_user
    retries: dict[str, int]                   # "task_id:tool" -> retries used
    tool_failures: dict[str, int]             # tool -> consecutive failures
    steps: int
    tool_calls: int
    replans: int
    status: Literal["running", "awaiting_input", "complete", "partial"]
    stop_reason: str | None
    report_path: str | None                   # written by the reporter
    report_md: str | None
