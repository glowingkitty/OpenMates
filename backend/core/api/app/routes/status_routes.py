# backend/core/api/app/routes/status_routes.py
# Status page API endpoints (v3).
# Serves the new compact status page with service groups, test categories,
# response time data, and incident history.
# Architecture: docs/architecture/infrastructure/status-page.md
# Tests: backend/tests/test_status_service_v2.py

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query, Request

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.services.status_aggregator import (
    filter_public_status_health_data,
    gather_health_data,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/v1/status",
    tags=["Status"],
)

# ── Service group definitions (mirrors backend/status/app/config.py) ──────────

SERVICE_GROUPS: list[tuple[str, list[tuple[str, list[str]]]]] = [
    ("Core Platform", [
        ("Web App", ["web_app"]),
        ("API Server", ["core_api"]),
        ("Upload Server", ["upload_server"]),
        ("Preview Server", ["preview_server"]),
    ]),
    ("AI Providers", [
        ("Anthropic", ["anthropic"]),
        ("OpenAI", ["openai"]),
        ("Groq", ["groq"]),
        ("Mistral", ["mistral"]),
        ("Google", ["google"]),
        ("Cerebras", ["cerebras"]),
        ("Together", ["together"]),
        ("OpenRouter", ["openrouter"]),
        ("AWS Bedrock", ["aws_bedrock"]),
    ]),
    ("Search & Data", [
        ("Brave Search", ["brave", "brave_search"]),
        ("SerpAPI", ["serpapi"]),
        ("Firecrawl", ["firecrawl"]),
        ("Context7", ["context7"]),
        ("YouTube", ["youtube"]),
        ("Google Maps", ["google_maps"]),
    ]),
    ("Image & Media", [
        ("FAL (Flux)", ["fal"]),
        ("Recraft", ["recraft"]),
    ]),
    ("Events & Health", [
        ("Doctolib", ["doctolib"]),
        ("Meetup", ["meetup"]),
        ("Luma Events", ["luma"]),
    ]),
    ("Travel", [
        ("Travelpayouts", ["travelpayouts"]),
        ("Transitous", ["transitous"]),
        ("FlightRadar24", ["flightradar24"]),
    ]),
    ("Payment", [
        ("Stripe", ["stripe"]),
        ("Polar", ["polar"]),
        ("Revolut", ["revolut"]),
    ]),
    ("Email & Moderation", [
        ("Brevo", ["brevo"]),
        ("Sightengine", ["sightengine"]),
    ]),
]

# E2E test categories
TEST_CATEGORIES: list[tuple[str, list[str]]] = [
    ("Chat", ["chat-flow", "chat-management", "chat-scroll", "chat-search", "daily-inspiration", "fork-conversation", "hidden-chats", "import-chats", "message-sync", "background-chat"]),
    ("Payment", ["buy-credits", "saved-payment", "settings-buy-credits"]),
    ("Signup", ["signup"]),
    ("Login", ["account-recovery", "backup-code", "multi-session", "recovery-key", "session-revoke"]),
    ("Search & AI", ["code-generation", "focus-mode", "follow-up-suggestions"]),
    ("Media & Embeds", ["audio-recording", "embed-", "file-attachment", "pdf-flow"]),
    ("Settings", ["api-keys", "incognito", "language-settings", "location-security", "pii-detection", "default-model", "model-override"]),
    ("Reminders", ["reminder-"]),
    ("Accessibility", ["a11y-"]),
    ("Skills", ["skill-", "cli-skills"]),
    ("CLI", ["cli-images", "cli-memories", "cli-pair", "cli-file"]),
    ("Infrastructure", ["status-page", "app-load", "connection-resilience", "page-load", "share-chat", "share-embed", "not-found", "embed-json"]),
]


def _categorize_test(spec_name: str) -> Optional[str]:
    """Return the category name for a spec file, or None if uncategorized."""
    name_lower = spec_name.lower()
    for cat_name, patterns in TEST_CATEGORIES:
        for pattern in patterns:
            if pattern.lower() in name_lower:
                return cat_name
    return None


