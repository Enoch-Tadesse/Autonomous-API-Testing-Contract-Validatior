"""Run every scenario in eval/scenarios.yaml against a real target_api server and write eval/report.md.

    python -m eval.run_eval              # real model if AGENT_MODEL is set, else the fake LLM
    python -m eval.run_eval --fake-llm   # always the fake LLM
    python -m eval.run_eval --only 2,7   # a subset (the report is still written)
"""

import argparse
import asyncio
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import yaml
from dotenv import load_dotenv
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.config import Deps, RunConfig, recursion_limit
from app.graph import build_graph, initial_state
from app.llm import FakeLLM, make_llm
from app.nodes.reporter import citation_check, merge_findings

ROOT = Path(__file__).resolve().parent.parent
SCENARIOS = ROOT / "eval" / "scenarios.yaml"
REPORT = ROOT / "eval" / "report.md"
DEFAULT_SPEC = "target_api/openapi.yaml"


# ---------- target server ----------

def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_target(bugs: list[str], faults: list[str]) -> tuple[subprocess.Popen, str]:
    port = free_port()
    env = {**os.environ, "SEEDED_BUGS": ",".join(bugs), "FAULTS": ",".join(faults)}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "target_api.main:app", "--port", str(port),
                             "--log-level", "warning"], cwd=ROOT, env=env)
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if httpx.get(f"{url}/docs", timeout=0.5).status_code == 200:
                return proc, url
        except httpx.HTTPError:
            time.sleep(0.1)
    proc.kill()
    raise RuntimeError("target_api did not start")


def stop_target(proc: subprocess.Popen) -> None:
    """Graceful stop; FAULT_TIMEOUT_ALWAYS leaves requests hanging, so kill after a few seconds."""
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


# ---------- one run ----------

async def run_agent(scenario: dict, base_url: str, llm, **config_overrides) -> dict:
    config = RunConfig(base_url=base_url, interactive=scenario.get("interactive", False),
                       **(scenario.get("config", {}) | config_overrides))
    run_id = f"eval_{scenario['id']}" + ("_budget" if config_overrides else "")
    graph = build_graph(InMemorySaver())
    cfg = {"configurable": {"thread_id": run_id}, "recursion_limit": recursion_limit(config.model_dump())}
    deps = Deps(llm=llm, backoff_scale=0.2, reports_dir=str(ROOT / "data" / "reports"))
    answers = list(scenario.get("answers", []))

    payload = initial_state(run_id, (ROOT / scenario.get("spec", DEFAULT_SPEC)).read_text(), config)
    while True:
        state = await graph.ainvoke(payload, cfg, context=deps)
        if "__interrupt__" not in state:
            return state
        payload = Command(resume=answers.pop(0) if answers else "skip")


def score(scenario: dict, state: dict) -> list[str]:
    """Problems found; an empty list means the scenario passed."""
    expect, problems = scenario["expect"], []
    findings = merge_findings(state.get("findings", []))
    confirmed = [f for f in findings if f["status"] == "confirmed"]
    classes = {f["class"] for f in confirmed}

    if "confirmed" in expect:
        missing, extra = set(expect["confirmed"]) - classes, classes - set(expect["confirmed"])
        if missing:
            problems.append(f"missed {sorted(missing)}")
        if extra:
            problems.append(f"unexpected confirmed {sorted(extra)}")
    if n := expect.get("min_evidence"):
        thin = [f["id"] for f in confirmed if len(f["evidence_ids"]) < n]
        if thin:
            problems.append(f"{thin} cite fewer than {n} evidence ids")
    if text := expect.get("trace_contains"):
        if not any(text in e["reason"] for e in state["decision_log"]):
            problems.append(f"trace has no '{text}'")
    if endpoint := expect.get("inconclusive_endpoint"):
        bad = [t["id"] for t in state["tasks"] if t["endpoint"] == endpoint and t["outcome"] != "inconclusive"]
        if bad:
            problems.append(f"{bad} on {endpoint} not inconclusive")
    if expect.get("asked") and not state.get("clarifications"):
        problems.append("never asked the user")
    if (status := expect.get("status")) and state["status"] != status:
        problems.append(f"status {state['status']}, expected {status}")
    if not Path(state.get("report_path") or "").is_file():
        problems.append("no report written")
    return problems


# ---------- report ----------

def first_line(states: list[dict], match) -> str:
    for state in states:
        for e in state["decision_log"]:
            if match(e):
                return f"`step {e['step']:02d} {e['node']} {e['decision']}: {e['reason'][:150]}` ({state['run_id']})"
    return "not seen in these runs"


