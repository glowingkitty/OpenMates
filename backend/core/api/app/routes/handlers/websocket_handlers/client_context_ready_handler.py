"""First-party authenticated context delivery; admission is the authority source."""
from __future__ import annotations

from typing import Any

from backend.core.api.app.services.client_context_continuation import receive_client_context


async def handle_client_context_ready(
    *, manager: Any, cache_service: Any, directus_service: Any, encryption_service: Any,
    user_id: str, device_fingerprint_hash: str, payload: dict,
) -> None:
    allowed = {"chat_id", "turn_id", "message_id", "request_id", "team_id", "phase", "context"}
    status = "rejected"
    if isinstance(payload, dict) and not set(payload) - allowed:
        try:
            # This live membership check supplements the exact admission binding;
            # neither the payload nor cached metadata can grant Team authority.
            if payload.get("team_id"):
                await directus_service.team.require_team_role(
                    payload["team_id"], user_id, {"owner", "admin", "member", "viewer"})
            status = await receive_client_context(
                cache_service=cache_service, encryption_service=encryption_service,
                user_id=user_id, device_fingerprint_hash=device_fingerprint_hash, **payload,
            )
        except Exception:
            # No private payload/error detail is reflected or logged.
            status = "rejected"
    payload = payload if isinstance(payload, dict) else {}
    await manager.send_personal_message(
        {"type": "chat_turn_context_ack", "payload": {
            key: payload.get(key) for key in ("chat_id", "turn_id", "message_id", "request_id", "phase")
        } | {"status": status}}, user_id, device_fingerprint_hash,
    )
