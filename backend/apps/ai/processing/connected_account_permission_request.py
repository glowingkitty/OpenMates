# backend/apps/ai/processing/connected_account_permission_request.py
#
# Creates provider-backed connected-account permission requests for the chat UI.
# The pending context is intentionally redacted: it stores proposed action data
# and account refs, never refresh/access tokens or provider plaintext secrets.
#
# Spec: docs/specs/calendar-permission-management/spec.yml

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from backend.apps.ai.processing.connected_account_execution import _action_scope_for_request, _request_items

logger = logging.getLogger(__name__)

CONNECTED_ACCOUNT_PERMISSION_TTL_SECONDS = 86400 * 7
CONNECTED_ACCOUNT_FORBIDDEN_FIELD_MARKERS = (
    "refresh_token",
    "access_token",
    "access_token_handle",
    "encrypted_refresh_token",
    "encrypted_refresh_token_bundle",
    "encrypted_access_token",
    "provider_account_id",
    "provider_email",
    "account_email",
    "oauth_scopes",
)


async def create_connected_account_permission_request(
    *,
    cache_service: Any,
    user_id: str,
    chat_id: str,
    message_id: str,
    user_id_hash: str,
    app_id: str,
    skill_id: str,
    action: str,
    skill_arguments: dict[str, Any],
    connected_account_directory: list[dict[str, Any]] | None,
    reason: str,
    task_id: str,
) -> str | None:
    """Store and publish a redacted connected-account permission request."""

    request_id = f"cap_{uuid.uuid4()}"
    action_requests = _build_action_requests(
        app_id=app_id,
        skill_id=skill_id,
        action=action,
        skill_arguments=skill_arguments,
    )
    payload = {
        "request_id": request_id,
        "chat_id": chat_id,
        "message_id": message_id,
        "app_id": app_id,
        "skill_id": skill_id,
        "action": action,
        "reason": reason,
        "accounts": _redacted_accounts(connected_account_directory or [], app_id=app_id, action=action),
        "requests": action_requests,
    }
    pending_context = {
        **payload,
        "user_id": user_id,
        "user_id_hash": user_id_hash,
        "task_id": task_id,
        "skill_arguments": skill_arguments,
    }
    _assert_no_connected_account_secrets(payload)
    _assert_no_connected_account_secrets(pending_context)

    stored = await cache_service.store_pending_connected_account_permission_request(
        request_id=request_id,
        context=pending_context,
        ttl=CONNECTED_ACCOUNT_PERMISSION_TTL_SECONDS,
    )
    if not stored:
        logger.error("Failed to store connected-account permission request %s", request_id)
        return None

    published = await _publish_connected_account_permission_request(
        cache_service=cache_service,
        user_id=user_id,
        payload=payload,
    )
    if not published:
        logger.warning("Stored connected-account permission request %s but could not publish it", request_id)
    return request_id


def _build_action_requests(
    *,
    app_id: str,
    skill_id: str,
    action: str,
    skill_arguments: dict[str, Any],
) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    for index, item in enumerate(_request_items(skill_arguments)):
        requests.append(
            {
                "action_id": f"{skill_id}:{index}",
                "app_id": app_id,
                "skill_id": skill_id,
                "action": action,
                "action_scope": _action_scope_for_request(item, action),
                "summary": _safe_action_summary(item, action),
            }
        )
    return requests


def _safe_action_summary(request: dict[str, Any], action: str) -> dict[str, Any]:
    summary: dict[str, Any] = {"calendar_id": request.get("calendar_id") or "primary"}
    if action == "read":
        if request.get("time_min"):
            summary["time_min"] = request["time_min"]
        if request.get("time_max"):
            summary["time_max"] = request["time_max"]
    if action in {"write", "update", "delete"}:
        if request.get("event_id"):
            summary["event_id"] = request["event_id"]
        if request.get("summary"):
            summary["event_title"] = request["summary"]
        if request.get("start"):
            summary["start"] = request["start"]
        if request.get("end"):
            summary["end"] = request["end"]
    return summary


def _redacted_accounts(
    connected_account_directory: list[dict[str, Any]],
    *,
    app_id: str,
    action: str,
) -> list[dict[str, Any]]:
    accounts: list[dict[str, Any]] = []
    for account in connected_account_directory:
        if account.get("app_id") != app_id:
            continue
        capabilities = list(account.get("capabilities") or [])
        if not _capabilities_allow_action(capabilities, action):
            continue
        accounts.append(
            {
                "connected_account_id": account.get("connected_account_id"),
                "app_id": app_id,
                "account_ref": account.get("account_ref") or account.get("connected_account_id"),
                "label": account.get("label") or "Connected account",
                "capabilities": capabilities,
                "runtime_modes": account.get("runtime_modes") or {},
            }
        )
    return accounts


def _capabilities_allow_action(capabilities: list[str], action: str) -> bool:
    if action == "read":
        return "read" in capabilities
    if action == "update":
        return "update" in capabilities or "write" in capabilities
    return action in capabilities


async def _publish_connected_account_permission_request(
    *,
    cache_service: Any,
    user_id: str,
    payload: dict[str, Any],
) -> bool:
    try:
        redis_client = await cache_service.client
        if not redis_client:
            return False
        await redis_client.publish(
            f"user_cache_events:{user_id}",
            json.dumps(
                {
                    "event_type": "send_connected_account_permission_request",
                    "payload": payload,
                }
            ),
        )
        return True
    except Exception as exc:
        logger.warning("Could not publish connected-account permission request: %s", exc)
        return False


def _assert_no_connected_account_secrets(value: Any) -> None:
    serialized = json.dumps(value, sort_keys=True)
    for marker in CONNECTED_ACCOUNT_FORBIDDEN_FIELD_MARKERS:
        if marker in serialized:
            raise ValueError(f"Connected-account permission payload contains forbidden field: {marker}")
