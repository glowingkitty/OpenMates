"""
OpenMates status service API and static frontend hosting.
Architecture: Independent status VM serving API + bundled Svelte SPA.
See docs/architecture/status-page.md for design rationale.
Tests: N/A (status service tests not added yet)
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import (
    ENV_PROD,
    STATUS_DEGRADED,
    STATUS_DOWN,
    STATUS_OPERATIONAL,
    STATUS_UNKNOWN,
    VALID_ENVS,
    get_status_db_path,
)
from app.database import calculate_uptime_percentages, get_current_service_status, get_response_time_series, get_status_history, init_db
from app.scheduler import run_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DB_PATH = get_status_db_path()
STATIC_DIR = Path(__file__).parent / "static"
INDEX_FILE = STATIC_DIR / "index.html"


def _validate_environment(env: str) -> str:
    if env not in VALID_ENVS:
        raise HTTPException(status_code=400, detail=f"invalid env '{env}', expected one of {sorted(VALID_ENVS)}")
    return env


def _compute_overall_status(services: list[dict[str, Any]]) -> str:
    if not services:
        return STATUS_UNKNOWN

    statuses = [service["status"] for service in services]
    if all(status == STATUS_OPERATIONAL for status in statuses):
        return STATUS_OPERATIONAL
    if any(status == STATUS_DOWN for status in statuses):
        return STATUS_DOWN
    if any(status == STATUS_DEGRADED for status in statuses):
        return STATUS_DEGRADED
    return STATUS_UNKNOWN


def _group_services(services: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for service in services:
        group_name = str(service["group_name"])
        grouped.setdefault(group_name, []).append(service)

    output: list[dict[str, Any]] = []
    for group_name, group_services in grouped.items():
        output.append(
            {
                "group_name": group_name,
                "status": _compute_overall_status(group_services),
                "services": group_services,
            }
        )
    return sorted(output, key=lambda item: item["group_name"])


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db(DB_PATH)
    stop_event = asyncio.Event()
    scheduler_task = asyncio.create_task(run_scheduler(DB_PATH, stop_event))

    try:
        yield
    finally:
        stop_event.set()
        await scheduler_task


app = FastAPI(title="OpenMates Status Service", version="1.0.0", lifespan=lifespan)

ASSETS_DIR = STATIC_DIR / "assets"
if ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy"}


@app.get("/api/status")
async def get_status(env: str = Query(default=ENV_PROD)) -> dict[str, Any]:
    environment = _validate_environment(env)
    services = await get_current_service_status(DB_PATH, environment)
    groups = _group_services(services)
    return {
        "environment": environment,
        "status": _compute_overall_status(services),
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "groups": groups,
    }


@app.get("/api/status/history")
async def get_history(
    env: str = Query(default=ENV_PROD),
    service_id: str | None = Query(default=None),
    since_days: int = Query(default=30, ge=1, le=90),
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict[str, Any]:
    environment = _validate_environment(env)
    since = datetime.now(timezone.utc) - timedelta(days=since_days)
    events = await get_status_history(
        DB_PATH,
        environment=environment,
        service_id=service_id,
        since_iso=since.isoformat(),
        limit=limit,
    )
    return {
        "environment": environment,
        "events": events,
        "total": len(events),
        "filters": {
            "service_id": service_id,
            "since_days": since_days,
            "limit": limit,
        },
    }


@app.get("/api/status/uptime")
async def get_uptime(env: str = Query(default=ENV_PROD)) -> dict[str, Any]:
    environment = _validate_environment(env)
    services = await calculate_uptime_percentages(DB_PATH, environment=environment)
    return {
        "environment": environment,
        "services": services,
    }


@app.get("/api/status/response-times")
async def get_response_times(
    env: str = Query(default=ENV_PROD),
    service_id: str = Query(default="core_api"),
    period: str = Query(default="24h"),
) -> dict[str, Any]:
    environment = _validate_environment(env)
    period_to_timedelta = {
        "24h": timedelta(hours=24),
        "7d": timedelta(days=7),
        "30d": timedelta(days=30),
    }
    if period not in period_to_timedelta:
        raise HTTPException(status_code=400, detail="period must be one of: 24h, 7d, 30d")

    since = datetime.now(timezone.utc) - period_to_timedelta[period]
    points = await get_response_time_series(
        DB_PATH,
        environment=environment,
        service_id=service_id,
        since_iso=since.isoformat(),
    )
    return {
        "environment": environment,
        "service_id": service_id,
        "period": period,
        "points": points,
    }


@app.get("/{full_path:path}", include_in_schema=False)
async def serve_spa(full_path: str) -> FileResponse:
    if not INDEX_FILE.exists():
        raise HTTPException(status_code=503, detail="frontend build missing")

    requested = STATIC_DIR / full_path
    if full_path and requested.exists() and requested.is_file():
        return FileResponse(requested)
    return FileResponse(INDEX_FILE)
