# backend/core/api/app/routes/handlers/websocket_handlers/chat_model_preference_handler.py
#
# WebSocket sync for the encrypted chat model selector. The route is a
# first-party authenticated client surface: it accepts only opaque client-side
# ciphertext, checks the caller's chat scope, persists one versioned row for the
# user/chat pair, and broadcasts only the encrypted record to the same user.

from __future__ import annotations

import hashlib
import logging
from typing import Any

from fastapi import WebSocket

from backend.core.api.app.routes.connection_manager import ConnectionManager
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.services.directus.chat_model_preference_methods import (
    ChatModelPreferenceConflictError,
    ChatModelPreferenceValidationError,
)
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.services.directus.team_methods import TeamPermissionError, hash_id


logger = logging.getLogger(__name__)

FORBIDDEN_PLAINTEXT_SELECTION_KEYS = {
    "selected_ai_model",
    "selected_model",
    "model_id",
    "model",
    "selection",
    "mode",
}


async def _can_write_chat_preference(
    directus_service: DirectusService,
    user_id: str,
    chat_id: str,
    team_id: str | None,
) -> bool:
    if team_id:
        try:
            await directus_service.team.require_team_role(team_id, user_id, {"owner", "admin", "member"})
        except TeamPermissionError:
            return False
        chat = await directus_service.chat.get_chat_metadata(chat_id, admin_required=True)
        return not chat or chat.get("hashed_team_id") == hash_id(team_id)

    if await directus_service.chat.check_chat_ownership(chat_id, user_id):
        return True
    chat = await directus_service.chat.get_chat_metadata(chat_id, admin_required=True)
    if not chat:
        return True
    return chat.get("hashed_user_id") == hashlib.sha256(user_id.encode()).hexdigest()


async def handle_chat_model_preference(
    websocket: WebSocket,
    manager: ConnectionManager,
    cache_service: CacheService,
    directus_service: DirectusService,
    encryption_service: EncryptionService,
    user_id: str,
    device_fingerprint_hash: str,
    payload: dict[str, Any],
    operation: str,
    user_otel_attrs: dict | None = None,
) -> None:
    _otel_span, _otel_token = None, None
    try:
        from backend.shared.python_utils.tracing.ws_span_helper import start_ws_handler_span

        _otel_span, _otel_token = start_ws_handler_span(f"chat_model_preference_{operation}", user_id, payload, user_otel_attrs)
    except Exception:
        pass

    try:
        chat_id = payload.get("chat_id")
        team_id = payload.get("team_id")
        if not isinstance(chat_id, str) or not chat_id.strip():
            await manager.send_personal_message(
                {"type": "error", "payload": {"code": "missing_chat_id", "message": "Missing chat_id for chat model preference."}},
                user_id,
                device_fingerprint_hash,
            )
            return
        chat_id = chat_id.strip()
        team_id = team_id.strip() if isinstance(team_id, str) and team_id.strip() else None

        if not await _can_write_chat_preference(directus_service, user_id, chat_id, team_id):
            if operation == "get":
                await manager.send_personal_message(
                    {"type": "chat_model_preference", "payload": {"chat_id": chat_id, "preference": None}},
                    user_id,
                    device_fingerprint_hash,
                )
                return
            await manager.send_personal_message(
                {"type": "error", "payload": {"code": "chat_model_preference_forbidden", "message": "You do not have permission to update this chat preference.", "chat_id": chat_id}},
                user_id,
                device_fingerprint_hash,
            )
            return

        if operation == "get":
            record = await directus_service.chat_model_preference.get_preference(user_id, chat_id)
            await manager.send_personal_message(
                {"type": "chat_model_preference", "payload": {"chat_id": chat_id, "preference": record}},
                user_id,
                device_fingerprint_hash,
            )
            return

        forbidden_keys = sorted(FORBIDDEN_PLAINTEXT_SELECTION_KEYS.intersection(payload.keys()))
        if forbidden_keys:
            await manager.send_personal_message(
                {"type": "error", "payload": {"code": "plaintext_chat_model_preference_forbidden", "message": "Chat model preference sync accepts encrypted selection only.", "chat_id": chat_id, "fields": forbidden_keys}},
                user_id,
                device_fingerprint_hash,
            )
            return

        expected_v_raw = payload.get("expected_preference_v")
        expected_preference_v = None
        if expected_v_raw is not None:
            try:
                expected_preference_v = int(expected_v_raw)
            except (TypeError, ValueError):
                await manager.send_personal_message(
                    {"type": "error", "payload": {"code": "invalid_preference_version", "message": "expected_preference_v must be an integer.", "chat_id": chat_id}},
                    user_id,
                    device_fingerprint_hash,
                )
                return

        try:
            record = await directus_service.chat_model_preference.upsert_preference(
                user_id=user_id,
                chat_id=chat_id,
                encrypted_selected_ai_model=payload.get("encrypted_selected_ai_model"),
                expected_preference_v=expected_preference_v,
            )
        except ChatModelPreferenceValidationError as exc:
            await manager.send_personal_message(
                {"type": "error", "payload": {"code": "invalid_chat_model_preference", "message": str(exc), "chat_id": chat_id}},
                user_id,
                device_fingerprint_hash,
            )
            return
        except ChatModelPreferenceConflictError as exc:
            await manager.send_personal_message(
                {"type": "chat_model_preference_conflict", "payload": {"chat_id": chat_id, "preference": exc.server_record}},
                user_id,
                device_fingerprint_hash,
            )
            return

        ack_payload = {"chat_id": chat_id, "preference": record, "success": True}
        await manager.send_personal_message(
            {"type": "chat_model_preference_updated", "payload": ack_payload},
            user_id,
            device_fingerprint_hash,
        )
        await manager.broadcast_to_user(
            {"type": "chat_model_preference_synced", "payload": ack_payload},
            user_id=user_id,
            exclude_device_hash=device_fingerprint_hash,
        )
    except Exception as exc:
        logger.error("Failed to handle chat model preference %s for user %s: %s", operation, user_id, exc, exc_info=True)
        await manager.send_personal_message(
            {"type": "error", "payload": {"code": "chat_model_preference_failed", "message": "Failed to sync chat model preference."}},
            user_id,
            device_fingerprint_hash,
        )
    finally:
        if _otel_span is not None:
            try:
                from backend.shared.python_utils.tracing.ws_span_helper import end_ws_handler_span as _end_span

                _end_span(_otel_span, _otel_token)
            except Exception:
                pass
