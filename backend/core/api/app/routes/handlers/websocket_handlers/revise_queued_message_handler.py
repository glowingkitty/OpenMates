"""Stable-ID queued message revision and mode changes."""

import asyncio
import copy
import json
import logging
from typing import Any, Dict

from backend.core.api.app.services.directus.team_methods import TeamPermissionError, hash_id

logger = logging.getLogger(__name__)
TEAM_CHAT_WRITE_ROLES = {"owner", "admin", "member"}


def _amended_recovery_inference_request(
    member: Dict[str, Any], *, queue_mode: str,
    content: str | None, encrypted_content: str | None,
    encrypted_pii_mappings: Any,
) -> tuple[Dict[str, Any], str, str]:
    """Amend only the same user turn in its committed epoch-one request."""
    from backend.core.api.app.routes.handlers.websocket_handlers.chat_turn_preflight_handler import build_inference_commitment

    original = member.get("recovery_inference_request")
    original_commitment = member.get("recovery_inference_commitment")
    message_id = member.get("message_id")
    if (not isinstance(original, dict) or not isinstance(original_commitment, str)
            or build_inference_commitment(original) != original_commitment):
        raise ValueError("Queued recovery commitment is missing or changed")
    replacement = copy.deepcopy(original)
    message = replacement.get("message")
    if not isinstance(message, dict) or message.get("message_id") != message_id:
        raise ValueError("Queued recovery message identity changed")
    replacement["queue_mode"] = queue_mode
    if content is not None:
        if "content" in message:
            message["content"] = content
        elif not isinstance(replacement.get("team_ai_invocation"), dict):
            raise ValueError("Queued recovery message has no editable text")
        message["encrypted_content"] = encrypted_content
        message["encrypted_pii_mappings"] = encrypted_pii_mappings
        history = replacement.get("message_history")
        if isinstance(history, list):
            for item in history:
                if isinstance(item, dict) and item.get("message_id") == message_id:
                    if item.get("role") != "user":
                        raise ValueError("Queued recovery history identity changed")
                    item["content"] = content
                    if "encrypted_content" in item:
                        item["encrypted_content"] = encrypted_content
                    if "encrypted_pii_mappings" in item:
                        item["encrypted_pii_mappings"] = encrypted_pii_mappings
        team_invocation = replacement.get("team_ai_invocation")
        if isinstance(team_invocation, dict):
            team_history = team_invocation.get("history")
            if (not isinstance(team_history, list) or not team_history
                    or not isinstance(team_history[-1], dict)
                    or team_history[-1].get("role") != "user"
                    or team_history[-1].get("created_at") != message.get("created_at")):
                raise ValueError("Queued Team recovery history cannot be amended safely")
            team_history[-1]["content"] = content
    return replacement, original_commitment, build_inference_commitment(replacement)


