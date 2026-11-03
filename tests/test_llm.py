"""ChatLLM: a failing model call falls back to the safe default instead of killing the run."""

from app.llm import ChatLLM, Critique, PlanOrder


class BrokenModel:
    def with_structured_output(self, schema):
        return self

    async def ainvoke(self, prompt):
        raise RuntimeError("quota exceeded")


class WorkingModel:
    def with_structured_output(self, schema):
        self.schema = schema
        return self

    async def ainvoke(self, prompt):
        return self.schema(order=["t_002", "t_001"], rationale="auth first")


async def test_model_error_returns_safe_default():
    critique = await ChatLLM(BrokenModel()).structured(Critique, "classify")
    assert critique.action == "next" and "quota exceeded" in critique.rationale


async def test_model_answer_is_returned():
    plan = await ChatLLM(WorkingModel()).structured(PlanOrder, "plan")
    assert plan.order == ["t_002", "t_001"]
