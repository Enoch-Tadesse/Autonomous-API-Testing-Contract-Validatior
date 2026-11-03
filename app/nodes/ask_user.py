"""Ask user (meta-tool). Pauses the run with interrupt(); Command(resume=answer) continues it.

LangGraph re-runs this node from the start on resume, so nothing before
interrupt() may have side effects.
"""

from langgraph.types import interrupt


async def ask_user(state: dict) -> dict:
    answer = interrupt({"question": state["pending_question"]})
    return {
        "clarifications": [{"task_id": state.get("current_task_id"), "question": state["pending_question"],
                            "answer": answer}],
        "pending_question": None,
        "status": "running",
        "decision_log": [{"step": len(state.get("decision_log", [])) + 1, "node": "ask_user",
                          "decision": "answered", "reason": f"user said: {answer}"}],
    }
