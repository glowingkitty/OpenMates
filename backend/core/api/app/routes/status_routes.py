# backend/core/api/app/routes/status_routes.py
# Unified status API endpoints for the public status page (v2).
# Three sections: Services (infrastructure), Apps (expandable), Functionalities (test-based).
# Architecture: See docs/architecture/status-page.md
# Tests: backend/tests/test_status_service.py, backend/tests/test_rest_api_status.py

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from backend.core.api.app.models.user import User
from backend.core.api.app.routes.auth_routes.auth_dependencies import (
    get_current_user_optional,
)
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.services.status_aggregator import (
    PRECOMPUTED_STATUS_KEY,
    build_all_service_daily_statuses,
    build_app_detail,
    build_apps_section,
    build_current_issues_v2,
    build_services_section,
    compute_overall_daily_timeline,
    compute_overall_status,
    filter_public_status_health_data,
    gather_health_data,
    strip_admin_fields_from_incidents,
)
from backend.core.api.app.services.test_results_service import (
    get_functionality_detail,
    get_functionality_summaries,
    get_intra_day_runs_hourly,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/v1/status",
    tags=["Status"],
)

VALID_DETAIL_LEVELS = {"summary", "full"}


@router.get("", dependencies=[])
@limiter.limit("30/minute")
async def get_status(
    request: Request,
    detail: str = Query(
        default="summary",
        description="Detail level: summary (default) or full (admin only — includes errors, response times).",
    ),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """
    Unified status endpoint. Returns the full status page initial payload.

    Sections: current_issues, overall_timeline_30d, services, apps, functionalities, incidents.
    Public — no auth required for summary. Admin auth required for detail=full.
    """
    if detail not in VALID_DETAIL_LEVELS:
        raise HTTPException(status_code=400, detail=f"detail must be one of: {', '.join(VALID_DETAIL_LEVELS)}")

    is_admin = current_user is not None and current_user.is_admin
    if detail == "full" and not is_admin:
        raise HTTPException(status_code=403, detail="detail=full requires admin authentication")

    # Fast path: serve precomputed payload for public (non-admin) summary requests
    if not is_admin and detail == "summary":
        try:
            cache_service = CacheService()
            client = await cache_service.client
            if client:
                cached = await client.get(PRECOMPUTED_STATUS_KEY)
                if cached:
                    import json as _json
                    if isinstance(cached, bytes):
                        cached = cached.decode("utf-8")
                    return _json.loads(cached)
        except Exception as e:
            logger.warning(f"[STATUS] Precomputed cache read failed, falling back to live: {e}")

    response: Dict[str, Any] = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "is_admin": is_admin,
    }

    # Health data (needed for overall_status, services, apps, current_issues)
    health_data = filter_public_status_health_data(await gather_health_data(request))
    response["overall_status"] = compute_overall_status(health_data)

    # Build per-service 30-day timelines
    service_timelines: Dict[str, Any] = {}
    try:
        directus = DirectusService(cache_service=CacheService())
        try:
            service_timelines = await build_all_service_daily_statuses(
                directus, health_data, days=30,
            )
        finally:
            await directus.close()
    except Exception as e:
        logger.error(f"[STATUS] Error building service timelines: {e}", exc_info=True)

    # Overall 30-day timeline
    response["overall_timeline_30d"] = compute_overall_daily_timeline(service_timelines)

    # Current issues (truncated to first 5 with totals)
    response["current_issues"] = build_current_issues_v2(health_data, is_admin=is_admin, limit=5)

    # Services section — flat infrastructure services
    response["services"] = build_services_section(health_data, service_timelines)

    # Apps section — app-level summaries
    response["apps"] = build_apps_section(health_data, service_timelines)

    # Functionalities section — test-based functionality summaries
    response["functionalities"] = get_functionality_summaries(days=30)

    # Incidents — 30-day count
    try:
        since_30d = int((datetime.now(timezone.utc) - timedelta(days=30)).timestamp())
        directus = DirectusService(cache_service=CacheService())
        try:
            incident_summary = await directus.health_event.get_incident_summary(
                since_timestamp=since_30d,
            )
            response["incidents"] = {
                "total_last_30d": incident_summary.get("total_incidents", 0),
            }
        finally:
            await directus.close()
    except Exception as e:
        logger.error(f"[STATUS] Error getting incidents: {e}", exc_info=True)
        response["incidents"] = {"total_last_30d": 0}

    return response


