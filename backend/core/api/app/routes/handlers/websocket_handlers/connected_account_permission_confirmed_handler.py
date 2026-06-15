# backend/core/api/app/routes/handlers/websocket_handlers/connected_account_permission_confirmed_handler.py
#
# Handles Calendar/connected-account approval responses from the browser.
# Approved continuations carry only fresh turn-token refs; rejected continuations
# carry no provider tokens and continue with a redacted denial tool result.
#
# Spec: docs/specs/calendar-permission-management/spec.yml

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import yaml

from backend.core.api.app.routes.connection_manager import ConnectionManager

logger = logging.getLogger(__name__)

CONNECTED_ACCOUNT_CONFIRMATION_FORBIDDEN_FIELDS = {
    "refresh_token",
    "access_token",
    "provider_email",
    "account_email",
    "provider_account_id",
    "oauth_scopes",
    "scopes",
}


async def handle_connected_account_permission_confirmed(
    websocket,
    manager: ConnectionManager,
    cache_service: Any,
    directus_service: Any,
    encryption_service: Any,
    user_id: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any],
    user_otel_attrs: dict | None = None,
) -> None:
    """Consume a connected-account permission response and trigger continuation."""

    _otel_span, _otel_token = None, None
    try:
        request_id = payload.get("request_id")
        chat_id = payload.get("chat_id")
        approved = bool(payload.get("approved"))
        token_refs = payload.get("connected_account_token_refs") or []

        if not request_id or not chat_id:
            logger.warning("Invalid connected-account confirmation from user %s: missing request_id/chat_id", user_id)
            return
        if token_refs is not None:
            _reject_secret_fields(token_refs)

        try:
            from backend.shared.python_utils.tracing.ws_span_helper import start_ws_handler_span

            _otel_span, _otel_token = start_ws_handler_span(
                "connected_account_permission_confirmed",
                user_id,
                payload,
                user_otel_attrs,
            )
        except Exception:
            pass

        if not await directus_service.chat.check_chat_ownership(chat_id, user_id):
            logger.warning("User %s attempted connected-account confirmation for unowned chat %s", user_id, chat_id)
            await manager.send_personal_message(
                {"type": "error", "payload": {"message": "You do not have permission to modify this chat."}},
                user_id,
                device_fingerprint_hash,
            )
            return

        pending_context = await cache_service.get_pending_connected_account_permission_request(request_id)
        if not pending_context:
            logger.warning("No pending connected-account permission request found for %s", request_id)
            return
        if pending_context.get("user_id") != user_id or pending_context.get("chat_id") != chat_id:
            logger.warning("Connected-account permission request %s owner/chat mismatch", request_id)
            return

        await _trigger_connected_account_continuation(
            cache_service=cache_service,
            directus_service=directus_service,
            encryption_service=encryption_service,
            user_id=user_id,
            pending_context=pending_context,
            approved=approved,
            connected_account_token_refs=token_refs if approved else [],
        )
        await cache_service.delete_pending_connected_account_permission_request(request_id)
    except Exception as exc:
        logger.error("Error handling connected-account permission confirmation for user %s: %s", user_id, exc, exc_info=True)
    finally:
        if _otel_span is not None:
            try:
                from backend.shared.python_utils.tracing.ws_span_helper import end_ws_handler_span

                end_ws_handler_span(_otel_span, _otel_token)
            except Exception:
                pass


