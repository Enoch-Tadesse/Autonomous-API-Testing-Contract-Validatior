"""One case per row of the routing table in spec section 5."""

import time

import pytest

from app.config import RunConfig
from app.graph import after_executor, after_planner, after_validator


def make_state(**overrides):
    config = RunConfig(base_url="http://x", max_steps=10, max_replans=3).model_dump()
    return {"config": config, "started_at": time.time(), "steps": 0, "tool_calls": 0,
            "replans": 0, "current_task_id": "t_001", "action": "next"} | overrides


OUT_OF_BUDGET = {"steps": 10}


@pytest.mark.parametrize("router, overrides, expected", [
    (after_planner, OUT_OF_BUDGET, "reporter"),                                   # planner 1
    (after_planner, {"current_task_id": None}, "reporter"),                       # planner 2
    (after_planner, {}, "executor"),                                              # planner 3
    (after_executor, OUT_OF_BUDGET, "reporter"),                                  # executor 1
    (after_executor, {}, "validator"),                                            # executor 2
    (after_validator, {**OUT_OF_BUDGET, "action": "retry"}, "reporter"),          # validator 1
    (after_validator, {"action": "retry"}, "executor"),                           # validator 2
    (after_validator, {"action": "rerun"}, "executor"),                           # validator 2
    (after_validator, {"action": "ask_user"}, "ask_user"),                        # validator 3
    (after_validator, {"action": "replan", "replans": 1}, "planner"),             # validator 4
    (after_validator, {"action": "replan", "replans": 3}, "planner"),             # validator 5 (replans used up)
    (after_validator, {"action": "next"}, "planner"),                             # validator 5
])
def test_routing_table(router, overrides, expected):
    assert router(make_state(**overrides)) == expected
