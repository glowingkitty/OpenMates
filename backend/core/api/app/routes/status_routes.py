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

    # Build provider timelines (scoped to providers only for efficiency)
    service_timelines: Dict[str, Any] = {}
    try:
        directus = DirectusService(cache_service=CacheService())
        try:
            service_timelines = await build_all_service_daily_statuses(
                directus, health_data, days=30,
                service_type_filter="provider",
            )
            # Also get the app's own timeline
            app_timelines = await build_all_service_daily_statuses(
                directus, health_data, days=30,
                service_type_filter="app",
                service_ids_filter={app},
            )
            service_timelines.update(app_timelines)
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

    Returns hours with aggregated summaries per hour.
    """
    return get_intra_day_runs_hourly(date, source=source, source_id=id)


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
