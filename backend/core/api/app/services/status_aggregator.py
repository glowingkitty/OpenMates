# backend/core/api/app/services/status_aggregator.py
# Aggregates health check data (Redis) + test results (disk) for the unified status API.
# Architecture: See docs/architecture/status-page.md
# Tests: N/A — covered by status API integration tests

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Set

logger = logging.getLogger(__name__)

# Status label normalization: core API → status page
_STATUS_MAP = {
    "healthy": "operational",
    "unhealthy": "down",
    "degraded": "degraded",
    "unknown": "unknown",
}

# Service group definitions matching backend/status/app/config.py
GROUP_DISPLAY_NAMES = {
    "ai_providers": "AI Providers",
    "core_platform": "Core Platform",
    "payment": "Payment",
    "email": "Email",
    "content_moderation": "Content Moderation",
    "search_and_data": "Search & Data",
    "infrastructure": "Infrastructure",
    "apps": "Applications",
}

# Map service IDs to their groups
_PAYMENT_IDS = {"stripe", "polar", "revolut", "invoiceninja"}
_EMAIL_IDS = {"brevo"}
_MODERATION_IDS = {"sightengine"}
_SEARCH_IDS = {"brave_search", "brave"}
_INFRA_IDS = {"vercel", "aws_bedrock"}


def _normalize_status(status: str) -> str:
    """Normalize health status labels to status page conventions."""
    return _STATUS_MAP.get(status, "unknown")


def _get_external_group(service_id: str) -> str:
    """Determine which group an external service belongs to."""
    if service_id in _PAYMENT_IDS:
        return "payment"
    if service_id in _EMAIL_IDS:
        return "email"
    if service_id in _MODERATION_IDS:
        return "content_moderation"
    if service_id in _SEARCH_IDS:
        return "search_and_data"
    if service_id in _INFRA_IDS:
        return "infrastructure"
    return "infrastructure"


def _compute_group_status(services: List[Dict[str, Any]]) -> str:
    """Compute overall group status from individual service statuses."""
    if not services:
        return "unknown"
    statuses = {s.get("status", "unknown") for s in services}
    if statuses == {"operational"}:
        return "operational"
    if "down" in statuses:
        return "down"
    if "degraded" in statuses:
        return "degraded"
    return "unknown"


async def gather_health_data(request) -> Dict[str, Dict[str, Any]]:
    """
    Gather current health data from Redis cache.

    Returns dict with keys: providers, apps, external_services.
    Each value is a dict of service_id → health data.

    This is extracted from the /v1/health endpoint logic in main.py
    to be reused by both /v1/health and /v1/status.
    """
    from backend.core.api.app.services.cache import CacheService

    providers_health: Dict[str, Any] = {}
    apps_health: Dict[str, Any] = {}
    external_services_health: Dict[str, Any] = {}

    # Build discovered app IDs set
    discovered_app_ids: Set[str] = set()
    if hasattr(request.app.state, "discovered_apps_metadata"):
        discovered_app_ids = set(request.app.state.discovered_apps_metadata.keys())

    try:
        cache_service = CacheService()
        client = await cache_service.client
        if not client:
            logger.warning("[STATUS] Redis client unavailable")
            return {"providers": {}, "apps": {}, "external_services": {}}

        # Supplement discovered apps from Redis cache
        cached_meta_json = await client.get("discovered_apps_metadata_v1")
        if cached_meta_json:
            if isinstance(cached_meta_json, bytes):
                cached_meta_json = cached_meta_json.decode("utf-8")
            cached_meta = json.loads(cached_meta_json)
            discovered_app_ids |= set(cached_meta.keys())

        # Provider health
        for key in await client.keys("health_check:provider:*"):
            if isinstance(key, bytes):
                key = key.decode("utf-8")
            provider_id = key.replace("health_check:provider:", "")
            raw = await client.get(key)
            if raw:
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                data = json.loads(raw)
                providers_health[provider_id] = {
                    "status": data.get("status", "unknown"),
                    "last_check": data.get("last_check"),
                    "last_error": data.get("last_error"),
                    "response_times_ms": data.get("response_times_ms", {}),
                }

        # App health (filtered by discovered apps)
        for key in await client.keys("health_check:app:*"):
            if isinstance(key, bytes):
                key = key.decode("utf-8")
            app_id = key.replace("health_check:app:", "")
            if discovered_app_ids and app_id not in discovered_app_ids:
                continue
            raw = await client.get(key)
            if raw:
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                data = json.loads(raw)
                apps_health[app_id] = {
                    "status": data.get("status", "unknown"),
                    "api": data.get("api", {}),
                    "worker": data.get("worker", {}),
                    "last_check": data.get("last_check"),
                }

        # External service health
        for key in await client.keys("health_check:external:*"):
            if isinstance(key, bytes):
                key = key.decode("utf-8")
            service_id = key.replace("health_check:external:", "")
            raw = await client.get(key)
            if raw:
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                data = json.loads(raw)
                external_services_health[service_id] = {
                    "status": data.get("status", "unknown"),
                    "last_check": data.get("last_check"),
                    "last_error": data.get("last_error"),
                    "response_times_ms": data.get("response_times_ms", {}),
                }

    except Exception as e:
        logger.error(f"[STATUS] Error gathering health data: {e}", exc_info=True)

    return {
        "providers": providers_health,
        "apps": apps_health,
        "external_services": external_services_health,
    }