def write_report(results: list[dict], budget_state: dict | None, llm_name: str) -> str:
    states = [r["state"] for r in results]
    expected = sum(len(r["scenario"]["expect"].get("confirmed", [])) for r in results)
    found = sum(len(set(r["scenario"]["expect"].get("confirmed", [])) & r["classes"]) for r in results)
    false_pos = sum(len(r["classes"] - set(r["scenario"]["expect"].get("confirmed", []))) for r in results)
    faulted = [r for r in results if r["scenario"].get("faults")]
    all_findings = [f for s in states for f in merge_findings(s.get("findings", []))]
    supported = sum(len(citation_check(merge_findings(s.get("findings", [])), s["evidence"])[0]) for s in states)
    passed = [r for r in results if not r["problems"]]

    lines = ["# Evaluation report", "",
             f"Model: `{llm_name}`. Each scenario ran against a fresh `target_api` server. "
             "Regenerate with `python -m eval.run_eval`.", "",
             "## Success rate", "",
             f"**{len(passed)}/{len(results)} scenarios passed.**", "",
             "| # | Scenario | Result | Confirmed | Steps | Tool calls | LLM errors | Status | Time |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        s = r["state"]
        lines.append(f"| {r['scenario']['id']} | {r['scenario']['name']} | {'pass' if not r['problems'] else 'FAIL'} | "
                     f"{', '.join(sorted(r['classes'])) or '-'} | {s['steps']} | {s['tool_calls']} | {r['llm_errors']} | {s['status']} | "
                     f"{r['seconds']:.1f}s |")
    pct = lambda a, b: f"{100 * a / b:.0f}%" if b else "n/a"
    lines += ["",
              f"Bug detection rate {pct(found, expected)} ({found}/{expected}) · false positives {false_pos} · "
              f"recovery under faults {pct(sum(not r['problems'] for r in faulted), len(faulted))} · "
              f"findings with valid citations {pct(supported, len(all_findings))} ({supported}/{len(all_findings)}) · "
              f"avg steps {sum(s['steps'] for s in states) / len(states):.1f} · "
              f"avg tool calls {sum(s['tool_calls'] for s in states) / len(states):.1f} · "
              f"partial runs {sum(s['status'] == 'partial' for s in states)}", "",
              "## Failures", ""]
    failures = [r for r in results if r["problems"]]
    lines += [f"- Scenario {r['scenario']['id']} ({r['scenario']['name']}): {'; '.join(r['problems'])}" for r in failures]
    blocked_by = {r["scenario"]["id"]: sum(e["decision"] == "blocked" for e in r["state"]["decision_log"]) for r in results}
    blocked = sum(blocked_by.values())
    if blocked:
        where = ", ".join(f"scenario {i}: {n}" for i, n in blocked_by.items() if n)
        lines.append(f"- {blocked} task(s) were blocked by the 25-calls-per-endpoint cap and reported inconclusive "
                     f"({where}). Reruns, follow-ups and the model's extra tests share the same endpoint budget.")
    llm_errors = sum(r["llm_errors"] for r in results)
    if llm_errors:
        lines.append(f"- {llm_errors} LLM call(s) failed (provider overload or dropped connection); those steps used "
                     "the safe defaults: generated order, no repair, template summary. Findings are unaffected because "
                     "they come from deterministic checks.")
    if not failures and not blocked and not llm_errors:
        lines.append("- None in this run.")

    lines += ["", "## Limitations", "",
              "- Only two endpoints, all GET; no request bodies, mutating calls or real auth flows (one static token).",
              "- Expectations come only from documented status codes and schemas, so business rules are not tested.",
              "- One model, temperature 0, one run per scenario: no variance measured.",
              "- Bugs are seeded and known in advance; the eval measures recall on these four, not on unknown bugs.",
              "", "## Improvements", "",
              "- Generate request bodies from schemas and test POST/PUT with `allow_mutating` against a sandbox.",
              "- Spend the per-endpoint call budget by risk instead of in task order.",
              "- Run each scenario several times and with more than one model to measure stability.",
              "- Persist runs with `AsyncSqliteSaver` so the service survives restarts.",
              "", "## Agentic behavior shown", "",
              f"- **Retry (transient):** {first_line(states, lambda e: 'retry 1/2' in e['reason'])}",
              f"- **Critique and rerun:** {first_line(states, lambda e: e['decision'] == 'api_defect:rerun')}",
              f"- **Replan:** {first_line(states, lambda e: e['decision'] == 'replan')}",
              f"- **Fallback tool:** {first_line(states, lambda e: e['decision'] == 'fallback')}",
              f"- **Ask user:** {first_line(states, lambda e: e['node'] == 'ask_user')}",
              f"- **Budget stop:** {first_line([budget_state] if budget_state else [], lambda e: e['node'] == 'reporter')}"
              + (" (extra run of scenario 2 with `max_steps=6`, not scored)" if budget_state else "")]
    return "\n".join(lines) + "\n"


async def main() -> None:
    load_dotenv()
    p = argparse.ArgumentParser()
    p.add_argument("--fake-llm", action="store_true")
    p.add_argument("--only", help="comma separated scenario ids")
    args = p.parse_args()

    scenarios = yaml.safe_load(SCENARIOS.read_text())
    if args.only:
        wanted = {int(i) for i in args.only.split(",")}
        scenarios = [s for s in scenarios if s["id"] in wanted]
    llm = make_llm(fake=args.fake_llm)
    llm_name = "fake LLM (scripted)" if isinstance(llm, FakeLLM) else os.environ["AGENT_MODEL"]

    results, budget_state = [], None
    for scenario in scenarios:
        proc, url = start_target(scenario.get("bugs", []), scenario.get("faults", []))
        try:
            started, failed_before = time.time(), len(getattr(llm, "failures", []))
            state = await run_agent(scenario, url, llm)
            llm_errors = len(getattr(llm, "failures", [])) - failed_before
            seconds = time.time() - started
            if scenario["id"] == 2:
                # Unscored demo of the budget stop; the fake LLM keeps it off the model's daily quota.
                budget_state = await run_agent(scenario, url, FakeLLM(), max_steps=6)
        finally:
            stop_target(proc)
        problems = score(scenario, state)
        classes = {f["class"] for f in merge_findings(state.get("findings", [])) if f["status"] == "confirmed"}
        results.append({"scenario": scenario, "state": state, "problems": problems, "classes": classes,
                        "seconds": seconds, "llm_errors": llm_errors})
        note = f" ({llm_errors} LLM call(s) failed, safe defaults used)" if llm_errors else ""
        print(f"scenario {scenario['id']}: {'pass' if not problems else 'FAIL ' + '; '.join(problems)}{note}")

    REPORT.write_text(write_report(results, budget_state, llm_name))
    print(f"\nwrote {REPORT.relative_to(ROOT)}")


if __name__ == "__main__":
    asyncio.run(main())
