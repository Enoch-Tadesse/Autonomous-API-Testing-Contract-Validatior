import time

from app.config import RunConfig, budget_exhausted


def make_state(**overrides):
    config = RunConfig(base_url="http://x", max_steps=10, max_tool_calls=20, max_seconds=300).model_dump()
    return {"config": config, "started_at": time.time(), "steps": 0, "tool_calls": 0} | overrides


def test_budget_exhausted_at_limit_and_not_before():
    assert budget_exhausted(make_state(steps=9)) is None
    assert budget_exhausted(make_state(steps=10)) == "step_budget"

    assert budget_exhausted(make_state(tool_calls=19)) is None
    assert budget_exhausted(make_state(tool_calls=20)) == "tool_call_budget"

    assert budget_exhausted(make_state(started_at=time.time() - 299)) is None
    assert budget_exhausted(make_state(started_at=time.time() - 300)) == "time_budget"