async def handle_revise_queued_message(
    *, manager, cache_service, directus_service, encryption_service,
    user_id: str, device_fingerprint_hash: str, payload: Dict[str, Any],
) -> None:
    """Revise an unleased queued turn without changing its user-message ID."""
    chat_id = payload.get("chat_id")
    message_id = payload.get("message_id")
    expected_revision = payload.get("expected_revision")
    client_request_id = payload.get("client_request_id")

    async def reject(reason: str, *, current_revision: int | None = None) -> None:
        response = {"chat_id": chat_id, "message_id": message_id,
                    "reason_code": reason, "retryable": reason in {
                        "busy", "conflict", "not_persisted", "storage_unavailable", "storage_uncertain",
                    }}
        if current_revision is not None:
            response["current_revision"] = current_revision
        if isinstance(client_request_id, str) and 1 <= len(client_request_id) <= 128:
            response["client_request_id"] = client_request_id
        await manager.send_personal_message(
            {"type": "queued_message_revision_rejected", "payload": response},
            user_id, device_fingerprint_hash,
        )

    if (not isinstance(chat_id, str) or not chat_id
            or not isinstance(message_id, str) or not 1 <= len(message_id) <= 255
            or type(expected_revision) is not int or expected_revision < 1
            or (client_request_id is not None and (
                not isinstance(client_request_id, str)
                or not 1 <= len(client_request_id) <= 128
            ))):
        await reject("invalid_request")
        return
    requested_mode = payload.get("queue_mode")
    if requested_mode is not None and requested_mode not in ("follow_up", "steer"):
        await reject("invalid_request")
        return
    has_content = "content" in payload
    content = payload.get("content")
    encrypted_content = payload.get("encrypted_content")
    if has_content and (not isinstance(content, str) or not content.strip()
                        or len(content.encode("utf-8")) > 2 * 1024 * 1024):
        await reject("invalid_request")
        return
    if has_content:
        from backend.core.api.app.utils.text_sanitization import sanitize_text_for_ascii_smuggling
        from backend.shared.python_utils.agent_context_history import sanitize_agent_context_message
        safe_content, _ = sanitize_text_for_ascii_smuggling(content)
        safe_content = sanitize_agent_context_message({"role": "user", "content": safe_content})["content"]
        if safe_content != content:
            await reject("unsafe_content_encoding")
            return
    if not has_content and ("encrypted_content" in payload or "encrypted_pii_mappings" in payload):
        await reject("invalid_request")
        return
    if not has_content and requested_mode is None:
        await reject("invalid_request")
        return

    try:
        marker = await cache_service.get_queued_message_revision_quarantine(chat_id)
        if marker:
            try:
                marker_owner = json.loads(marker).get("user_id")
            except (TypeError, ValueError):
                marker_owner = None
            if marker_owner != user_id:
                await reject("busy")
                return
            from backend.apps.ai.processing.queued_steering import reconcile_queued_revision_quarantine
            if not await reconcile_queued_revision_quarantine(cache_service, directus_service, chat_id):
                await reject("busy")
                return
        async with cache_service.queued_message_edit_lock(chat_id):
            row = await cache_service.get_queued_message_member(chat_id, user_id, message_id)
            if row is None:
                await reject("not_queued")
                return
            member = row["member"]
            is_incognito = bool(member.get("is_incognito"))
            if has_content:
                if is_incognito:
                    if "encrypted_content" in payload or "encrypted_pii_mappings" in payload:
                        await reject("invalid_request")
                        return
                elif (not isinstance(encrypted_content, str) or not encrypted_content
                      or "encrypted_pii_mappings" not in payload):
                    await reject("invalid_request")
                    return
            current_revision = member.get("queue_revision", 1)
            if current_revision != expected_revision:
                await reject("conflict", current_revision=current_revision)
                return
            active_task_id = await cache_service.get_active_ai_task(chat_id)
            if not active_task_id:
                await reject("inactive")
                return

            team_id = member.get("team_id")
            team_hash = member.get("team_id_hash")
            if team_id:
                if (payload.get("team_id") != team_id or team_hash != hash_id(team_id)):
                    await reject("forbidden")
                    return
                try:
                    await directus_service.team.require_team_role(
                        team_id, user_id, TEAM_CHAT_WRITE_ROLES,
                    )
                except TeamPermissionError:
                    await reject("forbidden")
                    return

            replacement = dict(member)
            replacement["queue_revision"] = expected_revision + 1
            replacement["queue_mode"] = requested_mode or member.get("queue_mode") or "follow_up"
            vault_content = None
            persisted = None
            quarantine_token = None
            amended_recovery = None
            if has_content:
                history = replacement.get("message_history")
                if (not isinstance(history, list) or not history or
                        history[-1].get("message_id") != message_id or
                        history[-1].get("role") != "user"):
                    await reject("invalid_queue_state")
                    return
                replacement["message_history"] = [*history[:-1], {**history[-1], "content": content}]
                replacement["current_user_content"] = content
                if not is_incognito:
                    vault_key_id = await cache_service.get_user_vault_key_id(user_id)
                    if not vault_key_id:
                        profile = await directus_service.get_user_profile(user_id)
                        vault_key_id = profile[1].get("vault_key_id") if profile and profile[1] else None
                    if not vault_key_id:
                        await reject("storage_unavailable")
                        return
                    vault_content, _ = await encryption_service.encrypt_with_user_key(
                        content, vault_key_id,
                    )
            if not is_incognito:
                if member.get("recovery_task_id"):
                    try:
                        amended_recovery = _amended_recovery_inference_request(
                            member, queue_mode=replacement["queue_mode"],
                            content=content if has_content else None,
                            encrypted_content=encrypted_content if has_content else None,
                            encrypted_pii_mappings=(payload.get("encrypted_pii_mappings")
                                                    if has_content else None),
                        )
                    except ValueError:
                        await reject("invalid_queue_state")
                        return
                    replacement["recovery_inference_request"] = amended_recovery[0]
                    replacement["recovery_inference_commitment"] = amended_recovery[2]
                quarantine_token = await cache_service.begin_queued_message_revision_quarantine(
                    chat_id, user_id, message_id, expected_revision,
                    hashed_team_id=team_hash,
                )
                if quarantine_token is None:
                    await reject("busy")
                    return
                persisted = await asyncio.wait_for(
                    directus_service.chat.revise_queued_message_ciphertext(
                        chat_id, user_id, message_id,
                        encrypted_content if has_content else None,
                        payload.get("encrypted_pii_mappings") if has_content else None,
                        expected_revision, queue_mode=replacement["queue_mode"],
                        stage_token=json.loads(quarantine_token)["nonce"],
                        hashed_team_id=team_hash,
                        recovery_preflight_id=member.get("recovery_preflight_id"),
                        recovery_task_id=member.get("recovery_task_id"),
                        expected_inference_commitment=(amended_recovery[1]
                                                       if amended_recovery else None),
                        next_inference_commitment=(amended_recovery[2]
                                                   if amended_recovery else None),
                    ), timeout=20,
                )
                status = persisted.get("status") if isinstance(persisted, dict) else "error"
                if status != "staged":
                    if status in ("not_persisted", "conflict", "forbidden"):
                        await cache_service.clear_queued_message_revision_quarantine(
                            chat_id, quarantine_token,
                        )
                    await reject("storage_unavailable" if status == "error" else status,
                                 current_revision=persisted.get("queue_revision") if isinstance(persisted, dict) else None)
                    return

            result = await cache_service.revise_queued_message_member(
                chat_id, user_id, message_id, expected_raw=row["raw"],
                replacement=replacement, active_task_id=active_task_id,
                vault_encrypted_content=(None if is_incognito else vault_content),
                quarantine_token=quarantine_token,
            )
            if result != "updated":
                if persisted and persisted.get("status") == "staged":
                    restored = await directus_service.chat.restore_queued_message_ciphertext(
                        chat_id, user_id, message_id,
                        expected_revision=expected_revision,
                        stage_token=persisted["stage_token"],
                        hashed_team_id=team_hash,
                    )
                    if not restored or restored.get("status") not in ("restored", "already_aborted"):
                        await cache_service.pause_queued_message_revisions(chat_id)
                        await reject("storage_uncertain")
                        return
                    await cache_service.clear_queued_message_revision_quarantine(
                        chat_id, quarantine_token,
                    )
                await reject(result)
                return

            if persisted:
                committed = await asyncio.wait_for(
                    directus_service.chat.commit_queued_message_revision(
                        chat_id, user_id, message_id, expected_revision,
                        persisted["stage_token"], hashed_team_id=team_hash,
                    ), timeout=20,
                )
                if not isinstance(committed, dict) or committed.get("status") not in (
                    "updated", "already_committed",
                ):
                    await cache_service.pause_queued_message_revisions(chat_id)
                    await reject("storage_uncertain")
                    return
                if not await cache_service.clear_queued_message_revision_quarantine(
                    chat_id, quarantine_token,
                ):
                    await reject("storage_uncertain")
                    return

            ack = {
                "chat_id": chat_id, "message_id": message_id,
                "queue_mode": replacement["queue_mode"],
                "queue_revision": replacement["queue_revision"],
            }
            if client_request_id is not None:
                ack["client_request_id"] = client_request_id
            if persisted:
                ack["encrypted_content"] = (
                    encrypted_content if has_content else persisted["previous_encrypted_content"]
                )
                ack["encrypted_pii_mappings"] = (
                    payload.get("encrypted_pii_mappings") if has_content
                    else persisted.get("previous_encrypted_pii_mappings")
                )
                ack["messages_v"] = committed["messages_v"]
                sync_result = await cache_service.replace_sync_message_revision(
                    user_id, chat_id, message_id, expected_revision,
                    encrypted_content if has_content else persisted["previous_encrypted_content"],
                    payload.get("encrypted_pii_mappings") if has_content else persisted.get("previous_encrypted_pii_mappings"),
                    expected_revision + 1, messages_v=committed["messages_v"],
                    queue_mode=replacement["queue_mode"],
                )
                if not sync_result:
                    logger.warning("Queued revision sync cache unavailable for chat %s", chat_id)
            if is_incognito:
                await manager.send_personal_message(
                    {"type": "queued_message_updated", "payload": ack},
                    user_id, device_fingerprint_hash,
                )
            else:
                await manager.broadcast_to_user(
                    {"type": "queued_message_updated", "payload": ack},
                    user_id, exclude_device_hash=None,
                )
    except asyncio.TimeoutError:
        await cache_service.pause_queued_message_revisions(chat_id)
        await reject("storage_uncertain")
    except Exception:
        logger.exception("Queued message revision failed for chat %s", chat_id)
        await reject("storage_unavailable")
