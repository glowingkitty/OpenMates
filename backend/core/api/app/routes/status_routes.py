# backend/core/api/app/routes/status_routes.py
# Unified status API endpoints for the public status page.
# Serves health + test data with optional admin-only detail.
# Architecture: See docs/architecture/status-page.md
# Tests: N/A — covered by status API integration tests

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

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
    build_health_groups,
    compute_overall_daily_timeline,
    compute_overall_status,
    gather_health_data,
    strip_admin_fields_from_incidents,
    strip_admin_fields_from_tests,
)
from backend.core.api.app.services.test_results_service import (
    get_categorized_test_summary,
    get_daily_trend,
    get_flaky_tests,
    get_latest_run_detail,
    get_latest_run_summary,
    get_per_suite_daily_history,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/v1/status",
    tags=["Status"],
)

VALID_SECTIONS = {"health", "tests", "timeline", "incidents"}
VALID_DETAIL_LEVELS = {"summary", "full"}


def _parse_sections(section_param: Optional[str]) -> set:
    """Parse comma-separated section filter, defaulting to all."""
    if not section_param:
        return VALID_SECTIONS
    requested = {s.strip() for s in section_param.split(",")}
    invalid = requested - VALID_SECTIONS
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid section(s): {', '.join(sorted(invalid))}. "
            f"Valid: {', '.join(sorted(VALID_SECTIONS))}",
        )
    return requested


def _check_admin_for_detail(detail: str, user: Optional[User]) -> bool:
    """
    Check if the user has admin access for detail=full.

    Returns True if the request is admin-authorized for full detail.
    Raises 403 if detail=full is requested without admin auth.
    """
    if detail != "full":
        return False
    if user is None or not user.is_admin:
        raise HTTPException(
            status_code=403,
            detail="detail=full requires admin authentication",
        )
    return True


@router.get("", dependencies=[])
@limiter.limit("30/minute")
async def get_status(
    request: Request,
    section: Optional[str] = Query(
        default=None,
        description="Comma-separated sections to include: health, tests, timeline, incidents. Default: all.",
    ),
    detail: str = Query(
        default="summary",
        description="Detail level: summary (status colors only) or full (admin: includes errors, response times).",
    ),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """
    Unified status endpoint. Returns summary-level data by default.

    Public endpoint — no auth required for summary view.
    Admin auth required for detail=full (includes error messages, response times).
    """
    sections = _parse_sections(section)

    if detail not in VALID_DETAIL_LEVELS:
        raise HTTPException(status_code=400, detail=f"detail must be one of: {', '.join(VALID_DETAIL_LEVELS)}")

    is_admin = current_user is not None and current_user.is_admin
    if detail == "full" and not is_admin:
        raise HTTPException(status_code=403, detail="detail=full requires admin authentication")

    response: Dict[str, Any] = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "is_admin": is_admin,
    }

    # Health data (always needed for overall_status)
    health_data = await gather_health_data(request)
    response["overall_status"] = compute_overall_status(health_data)

    # Build per-service 30-day timelines (needed for health groups and overall timeline)
    service_timelines: Dict[str, Any] = {}
    if "health" in sections or "timeline" in sections:
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

    # Overall 30-day timeline (one segment per day, aggregated from all services)
    if "timeline" in sections:
        response["overall_timeline_30d"] = compute_overall_daily_timeline(service_timelines)

    # Health groups with per-service and per-group timelines
    if "health" in sections:
        response["health"] = {
            "groups": build_health_groups(
                health_data, service_timelines, is_admin=is_admin,
            ),
        }

    # Tests — all data visible to all users (error messages gated by is_admin in categorized_test_summary)
    if "tests" in sections:
        test_summary = get_latest_run_summary()
        if test_summary:
            test_section = dict(test_summary)
            test_section["trend"] = get_daily_trend(days=30)
            # Add per-suite 30-day history
            suite_history = get_per_suite_daily_history(days=30)
            for suite in test_section.get("suites", []):
                suite["timeline_30d"] = suite_history.get(suite["name"], [])
            # Add categorized breakdown (all users see categories + test names; admin sees errors)
            categorized = get_categorized_test_summary(is_admin=True)  # Always include test names
            # Strip error fields for non-admin
            if not is_admin:
                for cat_data in categorized.get("categories", {}).values():
                    if cat_data.get("tests"):
                        for test in cat_data["tests"]:
                            test.pop("error", None)
            test_section["categories"] = categorized.get("categories", {})
            response["tests"] = test_section
        else:
            response["tests"] = {
                "overall_status": "unknown", "latest_run": None,
                "suites": [], "trend": [], "categories": {},
            }

    # Incidents — 30-day window
    if "incidents" in sections:
        try:
            from datetime import timedelta as _td
            since_30d = int((datetime.now(timezone.utc) - _td(days=30)).timestamp())
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


