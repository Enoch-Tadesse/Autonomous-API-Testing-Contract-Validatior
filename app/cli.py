"""Run the agent from the terminal.

    python -m app.cli --spec target_api/openapi.yaml --base-url http://localhost:9000
"""

import argparse
import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.config import Deps, RunConfig, recursion_limit
from app.graph import build_graph, initial_state, new_run_id
from app.llm import FakeLLM, make_llm
from app.nodes.reporter import merge_findings


def parse_args():
    p = argparse.ArgumentParser(description="API contract testing agent")
    p.add_argument("--spec", required=True, help="path to the OpenAPI file")
    p.add_argument("--base-url", required=True)
    p.add_argument("--fake-llm", action="store_true", help="use the scripted fake LLM (no API key needed)")
    p.add_argument("--non-interactive", action="store_true", help="never pause to ask questions")
    p.add_argument("--max-steps", type=int, default=50)
    p.add_argument("--max-tool-calls", type=int, default=60)
    return p.parse_args()


def print_run(state: dict) -> None:
    print("\nDecision log")
    for e in state.get("decision_log", []):
        print(f"  step {e['step']:02d} {e['node']:<9} {e['decision']:<22} {e['reason']}")

    print(f"\nStatus: {state['status']}" + (f" (stopped by {state['stop_reason']})" if state.get("stop_reason") else ""))
    print(f"Steps {state['steps']}, tool calls {state['tool_calls']}, replans {state.get('replans', 0)}")
    findings = merge_findings(state.get("findings", []))
    print(f"\nFindings ({len(findings)})")
    for f in findings:
        print(f"  {f['id']} [{f['status']}] {f['class']} {f['endpoint']}: expected {f['expected']}, "
              f"got {f['actual']}\n      repro: {f['repro']}   evidence: {', '.join(f['evidence_ids'])}")
    if state.get("report_path"):
        print(f"\nReport: {state['report_path']}")


async def main() -> None:
    load_dotenv()
    args = parse_args()
    llm = make_llm(fake=args.fake_llm)
    if isinstance(llm, FakeLLM):
        print("Using the fake LLM (set AGENT_MODEL and GEMINI_API_KEY in .env for the real one).")
    else:
        print(f"Using {os.environ['AGENT_MODEL']}.")

    config = RunConfig(base_url=args.base_url, interactive=not args.non_interactive,
                       max_steps=args.max_steps, max_tool_calls=args.max_tool_calls)
    run_id = new_run_id()
    graph = build_graph(InMemorySaver())
    cfg = {"configurable": {"thread_id": run_id}, "recursion_limit": recursion_limit(config.model_dump())}
    deps = Deps(llm=llm)

    payload = initial_state(run_id, Path(args.spec).read_text(), config)
    while True:
        result = await graph.ainvoke(payload, cfg, context=deps)
        if "__interrupt__" not in result:
            break
        question = result["__interrupt__"][0].value["question"]
        payload = Command(resume=input(f"\n{question}\n> "))
    print_run(result)


if __name__ == "__main__":
    asyncio.run(main())