def _normalize_status(raw: str) -> str:
    """Normalize health status from Redis cache to display status."""
    if raw in ("healthy", "operational", "available"):
        return "operational"
    if raw == "degraded":
        return "degraded"
    if raw in ("unhealthy", "down"):
        return "down"
    return "unknown"


def _build_uptime_90d(health_data: Dict[str, Any], service_id: str) -> list[Dict[str, str]]:
    """Build a 90-day uptime bar from current health data.

    Since we only have current status from Redis (not historical), we fill
    all 90 days with the current status. Historical data will come from
    the independent status service when it's running.
    """
    now = datetime.now(timezone.utc)
    current_status = "unknown"

    # Check providers, apps, and external_services for this service_id
    for section in ("providers", "apps", "external_services"):
        section_data = health_data.get(section, {})
        if service_id in section_data:
            raw = section_data[service_id].get("status", "unknown")
            current_status = _normalize_status(str(raw))
            break

    return [
        {"date": (now - timedelta(days=89 - i)).strftime("%Y-%m-%d"), "status": current_status}
        for i in range(90)
    ]


def _get_response_times(health_data: Dict[str, Any], service_id: str) -> Optional[list[Dict[str, Any]]]:
    """Extract response time data from health cache if available."""
    for section in ("providers", "external_services"):
        section_data = health_data.get(section, {})
        if service_id in section_data:
            rt_data = section_data[service_id].get("response_times_ms", {})
            if rt_data and isinstance(rt_data, dict):
                points = []
                for ts_str, ms_val in sorted(rt_data.items()):
                    try:
                        ts = datetime.fromtimestamp(float(ts_str), tz=timezone.utc)
                        points.append({
                            "timestamp": ts.isoformat(),
                            "avg_ms": round(float(ms_val), 1),
                            "min_ms": round(float(ms_val), 1),
                            "max_ms": round(float(ms_val), 1),
                            "samples": 1,
                        })
                    except (ValueError, TypeError):
                        continue
                return points if points else None
    return None


@router.get("/v2", dependencies=[])
@limiter.limit("30/minute")
async def get_status_v2(request: Request):
    """Unified status endpoint for the new status page (v3).

    Returns all service groups with current status, 90-day uptime bars,
    response time data, E2E test results by category, and incidents.
    Public — no auth required.
    """
    health_data = filter_public_status_health_data(await gather_health_data(request))

    # Build groups
    groups: list[Dict[str, Any]] = []
    all_statuses: list[str] = []

    for group_name, components in SERVICE_GROUPS:
        group_services: list[Dict[str, Any]] = []
        for comp_name, service_ids in components:
            # Aggregate status across service_ids
            comp_statuses = []
            for sid in service_ids:
                for section in ("providers", "apps", "external_services"):
                    section_data = health_data.get(section, {})
                    if sid in section_data:
                        raw = section_data[sid].get("status", "unknown")
                        comp_statuses.append(_normalize_status(str(raw)))
                        break

            if not comp_statuses:
                comp_status = "unknown"
            elif len(comp_statuses) == 1:
                comp_status = comp_statuses[0]
            else:
                op_count = sum(1 for s in comp_statuses if s == "operational")
                total = len(comp_statuses)
                if op_count > total * 0.5:
                    comp_status = "operational"
                elif op_count >= total * 0.25:
                    comp_status = "degraded"
                else:
                    comp_status = "down"

            all_statuses.append(comp_status)
            primary_sid = service_ids[0]

            # Build uptime bar and response times
            uptime_90d = _build_uptime_90d(health_data, primary_sid)
            uptime_pct = 100.0 if comp_status == "operational" else (50.0 if comp_status == "degraded" else 0.0)

            response_times_7d = None
            if group_name != "Core Platform":
                response_times_7d = _get_response_times(health_data, primary_sid)

            group_services.append({
                "id": primary_sid,
                "name": comp_name,
                "status": comp_status,
                "uptime_90d": uptime_90d,
                "uptime_pct": uptime_pct,
                "response_times_7d": response_times_7d,
            })

        groups.append({"name": group_name, "services": group_services})

    # Overall status
    if all(s == "operational" for s in all_statuses):
        overall_status = "operational"
    elif any(s == "down" for s in all_statuses):
        overall_status = "down"
    elif any(s == "degraded" for s in all_statuses):
        overall_status = "degraded"
    else:
        overall_status = "unknown"

    uptime_values = [s["uptime_pct"] for g in groups for s in g["services"]]
    overall_uptime = round(sum(uptime_values) / len(uptime_values), 1) if uptime_values else 100.0

    # Test results
    tests_data = _load_test_results()

    # Incidents
    incidents = await _load_incidents()

    return {
        "status": overall_status,
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "uptime_pct": overall_uptime,
        "groups": groups,
        "tests": tests_data,
        "incidents": incidents,
    }