def build_health_groups(
    health_data: Dict[str, Dict[str, Any]],
    is_admin: bool = False,
) -> List[Dict[str, Any]]:
    """
    Build grouped service health data for the status page.

    Args:
        health_data: Raw health data from gather_health_data()
        is_admin: If True, include error messages and response times

    Returns:
        List of group dicts with group_name, display_name, status, service_count.
        If is_admin, each group also has a services[] array with details.
    """
    groups: Dict[str, List[Dict[str, Any]]] = {}

    # AI providers
    for provider_id, data in health_data.get("providers", {}).items():
        group_name = "ai_providers"
        service = {
            "id": provider_id,
            "name": provider_id.replace("_", " ").title(),
            "status": _normalize_status(data.get("status", "unknown")),
        }
        if is_admin:
            service["error_message"] = data.get("last_error")
            service["response_time_ms"] = data.get("response_times_ms", {})
            service["last_check"] = data.get("last_check")
        groups.setdefault(group_name, []).append(service)

    # Applications
    for app_id, data in health_data.get("apps", {}).items():
        group_name = "apps"
        service = {
            "id": app_id,
            "name": app_id.replace("_", " ").title(),
            "status": _normalize_status(data.get("status", "unknown")),
        }
        if is_admin:
            service["api"] = data.get("api", {})
            service["worker"] = data.get("worker", {})
            service["last_check"] = data.get("last_check")
        groups.setdefault(group_name, []).append(service)

    # External services (grouped by type)
    for service_id, data in health_data.get("external_services", {}).items():
        group_name = _get_external_group(service_id)
        service = {
            "id": service_id,
            "name": service_id.replace("_", " ").title(),
            "status": _normalize_status(data.get("status", "unknown")),
        }
        if is_admin:
            service["error_message"] = data.get("last_error")
            service["response_time_ms"] = data.get("response_times_ms", {})
            service["last_check"] = data.get("last_check")
        groups.setdefault(group_name, []).append(service)

    # Build final group list
    result = []
    for group_name, services in sorted(groups.items()):
        group = {
            "group_name": group_name,
            "display_name": GROUP_DISPLAY_NAMES.get(group_name, group_name.replace("_", " ").title()),
            "status": _compute_group_status(services),
            "service_count": len(services),
        }
        if is_admin:
            group["services"] = services
        result.append(group)

    return result


def compute_overall_status(health_data: Dict[str, Dict[str, Any]]) -> str:
    """Compute overall system status from raw health data."""
    all_statuses = []
    for category in health_data.values():
        for service_data in category.values():
            all_statuses.append(service_data.get("status", "unknown"))

    if not all_statuses:
        return "unknown"

    unhealthy = sum(1 for s in all_statuses if s == "unhealthy")
    degraded = sum(1 for s in all_statuses if s == "degraded")

    if unhealthy > 0:
        if unhealthy < len(all_statuses):
            return "degraded"
        return "down"
    if degraded > 0:
        return "degraded"
    return "operational"