async def _trigger_connected_account_continuation(
    *,
    cache_service: Any,
    directus_service: Any,
    encryption_service: Any,
    user_id: str,
    pending_context: dict[str, Any],
    approved: bool,
    connected_account_token_refs: list[dict[str, Any]],
) -> None:
    chat_id = str(pending_context["chat_id"])
    message_id = str(pending_context["message_id"])
    user_id_hash = str(pending_context.get("user_id_hash") or "")
    message_history = await _load_cached_message_history(
        cache_service=cache_service,
        directus_service=directus_service,
        encryption_service=encryption_service,
        user_id=user_id,
        chat_id=chat_id,
    )
    if not message_history:
        logger.error("Cannot continue connected-account request %s: no cached message history", pending_context.get("request_id"))
        return

    from backend.apps.ai.tasks.ask_skill_task import process_ai_skill_ask_task

    request_data_dict = {
        "chat_id": chat_id,
        "message_id": message_id,
        "user_id": user_id,
        "user_id_hash": user_id_hash,
        "message_history": message_history,
        "connected_account_directory": pending_context.get("accounts") or [],
        "connected_account_token_refs": connected_account_token_refs,
        "connected_account_permission_state": {
            "request_id": pending_context.get("request_id"),
            "approved": approved,
            "app_id": pending_context.get("app_id"),
            "skill_id": pending_context.get("skill_id"),
            "action": pending_context.get("action"),
        },
        "is_connected_account_permission_continuation": True,
    }
    skill_config_dict = _load_ask_skill_config_from_app_yml()
    task = process_ai_skill_ask_task.apply_async(
        kwargs={
            "request_data_dict": request_data_dict,
            "skill_config_dict": skill_config_dict,
        },
        queue="app_ai",
        exchange="app_ai",
        routing_key="app_ai",
    )
    logger.info(
        "Triggered connected-account continuation task %s for request %s approved=%s",
        task.id,
        pending_context.get("request_id"),
        approved,
    )


async def _load_cached_message_history(
    *,
    cache_service: Any,
    directus_service: Any,
    encryption_service: Any,
    user_id: str,
    chat_id: str,
) -> List[Dict[str, Any]]:
    cached_messages_str_list = await cache_service.get_ai_messages_history(user_id, chat_id)
    if not cached_messages_str_list:
        return []

    user_vault_key_id = await cache_service.get_user_vault_key_id(user_id)
    if not user_vault_key_id:
        try:
            user_profile_result = await directus_service.get_user_profile(user_id)
            if user_profile_result and user_profile_result[0]:
                user_vault_key_id = user_profile_result[1].get("vault_key_id")
        except Exception as exc:
            logger.error("Error fetching user profile for connected-account continuation: %s", exc, exc_info=True)

    if not user_vault_key_id:
        return []

    message_history: List[Dict[str, Any]] = []
    for msg_str in reversed(cached_messages_str_list):
        try:
            msg_cache_data = json.loads(msg_str)
            role = msg_cache_data.get("role", "")
            if role not in ("user", "assistant"):
                continue
            encrypted_content = msg_cache_data.get("encrypted_content")
            if not encrypted_content:
                continue
            decrypted_content = await encryption_service.decrypt_with_user_key(
                encrypted_content,
                user_vault_key_id,
            )
            if not decrypted_content:
                continue
            message_history.append(
                {
                    "role": role,
                    "content": decrypted_content,
                    "created_at": msg_cache_data.get("created_at", int(datetime.now(timezone.utc).timestamp())),
                    "sender_name": msg_cache_data.get("sender_name", role),
                    "category": msg_cache_data.get("category"),
                }
            )
        except Exception:
            continue
    return message_history


def _reject_secret_fields(value: Any) -> None:
    serialized = json.dumps(value or {})
    for key in CONNECTED_ACCOUNT_CONFIRMATION_FORBIDDEN_FIELDS:
        if f'"{key}"' in serialized:
            raise ValueError(f"connected-account confirmation contains forbidden field: {key}")


def _load_ask_skill_config_from_app_yml() -> Dict[str, Any]:
    backend_dir = Path(__file__).resolve().parents[6]
    app_yml_path = backend_dir / "apps" / "ai" / "app.yml"
    with app_yml_path.open("r", encoding="utf-8") as file:
        app_config = yaml.safe_load(file) or {}

    for skill in app_config.get("skills", []):
        if skill.get("id") == "ask":
            return skill.get("skill_config", {}) or {}
    raise ValueError("ask skill configuration not found in backend/apps/ai/app.yml")