@router.get("/health", dependencies=[])
@limiter.limit("60/minute")
async def get_status_health_detail(
    request: Request,
    group: str = Query(
        ...,
        description="Service group to get details for (e.g., ai_providers, apps, payment).",
    ),
    detail: str = Query(
        default="summary",
        description="Detail level: summary or full (admin only).",
    ),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """
    Get detailed health data for a specific service group.
    Called when a user expands a group on the status page.

    Summary: per-service status colors only.
    Full (admin): includes error messages, response times, last check.
    """
    if detail not in VALID_DETAIL_LEVELS:
        raise HTTPException(status_code=400, detail=f"detail must be one of: {', '.join(VALID_DETAIL_LEVELS)}")

    is_admin = current_user is not None and current_user.is_admin
    if detail == "full" and not is_admin:
        raise HTTPException(status_code=403, detail="detail=full requires admin authentication")

    health_data = await gather_health_data(request)
    # Always pass is_admin=True to build_health_groups to get services[]
    # Then strip admin fields if not admin
    all_groups = build_health_groups(health_data, is_admin=True)

    target_group = None
    for g in all_groups:
        if g["group_name"] == group:
            target_group = g
            break

    if target_group is None:
        raise HTTPException(status_code=404, detail=f"Group '{group}' not found")

    # Strip admin-only fields if not admin
    if not is_admin or detail != "full":
        if "services" in target_group:
            target_group["services"] = [
                {
                    "id": s["id"],
                    "name": s["name"],
                    "status": s["status"],
                }
                for s in target_group["services"]
            ]

    return target_group


@router.get("/tests", dependencies=[])
@limiter.limit("60/minute")
async def get_status_tests_detail(
    request: Request,
    suite: Optional[str] = Query(
        default=None,
        description="Filter by suite name: playwright, vitest, pytest_unit.",
    ),
    detail: str = Query(
        default="summary",
        description="Detail level: summary or full (admin only).",
    ),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """
    Get detailed test results, optionally filtered by suite.
    Called when a user expands a test suite on the status page.

    Summary: pass/fail/skip counts per suite.
    Full (admin): individual test rows with error messages.
    """
    if detail not in VALID_DETAIL_LEVELS:
        raise HTTPException(status_code=400, detail=f"detail must be one of: {', '.join(VALID_DETAIL_LEVELS)}")

    is_admin = current_user is not None and current_user.is_admin
    if detail == "full" and not is_admin:
        raise HTTPException(status_code=403, detail="detail=full requires admin authentication")

    # Get detailed test data
    test_detail = get_latest_run_detail(suite_name=suite)
    if not test_detail:
        return {"run_id": None, "suites": {}, "summary": {}}

    # Get flaky tests
    flaky = get_flaky_tests()

    result = dict(test_detail)
    result["flaky_tests"] = flaky

    # Strip error messages for non-admin
    if not is_admin or detail != "full":
        result = strip_admin_fields_from_tests(result)

    return result


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
    Called when a user expands the incidents section on the status page.

    Summary: timestamps and status transitions only.
    Full (admin): includes error messages and durations.
    """
    if detail not in VALID_DETAIL_LEVELS:
        raise HTTPException(status_code=400, detail=f"detail must be one of: {', '.join(VALID_DETAIL_LEVELS)}")

    is_admin = current_user is not None and current_user.is_admin
    if detail == "full" and not is_admin:
        raise HTTPException(status_code=403, detail="detail=full requires admin authentication")

    from datetime import timedelta

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
