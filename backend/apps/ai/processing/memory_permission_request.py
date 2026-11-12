"""Create a real "load this memory?" permission request for a turn.

Shared by the main processor (model-driven turns) and mock replay (fixtures
with ``memory_request``) so both issue the same request system message, store
the same pending continuation context and encrypted catalog snapshot.
"""
import json
import logging
from typing import Any, Dict, List, Optional

from backend.apps.ai.processing.rule_context import (
    memory_catalog_snapshot, personal_catalog, request_memory_catalog,
)
from backend.apps.ai.skills.ask_skill import AskSkillRequest

logger = logging.getLogger(__name__)


def build_pending_app_settings_memories_context(
    request_data: AskSkillRequest,
    request_id: str,
    missing_keys: List[str],
    task_id: str,
) -> Dict[str, Any]:
    """Build the request context needed to restart after memory permission."""
    return {
        "request_id": request_id,
        "chat_id": request_data.chat_id,
        "message_id": request_data.message_id,
        "user_id": request_data.user_id,
        "user_id_hash": request_data.user_id_hash,
        "mate_id": request_data.mate_id,
        "active_focus_id": request_data.active_focus_id,
        "chat_has_title": request_data.chat_has_title,
        "current_chat_title": request_data.current_chat_title,
        "is_incognito": request_data.is_incognito,
        "user_preferences": request_data.user_preferences or {},
        "embed_file_path_index": request_data.embed_file_path_index,
        "has_image_upload_embed": getattr(request_data, "has_image_upload_embed", False),
        "requested_keys": missing_keys,
        "task_id": task_id,
        # Resume the authorized turn without claiming a second inference identity.
        # See docs/architecture/core/chat-encryption-implementation.md.
        "recovery_inference_task_id": (
            getattr(request_data, "recovery_task_id", None)
            or getattr(request_data, "recovery_inference_task_id", None)
        ),
        "recovery_preflight_id": getattr(request_data, "recovery_preflight_id", None),
        # Web turns are admitted under the legacy cutover identity instead of a
        # recovery turn; the continuation must inherit it as its root admission.
        "root_legacy_cutover_task_id": (
            getattr(request_data, "root_legacy_cutover_task_id", None)
            or getattr(request_data, "legacy_cutover_task_id", None)
        ),
        "recovery_turn_id": getattr(request_data, "recovery_turn_id", None),
        "recovery_public_key": getattr(request_data, "recovery_public_key", None),
        "chat_key_version": getattr(request_data, "chat_key_version", None),
        "preprocessing_resume_ref": getattr(request_data, "preprocessing_resume_ref", None),
    }


async def issue_memory_permission_request(
    *,
    request_data: AskSkillRequest,
    missing_keys: List[str],
    task_id: str,
    cache_service: Any,
    encryption_service: Any,
    user_vault_key_id: Optional[str],
    log_prefix: str,
) -> Optional[str]:
    """Create the request message, store pending context and return the request id.

    Returns None when the request message could not be created; the caller then
    continues without the data. On success the caller must end its turn without a
    reply (the main processor yields the awaiting-permission marker).
    """
    from backend.core.api.app.utils.app_settings_memories_request import (
        create_app_settings_memories_request_message,
    )

    request_id = await create_app_settings_memories_request_message(
        chat_id=request_data.chat_id,
        requested_keys=missing_keys,
        cache_service=cache_service,
        connection_manager=None,  # Celery tasks run in separate processes, can't access WebSocket manager directly
        user_id=request_data.user_id,
        device_fingerprint_hash=None,  # Will use first available device connection
        message_id=request_data.message_id,  # User message that triggered this request (for UI display)
        memory_titles={
            entry.id: entry.title
            for entry in personal_catalog(request_memory_catalog(request_data))
            if f"memory:{entry.id}" in missing_keys
        },
    )

    if request_id:
        logger.info(f"{log_prefix} Created app settings/memories request {request_id} - storing pending context and returning")
        # IMPORTANT: Store the pending request context so we can re-trigger processing
        # when user confirms or rejects. The confirmation/rejection acts as a trigger
        # for a NEW AI processing pass - not a continuation of this task.
        #
        # Flow:
        # 1. This task completes (no LLM response)
        # 2. Client shows permission dialog
        # 3. User confirms/rejects (could be seconds or hours later)
        # 4. Server receives confirmation → triggers NEW ask_skill task
        # 5. New task finds data in cache (if confirmed) → normal LLM response
        #
        # NOTE: We only store minimal context here - NOT the message_history!
        # The chat history is already cached on the server (recent chat).
        # When continuing, we retrieve the chat from cache.
        try:
            # Store MINIMAL context needed to re-trigger processing
            # Do NOT store message_history - it's already in the chat cache
            pending_context = build_pending_app_settings_memories_context(
                request_data=request_data,
                request_id=request_id,
                missing_keys=missing_keys,
                task_id=task_id,
            )
            # Metadata-only catalog snapshot (no bodies), vault-encrypted,
            # so the continuation never depends on the client resending it.
            if user_vault_key_id and encryption_service and any(
                key.startswith("memory:") for key in missing_keys
            ):
                snapshot_json = json.dumps(
                    memory_catalog_snapshot(personal_catalog(request_memory_catalog(request_data))),
                    separators=(",", ":"), ensure_ascii=True,
                )
                pending_context["memory_catalog_ciphertext"], _ = (
                    await encryption_service.encrypt_with_user_key(
                        plaintext=snapshot_json, key_id=user_vault_key_id,
                    )
                )
            await cache_service.store_pending_app_settings_memories_request(
                chat_id=request_data.chat_id,
                context=pending_context,
                ttl=86400 * 7  # 7 days - user can confirm/reject within a week
            )
            logger.info(f"{log_prefix} Stored pending context for request {request_id}")
        except Exception as e:
            logger.error(f"{log_prefix} Failed to store pending context: {e}", exc_info=True)
            # Continue without storing - user will need to send a new message

    return request_id
