"""Citation check: a finding that cites missing evidence ends up in "Unsupported"."""

from langgraph.runtime import Runtime

from app.config import Deps, RunConfig
from app.llm import FakeLLM, Summary
from app.nodes.reporter import reporter


def finding(key, evidence_ids):
    return {"key": key, "endpoint": "GET /v1/x", "task_id": "t_001", "class": "validation", "status": "confirmed",
            "expected": "HTTP 400", "actual": "HTTP 200", "evidence_ids": evidence_ids, "repro": "GET /v1/x?a=0"}


async def test_finding_with_missing_evidence_is_unsupported(tmp_path):
    state = {
        "run_id": "r1", "base_url": "http://target", "config": RunConfig(base_url="http://target").model_dump(),
        "evidence": [{"id": "e_001", "task_id": "t_001", "tool": "http_request",
                      "request": {"method": "GET", "path": "/v1/x"}, "response": {"status": 200}}],
        "findings": [finding("good", ["e_001"]), finding("bad", ["e_999"])],
        "tasks": [], "decision_log": [], "steps": 2, "tool_calls": 2,
    }
    # The fake LLM's summary cites an id that does not exist, so the template sentence is used instead.
    llm = FakeLLM({"Summary": [Summary(text="F7 shows a bug [e_123].")]})

    update = await reporter(state, Runtime(context=Deps(llm=llm, reports_dir=str(tmp_path))))

    report = update["report_md"]
    unsupported = report.split("## Unsupported")[1].split("##")[0]
    assert "e_999" in unsupported and "e_001" not in unsupported
    assert "[e_001]" in report.split("## Confirmed defects")[1].split("##")[0]
    assert "F7" not in report and "1 confirmed defect(s)" in report
    assert (tmp_path / "r1.md").read_text() == report