@router.get("/v2/intraday", dependencies=[])
@limiter.limit("60/minute")
async def get_status_v2_intraday(
    request: Request,
    date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
    type: str = Query(..., description="'service' or 'test'"),
    id: str = Query(..., description="service_id or spec name"),
):
    """Intra-day drill-down for a specific service or test on a specific date."""
    if type == "service":
        checks = await _load_service_intraday(id, date)
        return {"date": date, "type": "service", "id": id, "checks": checks}
    elif type == "test":
        runs = _load_test_intraday(id, date)
        return {"date": date, "type": "test", "id": id, "runs": runs}
    else:
        raise HTTPException(status_code=400, detail="type must be 'service' or 'test'")


# ── Data loading helpers ──────────────────────────────────────────────

def _load_test_results() -> Dict[str, Any]:
    """Load E2E test results from JSON files, grouped by category."""
    results_dir = Path("/app/data/test-results")
    if not results_dir.exists():
        results_dir = Path(__file__).parent.parent.parent.parent.parent / "data" / "test-results"

    specs: list[Dict[str, Any]] = []
    last_run_time = None

    last_run_file = results_dir / "last-run.json"
    if last_run_file.exists():
        try:
            with open(last_run_file) as f:
                run_data = json.load(f)
            last_run_time = run_data.get("timestamp") or run_data.get("started_at")
            for test in run_data.get("tests", []):
                name = test.get("name", test.get("file", ""))
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

    # 30-day history
    history_dir = results_dir / "history"
    spec_timelines: Dict[str, list[Dict[str, str]]] = {}
    if history_dir.exists():
        now = datetime.now(timezone.utc)
        for i in range(30):
            date_str = (now - timedelta(days=29 - i)).strftime("%Y-%m-%d")
            day_file = history_dir / f"{date_str}.json"
            if day_file.exists():
                try:
                    with open(day_file) as f:
                        day_data = json.load(f)
                    for test in day_data.get("tests", []):
                        sname = Path(test.get("file", test.get("name", ""))).stem.replace(".spec", "")
                        spec_timelines.setdefault(sname, []).append({
                            "date": date_str,
                            "status": "passed" if test.get("status") == "passed" else "failed",
                        })
                except (json.JSONDecodeError, OSError):
                    pass

    for spec in specs:
        spec["timeline_30d"] = spec_timelines.get(spec["name"], [])

    # Group into categories
    categories: list[Dict[str, Any]] = []
    categorized: set[str] = set()

    for cat_name, _ in TEST_CATEGORIES:
        cat_specs = [s for s in specs if _categorize_test(s["name"]) == cat_name]
        if not cat_specs:
            continue
        for s in cat_specs:
            categorized.add(s["name"])
        passed = sum(1 for s in cat_specs if s["status"] == "passed")
        categories.append({
            "name": cat_name,
            "total": len(cat_specs),
            "passed": passed,
            "failed": len(cat_specs) - passed,
            "specs": cat_specs,
        })

    uncategorized = [s for s in specs if s["name"] not in categorized]
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


