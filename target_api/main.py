"""Small API with switchable bugs and faults, used as the agent's test target.

Run:  SEEDED_BUGS=BUG_RADIUS_MIN FAULTS=FAULT_503_THEN_OK uvicorn target_api.main:app --port 9000

Bugs and faults are read from the environment on every request, so tests can
change them with monkeypatch without restarting the app.
"""

import asyncio
import math
import os
from pathlib import Path

import yaml
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

SPEC_PATH = Path(__file__).with_name("openapi.yaml")
VALID_TOKEN = os.environ.get("TARGET_API_TOKEN", "test-token")
PAGE_SIZE = 5

RESTAURANTS = [
    {"id": "r1", "name": "Blue Nile", "cuisine": "ethiopian", "lat": 9.0300, "lng": 38.7400},
    {"id": "r2", "name": "Piassa Pizza", "cuisine": "italian", "lat": 9.0350, "lng": 38.7520},
    {"id": "r3", "name": "Bole Grill", "cuisine": "grill", "lat": 8.9950, "lng": 38.7890},
    {"id": "r4", "name": "Sheger Cafe", "cuisine": "cafe", "lat": 9.0100, "lng": 38.7610},
    {"id": "r5", "name": "Entoto View", "cuisine": "ethiopian", "lat": 9.0800, "lng": 38.7650},
    {"id": "r6", "name": "Kazanchis Noodles", "cuisine": "asian", "lat": 9.0180, "lng": 38.7700},
    {"id": "r7", "name": "Megenagna Burgers", "cuisine": "american", "lat": 9.0200, "lng": 38.8000},
    {"id": "r8", "name": "Merkato Spice", "cuisine": "ethiopian", "lat": 9.0330, "lng": 38.7300},
]
FAVORITES = [{"id": "r1", "name": "Blue Nile"}, {"id": "r4", "name": "Sheger Cafe"}]

# Fault counters, cleared by POST /__admin/reset.
fault_counters: dict[str, int] = {}

BUG_IDS = ["BUG_RADIUS_MIN", "BUG_DISTANCE_STRING", "BUG_MISSING_LNG_500", "BUG_AUTH_BYPASS", "BUG_PAGE_OVERLAP"]
FAULT_IDS = ["FAULT_503_THEN_OK", "FAULT_TIMEOUT_ALWAYS"]
# Set by POST /__admin/config (the web demo). None means "use the env var".
overrides: dict[str, set[str] | None] = {"SEEDED_BUGS": None, "FAULTS": None}


def enabled(env_var: str) -> set[str]:
    """Ids switched on at runtime, or else in a comma separated env var, e.g. SEEDED_BUGS=BUG_A,BUG_B."""
    if overrides[env_var] is not None:
        return overrides[env_var]
    return {part.strip() for part in os.environ.get(env_var, "").split(",") if part.strip()}


def bug(bug_id: str) -> bool:
    return bug_id in enabled("SEEDED_BUGS")


def fault(fault_id: str) -> bool:
    return fault_id in enabled("FAULTS")


def error(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": code, "detail": detail})


def load_openapi() -> dict:
    with SPEC_PATH.open() as f:
        return yaml.safe_load(f)


app = FastAPI()
# /docs shows the hand-written contract, which is also what the agent reads.
app.openapi = load_openapi


@app.middleware("http")
async def apply_faults(request: Request, call_next):
    if request.url.path.startswith("/v1/"):
        if fault("FAULT_503_THEN_OK"):
            seen = fault_counters.get("FAULT_503_THEN_OK", 0)
            fault_counters["FAULT_503_THEN_OK"] = seen + 1
            if seen < 2:
                return error(503, "unavailable", "Temporary outage, try again")
        if fault("FAULT_TIMEOUT_ALWAYS") and request.url.path == "/v1/favorites":
            await asyncio.sleep(float(os.environ.get("FAULT_HANG_SECONDS", "3600")))
    return await call_next(request)


def parse_number(params, name: str, kind: type, required: bool, low: float, high: float | None, default=None):
    """Return (value, None) or (None, error_response) for one query parameter."""
    raw = params.get(name)
    if raw is None or raw == "":
        if required:
            return None, error(400, "missing_parameter", f"'{name}' is required")
        return default, None
    try:
        value = kind(raw)
    except ValueError:
        return None, error(400, "invalid_type", f"'{name}' must be {'an integer' if kind is int else 'a number'}")
    if kind is float and not math.isfinite(value):
        return None, error(400, "invalid_type", f"'{name}' must be a finite number")
    if value < low or (high is not None and value > high):
        limit = f"between {low} and {high}" if high is not None else f">= {low}"
        return None, error(400, "out_of_range", f"'{name}' must be {limit}")
    return value, None


def distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in meters (haversine)."""
    r = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


@app.get("/v1/restaurants/nearby")
async def nearby(request: Request):
    q = request.query_params

    lat, err = parse_number(q, "lat", float, True, -90, 90)
    if err:
        return err

    if bug("BUG_MISSING_LNG_500") and not q.get("lng"):
        return error(500, "internal_error", "unexpected server error")
    lng, err = parse_number(q, "lng", float, True, -180, 180)
    if err:
        return err

    # BUG_RADIUS_MIN drops the lower bound, so radius <= 0 is accepted.
    radius_low = -math.inf if bug("BUG_RADIUS_MIN") else 1
    radius, err = parse_number(q, "radius", int, False, radius_low, 50000, default=5000)
    if err:
        return err

    page, err = parse_number(q, "page", int, False, 1, None, default=1)
    if err:
        return err

    matches = []
    for r in RESTAURANTS:
        d = round(distance_m(lat, lng, r["lat"], r["lng"]), 1)
        if d <= radius:
            matches.append({**r, "distance": str(d) if bug("BUG_DISTANCE_STRING") else d})
    matches.sort(key=lambda m: float(m["distance"]))

    start = (page - 1) * PAGE_SIZE - (1 if bug("BUG_PAGE_OVERLAP") and page > 1 else 0)  # repeats the last item
    return {"page": page, "total": len(matches), "results": matches[start:start + PAGE_SIZE]}


@app.get("/v1/favorites")
async def favorites(request: Request):
    auth = request.headers.get("authorization", "")
    if not bug("BUG_AUTH_BYPASS") and auth != f"Bearer {VALID_TOKEN}":
        return error(401, "unauthorized", "missing or invalid bearer token")
    return {"favorites": FAVORITES}


class AdminConfig(BaseModel):
    bugs: list[str] = []
    faults: list[str] = []


@app.get("/__admin/config", include_in_schema=False)
async def get_config():
    return {"bugs": sorted(enabled("SEEDED_BUGS")), "faults": sorted(enabled("FAULTS")),
            "known_bugs": BUG_IDS, "known_faults": FAULT_IDS}


@app.post("/__admin/config", include_in_schema=False)
async def set_config(config: AdminConfig):
    unknown = [i for i in config.bugs if i not in BUG_IDS] + [i for i in config.faults if i not in FAULT_IDS]
    if unknown:
        return error(400, "unknown_id", f"unknown bug or fault ids: {unknown}")
    overrides.update(SEEDED_BUGS=set(config.bugs), FAULTS=set(config.faults))
    fault_counters.clear()
    return await get_config()


@app.post("/__admin/reset", include_in_schema=False)
async def reset():
    fault_counters.clear()
    return {"reset": True}
