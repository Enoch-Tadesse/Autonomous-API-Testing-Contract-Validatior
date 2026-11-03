import pytest

from target_api import main as target


@pytest.fixture(autouse=True)
def reset_target_overrides():
    """Runtime bug/fault switches (web demo) are module state; never let them leak between tests."""
    target.overrides.update(SEEDED_BUGS=None, FAULTS=None)
    yield
    target.overrides.update(SEEDED_BUGS=None, FAULTS=None)
