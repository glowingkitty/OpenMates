"""Preflight and claim a queued steer at a completed tool-batch boundary."""

import logging
import json
from typing import Any, Optional

from backend.apps.ai.skills.ask_skill import AskSkillDefaultConfig, AskSkillRequest
from backend.core.api.app.schemas.chat import AIHistoryMessage

logger = logging.getLogger(__name__)


async def reconcile_queued_revision_quarantine(cache, directus, chat_id: str) -> bool:
    """Finish or abort one staged edit before queue lease can admit inference."""
    raw_marker = await cache.get_queued_message_revision_quarantine(chat_id)
    if raw_marker is None:
        return True
    try:
        marker = json.loads(raw_marker)
        user_id = marker["user_id"]
        message_id = marker["message_id"]
        old_revision = int(marker["expected_revision"])
        nonce = marker["nonce"]
        if not all(isinstance(value, str) and value for value in (user_id, message_id, nonce)):
            return False
    except (TypeError, ValueError, KeyError):
        return False
    async with cache.queued_message_edit_lock(chat_id):
        if await cache.get_queued_message_revision_quarantine(chat_id) != raw_marker:
            return False
        row = await cache.get_queued_message_member(chat_id, user_id, message_id)
        if not row:
            return False
        queue_revision = int(row["member"].get("queue_revision") or 1)
        state = await directus.chat.get_queued_revision_state(
            chat_id, user_id, message_id,
            hashed_team_id=marker.get("hashed_team_id"),
        )
        if not isinstance(state, dict) or state.get("status") != "found":
            return False
        committed_revision = False
        if state.get("pending_token") == nonce and state.get("pending_revision") == old_revision + 1:
            if queue_revision == old_revision:
                receipt = await directus.chat.restore_queued_message_ciphertext(
                    chat_id, user_id, message_id, old_revision, nonce,
                    hashed_team_id=marker.get("hashed_team_id"),
                )
                safe = receipt.get("status") in ("restored", "already_aborted")
            elif queue_revision == old_revision + 1:
                receipt = await directus.chat.commit_queued_message_revision(
                    chat_id, user_id, message_id, old_revision, nonce,
                    hashed_team_id=marker.get("hashed_team_id"),
                )
                safe = receipt.get("status") in ("updated", "already_committed")
                committed_revision = safe
            else:
                return False
        elif (state.get("last_committed_stage_token") == nonce
              and queue_revision == old_revision + 1
              and state.get("queue_revision") == queue_revision):
            safe = True
            committed_revision = True
        elif (state.get("last_aborted_stage_token") == nonce
              and queue_revision == old_revision
              and state.get("queue_revision") == queue_revision):
            safe = True
        elif (state.get("pending_token") is None
              and queue_revision == old_revision
              and state.get("queue_revision") == old_revision):
            receipt = await directus.chat.restore_queued_message_ciphertext(
                chat_id, user_id, message_id, old_revision, nonce,
                hashed_team_id=marker.get("hashed_team_id"),
            )
            safe = receipt.get("status") in ("restored", "already_aborted")
        else:
            # A stage request may still be in flight. Preserve the quarantine.
            return False
        if safe and committed_revision:
            # A dead sender may have committed Directus without refreshing the
            # short-lived encrypted sync row. Force its authoritative reload.
            await cache.delete_sync_messages_history(user_id, chat_id)
        return bool(safe and await cache.clear_queued_message_revision_quarantine(
            chat_id, raw_marker,
        ))


async def _queue_event(cache, request: AskSkillRequest, name: str, payload: dict) -> None:
    await cache.publish_event(f"user_updates::{request.user_id_hash}", {
        "event_for_client": name,
        "user_id_uuid": request.user_id,
        "payload": {"chat_id": request.chat_id, **payload},
    })


