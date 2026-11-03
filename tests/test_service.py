"""FastAPI wrapper with the fake LLM injected, driven through httpx.ASGITransport."""

import asyncio
from pathlib import Path

import httpx

from app.config import Deps
from app.llm import FakeLLM
from app.main import app as service
from target_api.main import app as target_app

SPEC = Path("target_api/openapi.yaml").read_text()
UNDOCUMENTED = Path("target_api/openapi_undocumented.yaml").read_text()


async def wait_until(client, run_id, wanted, tries=200):
    for _ in range(tries):
        body = (await client.get(f"/runs/{run_id}")).json()
        if body["status"] in wanted:
            return body
        await asyncio.sleep(0.02)
    raise AssertionError(f"run stayed {body['status']}")


async def with_service(tmp_path, test):
    service.state.deps = Deps(llm=FakeLLM(), http_transport=httpx.ASGITransport(app=target_app),
                              backoff_scale=0, reports_dir=str(tmp_path))
    async with service.router.lifespan_context(service):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=service), base_url="http://svc") as client:
            await test(client)
    service.state.deps = None


async def test_start_run_read_status_and_report(monkeypatch, tmp_path):
    monkeypatch.setenv("SEEDED_BUGS", "BUG_RADIUS_MIN")
    monkeypatch.delenv("FAULTS", raising=False)

    async def test(client):
        assert (await client.get("/health")).json() == {"status": "ok"}
        started = await client.post("/runs", json={"spec": SPEC, "base_url": "http://target",
                                                    "config": {"interactive": False}})
        assert started.status_code == 202
        run_id = started.json()["run_id"]

        status = await wait_until(client, run_id, {"complete", "partial", "error"})
        assert status["status"] == "complete" and status["findings"] >= 1

        trace = (await client.get(f"/runs/{run_id}/trace")).json()["decision_log"]
        assert any(e["decision"] == "replan" for e in trace)
        report = await client.get(f"/runs/{run_id}/report")
        assert report.status_code == 200 and "## Confirmed defects" in report.text

    await with_service(tmp_path, test)


async def test_pause_and_resume(monkeypatch, tmp_path):
    monkeypatch.delenv("SEEDED_BUGS", raising=False)
    monkeypatch.delenv("FAULTS", raising=False)

    async def test(client):
        run_id = (await client.post("/runs", json={"spec": UNDOCUMENTED, "base_url": "http://target"})).json()["run_id"]
        paused = await wait_until(client, run_id, {"awaiting_input", "complete", "error"})
        assert paused["status"] == "awaiting_input" and "bearer token" in paused["pending_question"]
        assert (await client.get(f"/runs/{run_id}/report")).status_code == 409

        assert (await client.post(f"/runs/{run_id}/resume", json={"answer": "401"})).status_code == 202
        done = await wait_until(client, run_id, {"complete", "partial", "error"})
        assert done["status"] == "complete"

    await with_service(tmp_path, test)