@router.get("/apps", dependencies=[])
@limiter.limit("60/minute")
async def get_status_app_detail(
    request: Request,
    app: str = Query(
        ...,
        description="App ID to get details for (e.g., 'ai', 'web').",
    ),
    detail: str = Query(
        default="summary",
        description="Detail level: summary or full (admin only).",
    ),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """
    Get detailed health data for a specific app.
    Called when a user expands an app on the status page.

    Returns providers with timelines and skills with overall status.
    """
    if detail not in VALID_DETAIL_LEVELS:
        raise HTTPException(status_code=400, detail=f"detail must be one of: {', '.join(VALID_DETAIL_LEVELS)}")

    is_admin = current_user is not None and current_user.is_admin
    if detail == "full" and not is_admin:
        raise HTTPException(status_code=403, detail="detail=full requires admin authentication")

    health_data = filter_public_status_health_data(await gather_health_data(request))

    # Build the app's own timeline only (per-app providers are from skills, not global LLM providers)
    service_timelines: Dict[str, Any] = {}
    try:
        directus = DirectusService(cache_service=CacheService())
        try:
            service_timelines = await build_all_service_daily_statuses(
                directus, health_data, days=30,
                service_type_filter="app",
                service_ids_filter={app},
            )
        finally:
            await directus.close()
    except Exception as e:
        logger.error(f"[STATUS] Error building app detail timelines for {app}: {e}", exc_info=True)

    result = build_app_detail(app, health_data, service_timelines, is_admin=is_admin)
    if result is None:
        raise HTTPException(status_code=404, detail=f"App '{app}' not found")

    return result


@router.get("/functionalities", dependencies=[])
@limiter.limit("60/minute")
async def get_status_functionality_detail(
    request: Request,
    name: str = Query(
        ...,
        description="Functionality name (e.g., 'Chat', 'Signup', 'Payment').",
    ),
    detail: str = Query(
        default="summary",
        description="Detail level: summary or full (admin only).",
    ),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """
    Get detailed data for a specific functionality.
    Called when a user expands a functionality on the status page.

    Returns sub-category timelines and individual tests per sub-category.
    """
    if detail not in VALID_DETAIL_LEVELS:
        raise HTTPException(status_code=400, detail=f"detail must be one of: {', '.join(VALID_DETAIL_LEVELS)}")

    is_admin = current_user is not None and current_user.is_admin
    if detail == "full" and not is_admin:
        raise HTTPException(status_code=403, detail="detail=full requires admin authentication")

    result = get_functionality_detail(name, is_admin=is_admin)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Functionality '{name}' not found")

    # Strip error messages for non-admin
    if not is_admin:
        for test in result.get("tests", []):
            test.pop("error", None)

    return result


@router.get("/timeline/intraday", dependencies=[])
@limiter.limit("60/minute")
async def get_status_intraday(
    request: Request,
    date: str = Query(
        ...,
        description="Date in YYYY-MM-DD format.",
        pattern=r"^\d{4}-\d{2}-\d{2}$",
    ),
    source: Optional[str] = Query(
        default=None,
        description="Source type: 'functionality' or 'service'.",
    ),
    id: Optional[str] = Query(
        default=None,
        description="Source ID: functionality name or service ID.",
    ),
):
    """
    Get hourly-grouped intra-day data for any timeline.
    Used when clicking a day segment that has multiple checks/runs.

    For services: queries health events from database, grouped by hour.
    For functionalities/tests: queries test run files, grouped by hour.
    """
    if source == "service" and id:
        # Query health events for this service on this date
        from backend.core.api.app.services.status_aggregator import INFRASTRUCTURE_SERVICES
        svc_config = INFRASTRUCTURE_SERVICES.get(id)
        if svc_config:
            return await _get_service_intraday(date, svc_config["source_type"], svc_config["source_id"])
        # Fallback: try as raw service type/id
        return await _get_service_intraday(date, "external", id)

    return get_intra_day_runs_hourly(date, source=source, source_id=id)


async def _get_service_intraday(date: str, service_type: str, service_id: str) -> Dict[str, Any]:
    """Query health events for a service on a specific date, grouped by hour."""
    from datetime import datetime as _dt

    try:
        # Parse date to get timestamp range for this day
        day_start = _dt.fromisoformat(f"{date}T00:00:00+00:00")
        since_ts = int(day_start.timestamp())

        directus = DirectusService(cache_service=CacheService())
        try:
            events = await directus.health_event.get_health_history(
                since_timestamp=since_ts,
                service_type=service_type,
                limit=500,
            )
        finally:
            await directus.close()

        # Filter to this service_id and date
        day_events = []
        for ev in events:
            if ev.get("service_id") != service_id:
                continue
            created_at = ev.get("created_at", "")
            if created_at[:10] == date:
                day_events.append(ev)

        # Group by hour
        hours_map: Dict[int, List[Dict[str, Any]]] = {}
        for ev in day_events:
            created_at = ev.get("created_at", "")
            try:
                hour = int(created_at[11:13])
            except (ValueError, IndexError):
                hour = 0
            hours_map.setdefault(hour, []).append({
                "timestamp": created_at,
                "status": ev.get("new_status", "unknown"),
                "previous_status": ev.get("previous_status"),
                "error_message": ev.get("error_message"),
                "response_time_ms": ev.get("response_time_ms"),
            })

        hours = []
        for hour in sorted(hours_map.keys()):
            hour_events = hours_map[hour]
            statuses = [e["status"] for e in hour_events]

            hours.append({
                "hour": hour,
                "run_count": len(hour_events),
                "summary": {
                    "total": len(hour_events),
                    "passed": sum(1 for s in statuses if s == "healthy"),
                    "failed": sum(1 for s in statuses if s == "unhealthy"),
                    "skipped": 0,
                },
                "runs": hour_events,
            })

        return {
            "date": date,
            "source": "service",
            "id": service_id,
            "hours": hours,
        }

    except Exception as e:
        logger.error(f"[STATUS] Error getting service intraday: {e}", exc_info=True)
        return {"date": date, "source": "service", "id": service_id, "hours": []}


@router.get("/incidents", dependencies=[])
@limiter.limit("60/minute")
async def get_status_incidents_detail(
    request: Request,
    since_days: int = Query(
        default=30,
        ge=1,
        le=90,
        description="Number of days of incident history to return.",
    ),
    detail: str = Query(
        default="summary",
        description="Detail level: summary or full (admin only).",
    ),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """
    Get detailed incident history.
    Called when a user expands the incidents section.

    Summary: timestamps and status transitions only.
    Full (admin): includes error messages and durations.
    """
    if detail not in VALID_DETAIL_LEVELS:
        raise HTTPException(status_code=400, detail=f"detail must be one of: {', '.join(VALID_DETAIL_LEVELS)}")

    is_admin = current_user is not None and current_user.is_admin
    if detail == "full" and not is_admin:
        raise HTTPException(status_code=403, detail="detail=full requires admin authentication")

    since_ts = int((datetime.now(timezone.utc) - timedelta(days=since_days)).timestamp())

    directus = DirectusService(cache_service=CacheService())
    try:
        events = await directus.health_event.get_health_history(
            since_timestamp=since_ts,
            limit=500,
        )

        if not is_admin or detail != "full":
            events = strip_admin_fields_from_incidents(events)

        incident_summary = await directus.health_event.get_incident_summary(
            since_timestamp=since_ts,
        )

        return {
            "since_days": since_days,
            "total_incidents": incident_summary.get("total_incidents", 0),
            "total_downtime_seconds": incident_summary.get("total_downtime_seconds", 0) if is_admin else None,
            "events": events,
            "services": incident_summary.get("services", []) if is_admin else None,
        }
    finally:
        await directus.close()
