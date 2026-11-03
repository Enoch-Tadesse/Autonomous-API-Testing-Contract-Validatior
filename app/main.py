"""FastAPI wrapper. It only starts runs and reports their state; the graph does the work.

    uvicorn app.main:app

The graph is built once at startup. Each run is an asyncio task under its own
thread_id (= run_id). The run registry is a plain dict, so runs live as long as
the process. Swap InMemorySaver for AsyncSqliteSaver in lifespan to keep them.
"""

import asyncio
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pydantic import BaseModel

from app.config import Deps, RunConfig, recursion_limit
from app.graph import build_graph, initial_state, new_run_id
from app.llm import make_llm
from app.nodes.reporter import merge_findings

runs: dict[str, dict] = {}   # run_id -> {"task": asyncio.Task, "status": str, "question": str | None, "config": dict}


class StartRunRequest(BaseModel):
    spec: str                    # OpenAPI document as YAML or JSON text
    base_url: str
    config: dict = {}            # any RunConfig field except base_url


class ResumeBody(BaseModel):
    answer: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_dotenv()
    app.state.graph = build_graph(InMemorySaver())
    # Tests set app.state.deps (fake LLM, in-process transport) before startup.
    if getattr(app.state, "deps", None) is None:
        app.state.deps = Deps(llm=make_llm())
    yield
    for run in runs.values():
        run["task"].cancel()


app = FastAPI(title="API Testing Agent", lifespan=lifespan)


def graph_config(run_id: str) -> dict:
    return {"configurable": {"thread_id": run_id}, "recursion_limit": recursion_limit(runs[run_id]["config"])}


async def drive(run_id: str, payload) -> None:
    try:
        result = await app.state.graph.ainvoke(payload, graph_config(run_id), context=app.state.deps)
    except Exception as e:  # keep the service up and tell the caller what happened
        runs[run_id].update(status="error", question=None, error=f"{type(e).__name__}: {e}")
        return
    if "__interrupt__" in result:
        runs[run_id].update(status="awaiting_input", question=result["__interrupt__"][0].value["question"])
    else:
        runs[run_id].update(status=result["status"], question=None)


def get_run(run_id: str) -> dict:
    if run_id not in runs:
        raise HTTPException(404, f"unknown run {run_id}")
    return runs[run_id]


async def run_values(run_id: str) -> dict:
    return (await app.state.graph.aget_state(graph_config(run_id))).values


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/runs", status_code=202)
async def start_run(req: StartRunRequest):
    config = RunConfig(base_url=req.base_url, **{k: v for k, v in req.config.items() if k != "base_url"})
    run_id = new_run_id()
    runs[run_id] = {"status": "running", "question": None, "config": config.model_dump()}
    payload = initial_state(run_id, req.spec, config)
    runs[run_id]["task"] = asyncio.create_task(drive(run_id, payload))
    return {"run_id": run_id, "status": "running"}


@app.get("/runs/{run_id}")
async def run_status(run_id: str):
    run = get_run(run_id)
    values = await run_values(run_id)
    tasks = values.get("tasks", [])
    return {
        "run_id": run_id,
        "status": run["status"],
        "pending_question": run["question"],
        "error": run.get("error"),
        "steps": values.get("steps", 0),
        "tool_calls": values.get("tool_calls", 0),
        "replans": values.get("replans", 0),
        "tasks_done": sum(t["status"] == "done" for t in tasks),
        "tasks_total": len(tasks),
        "findings": len(merge_findings(values.get("findings", []))),
        "stop_reason": values.get("stop_reason"),
    }


@app.get("/runs/{run_id}/trace")
async def run_trace(run_id: str):
    get_run(run_id)
    return {"run_id": run_id, "decision_log": (await run_values(run_id)).get("decision_log", [])}


@app.post("/runs/{run_id}/resume", status_code=202)
async def resume(run_id: str, body: ResumeBody):
    run = get_run(run_id)
    if run["status"] != "awaiting_input":
        raise HTTPException(409, f"run is {run['status']}, not awaiting input")
    run.update(status="running", question=None)
    run["task"] = asyncio.create_task(drive(run_id, Command(resume=body.answer)))
    return {"run_id": run_id, "status": "running"}


@app.get("/runs/{run_id}/report", response_class=PlainTextResponse)
async def report(run_id: str):
    run = get_run(run_id)
    if run["status"] not in ("complete", "partial"):
        raise HTTPException(409, f"run is {run['status']}, the report is ready once it is complete or partial")
    return (await run_values(run_id)).get("report_md") or ""
