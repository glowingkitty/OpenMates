# backend/core/api/app/routes/status_routes.py
# Unified status API endpoints for the public status page.
# Serves health + test data with optional admin-only detail.
# Architecture: See docs/architecture/status-page.md
# Tests: N/A — covered by status API integration tests

from __future__ import annotations

import logging
from datetime import datetime, timezone
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
    GROUP_DISPLAY_NAMES,
    build_all_service_daily_statuses,
    build_current_issues,
    build_health_groups,
    build_health_groups_summary,
    compute_overall_daily_timeline,
    compute_overall_status,
    gather_health_data,
    get_group_service_info,
    filter_public_status_health_data,
    strip_admin_fields_from_incidents,
    strip_admin_fields_from_tests,
)
from backend.core.api.app.services.test_results_service import (
    get_intra_day_runs,
    get_per_test_history,
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

    # Health data (always needed for overall_status and current_issues)
    health_data = filter_public_status_health_data(await gather_health_data(request))
    response["overall_status"] = compute_overall_status(health_data)

    # Current issues overview — unhealthy services + failed tests (always included)
    service_issues = build_current_issues(health_data, is_admin=is_admin)
    # Add failed test names from latest run
    test_issues: List[Dict[str, Any]] = []
    latest_detail = get_latest_run_detail()
    if latest_detail:
        for suite_name, suite_data in latest_detail.get("suites", {}).items():
            for test in suite_data.get("tests", []):
                if test.get("status") == "failed":
                    entry: Dict[str, Any] = {
                        "suite": suite_name,
                        "name": test.get("name") or test.get("file", ""),
                        "file": test.get("file", ""),
                    }
                    if is_admin:
                        entry["error"] = test.get("error")
                    test_issues.append(entry)
    response["current_issues"] = {
        "services": service_issues,
        "failed_tests": test_issues,
    }

    # Build per-service 30-day timelines (needed for group-level timelines and overall timeline)
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

    # Health groups — summary only (no services[], those load lazily via /v1/status/health?group=)
    if "health" in sections:
        response["health"] = {
            "groups": build_health_groups_summary(health_data, service_timelines),
        }

    # Tests — summary only (suite-level counts + timelines, no per-test data or categories)
    if "tests" in sections:
        test_summary = get_latest_run_summary()
        if test_summary:
            test_section = dict(test_summary)
            test_section["trend"] = get_daily_trend(days=30)
            # Add per-suite 30-day timeline (lightweight: pass_rate per day)
            suite_history = get_per_suite_daily_history(days=30)
            for suite in test_section.get("suites", []):
                suite["timeline_30d"] = suite_history.get(suite["name"], [])
            response["tests"] = test_section
        else:
            response["tests"] = {
                "overall_status": "unknown", "latest_run": None,
                "suites": [], "trend": [],
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

    health_data = filter_public_status_health_data(await gather_health_data(request))

    # Get group→service mapping to scope the timeline query
    group_info = get_group_service_info(health_data)
    if group not in group_info:
        # Group might exist but have no services — check if it's a valid group name
        if group not in GROUP_DISPLAY_NAMES:
            raise HTTPException(status_code=404, detail=f"Group '{group}' not found")

    # Build per-service timelines scoped to this group only
    service_timelines: Dict[str, Any] = {}
    info = group_info.get(group)
    if info:
        try:
            directus = DirectusService(cache_service=CacheService())
            try:
                service_timelines = await build_all_service_daily_statuses(
                    directus, health_data, days=30,
                    service_type_filter=info["service_type"],
                    service_ids_filter=info["service_ids"],
                )
            finally:
                await directus.close()
        except Exception as e:
            logger.error(f"[STATUS] Error building group timelines for {group}: {e}", exc_info=True)

    # Build full group with services[] and per-service timelines
    all_groups = build_health_groups(health_data, service_timelines, is_admin=True)

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
                    "timeline_30d": s.get("timeline_30d", []),
                    **({"skills": s["skills"]} if s.get("skills") else {}),
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
    category: Optional[str] = Query(
        default=None,
        description="Filter by test category name (e.g., 'Chat', 'Auth & Signup'). Only applies to playwright suite.",
    ),
    detail: str = Query(
        default="summary",
        description="Detail level: summary or full (admin only).",
    ),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """
    Get detailed test results for a suite, with per-test histories and categories.
    Called when a user expands a test suite on the status page.

    Returns individual tests with history_30d, and category breakdown for playwright.
    Admin additionally gets error messages.
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

    result = dict(test_detail)

    # Add per-test 30-day histories
    per_test_history = get_per_test_history(days=30)
    test_summary = get_latest_run_summary()
    if result.get("suites") and isinstance(result["suites"], dict):
        for suite_name, suite_data in result["suites"].items():
            for test in suite_data.get("tests", []):
                test_key = test.get("file") or test.get("name", "")
                test["history_30d"] = per_test_history.get(test_key, [])
                test["last_run"] = test.get("run_id") or (
                    test_summary.get("latest_run", {}).get("timestamp") if test_summary else None
                )

    # Add categorized breakdown filtered to the requested suite
    categorized = get_categorized_test_summary(is_admin=True)
    all_categories = categorized.get("categories", {})

    # Filter categories to the requested suite
    categories = {}
    for cat_key, cat_data in all_categories.items():
        cat_suite = cat_data.get("suite", "playwright")
        if suite and cat_suite != suite:
            continue
        # Use display_name as key for frontend (strip suite prefix)
        display_key = cat_data.get("display_name", cat_key)
        categories[display_key] = cat_data

    # Filter to specific category if requested
    if category and categories:
        categories = {k: v for k, v in categories.items() if k == category}

    result["categories"] = categories

    # Get flaky tests
    result["flaky_tests"] = get_flaky_tests()

    # Strip error messages for non-admin
    if not is_admin:
        result = strip_admin_fields_from_tests(result)
        # Also strip errors from categories
        for cat_data in result.get("categories", {}).values():
            if cat_data.get("tests"):
                for test in cat_data["tests"]:
                    test.pop("error", None)

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


@router.get("/tests/runs", dependencies=[])
@limiter.limit("60/minute")
async def get_status_intra_day_runs(
    request: Request,
    date: str = Query(
        ...,
        description="Date in YYYY-MM-DD format to get all test runs for.",
        pattern=r"^\d{4}-\d{2}-\d{2}$",
    ),
):
    """
    Get all individual test runs for a specific date.
    Used for the intra-day sub-timeline when clicking a day with multiple runs.
    Returns run summaries sorted by timestamp ascending.
    """
    runs = get_intra_day_runs(date)
    return {
        "date": date,
        "run_count": len(runs),
        "runs": runs,
    }