async def build_timeline_buckets(
    directus_service,
    period_days: int = 90,
) -> List[Dict[str, Any]]:
    """
    Build timeline buckets from health event history.

    Computes time buckets where each bucket has the worst status
    during that period. Gaps are filled with the previous status.

    Args:
        directus_service: DirectusService instance for querying health events
        period_days: How many days of history to include

    Returns:
        List of {start, end, status} dicts, oldest first.
    """
    import math

    now = datetime.now(timezone.utc)
    since = now - timedelta(days=period_days)
    since_ts = int(since.timestamp())

    # Choose bucket size based on period
    if period_days <= 7:
        bucket_hours = 1
    elif period_days <= 30:
        bucket_hours = 4
    else:
        bucket_hours = 24

    # Get health events for the period
    events = await directus_service.health_event.get_health_history(
        since_timestamp=since_ts,
        limit=1000,
    )

    # Build buckets
    total_hours = period_days * 24
    num_buckets = math.ceil(total_hours / bucket_hours)
    buckets = []

    for i in range(num_buckets):
        bucket_start = since + timedelta(hours=i * bucket_hours)
        bucket_end = since + timedelta(hours=(i + 1) * bucket_hours)
        if bucket_end > now:
            bucket_end = now

        # Find events in this bucket
        bucket_statuses = set()
        for event in events:
            event_time_str = event.get("created_at", "")
            try:
                event_time = datetime.fromisoformat(event_time_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                continue
            if bucket_start <= event_time < bucket_end:
                new_status = event.get("new_status", "unknown")
                bucket_statuses.add(_normalize_status(new_status))

        # Determine bucket status (worst wins)
        if "down" in bucket_statuses:
            bucket_status = "down"
        elif "degraded" in bucket_statuses:
            bucket_status = "degraded"
        elif bucket_statuses:
            bucket_status = "operational"
        else:
            bucket_status = "operational"  # No events = assume operational

        buckets.append({
            "start": bucket_start.isoformat(),
            "end": bucket_end.isoformat(),
            "status": bucket_status,
        })

    return buckets


def strip_admin_fields_from_tests(test_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Remove admin-only fields (error messages, detailed errors) from test data.
    Returns a copy safe for non-admin users.
    """
    if not test_data:
        return test_data

    result = dict(test_data)

    # Strip errors from individual test rows in suites
    if "suites" in result and isinstance(result["suites"], dict):
        cleaned_suites = {}
        for suite_name, suite_data in result["suites"].items():
            cleaned_suite = dict(suite_data)
            if "tests" in cleaned_suite:
                cleaned_suite["tests"] = [
                    {
                        "name": t.get("name", ""),
                        "file": t.get("file", ""),
                        "status": t.get("status", "unknown"),
                        "duration_seconds": t.get("duration_seconds", 0),
                        # error deliberately omitted
                    }
                    for t in cleaned_suite["tests"]
                ]
            cleaned_suites[suite_name] = cleaned_suite
        result["suites"] = cleaned_suites

    # Strip errors from flaky tests
    if "flaky_tests" in result:
        result["flaky_tests"] = [
            {
                "name": t.get("name", ""),
                "flaky_count": t.get("flaky_count", 0),
                "total_runs": t.get("total_runs", 0),
                "last_flaky": t.get("last_flaky"),
                # error deliberately omitted
            }
            for t in result.get("flaky_tests", [])
        ]

    return result


def strip_admin_fields_from_incidents(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove error_message from incident events for non-admin users."""
    return [
        {
            "service_type": e.get("service_type"),
            "service_id": e.get("service_id"),
            "previous_status": _normalize_status(e.get("previous_status", "unknown")),
            "new_status": _normalize_status(e.get("new_status", "unknown")),
            "created_at": e.get("created_at"),
            # error_message and duration_seconds deliberately omitted
        }
        for e in events
    ]