async def _defer_steer(cache, directus, request: AskSkillRequest, row: dict,
                       task_id: str, reason: str) -> None:
    """Make a rejected steer an ordinary follow-up without changing its message ID."""
    member = row["member"]
    message_id = member["message_id"]
    revision = int(member.get("queue_revision") or 1)
    new_revision = revision
    new_mode = member.get("queue_mode") or "steer"
    async with cache.queued_message_edit_lock(request.chat_id):
        fresh = await cache.get_queued_message_member(request.chat_id, request.user_id, message_id)
        if fresh and fresh["raw"] == row["raw"]:
            persisted = None
            quarantine_token = None
            amended_recovery = None
            if not request.is_incognito:
                if member.get("recovery_task_id"):
                    from backend.core.api.app.routes.handlers.websocket_handlers.revise_queued_message_handler import _amended_recovery_inference_request
                    amended_recovery = _amended_recovery_inference_request(
                        member, queue_mode="follow_up", content=None,
                        encrypted_content=None, encrypted_pii_mappings=None,
                    )
                quarantine_token = await cache.begin_queued_message_revision_quarantine(
                    request.chat_id, request.user_id, message_id, revision,
                    hashed_team_id=request.team_id_hash,
                )
                if quarantine_token is None:
                    return
                persisted = await directus.chat.revise_queued_message_ciphertext(
                    request.chat_id, request.user_id, message_id, None, None, revision,
                    queue_mode="follow_up",
                    stage_token=json.loads(quarantine_token)["nonce"],
                    hashed_team_id=request.team_id_hash,
                    recovery_preflight_id=member.get("recovery_preflight_id"),
                    recovery_task_id=member.get("recovery_task_id"),
                    expected_inference_commitment=(amended_recovery[1]
                                                   if amended_recovery else None),
                    next_inference_commitment=(amended_recovery[2]
                                               if amended_recovery else None),
                )
                if persisted.get("status") in ("not_persisted", "conflict", "forbidden"):
                    await cache.clear_queued_message_revision_quarantine(
                        request.chat_id, quarantine_token,
                    )
            if request.is_incognito or (persisted and persisted.get("status") == "staged"):
                replacement = {**member, "queue_mode": "follow_up", "queue_revision": revision + 1}
                if amended_recovery:
                    replacement["recovery_inference_request"] = amended_recovery[0]
                    replacement["recovery_inference_commitment"] = amended_recovery[2]
                status = await cache.revise_queued_message_member(
                    request.chat_id, request.user_id, message_id,
                    expected_raw=row["raw"], replacement=replacement,
                    active_task_id=task_id,
                    quarantine_token=quarantine_token,
                )
                if status == "updated":
                    if persisted:
                        committed = await directus.chat.commit_queued_message_revision(
                            request.chat_id, request.user_id, message_id,
                            revision, persisted["stage_token"],
                            hashed_team_id=request.team_id_hash,
                        )
                        if committed.get("status") in ("updated", "already_committed"):
                            if await cache.clear_queued_message_revision_quarantine(
                                request.chat_id, quarantine_token,
                            ):
                                new_revision = revision + 1
                                new_mode = "follow_up"
                                await cache.replace_sync_message_revision(
                                    request.user_id, request.chat_id, message_id, revision,
                                    persisted["previous_encrypted_content"],
                                    persisted.get("previous_encrypted_pii_mappings"), new_revision,
                                    messages_v=committed["messages_v"],
                                    queue_mode="follow_up",
                                )
                        else:
                            await cache.pause_queued_message_revisions(request.chat_id)
                    else:
                        new_revision = revision + 1
                        new_mode = "follow_up"
                elif persisted and persisted.get("status") == "staged":
                    restored = await directus.chat.restore_queued_message_ciphertext(
                        request.chat_id, request.user_id, message_id,
                        revision, persisted["stage_token"],
                        hashed_team_id=request.team_id_hash,
                    )
                    if not restored or restored.get("status") not in ("restored", "already_aborted"):
                        await cache.pause_queued_message_revisions(request.chat_id)
                    else:
                        await cache.clear_queued_message_revision_quarantine(
                            request.chat_id, quarantine_token,
                        )
    await _queue_event(cache, request, "queued_message_steer_deferred", {
        "message_id": message_id, "queue_mode": new_mode,
        "queue_revision": new_revision, "reason_code": reason,
    })


def _selected_snapshots_already_loaded(selected: Any, loaded: Any) -> bool:
    """A new private snapshot cannot enter the active run through a Steer."""
    return not selected or bool(
        isinstance(selected, list) and isinstance(loaded, list)
        and all(snapshot in loaded for snapshot in selected)
    )


