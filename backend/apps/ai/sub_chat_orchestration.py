# backend/apps/ai/sub_chat_orchestration.py
#
# Shared sub-chat orchestration helpers for the AI app.
# Keeps fan-out limits, pending confirmation state, and child task dispatch in
# one backend-owned place so the frontend never becomes the enforcement layer.
# Sub-chats are zero-knowledge shells until the client receives spawn events and
# persists the encrypted first user message.

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

MAX_DIRECT_SUB_CHATS_PER_PARENT = 20
MAX_AUTO_SUB_CHATS_PER_TURN = 3
MAX_TEMPLATE_EXPANSION_ITEMS = 20
SUB_CHAT_CONFIRMATION_TTL_SECONDS = 15 * 60
SUB_CHAT_CONFIRMATION_KEY_PREFIX = "sub_chat_confirmation"
SUB_CHAT_SEQUENCE_CONTEXT_VERSION = 1


def sub_chat_confirmation_key(chat_id: str, task_id: str) -> str:
    return f"{SUB_CHAT_CONFIRMATION_KEY_PREFIX}:{chat_id}:{task_id}"


def expand_sub_chat_requests(sub_chats_args: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Expand model-proposed sub-chat arguments into concrete child specs."""
    spawned_sub_chats: list[dict[str, Any]] = []
    for sc in sub_chats_args:
        prompt = sc.get("prompt")
        prompt_template = sc.get("prompt_template")
        sc_list = sc.get("list", [])
        wait_for_completion = sc.get("wait_for_completion", True)
        budget_limit = sc.get("budget_limit")
        report_trigger = sc.get("report_trigger", "all")

        if prompt_template and sc_list:
            for item in sc_list[:MAX_TEMPLATE_EXPANSION_ITEMS]:
                resolved_prompt = prompt_template.replace("{x}", str(item))
                sc_id = str(uuid.uuid4())
                spawned_sub_chats.append({
                    "id": sc_id,
                    "user_message_id": f"{sc_id[-10:]}-{uuid.uuid4()}",
                    "prompt": resolved_prompt,
                    "wait_for_completion": wait_for_completion,
                    "budget_limit": budget_limit,
                    "report_trigger": report_trigger,
                })
        else:
            sc_id = str(uuid.uuid4())
            spawned_sub_chats.append({
                "id": sc_id,
                "user_message_id": f"{sc_id[-10:]}-{uuid.uuid4()}",
                "prompt": prompt or prompt_template or "",
                "wait_for_completion": wait_for_completion,
                "budget_limit": budget_limit,
                "report_trigger": report_trigger,
            })

    return spawned_sub_chats


def get_sub_chat_execution_mode(parsed_args: dict[str, Any]) -> str:
    mode = str(parsed_args.get("execution_mode") or "parallel").lower()
    return "sequential" if mode == "sequential" else "parallel"


def get_sub_chat_context_policy(parsed_args: dict[str, Any]) -> str:
    policy = str(parsed_args.get("context_policy") or "previous_summary").lower()
    return policy if policy in {"none", "previous_summary", "cumulative_summaries"} else "previous_summary"


async def count_direct_sub_chats(directus_service: Any, parent_chat_id: str) -> int:
    if not directus_service:
        return 0

    sub_chats = await directus_service.get_items(
        "chats",
        params={
            "filter[parent_id][_eq]": parent_chat_id,
            "fields": "id",
            "limit": -1,
        },
        admin_required=True,
    ) or []
    return len(sub_chats)


def validate_sub_chat_capacity(existing_count: int, requested_count: int) -> dict[str, Any]:
    remaining = max(MAX_DIRECT_SUB_CHATS_PER_PARENT - existing_count, 0)
    if requested_count > remaining:
        return {
            "allowed": False,
            "remaining": remaining,
            "message": (
                f"This chat can have at most {MAX_DIRECT_SUB_CHATS_PER_PARENT} direct sub-chats. "
                f"It already has {existing_count}, so only {remaining} more can be started."
            ),
        }

    return {"allowed": True, "remaining": remaining, "message": ""}


async def store_pending_sub_chat_confirmation(
    *,
    cache_service: Any,
    chat_id: str,
    task_id: str,
    context: dict[str, Any],
) -> None:
    if not cache_service:
        return
    await cache_service.set(
        sub_chat_confirmation_key(chat_id, task_id),
        context,
        ttl=SUB_CHAT_CONFIRMATION_TTL_SECONDS,
    )


async def consume_pending_sub_chat_confirmation(
    *,
    cache_service: Any,
    chat_id: str,
    task_id: str,
) -> dict[str, Any] | None:
    if not cache_service:
        return None

    key = sub_chat_confirmation_key(chat_id, task_id)
    context = await cache_service.get(key)
    if context is not None:
        await cache_service.delete(key)
    return context if isinstance(context, dict) else None


async def create_sub_chat_records(
    *,
    directus_service: Any,
    request_data: Any,
    spawned_sub_chats: list[dict[str, Any]],
    log_prefix: str,
) -> None:
    if not directus_service:
        logger.warning("%s [SUB_CHAT] No Directus service; cannot create sub-chat records", log_prefix)
        return

    for sc in spawned_sub_chats:
        try:
            sc_id = sc["id"]
            prompt = sc["prompt"]
            timestamp = int(time.time())

            sub_chat_payload = {
                "id": sc_id,
                "hashed_user_id": request_data.user_id_hash,
                "created_at": timestamp,
                "updated_at": timestamp,
                "messages_v": 1,
                "title_v": 0,
                "last_edited_overall_timestamp": timestamp,
                "last_message_timestamp": timestamp,
                "unread_count": 0,
                "encrypted_title": "",
                "title": prompt[:30] + "..." if len(prompt) > 30 else prompt,
                "parent_id": request_data.chat_id,
                "is_sub_chat": True,
                "budget_limit": sc.get("budget_limit"),
            }
            await directus_service.chat.create_chat_in_directus(sub_chat_payload)
            logger.info("%s [SUB_CHAT] Created child chat record %s in Directus", log_prefix, sc_id)
        except Exception as sc_err:
            logger.error("%s [SUB_CHAT] Error creating sub-chat record: %s", log_prefix, sc_err, exc_info=True)


async def dispatch_sub_chat_task(
    *,
    request_data: Any,
    skill_config_dict: dict[str, Any] | None,
    sub_chat: dict[str, Any],
    log_prefix: str,
    prompt_override: str | None = None,
) -> str | None:
    from backend.apps.ai.tasks.ask_skill_task import process_ai_skill_ask_task

    try:
        sc_id = sub_chat["id"]
        prompt = prompt_override if prompt_override is not None else sub_chat["prompt"]
        msg_id = sub_chat["user_message_id"]
        timestamp = int(time.time())

        child_request_data = {
            "chat_id": sc_id,
            "message_id": msg_id,
            "user_id": request_data.user_id,
            "user_id_hash": request_data.user_id_hash,
            "message_history": [{
                "role": "user",
                "content": prompt,
                "created_at": timestamp,
                "sender_name": "user",
            }],
            "chat_has_title": False,
            "parent_id": request_data.chat_id,
            "is_sub_chat": True,
            "is_incognito": request_data.is_incognito,
            "is_external": request_data.is_external,
            "mate_id": "george",
            "user_preferences": request_data.user_preferences or {},
            "budget_limit": sub_chat.get("budget_limit"),
        }

        task_result = process_ai_skill_ask_task.apply_async(
            kwargs={
                "request_data_dict": child_request_data,
                "skill_config_dict": skill_config_dict or {},
            },
            queue="app_ai",
            exchange="app_ai",
            routing_key="app_ai",
        )
        logger.info("%s [SUB_CHAT] Dispatched process_ai_skill_ask_task %s for child chat %s", log_prefix, task_result.id, sc_id)
        return str(task_result.id)
    except Exception as sc_err:
        logger.error("%s [SUB_CHAT] Error dispatching sub-chat task: %s", log_prefix, sc_err, exc_info=True)
        return None


def build_sequential_child_prompt(sub_chat: dict[str, Any], pending_context: dict[str, Any]) -> str:
    base_prompt = str(sub_chat.get("prompt") or "")
    context_policy = pending_context.get("context_policy") or "previous_summary"
    if context_policy == "none":
        return base_prompt

    completed = pending_context.get("completed") if isinstance(pending_context.get("completed"), dict) else {}
    expected_ids = [str(chat_id) for chat_id in pending_context.get("expected_sub_chat_ids", [])]
    completed_lines: list[str] = []
    for index, chat_id in enumerate(expected_ids, start=1):
        entry = completed.get(chat_id)
        if not isinstance(entry, dict) or not entry.get("summary"):
            continue
        completed_lines.append(f"## Previous sub-chat {index}: {chat_id}\n{entry['summary']}")
        if context_policy == "previous_summary":
            completed_lines = completed_lines[-1:]

    if not completed_lines:
        return base_prompt

    return (
        "Previous sub-chat context is included below. Use it to avoid repeating work and to prevent collisions.\n\n"
        + "\n\n".join(completed_lines)
        + "\n\nNow execute your assigned task:\n"
        + base_prompt
    )


async def create_and_dispatch_sub_chats(
    *,
    directus_service: Any,
    request_data: Any,
    skill_config_dict: dict[str, Any] | None,
    spawned_sub_chats: list[dict[str, Any]],
    log_prefix: str,
) -> None:
    await create_sub_chat_records(
        directus_service=directus_service,
        request_data=request_data,
        spawned_sub_chats=spawned_sub_chats,
        log_prefix=log_prefix,
    )
    for sub_chat in spawned_sub_chats:
        await dispatch_sub_chat_task(
            request_data=request_data,
            skill_config_dict=skill_config_dict,
            sub_chat=sub_chat,
            log_prefix=log_prefix,
        )
