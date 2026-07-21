# backend/shared/python_utils/connected_account_registry.py
#
# Provider/capability registry for connected-account skill execution.
# Connected accounts are provider-owned resources that may authorize multiple
# OpenMates apps; app skills declare the provider and action they need here while
# token refs remain scoped to a specific active chat message and app action.
#
# Spec: docs/specs/calendar-permission-management/spec.yml

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from backend.shared.providers.google_calendar.oauth import exchange_google_refresh_token
from backend.shared.providers.revolut_business.oauth import exchange_revolut_business_refresh_token

ExchangeRefreshToken = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class ConnectedAccountSkillConfig:
    app_id: str
    skill_id: str
    provider_id: str
    action: str
    request_field: str = "requests"
    scope_kind: str = "generic"


CONNECTED_ACCOUNT_SKILL_CONFIGS: dict[tuple[str, str], ConnectedAccountSkillConfig] = {
    ("calendar", "get-events"): ConnectedAccountSkillConfig(
        app_id="calendar",
        skill_id="get-events",
        provider_id="google",
        action="read",
        scope_kind="calendar_events",
    ),
    ("calendar", "create-event"): ConnectedAccountSkillConfig(
        app_id="calendar",
        skill_id="create-event",
        provider_id="google",
        action="write",
        scope_kind="calendar_events",
    ),
    ("calendar", "update-event"): ConnectedAccountSkillConfig(
        app_id="calendar",
        skill_id="update-event",
        provider_id="google",
        action="update",
        scope_kind="calendar_events",
    ),
    ("calendar", "delete-event"): ConnectedAccountSkillConfig(
        app_id="calendar",
        skill_id="delete-event",
        provider_id="google",
        action="delete",
        scope_kind="calendar_events",
    ),
    ("finance", "check_accounts"): ConnectedAccountSkillConfig(
        app_id="finance",
        skill_id="check_accounts",
        provider_id="revolut_business",
        action="read",
        request_field="connected_account_requests",
        scope_kind="provider_account",
    ),
}


def normalize_connected_account_app_id(value: Any) -> str:
    if value == "google_calendar":
        return "calendar"
    return str(value or "")


def normalize_connected_account_provider_id(value: Any) -> str:
    normalized = str(value or "").strip()
    if normalized in {"calendar", "google_calendar"}:
        return "google"
    if normalized == "finance":
        return "revolut_business"
    return normalized


def connected_account_skill_config(app_id: str, skill_id: str) -> ConnectedAccountSkillConfig:
    config = CONNECTED_ACCOUNT_SKILL_CONFIGS.get((app_id, skill_id))
    if not config:
        raise ValueError(f"{app_id}.{skill_id} is not a connected-account skill")
    return config


def is_connected_account_skill(app_id: str, skill_id: str) -> bool:
    return (app_id, skill_id) in CONNECTED_ACCOUNT_SKILL_CONFIGS


def is_connected_account_action_allowed(app_id: str, provider_id: str | None, action: str) -> bool:
    normalized_app = normalize_connected_account_app_id(app_id)
    normalized_provider = normalize_connected_account_provider_id(provider_id or app_id)
    return any(
        config.app_id == normalized_app
        and normalize_connected_account_provider_id(config.provider_id) == normalized_provider
        and config.action == action
        for config in CONNECTED_ACCOUNT_SKILL_CONFIGS.values()
    )


def exchange_refresh_token_for_provider(provider_id: str | None) -> ExchangeRefreshToken:
    provider = normalize_connected_account_provider_id(provider_id)
    if provider == "google":
        return exchange_google_refresh_token
    if provider == "revolut_business":
        return exchange_revolut_business_refresh_token
    raise ValueError(f"Unsupported connected-account provider: {provider}")


def action_scope_for_request(
    request: dict[str, Any],
    *,
    action: str,
    config: ConnectedAccountSkillConfig,
) -> dict[str, Any]:
    if config.scope_kind == "provider_account":
        return {"provider": config.provider_id}

    if config.scope_kind == "calendar_events":
        scope: dict[str, Any] = {"calendar_id": request.get("calendar_id") or "primary"}
        if action in {"update", "delete"} and request.get("event_id"):
            scope["event_id"] = request["event_id"]
        if action == "read":
            if request.get("time_min"):
                scope["time_min"] = request["time_min"]
            if request.get("time_max"):
                scope["time_max"] = request["time_max"]
        return scope

    return {"provider": config.provider_id}
