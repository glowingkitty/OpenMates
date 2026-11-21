# backend/core/api/app/routes/handlers/websocket_handlers/e2b_upload_consent_answer_handler.py
#
# Client -> server e2b_upload_consent_answer {request_id, chat_id, choice}.
# Records the account's E2B upload decision (allow -> allowed; own_machine and
# not_now -> declined), fans out e2b_upload_consent_updated to the user's
# devices and continues the paused assistant turn. An answer whose pending
# context expired only records the decision.
#
# Spec: specifications/features/app-skills/code-run/specification.yml
#       (assertion code-run.e2b.upload-consent)

from __future__ import annotations

import logging
from typing import Any, Dict

from backend.apps.ai.processing import e2b_upload_consent_request as pending
from backend.core.api.app.routes.connection_manager import ConnectionManager
from backend.core.api.app.routes.handlers.websocket_handlers.connected_account_permission_confirmed_handler import (
    _load_ask_skill_config_from_app_yml,
    _load_cached_message_history,
)
from backend.core.api.app.services import e2b_upload_consent as consent
from backend.shared.python_utils.tracing.ws_span_helper import end_ws_handler_span, start_ws_handler_span

logger = logging.getLogger(__name__)

CHOICE_TO_DECISION = {"allow": "allowed", "own_machine": "declined", "not_now": "declined"}


async def _reject(manager: ConnectionManager, user_id: str, device: str, message: str) -> None:
    await manager.send_personal_message({"type": "error", "payload": {"message": message}}, user_id, device)


async def handle_e2b_upload_consent_answer(
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
    """Record the consent answer and continue the paused turn."""
    span, token = start_ws_handler_span("e2b_upload_consent_answer", user_id, payload, user_otel_attrs)
    try:
        await _handle_answer(manager, cache_service, directus_service, encryption_service,
                             user_id, device_fingerprint_hash, payload)
    finally:
        end_ws_handler_span(span, token)


async def _handle_answer(
    manager: ConnectionManager,
    cache_service: Any,
    directus_service: Any,
    encryption_service: Any,
    user_id: str,
    device_fingerprint_hash: str,
    payload: Dict[str, Any],
) -> None:
    request_id = payload.get("request_id")
    chat_id = payload.get("chat_id")
    choice = payload.get("choice")
    if not request_id or not chat_id or not isinstance(request_id, str) or not isinstance(chat_id, str):
        await _reject(manager, user_id, device_fingerprint_hash, "e2b_consent_invalid_answer")
        return
    if choice not in CHOICE_TO_DECISION:
        await _reject(manager, user_id, device_fingerprint_hash, "e2b_consent_invalid_choice")
        return
    if not await directus_service.chat.check_chat_ownership(chat_id, user_id):
        logger.warning("User %s sent an E2B consent answer for unowned chat %s", user_id, chat_id)
        await _reject(manager, user_id, device_fingerprint_hash, "You do not have permission to modify this chat.")
        return

    vault_key_id = await cache_service.get_user_vault_key_id(user_id)
    if not vault_key_id:
        profile = await directus_service.get_user_profile(user_id)
        vault_key_id = profile[1].get("vault_key_id") if profile and profile[0] else None
    context = None
    if vault_key_id:
        context = await pending.load_pending_context(
            cache_service=cache_service, encryption_service=encryption_service,
            vault_key_id=vault_key_id, chat_id=chat_id,
        )
    if context is not None and (context.get("request_id") != request_id or context.get("user_id") != user_id):
        logger.warning("E2B consent answer %s does not match the pending request of chat %s", request_id, chat_id)
        await _reject(manager, user_id, device_fingerprint_hash, "e2b_consent_request_mismatch")
        return

    stored = await consent.record_decision(user_id, CHOICE_TO_DECISION[choice], directus_service)
    await pending.publish_user_event(
        cache_service=cache_service,
        user_id=user_id,
        event_type="send_e2b_upload_consent_updated",
        payload={"decision": stored["decision"], "decided_at": stored["decided_at"], "version": stored["version"]},
    )
    if context is None:
        logger.info("E2B consent answer %s recorded without a pending turn (expired or none)", request_id)
        return

    await _trigger_continuation(
        cache_service=cache_service, directus_service=directus_service,
        encryption_service=encryption_service, user_id=user_id, context=context,
    )
    await pending.delete_pending_context(cache_service=cache_service, chat_id=chat_id)


async def _trigger_continuation(
    *, cache_service: Any, directus_service: Any, encryption_service: Any, user_id: str, context: dict[str, Any]
) -> None:
    """Re-run the paused turn; the code.run gate now reads the recorded decision."""
    chat_id = str(context["chat_id"])
    message_history = await _load_cached_message_history(
        cache_service=cache_service, directus_service=directus_service,
        encryption_service=encryption_service, user_id=user_id, chat_id=chat_id,
    )
    if not message_history:
        logger.error("Cannot continue E2B consent request %s: no cached message history", context.get("request_id"))
        return

    from backend.apps.ai.tasks.ask_skill_task import process_ai_skill_ask_task

    request_data_dict = {
        "chat_id": chat_id,
        "message_id": str(context["message_id"]),
        "user_id": user_id,
        "user_id_hash": str(context.get("user_id_hash") or ""),
        "message_history": message_history,
        "preprocessing_resume_ref": context.get("preprocessing_resume_ref"),
        "team_id": context.get("team_id"),
        "team_role": context.get("team_role"),
        # Shared continuation flag: the turn resumes from cached history without a new user message.
        "is_connected_account_permission_continuation": True,
        # Keeps connected-account permission requests in the resumed turn asking instead of auto-denying.
        "is_e2b_upload_consent_continuation": True,
    }
    task = process_ai_skill_ask_task.apply_async(
        kwargs={"request_data_dict": request_data_dict, "skill_config_dict": _load_ask_skill_config_from_app_yml()},
        queue="app_ai", exchange="app_ai", routing_key="app_ai",
    )
    logger.info("Triggered E2B consent continuation task %s for request %s", task.id, context.get("request_id"))
