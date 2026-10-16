"""First-party authenticated WebSocket transport for optional Team mail previews.

The parent WebSocket authenticates the user. This handler additionally checks
Team write access, exact chat scope, recipient consent and a modest per-user
request limit; it has no developer/public REST or credit-bearing surface.
"""

from __future__ import annotations

from typing import Any

from backend.core.api.app.services.directus.team_methods import hash_id
from backend.core.api.app.services.team_chat_notification_service import (
    issue_preview_capability,
    stage_team_preview,
)


async def _reply(websocket: Any, manager: Any, user_id: str, device_fingerprint_hash: str, kind: str, payload: dict[str, Any]) -> None:
    message = {"type": kind, "payload": payload}
    if websocket is not None:
        await websocket.send_json(message)
    else:
        await manager.send_personal_message(message, user_id, device_fingerprint_hash)


async def _within_limit(cache_service: Any, user_id: str, operation: str) -> bool:
    client = await cache_service.client
    if not client:
        return False
    key = f"team:notification:rate:{operation}:{hash_id(user_id)}"
    count = await client.incr(key)
    if count == 1:
        await client.expire(key, 60)
    return count <= 30


async def handle_team_notification_preview_capabilities(
    *, websocket: Any, manager: Any, directus_service: Any, cache_service: Any,
    user_id: str, device_fingerprint_hash: str, payload: dict[str, Any],
) -> None:
    payload = payload if isinstance(payload, dict) else {}
    request_id = payload.get("request_id")
    response = {"request_id": request_id, "capability_id": None, "recipient_count": 0}
    try:
        team_id, chat_id = payload.get("team_id"), payload.get("chat_id")
        if not all(isinstance(value, str) and 0 < len(value) <= 255 for value in (team_id, chat_id, request_id)):
            raise ValueError("Invalid notification preview request")
        if await _within_limit(cache_service, user_id, "capability"):
            response.update(await issue_preview_capability(
                directus=directus_service, cache=cache_service,
                team_id=team_id, chat_id=chat_id, sender_id=user_id,
            ))
    except (ValueError, PermissionError):
        pass
    # Permission, cache and missing-chat failures all return empty capability.
    except Exception:
        pass
    await _reply(websocket, manager, user_id, device_fingerprint_hash, "team_notification_preview_capabilities_result", response)


async def handle_team_notification_preview_stage(
    *, websocket: Any, manager: Any, directus_service: Any, cache_service: Any,
    encryption_service: Any, user_id: str, device_fingerprint_hash: str,
    payload: dict[str, Any],
) -> None:
    payload = payload if isinstance(payload, dict) else {}
    request_id = payload.get("request_id")
    response = {"request_id": request_id, "staged": 0}
    try:
        values = [payload.get(key) for key in ("team_id", "chat_id", "message_id", "capability_id", "request_id")]
        if not all(isinstance(value, str) and 0 < len(value) <= 255 for value in values):
            raise ValueError("Invalid notification preview request")
        if await _within_limit(cache_service, user_id, "stage"):
            response["staged"] = await stage_team_preview(
                directus=directus_service, cache=cache_service, encryption=encryption_service,
                team_id=payload["team_id"], chat_id=payload["chat_id"],
                message_id=payload["message_id"], sender_id=user_id,
                capability_id=payload["capability_id"],
                preview=payload.get("preview"), title=payload.get("title"),
            )
    except (ValueError, PermissionError):
        pass
    except Exception:
        pass
    await _reply(websocket, manager, user_id, device_fingerprint_hash, "team_notification_preview_stage_result", response)
