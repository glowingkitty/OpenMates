# backend/core/api/app/services/status_aggregator.py
# Aggregates health check data (Redis) + test results (disk) for the unified status API.
# Architecture: See docs/architecture/status-page.md
# Tests: backend/tests/test_status_service.py

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# Status label normalization: core API → status page
_STATUS_MAP = {
    "healthy": "operational",
    "unhealthy": "down",
    "degraded": "degraded",
    "unknown": "unknown",
}

# Service group definitions
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

_PAYMENT_IDS = {"stripe", "polar", "revolut", "invoiceninja"}
_EMAIL_IDS = {"brevo"}
_MODERATION_IDS = {"sightengine"}
_SEARCH_IDS = {"brave_search", "brave"}
_INFRA_IDS = {"vercel", "aws_bedrock"}
_PUBLIC_STATUS_EXCLUDED_PROVIDER_IDS = {"protonmail"}

_STATUS_SEVERITY = {"down": 3, "degraded": 2, "operational": 1, "unknown": 0}


def _normalize_status(status: str) -> str:
    """Normalize health status labels to status page conventions."""
    return _STATUS_MAP.get(status, "unknown")


def _worst_status(statuses: set) -> str:
    """Return the worst status from a set of statuses."""
    if "down" in statuses:
        return "down"
    if "degraded" in statuses:
        return "degraded"
    if "operational" in statuses:
        return "operational"
    return "unknown"


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
    return _worst_status({s.get("status", "unknown") for s in services})


