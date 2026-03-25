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
    SERVICE_GROUPS,
    STATUS_DEGRADED,
    STATUS_DOWN,
    STATUS_OPERATIONAL,
    STATUS_UNKNOWN,
    TEST_CATEGORIES,
    VALID_ENVS,
    categorize_test,
    get_status_db_path,
)
from app.database import (
    calculate_uptime_percentages,
    compute_uptime_pct,
    get_current_service_status,
    get_daily_service_status,
    get_incidents,
    get_intraday_checks,
    get_response_time_series,
    get_response_time_series_hourly,
    get_status_history,
    init_db,
)
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


@app.get("/api/status/v2")
async def get_status_v2(env: str = Query(default=ENV_PROD)) -> dict[str, Any]:
    """Unified status endpoint for the new status page.

    Returns all service groups with uptime bars, response time data,
    test results grouped by category, and incidents.
    """
    environment = _validate_environment(env)
    services = await get_current_service_status(DB_PATH, environment)

    # Build service lookup map
    service_map: dict[str, dict[str, Any]] = {}
    for svc in services:
        service_map[str(svc["service_id"])] = svc

    # Build groups with uptime data
    groups: list[dict[str, Any]] = []
    all_statuses: list[str] = []

    for group_name, components in SERVICE_GROUPS:
        group_services: list[dict[str, Any]] = []
        for comp in components:
            # Aggregate status across all service_ids for this component
            comp_statuses = []
            for sid in comp.service_ids:
                svc = service_map.get(sid)
                if svc:
                    comp_statuses.append(str(svc["status"]))

            if not comp_statuses:
                comp_status = "unknown"
            elif len(comp_statuses) == 1:
                comp_status = comp_statuses[0]
            else:
                # Majority-based aggregation
                op_count = sum(1 for s in comp_statuses if s == "operational")
                total = len(comp_statuses)
                if op_count > total * 0.5:
                    comp_status = "operational"
                elif op_count >= total * 0.25:
                    comp_status = "degraded"
                else:
                    comp_status = "down"

            all_statuses.append(comp_status)

            # Get uptime data for primary service_id
            primary_sid = comp.service_ids[0]
            uptime_90d = await get_daily_service_status(
                DB_PATH, environment=environment, service_id=primary_sid, days=90
            )
            uptime_pct = await compute_uptime_pct(
                DB_PATH, environment=environment, service_id=primary_sid, days=90
            )

            # Response time data (only for providers, not core platform)
            response_times_7d = None
            if group_name != "Core Platform":
                response_times_7d = await get_response_time_series_hourly(
                    DB_PATH, environment=environment, service_id=primary_sid, hours=168
                )
                if not response_times_7d:
                    response_times_7d = None

            group_services.append({
                "id": primary_sid,
                "name": comp.name,
                "status": comp_status,
                "uptime_90d": uptime_90d,
                "uptime_pct": uptime_pct,
                "response_times_7d": response_times_7d,
            })

        groups.append({
            "name": group_name,
            "services": group_services,
        })

    # Compute overall status
    if all(s == "operational" for s in all_statuses):
        overall_status = "operational"
    elif any(s == "down" for s in all_statuses):
        overall_status = "down"
    elif any(s == "degraded" for s in all_statuses):
        overall_status = "degraded"
    else:
        overall_status = "unknown"

    # Compute overall uptime percentage (average across all components)
    uptime_values = [s.get("uptime_pct", 100.0) for g in groups for s in g["services"]]
    overall_uptime = round(sum(uptime_values) / len(uptime_values), 1) if uptime_values else 100.0

    # Test results
    tests_data = _load_test_results()

    # Incidents
    incidents = await get_incidents(DB_PATH, environment=environment, since_days=14)

    return {
        "status": overall_status,
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "uptime_pct": overall_uptime,
        "groups": groups,
        "tests": tests_data,
        "incidents": incidents,
    }


@app.get("/api/status/v2/intraday")
async def get_status_v2_intraday(
    env: str = Query(default=ENV_PROD),
    date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
    type: str = Query(..., description="'service' or 'test'"),
    id: str = Query(..., description="service_id or spec name"),
) -> dict[str, Any]:
    """Intra-day drill-down for a specific service or test on a specific date."""
    environment = _validate_environment(env)

    if type == "service":
        checks = await get_intraday_checks(
            DB_PATH, environment=environment, service_id=id, date=date
        )
        return {"date": date, "type": "service", "id": id, "checks": checks}
    elif type == "test":
        # Load test run data for this spec on this date
        runs = _load_test_intraday(id, date)
        return {"date": date, "type": "test", "id": id, "runs": runs}
    else:
        raise HTTPException(status_code=400, detail="type must be 'service' or 'test'")


