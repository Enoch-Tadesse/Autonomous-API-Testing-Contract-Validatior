"""FastAPI wrapper. It only starts runs and reports their state; the graph does the work.

    uvicorn app.main:app

The graph is built once at startup. Each run is an asyncio task under its own
thread_id (= run_id). The run registry is a plain dict, so runs live as long as
the process. Swap InMemorySaver for AsyncSqliteSaver in lifespan to keep them.
"""

import asyncio
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pydantic import BaseModel

from app.config import Deps, RunConfig, recursion_limit
from app.graph import build_graph, initial_state, new_run_id
from app.llm import make_llm
from app.nodes.reporter import citation_check, merge_findings, statistics

ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIST = ROOT / "frontend" / "dist"
DEMO_SPECS = {
    "standard": ("Restaurant Finder API", ROOT / "target_api" / "openapi.yaml"),
    "undocumented": ("Restaurant Finder API, favorites 401 undocumented (agent asks you)",
                     ROOT / "target_api" / "openapi_undocumented.yaml"),
}

runs: dict[str, dict] = {}   # run_id -> {"task", "status", "question", "config", "created_at", "label", "target"}


class TargetConfig(BaseModel):
    bugs: list[str] = []
    faults: list[str] = []


class StartRunRequest(BaseModel):
    spec: str                    # OpenAPI document as YAML or JSON text
    base_url: str
    config: dict = {}            # any RunConfig field except base_url
    target: TargetConfig | None = None   # demo only: switch target_api bugs/faults before the run
    label: str | None = None     # demo only: a name for the run list


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
    if req.target is not None:
        await target_admin(req.base_url, "POST", req.target.model_dump())
    run_id = new_run_id()
    runs[run_id] = {"status": "running", "question": None, "config": config.model_dump(), "created_at": time.time(),
                    "label": req.label or "custom spec", "target": req.target.model_dump() if req.target else None}
    payload = initial_state(run_id, req.spec, config)
    runs[run_id]["task"] = asyncio.create_task(drive(run_id, payload))
    return {"run_id": run_id, "status": "running"}


@app.get("/runs")
async def list_runs():
    rows = [{"run_id": i, "status": r["status"], "created_at": r.get("created_at"), "label": r.get("label"),
             "target": r.get("target")} for i, r in runs.items()]
    return {"runs": sorted(rows, key=lambda r: r["created_at"] or 0, reverse=True)}


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


@app.get("/runs/{run_id}/details")
async def run_details(run_id: str):
    """Everything the web demo shows besides the log: tasks, citation-checked findings, evidence, statistics."""
    get_run(run_id)
    values = await run_values(run_id)
    supported, unsupported = citation_check(merge_findings(values.get("findings", [])), values.get("evidence", []))
    return {
        "run_id": run_id,
        "base_url": values.get("base_url"),
        "tasks": values.get("tasks", []),
        "findings": supported,
        "unsupported": unsupported,
        "evidence": values.get("evidence", []),
        "stats": statistics(values) if values else {},
        "clarifications": values.get("clarifications", []),
    }


# ---------- web demo helpers ----------

def demo_target_url() -> str:
    return os.environ.get("DEMO_TARGET_URL", "http://localhost:9000")


async def target_admin(base_url: str, method: str, body: dict | None = None) -> dict:
    """Read or set target_api's runtime bug/fault switches (only target_api has /__admin/config)."""
    try:
        async with httpx.AsyncClient(transport=app.state.deps.http_transport, timeout=5) as client:
            response = await client.request(method, base_url.rstrip("/") + "/__admin/config", json=body)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"target API at {base_url} is not reachable ({type(e).__name__})")
    if response.status_code != 200:
        raise HTTPException(502 if response.status_code >= 500 or response.status_code == 404 else 400,
                            response.json().get("detail", response.text) if response.content else "target error")
    return response.json()


@app.get("/demo/info")
async def demo_info():
    llm = app.state.deps.llm
    model = os.environ.get("AGENT_MODEL", "").strip()
    return {
        "model": model or None,
        "model_kind": "real" if hasattr(llm, "failures") else "fake",
        "llm_calls": len(getattr(llm, "calls", [])),
        "llm_failures": len(getattr(llm, "failures", [])),
        "last_llm_error": (getattr(llm, "failures", None) or [None])[-1],
        "daily_quota_hint": 20,
        "target_url": demo_target_url(),
    }


@app.get("/demo/specs")
async def demo_specs():
    return {"specs": [{"id": key, "label": label, "text": path.read_text()} for key, (label, path) in DEMO_SPECS.items()]}


@app.get("/demo/architecture", response_class=PlainTextResponse)
async def demo_architecture():
    return (ROOT / "docs" / "architecture.mmd").read_text()


@app.get("/demo/eval", response_class=PlainTextResponse)
async def demo_eval():
    path = ROOT / "eval" / "report.md"
    if not path.is_file():
        raise HTTPException(404, "no evaluation report yet: run python -m eval.run_eval")
    return path.read_text()


@app.get("/demo/target")
async def get_target(base_url: str | None = None):
    return await target_admin(base_url or demo_target_url(), "GET")


@app.post("/demo/target")
async def set_target(config: TargetConfig, base_url: str | None = None):
    return await target_admin(base_url or demo_target_url(), "POST", config.model_dump())


# The built React app (frontend/dist), served last so the API routes above win.
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