def filter_public_status_health_data(health_data: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Remove internal-only providers from the public status overview payload."""
    filtered_providers = {
        provider_id: provider_data
        for provider_id, provider_data in health_data.get("providers", {}).items()
        if provider_id not in _PUBLIC_STATUS_EXCLUDED_PROVIDER_IDS
    }
    return {
        "providers": filtered_providers,
        "apps": dict(health_data.get("apps", {})),
        "external_services": dict(health_data.get("external_services", {})),
    }


async def gather_health_data(request) -> Dict[str, Dict[str, Any]]:
    """
    Gather current health data from Redis cache.
    Returns dict with keys: providers, apps, external_services.
    """
    from backend.core.api.app.services.cache import CacheService

    providers_health: Dict[str, Any] = {}
    apps_health: Dict[str, Any] = {}
    external_services_health: Dict[str, Any] = {}

    discovered_app_ids: Set[str] = set()
    if hasattr(request.app.state, "discovered_apps_metadata"):
        discovered_app_ids = set(request.app.state.discovered_apps_metadata.keys())

    try:
        cache_service = CacheService()
        client = await cache_service.client
        if not client:
            logger.warning("[STATUS] Redis client unavailable")
            return {"providers": {}, "apps": {}, "external_services": {}}

        cached_meta_json = await client.get("discovered_apps_metadata_v1")
        if cached_meta_json:
            if isinstance(cached_meta_json, bytes):
                cached_meta_json = cached_meta_json.decode("utf-8")
            cached_meta = json.loads(cached_meta_json)
            discovered_app_ids |= set(cached_meta.keys())

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


# ─── Per-service 30-day daily timelines ──────────────────────────────────────


def _generate_date_range(days: int = 30) -> List[str]:
    """Generate list of date strings for the last N days (oldest first)."""
    today = date.today()
    return [(today - timedelta(days=days - 1 - i)).isoformat() for i in range(days)]


async def build_all_service_daily_statuses(
    directus_service,
    health_data: Dict[str, Dict[str, Any]],
    days: int = 30,
    service_type_filter: Optional[str] = None,
    service_ids_filter: Optional[Set[str]] = None,
) -> Dict[str, List[Dict[str, str]]]:
    """
    Build per-service 30-day daily status from health transition events.

    Returns dict keyed by "service_type/service_id" → [{date, status}, ...] (30 entries).
    Uses single bulk query for all events, then fills gaps per service.

    Args:
        service_type_filter: Only include services of this type (provider, app, external).
        service_ids_filter: Only include services with these IDs (within the type filter).
    """
    since_ts = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp())
    dates = _generate_date_range(days)

    # Query events — scoped when filter is provided
    events = await directus_service.health_event.get_health_history(
        since_timestamp=since_ts,
        service_type=service_type_filter,
        limit=1000,
    )

    # Group events by service key
    events_by_service: Dict[str, List[Dict[str, Any]]] = {}
    for event in events:
        stype = event.get("service_type", "")
        sid = event.get("service_id", "")
        key = f"{stype}/{sid}"
        events_by_service.setdefault(key, []).append(event)

    # Build current status lookup from Redis data (applying filters)
    current_statuses: Dict[str, str] = {}
    type_map = {"providers": "provider", "apps": "app", "external_services": "external"}
    for category, stype in type_map.items():
        if service_type_filter and stype != service_type_filter:
            continue
        for sid, data in health_data.get(category, {}).items():
            if service_ids_filter and sid not in service_ids_filter:
                continue
            current_statuses[f"{stype}/{sid}"] = _normalize_status(data.get("status", "unknown"))

    # Build per-service timeline
    result: Dict[str, List[Dict[str, str]]] = {}

    for svc_key, current in current_statuses.items():
        svc_events = events_by_service.get(svc_key, [])

        # Sort oldest-first
        svc_events.sort(key=lambda e: e.get("created_at", ""))

        # For each day, determine status
        timeline = []

        # Find the initial status: the event just before the window, or fallback to current
        # Walk events oldest-first to carry forward
        running_status = current
        for d in dates:
            day_statuses = set()
            for ev in svc_events:
                ev_date = ev.get("created_at", "")[:10]  # "2026-03-22T..." → "2026-03-22"
                if ev_date == d:
                    day_statuses.add(_normalize_status(ev.get("new_status", "unknown")))
                elif ev_date < d:
                    # This event happened before this day — update running status
                    running_status = _normalize_status(ev.get("new_status", "unknown"))

            if day_statuses:
                # Multiple transitions on this day — use worst
                day_status = _worst_status(day_statuses)
                running_status = day_status
            else:
                day_status = running_status

            timeline.append({"date": d, "status": day_status})

        result[svc_key] = timeline

    return result


def compute_group_daily_timeline(
    service_timelines: Dict[str, List[Dict[str, str]]],
    service_keys: List[str],
) -> List[Dict[str, str]]:
    """Aggregate multiple service timelines into one group timeline. Worst status per day wins."""
    if not service_keys:
        return []

    # Get the date list from the first service
    first_key = next((k for k in service_keys if k in service_timelines), None)
    if not first_key:
        return []

    dates = [entry["date"] for entry in service_timelines[first_key]]
    result = []
    for i, d in enumerate(dates):
        day_statuses = set()
        for key in service_keys:
            tl = service_timelines.get(key, [])
            if i < len(tl):
                day_statuses.add(tl[i]["status"])
        result.append({"date": d, "status": _worst_status(day_statuses)})
    return result


def compute_overall_daily_timeline(
    service_timelines: Dict[str, List[Dict[str, str]]],
) -> List[Dict[str, str]]:
    """Compute overall daily timeline from all service timelines."""
    return compute_group_daily_timeline(service_timelines, list(service_timelines.keys()))


# ─── Health groups with timelines ────────────────────────────────────────────


def build_health_groups_summary(
    health_data: Dict[str, Dict[str, Any]],
    service_timelines: Dict[str, List[Dict[str, str]]],
) -> List[Dict[str, Any]]:
    """
    Build lightweight group summaries for the main /v1/status endpoint.

    Returns group_name, display_name, status, service_count, and group-level timeline_30d.
    Does NOT include services[] — those are loaded lazily via /v1/status/health?group=.
    """
    groups: Dict[str, List[str]] = {}  # group_name → list of normalized statuses
    group_service_keys: Dict[str, List[str]] = {}
    group_service_counts: Dict[str, int] = {}

    # AI providers
    for provider_id, data in health_data.get("providers", {}).items():
        group_name = "ai_providers"
        svc_key = f"provider/{provider_id}"
        groups.setdefault(group_name, []).append(
            _normalize_status(data.get("status", "unknown"))
        )
        group_service_keys.setdefault(group_name, []).append(svc_key)
        group_service_counts[group_name] = group_service_counts.get(group_name, 0) + 1

    # Applications
    for app_id, data in health_data.get("apps", {}).items():
        group_name = "apps"
        svc_key = f"app/{app_id}"
        groups.setdefault(group_name, []).append(
            _normalize_status(data.get("status", "unknown"))
        )
        group_service_keys.setdefault(group_name, []).append(svc_key)
        group_service_counts[group_name] = group_service_counts.get(group_name, 0) + 1

    # External services (grouped by type)
    for service_id, data in health_data.get("external_services", {}).items():
        group_name = _get_external_group(service_id)
        svc_key = f"external/{service_id}"
        groups.setdefault(group_name, []).append(
            _normalize_status(data.get("status", "unknown"))
        )
        group_service_keys.setdefault(group_name, []).append(svc_key)
        group_service_counts[group_name] = group_service_counts.get(group_name, 0) + 1

    result = []
    for group_name in sorted(groups.keys()):
        statuses = groups[group_name]
        group_tl = compute_group_daily_timeline(
            service_timelines, group_service_keys.get(group_name, [])
        )
        result.append({
            "group_name": group_name,
            "display_name": GROUP_DISPLAY_NAMES.get(group_name, group_name.replace("_", " ").title()),
            "status": _worst_status(set(statuses)),
            "service_count": group_service_counts.get(group_name, 0),
            "timeline_30d": group_tl,
        })

    return result


def get_group_service_info(
    health_data: Dict[str, Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """
    Return mapping from group_name → {service_type, service_ids} for use in filtered queries.
    """
    result: Dict[str, Dict[str, Any]] = {}

    # AI providers
    provider_ids = set(health_data.get("providers", {}).keys())
    if provider_ids:
        result["ai_providers"] = {"service_type": "provider", "service_ids": provider_ids}

    # Applications
    app_ids = set(health_data.get("apps", {}).keys())
    if app_ids:
        result["apps"] = {"service_type": "app", "service_ids": app_ids}

    # External services (grouped by type)
    ext_groups: Dict[str, Set[str]] = {}
    for service_id in health_data.get("external_services", {}).keys():
        group_name = _get_external_group(service_id)
        ext_groups.setdefault(group_name, set()).add(service_id)
    for group_name, svc_ids in ext_groups.items():
        result[group_name] = {"service_type": "external", "service_ids": svc_ids}

    return result


def build_health_groups(
    health_data: Dict[str, Dict[str, Any]],
    service_timelines: Dict[str, List[Dict[str, str]]],
    is_admin: bool = False,
) -> List[Dict[str, Any]]:
    """
    Build grouped service health data with per-service and per-group 30-day timelines.

    Always includes services[] (all users can see individual service status + timelines).
    Admin additionally gets error_message, response_time_ms, last_check.
    """
    groups: Dict[str, List[Dict[str, Any]]] = {}
    group_service_keys: Dict[str, List[str]] = {}

    # AI providers
    for provider_id, data in health_data.get("providers", {}).items():
        group_name = "ai_providers"
        svc_key = f"provider/{provider_id}"
        service: Dict[str, Any] = {
            "id": provider_id,
            "name": provider_id.replace("_", " ").title(),
            "status": _normalize_status(data.get("status", "unknown")),
            "timeline_30d": service_timelines.get(svc_key, []),
        }
        if is_admin:
            service["error_message"] = data.get("last_error")
            service["response_time_ms"] = data.get("response_times_ms", {})
            service["last_check"] = data.get("last_check")
        groups.setdefault(group_name, []).append(service)
        group_service_keys.setdefault(group_name, []).append(svc_key)

    # Applications
    for app_id, data in health_data.get("apps", {}).items():
        group_name = "apps"
        svc_key = f"app/{app_id}"
        service = {
            "id": app_id,
            "name": app_id.replace("_", " ").title(),
            "status": _normalize_status(data.get("status", "unknown")),
            "timeline_30d": service_timelines.get(svc_key, []),
        }
        if is_admin:
            service["api"] = data.get("api", {})
            service["worker"] = data.get("worker", {})
            service["last_check"] = data.get("last_check")
        groups.setdefault(group_name, []).append(service)
        group_service_keys.setdefault(group_name, []).append(svc_key)

    # External services (grouped by type)
    for service_id, data in health_data.get("external_services", {}).items():
        group_name = _get_external_group(service_id)
        svc_key = f"external/{service_id}"
        service = {
            "id": service_id,
            "name": service_id.replace("_", " ").title(),
            "status": _normalize_status(data.get("status", "unknown")),
            "timeline_30d": service_timelines.get(svc_key, []),
        }
        if is_admin:
            service["error_message"] = data.get("last_error")
            service["response_time_ms"] = data.get("response_times_ms", {})
            service["last_check"] = data.get("last_check")
        groups.setdefault(group_name, []).append(service)
        group_service_keys.setdefault(group_name, []).append(svc_key)

    # Build final group list with group-level timelines
    result = []
    for group_name, services in sorted(groups.items()):
        group_tl = compute_group_daily_timeline(
            service_timelines, group_service_keys.get(group_name, [])
        )
        result.append({
            "group_name": group_name,
            "display_name": GROUP_DISPLAY_NAMES.get(group_name, group_name.replace("_", " ").title()),
            "status": _compute_group_status(services),
            "service_count": len(services),
            "timeline_30d": group_tl,
            "services": services,
        })

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


# ─── Admin field stripping ───────────────────────────────────────────────────


def strip_admin_fields_from_tests(test_data: Dict[str, Any]) -> Dict[str, Any]:
    """Remove admin-only fields (error messages) from test data."""
    if not test_data:
        return test_data

    result = dict(test_data)

    if "suites" in result and isinstance(result["suites"], dict):
        cleaned_suites = {}
        for suite_name, suite_data in result["suites"].items():
            cleaned_suite = dict(suite_data)
            if "tests" in cleaned_suite:
                cleaned_suite["tests"] = [
                    {k: v for k, v in t.items() if k != "error"}
                    for t in cleaned_suite["tests"]
                ]
            cleaned_suites[suite_name] = cleaned_suite
        result["suites"] = cleaned_suites

    if "flaky_tests" in result:
        result["flaky_tests"] = [
            {k: v for k, v in t.items() if k != "error"}
            for t in result.get("flaky_tests", [])
        ]

    return result


def build_current_issues(
    health_data: Dict[str, Dict[str, Any]],
    is_admin: bool = False,
) -> List[Dict[str, Any]]:
    """
    Build a list of current issues (unhealthy/degraded services) for the overview.
    Admin users see error messages. Public users see status only.
    """
    issues: List[Dict[str, Any]] = []

    type_map = {
        "providers": ("provider", "ai_providers"),
        "external_services": ("external", None),  # group determined dynamically
    }

    for category, (stype, default_group) in type_map.items():
        for sid, data in health_data.get(category, {}).items():
            status = _normalize_status(data.get("status", "unknown"))
            if status in ("down", "degraded"):
                group = default_group or _get_external_group(sid)
                issue: Dict[str, Any] = {
                    "service_type": stype,
                    "service_id": sid,
                    "name": sid.replace("_", " ").title(),
                    "group": GROUP_DISPLAY_NAMES.get(group, group),
                    "status": status,
                }
                if is_admin:
                    issue["error_message"] = data.get("last_error")
                    issue["last_check"] = data.get("last_check")
                issues.append(issue)

    # Apps
    for app_id, data in health_data.get("apps", {}).items():
        status = _normalize_status(data.get("status", "unknown"))
        if status in ("down", "degraded"):
            issue = {
                "service_type": "app",
                "service_id": app_id,
                "name": app_id.replace("_", " ").title(),
                "group": "Applications",
                "status": status,
            }
            if is_admin:
                issue["last_check"] = data.get("last_check")
            issues.append(issue)

    # Sort by severity (down first, then degraded)
    issues.sort(key=lambda i: (0 if i["status"] == "down" else 1, i["name"]))
    return issues


def strip_admin_fields_from_incidents(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove error_message from incident events for non-admin users."""
    return [
        {
            "service_type": e.get("service_type"),
            "service_id": e.get("service_id"),
            "previous_status": _normalize_status(e.get("previous_status", "unknown")),
            "new_status": _normalize_status(e.get("new_status", "unknown")),
            "created_at": e.get("created_at"),
        }
        for e in events
    ]