def _load_test_results() -> dict[str, Any]:
    """Load E2E test results from the test results JSON files.

    Reads the same files that the daily test runner produces.
    Groups tests into categories defined in config.py.
    """
    import json

    results_dir = Path("/app/data/test-results")
    if not results_dir.exists():
        # Fallback for dev environment
        results_dir = Path(__file__).parent.parent.parent.parent / "data" / "test-results"

    # Find the latest run file
    last_run_file = results_dir / "last-run.json"
    specs: list[dict[str, Any]] = []
    last_run_time = None

    if last_run_file.exists():
        try:
            with open(last_run_file) as f:
                run_data = json.load(f)
            last_run_time = run_data.get("timestamp") or run_data.get("started_at")

            for test in run_data.get("tests", []):
                name = test.get("name", test.get("file", ""))
                # Extract spec name from file path
                spec_name = Path(name).stem if "/" in name else name
                spec_name = spec_name.replace(".spec", "")

                specs.append({
                    "name": spec_name,
                    "status": "passed" if test.get("status") == "passed" else "failed",
                    "error": test.get("error") if test.get("status") != "passed" else None,
                    "duration_s": test.get("duration"),
                })
        except (json.JSONDecodeError, OSError):
            pass

    # Load 30-day history
    history_dir = results_dir / "history"
    spec_timelines: dict[str, list[dict[str, str]]] = {}

    if history_dir.exists():
        now = datetime.now(timezone.utc)
        for i in range(30):
            date = (now - timedelta(days=29 - i)).strftime("%Y-%m-%d")
            day_file = history_dir / f"{date}.json"
            if day_file.exists():
                try:
                    with open(day_file) as f:
                        day_data = json.load(f)
                    for test in day_data.get("tests", []):
                        spec_name = Path(test.get("file", test.get("name", ""))).stem.replace(".spec", "")
                        if spec_name not in spec_timelines:
                            spec_timelines[spec_name] = []
                        spec_timelines[spec_name].append({
                            "date": date,
                            "status": "passed" if test.get("status") == "passed" else "failed",
                        })
                except (json.JSONDecodeError, OSError):
                    pass

    # Attach timelines to specs
    for spec in specs:
        spec["timeline_30d"] = spec_timelines.get(spec["name"], [])

    # Group into categories
    categories: list[dict[str, Any]] = []
    categorized_specs: set[str] = set()

    for cat_name, _ in TEST_CATEGORIES:
        cat_specs = [s for s in specs if categorize_test(s["name"]) == cat_name]
        if not cat_specs:
            continue
        for s in cat_specs:
            categorized_specs.add(s["name"])

        passed = sum(1 for s in cat_specs if s["status"] == "passed")
        categories.append({
            "name": cat_name,
            "total": len(cat_specs),
            "passed": passed,
            "failed": len(cat_specs) - passed,
            "specs": cat_specs,
        })

    # Add uncategorized specs as "Other"
    uncategorized = [s for s in specs if s["name"] not in categorized_specs]
    if uncategorized:
        passed = sum(1 for s in uncategorized if s["status"] == "passed")
        categories.append({
            "name": "Other",
            "total": len(uncategorized),
            "passed": passed,
            "failed": len(uncategorized) - passed,
            "specs": uncategorized,
        })

    total = len(specs)
    total_passed = sum(1 for s in specs if s["status"] == "passed")

    return {
        "total": total,
        "passed": total_passed,
        "failed": total - total_passed,
        "last_run": last_run_time,
        "categories": categories,
    }


def _load_test_intraday(spec_name: str, date: str) -> list[dict[str, Any]]:
    """Load test run details for a specific spec on a specific date."""
    import json

    results_dir = Path("/app/data/test-results")
    if not results_dir.exists():
        results_dir = Path(__file__).parent.parent.parent.parent / "data" / "test-results"

    runs_dir = results_dir / "runs" / date
    runs: list[dict[str, Any]] = []

    if runs_dir.exists():
        for run_file in sorted(runs_dir.glob("*.json")):
            try:
                with open(run_file) as f:
                    run_data = json.load(f)
                for test in run_data.get("tests", []):
                    test_name = Path(test.get("file", test.get("name", ""))).stem.replace(".spec", "")
                    if test_name == spec_name or spec_name in test_name:
                        time_str = run_data.get("timestamp", "")
                        if "T" in time_str:
                            time_str = time_str.split("T")[1][:8]
                        runs.append({
                            "time": time_str,
                            "status": "passed" if test.get("status") == "passed" else "failed",
                            "duration_s": test.get("duration"),
                            "error": test.get("error") if test.get("status") != "passed" else None,
                        })
            except (json.JSONDecodeError, OSError):
                continue

    return runs


@app.get("/{full_path:path}", include_in_schema=False)
async def serve_spa(full_path: str) -> FileResponse:
    if not INDEX_FILE.exists():
        raise HTTPException(status_code=503, detail="frontend build missing")

    requested = STATIC_DIR / full_path
    if full_path and requested.exists() and requested.is_file():
        return FileResponse(requested)
    return FileResponse(INDEX_FILE)