def _compatible(preflight: Any, current: Any, queued: AskSkillRequest,
                request: AskSkillRequest) -> bool:
    if not preflight.can_proceed or preflight.routing_only:
        return False
    if (preflight.pending_project_focus_id or preflight.pending_project_catalog_id
            or preflight.pending_project_specialist):
        return False
    # The queued turn was preflighted for live safety and credits, but its
    # automatic model/Mate routing does not replace the model already running
    # this response. An explicit identity change needs its own inference turn.
    if (not current.selected_main_llm_model_id or not current.selected_mate_id
            or (queued.mate_id and queued.mate_id != current.selected_mate_id)
            or queued.user_preferences != request.user_preferences
            or queued.learning_mode != request.learning_mode):
        return False
    if queued.active_focus_id != request.active_focus_id:
        return False
    if (queued.current_project or {}).get("project_id") != (request.current_project or {}).get("project_id"):
        return False
    if (preflight.relevant_focus_modes
            or (preflight.requires_advice_disclaimer
                and preflight.requires_advice_disclaimer != current.requires_advice_disclaimer)
            or (preflight.filtered_cn_models and not current.filtered_cn_models)):
        return False
    if not _selected_snapshots_already_loaded(preflight.relevant_rules, current.relevant_rules):
        return False
    if not _selected_snapshots_already_loaded(preflight.relevant_workflows, current.relevant_workflows):
        return False
    if not _selected_snapshots_already_loaded(
        preflight.load_app_settings_and_memories, current.load_app_settings_and_memories,
    ):
        return False
    # These client/private inputs may contain newly decrypted context. Even if
    # Jev selected no new key, the active run cannot silently adopt a revision
    # that was not in its original authorized snapshot.
    private_context_fields = (
        "active_project_focus", "custom_rule_documents", "project_focus_documents",
        "project_context_documents", "related_task_candidates", "accepted_plan_context",
        "connected_account_directory", "connected_account_token_refs",
        "focus_phase_state",
    )
    if any(getattr(queued, field, None) != getattr(request, field, None)
           for field in private_context_fields):
        return False
    available_skills = set(current.relevant_app_skills or ())
    if not set(preflight.relevant_app_skills or ()).issubset(available_skills):
        return False
    return True