def _load_test_intraday(spec_name: str, date: str) -> list[Dict[str, Any]]:
    """Load test run details for a specific spec on a specific date."""
    results_dir = Path("/app/data/test-results")
    if not results_dir.exists():
        results_dir = Path(__file__).parent.parent.parent.parent.parent / "data" / "test-results"

    runs_dir = results_dir / "runs" / date
    runs: list[Dict[str, Any]] = []

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


async def _load_service_intraday(service_id: str, date: str) -> list[Dict[str, Any]]:
    """Load health check events for a service on a specific date."""
    try:
        day_start = datetime.fromisoformat(f"{date}T00:00:00+00:00")
        since_ts = int(day_start.timestamp())

        directus = DirectusService(cache_service=CacheService())
        try:
            events = await directus.health_event.get_health_history(
                since_timestamp=since_ts,
                service_type=None,
                limit=500,
            )
        finally:
            await directus.close()

        checks: list[Dict[str, Any]] = []
        for ev in events:
            if ev.get("service_id") != service_id:
                continue
            created_at = ev.get("created_at", "")
            if created_at[:10] != date:
                continue
            time_part = created_at[11:19] if len(created_at) >= 19 else created_at[11:]
            entry: Dict[str, Any] = {
                "time": time_part,
                "status": _normalize_status(str(ev.get("new_status", "unknown"))),
                "response_time_ms": ev.get("response_time_ms"),
            }
            if ev.get("error_message"):
                entry["error"] = ev["error_message"]
            checks.append(entry)

        checks.sort(key=lambda c: c["time"])
        return checks

    except Exception as e:
        logger.error(f"[STATUS] Error loading service intraday: {e}", exc_info=True)
        return []


async def _load_incidents() -> list[Dict[str, Any]]:
    """Load recent incidents from health event history."""
    try:
        since_ts = int((datetime.now(timezone.utc) - timedelta(days=14)).timestamp())
        directus = DirectusService(cache_service=CacheService())
        try:
            events = await directus.health_event.get_health_history(
                since_timestamp=since_ts,
                limit=500,
            )
        finally:
            await directus.close()

        # Group into incidents
        open_incidents: Dict[str, Dict[str, Any]] = {}
        closed: list[Dict[str, Any]] = []
        now = datetime.now(timezone.utc)

        for ev in sorted(events, key=lambda e: e.get("created_at", "")):
            sid = ev.get("service_id", "")
            new_status = _normalize_status(str(ev.get("new_status", "")))
            created_at = ev.get("created_at", "")

            if new_status in ("down", "degraded"):
                if sid not in open_incidents:
                    open_incidents[sid] = {
                        "component": ev.get("service_name", sid),
                        "group": ev.get("service_type", ""),
                        "severity": new_status,
                        "started_at": created_at,
                        "resolved_at": None,
                        "duration_minutes": None,
                        "updates": [],
                    }
                inc = open_incidents[sid]
                if new_status == "down":
                    inc["severity"] = "down"
                inc["updates"].append({"status": new_status, "timestamp": created_at})
            elif new_status == "operational" and sid in open_incidents:
                inc = open_incidents.pop(sid)
                inc["resolved_at"] = created_at
                inc["updates"].append({"status": "operational", "timestamp": created_at})
                try:
                    start = datetime.fromisoformat(inc["started_at"].replace("Z", "+00:00"))
                    end = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    inc["duration_minutes"] = int((end - start).total_seconds() / 60)
                except (ValueError, TypeError):
                    pass
                closed.append(inc)

        for inc in open_incidents.values():
            try:
                start = datetime.fromisoformat(inc["started_at"].replace("Z", "+00:00"))
                inc["duration_minutes"] = int((now - start).total_seconds() / 60)
            except (ValueError, TypeError):
                pass
            closed.append(inc)

        closed.sort(key=lambda i: i["started_at"], reverse=True)
        return closed

    except Exception as e:
        logger.error(f"[STATUS] Error loading incidents: {e}", exc_info=True)
        return []
