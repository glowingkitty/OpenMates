# backend/apps/ai/processing/connected_account_execution.py
#
# Helpers for provider-backed connected-account skill execution.
# The main processor calls these before app skill dispatch to exchange only the
# selected active-turn token refs and inject opaque handles into skill arguments.
#
# Spec: docs/specs/calendar-permission-management/spec.yml

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.core.api.app.services.token_broker import TokenBrokerService
from backend.shared.python_utils.connected_account_registry import (
    action_scope_for_request,
    ConnectedAccountSkillConfig,
    connected_account_skill_config,
    exchange_refresh_token_for_provider,
    is_connected_account_skill as _registry_is_connected_account_skill,
    normalize_connected_account_app_id,
    normalize_connected_account_provider_id,
)


@dataclass
class ConnectedAccountExecutionContext:
    """Server-injected execution context for connected-account skills."""

    skill_arguments: dict[str, Any]
    token_artifacts: list[dict[str, str]] = field(default_factory=list)


def is_connected_account_skill(app_id: str, skill_id: str) -> bool:
    return _registry_is_connected_account_skill(app_id, skill_id)


def connected_account_action_for_skill(app_id: str, skill_id: str) -> str:
    return connected_account_skill_config(app_id, skill_id).action


async def prepare_connected_account_skill_execution(
    *,
    app_id: str,
    skill_id: str,
    skill_arguments: dict[str, Any],
    connected_account_token_refs: list[dict[str, Any]] | None,
    user_id: str,
    user_vault_key_id: str | None,
    chat_id: str,
    message_id: str,
    cache_service: Any,
    encryption_service: Any,
) -> ConnectedAccountExecutionContext:
    """Exchange matching token refs and inject access-token handles for a skill."""

    config = connected_account_skill_config(app_id, skill_id)
    action = config.action
    if not user_vault_key_id:
        raise PermissionError("User vault key is required for connected-account execution")
    if not cache_service or not encryption_service:
        raise PermissionError("Token broker dependencies are unavailable")

    requests = _request_items(skill_arguments, request_field=config.request_field)
    if not requests:
        raise PermissionError("Connected-account skill requires at least one request")

    broker = TokenBrokerService(
        cache_service=cache_service,
        encryption_service=encryption_service,
        exchange_refresh_token=exchange_refresh_token_for_provider(config.provider_id),
    )
    token_map: dict[str, str] = {}
    artifacts: list[dict[str, str]] = []

    for item in requests:
        token_ref_payload = _find_token_ref(
            connected_account_token_refs or [],
            app_id=app_id,
            action=action,
            request=item,
            config=config,
            provider_id=config.provider_id,
        )
        if not token_ref_payload:
            raise PermissionError(
                f"Connected-account permission is required before executing {app_id}.{skill_id}"
            )
        action_scope = action_scope_for_request(item, action=action, config=config)
        turn_token_ref = str(token_ref_payload["turn_token_ref"])
        handle = await broker.exchange_turn_token_ref(
            turn_token_ref=turn_token_ref,
            user_id=user_id,
            user_vault_key_id=user_vault_key_id,
            chat_id=chat_id,
            message_id=message_id,
            app_id=app_id,
            action=action,
            provider_id=config.provider_id,
            action_scope=action_scope,
        )
        access_token = await broker.resolve_access_token_handle(
            access_token_handle=handle.access_token_handle,
            user_id=user_id,
            user_vault_key_id=user_vault_key_id,
            chat_id=chat_id,
            message_id=message_id,
            app_id=app_id,
            action=action,
            provider_id=config.provider_id,
            action_scope=action_scope,
        )
        item["access_token_handle"] = handle.access_token_handle
        token_map[handle.access_token_handle] = access_token
        artifacts.append(
            {
                "turn_token_ref": turn_token_ref,
                "access_token_handle": handle.access_token_handle,
                "connected_account_id": str(token_ref_payload.get("connected_account_id") or ""),
                "app_id": app_id,
                "provider_id": config.provider_id,
                "action": action,
                "action_scope": action_scope,
            }
        )

    updated = dict(skill_arguments)
    updated[config.request_field] = requests
    updated["_connected_account_access_tokens"] = token_map
    return ConnectedAccountExecutionContext(skill_arguments=updated, token_artifacts=artifacts)


async def cleanup_connected_account_token_artifacts(
    *,
    token_artifacts: list[dict[str, str]],
    cache_service: Any,
    encryption_service: Any,
) -> None:
    if not token_artifacts or not cache_service or not encryption_service:
        return

    async def _unused_exchange_refresh_token(_refresh_token: str, _scope_context: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("Cleanup must not exchange connected-account refresh tokens")

    broker = TokenBrokerService(
        cache_service=cache_service,
        encryption_service=encryption_service,
        exchange_refresh_token=_unused_exchange_refresh_token,
    )
    for artifact in token_artifacts:
        await broker.delete_turn_artifacts(
            turn_token_ref=artifact.get("turn_token_ref"),
            access_token_handle=artifact.get("access_token_handle"),
        )


def _request_items(skill_arguments: dict[str, Any], *, request_field: str) -> list[dict[str, Any]]:
    requests = skill_arguments.get(request_field)
    if isinstance(requests, list):
        return [dict(item) for item in requests if isinstance(item, dict)]
    return [dict(skill_arguments)]


def _find_token_ref(
    token_refs: list[dict[str, Any]],
    *,
    app_id: str,
    action: str,
    request: dict[str, Any],
    config: ConnectedAccountSkillConfig,
    provider_id: str,
) -> dict[str, Any] | None:
    request_scope = action_scope_for_request(request, action=action, config=config)
    for token_ref in token_refs:
        if normalize_connected_account_app_id(token_ref.get("app_id")) != app_id:
            continue
        token_provider = normalize_connected_account_provider_id(
            token_ref.get("provider_id") or token_ref.get("provider") or token_ref.get("app_id")
        )
        if token_provider and token_provider != normalize_connected_account_provider_id(provider_id):
            continue
        allowed_actions = set(token_ref.get("allowed_actions") or [])
        if action not in allowed_actions:
            continue
        stored_scope = token_ref.get("action_scope") or {}
        if stored_scope and stored_scope != request_scope:
            continue
        if token_ref.get("turn_token_ref"):
            return token_ref
    return None