async def consume_safe_queued_steer(
    *, task_id: str, request: AskSkillRequest, current_preprocessing: Any,
    base_instructions: dict, skill_config_dict: Optional[dict],
    cache: Any, directus: Any, encryption: Any, secrets: Any,
    discovered_apps: dict, excluded_ids: set[str],
) -> Optional[AIHistoryMessage]:
    """Return one newly claimed user turn, or leave it queued for normal handoff."""
    if not cache or not directus or not encryption or not secrets or not skill_config_dict:
        return None
    row = await cache.peek_steer_queued_message(
        request.chat_id, request.user_id, exclude_ids=excluded_ids,
    )
    if not row:
        return None
    member = row["member"]
    message_id = member["message_id"]
    excluded_ids.add(message_id)
    if member.get("recovery_task_id") or member.get("recovery_preflight_id"):
        from backend.core.api.app.routes.handlers.websocket_handlers.chat_turn_preflight_handler import build_inference_commitment
        original = member.get("recovery_inference_request")
        commitment = member.get("recovery_inference_commitment")
        if (not member.get("recovery_task_id") or not member.get("recovery_preflight_id")
                or not isinstance(original, dict) or not isinstance(commitment, str)
                or build_inference_commitment(original) != commitment):
            await _queue_event(cache, request, "queued_message_steer_deferred", {
                "message_id": message_id, "queue_mode": member.get("queue_mode") or "steer",
                "queue_revision": int(member.get("queue_revision") or 1),
                "reason_code": "invalid_recovery_binding",
            })
            return None
    scope = ("chat_id", "user_id", "user_id_hash", "is_incognito", "is_external",
             "is_anonymous", "team_id", "team_id_hash", "team_workspace_type",
             "team_object_id_hash")
    if (any(member.get(field) != getattr(request, field, None) for field in scope)
            or member.get("agentic_context_ref") or member.get("mentioned_settings_memories_cleartext")
            or "@" in str(member.get("current_user_content") or "")):
        await _defer_steer(cache, directus, request, row, task_id, "requires_new_turn")
        return None
    try:
        queued = AskSkillRequest.model_validate(member)
        latest = queued.message_history[-1]
        if (latest.role != "user" or latest.message_id != message_id
                or not isinstance(latest.content, str) or not latest.content.strip()
                or latest.content != queued.current_user_content):
            raise ValueError("Queued history does not match message identity")
        from backend.apps.ai.processing.preprocessor import handle_preprocessing
        config = AskSkillDefaultConfig.model_validate(skill_config_dict)
        preflight = await handle_preprocessing(
            request_data=queued, base_instructions=base_instructions, skill_config=config,
            cache_service=cache, secrets_manager=secrets,
            directus_service=directus, encryption_service=encryption,
            discovered_apps_metadata=discovered_apps,
            preprocessing_stream_channel=None, is_new_chat=False,
        )
    except Exception:
        logger.exception("Queued steer preflight failed for message %s", message_id)
        await _defer_steer(cache, directus, request, row, task_id, "preflight_unavailable")
        return None
    if not _compatible(preflight, current_preprocessing, queued, request):
        reason = "preflight_rejected" if not preflight.can_proceed else "requires_new_turn"
        await _defer_steer(cache, directus, request, row, task_id, reason)
        return None

    storage_unavailable = False
    async with cache.queued_message_edit_lock(request.chat_id) as lock:
        fresh = await cache.get_queued_message_member(request.chat_id, request.user_id, message_id)
        if not fresh or fresh["raw"] != row["raw"]:
            return None
        revision = int(member.get("queue_revision") or 1)
        if not request.is_incognito:
            status = await directus.chat.mark_queued_message_started(
                request.chat_id, request.user_id, message_id, revision, task_id, "steer",
                hashed_team_id=request.team_id_hash,
                recovery_preflight_id=member.get("recovery_preflight_id"),
                recovery_task_id=member.get("recovery_task_id"),
                expected_inference_commitment=member.get("recovery_inference_commitment"),
            )
            if status.get("status") not in ("started", "already_started"):
                storage_unavailable = True
        if not storage_unavailable:
            try:
                claimed = await cache.claim_steer_queued_message(
                    request.chat_id, message_id, expected_raw=row["raw"],
                    active_task_id=task_id, edit_lock_token=lock.local.token,
                    volatile_receipt={
                        "user_id": request.user_id,
                        "user_id_hash": request.user_id_hash,
                        "message_id": message_id,
                    } if request.is_incognito or request.is_external else None,
                )
            except Exception:
                logger.exception("Queued steer claim unavailable for message %s", message_id)
                claimed = False
            if not claimed:
                if not request.is_incognito:
                    try:
                        restored = await directus.chat.restore_queued_message_pending(
                            request.chat_id, request.user_id, message_id,
                            revision, task_id, "steer", hashed_team_id=request.team_id_hash,
                            recovery_preflight_id=member.get("recovery_preflight_id"),
                            recovery_task_id=member.get("recovery_task_id"),
                            expected_inference_commitment=member.get("recovery_inference_commitment"),
                        )
                    except Exception:
                        restored = None
                        logger.exception("Queued steer durable compensation failed for %s", message_id)
                    if not restored or restored.get("status") != "restored":
                        await cache.pause_queued_message_revisions(request.chat_id)
                return None
            if not request.is_incognito and status.get("messages_v") is not None:
                await cache.mark_sync_message_processing(
                    request.user_id, request.chat_id, message_id,
                    revision, status["messages_v"],
                )
    if storage_unavailable:
        await _defer_steer(cache, directus, request, row, task_id, "storage_unavailable")
        return None
    await _queue_event(cache, request, "queued_message_steered", {
        "message_id": message_id, "task_id": task_id,
        "queue_revision": revision,
    })
    return AIHistoryMessage(
        role="user", message_id=message_id, content=latest.content,
        created_at=latest.created_at, sender_name="user",
    )
