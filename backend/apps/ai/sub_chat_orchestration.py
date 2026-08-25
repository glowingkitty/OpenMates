# backend/apps/ai/sub_chat_orchestration.py
#
# Shared sub-chat orchestration helpers for the AI app.
# Keeps fan-out concurrency limits, pending confirmation state, and child task dispatch in
# one backend-owned place so the frontend never becomes the enforcement layer.
# Sub-chats are zero-knowledge shells until the client receives spawn events and
# persists the encrypted first user message.

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
import uuid
from typing import Any

from backend.core.api.app.services.sub_chat_orchestration_service import (
    SubChatOrchestrationService,
)

logger = logging.getLogger(__name__)

MAX_CONCURRENT_SUB_CHATS_PER_PARENT = 20
MAX_DIRECT_SUB_CHATS_PER_PARENT = MAX_CONCURRENT_SUB_CHATS_PER_PARENT
MAX_AUTO_SUB_CHATS_PER_TURN = 3
MAX_AUTO_SUB_CHAT_CREDITS = 2_000
MAX_TEMPLATE_EXPANSION_ITEMS = 20
SUB_CHAT_CONFIRMATION_TTL_SECONDS = 15 * 60
SUB_CHAT_CONFIRMATION_KEY_PREFIX = "sub_chat_confirmation"
SUB_CHAT_SEQUENCE_CONTEXT_VERSION = 1


def is_sub_chat_continuation(request_data: Any) -> bool:
    return bool(
        getattr(request_data, "is_sub_chat_continuation", False)
        or getattr(request_data, "is_app_settings_memories_continuation", False)
        or getattr(request_data, "is_connected_account_permission_continuation", False)
    )


def ensure_orchestration_envelope(request_data: Any) -> None:
    """Create a root envelope or reject incomplete child ancestry."""
    if is_sub_chat_continuation(request_data):
        raise RuntimeError("Sub-chat continuations cannot start descendants")

    if request_data.is_sub_chat:
        required = (
            request_data.orchestration_id,
            request_data.root_chat_id,
            request_data.root_turn_id,
            request_data.orchestration_dispatch_token,
        )
        if not all(required) or request_data.sub_chat_depth not in {1, 2}:
            raise RuntimeError("Sub-chat orchestration ancestry is missing")
        return

    request_data.root_chat_id = request_data.root_chat_id or request_data.chat_id
    request_data.root_turn_id = request_data.root_turn_id or str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"openmates:sub-chat-turn:{request_data.chat_id}:{request_data.message_id}",
        )
    )
    request_data.orchestration_id = request_data.orchestration_id or str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"openmates:sub-chat-orchestration:{request_data.user_id_hash}:"
            f"{request_data.root_chat_id}:{request_data.root_turn_id}",
        )
    )
    request_data.sub_chat_depth = 0


def resolve_sub_chat_depth(request_data: Any) -> int:
    """Fail closed when a child does not carry a complete server envelope."""
    if not request_data.is_sub_chat:
        return 0
    if (
        request_data.orchestration_id
        and request_data.root_chat_id
        and request_data.root_turn_id
        and request_data.orchestration_dispatch_token
        and request_data.sub_chat_depth in {1, 2}
    ):
        return request_data.sub_chat_depth
    return 2


def sub_chat_confirmation_key(chat_id: str, task_id: str) -> str:
    return f"{SUB_CHAT_CONFIRMATION_KEY_PREFIX}:{chat_id}:{task_id}"


def expand_sub_chat_requests(sub_chats_args: list[dict[str, Any]], max_template_items: int | None = None) -> list[dict[str, Any]]:
    """Expand model-proposed sub-chat arguments into concrete child specs."""
    spawned_sub_chats: list[dict[str, Any]] = []
    for sc in sub_chats_args:
        prompt = sc.get("prompt")
        prompt_template = sc.get("prompt_template")
        sc_list = sc.get("list", [])
        wait_for_completion = sc.get("wait_for_completion", True)
        budget_limit = sc.get("budget_limit")
        report_trigger = sc.get("report_trigger", "all")

        def resolve_metadata(value: Any, item: Any | None = None) -> str | None:
            if not isinstance(value, str) or not value.strip():
                return None
            return value.replace("{x}", str(item)).strip() if item is not None else value.strip()

        if prompt_template and sc_list:
            template_limit = max_template_items if max_template_items is not None else MAX_TEMPLATE_EXPANSION_ITEMS
            items = sc_list[:template_limit]
            for item in items:
                resolved_prompt = prompt_template.replace("{x}", str(item))
                sc_id = str(uuid.uuid4())
                spawned_sub_chats.append({
                    "id": sc_id,
                    "user_message_id": f"{sc_id[-10:]}-{uuid.uuid4()}",
                    "prompt": resolved_prompt,
                    "title": resolve_metadata(sc.get("title"), item),
                    "category": resolve_metadata(sc.get("category"), item),
                    "icon": resolve_metadata(sc.get("icon"), item),
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
                "title": resolve_metadata(sc.get("title")),
                "category": resolve_metadata(sc.get("category")),
                "icon": resolve_metadata(sc.get("icon")),
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
    requested_total = existing_count + requested_count
    remaining = max(MAX_CONCURRENT_SUB_CHATS_PER_PARENT - existing_count, 0)
    if requested_total > MAX_CONCURRENT_SUB_CHATS_PER_PARENT:
        return {
            "allowed": False,
            "remaining": remaining,
            "message": (
                f"This chat can start at most {MAX_CONCURRENT_SUB_CHATS_PER_PARENT} cumulative concurrent sub-chats."
            ),
        }

    return {
        "allowed": True,
        "remaining": MAX_CONCURRENT_SUB_CHATS_PER_PARENT - requested_total,
        "message": "",
    }


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
    context = await cache_service.get_and_delete(key)
    return context if isinstance(context, dict) else None


async def create_sub_chat_records(
    *,
    directus_service: Any,
    request_data: Any,
    spawned_sub_chats: list[dict[str, Any]],
    log_prefix: str,
) -> dict[str, str]:
    if not directus_service:
        raise RuntimeError("Sub-chat child persistence requires Directus")
    if not spawned_sub_chats:
        return {}

    try:
        ensure_orchestration_envelope(request_data)
        service = SubChatOrchestrationService(directus_service)
        if request_data.sub_chat_depth == 0:
            await create_orchestration_root(directus_service, request_data)
            if request_data.orchestration_approved:
                await service.execute("approve_root_limits", {
                    "protocol_version": 1,
                    "orchestration_id": request_data.orchestration_id,
                    "hashed_user_id": request_data.user_id_hash,
                    "descendant_limit": request_data.orchestration_descendant_limit,
                    "credit_limit": request_data.orchestration_credit_limit,
                })

        internal_token = os.getenv("INTERNAL_API_SHARED_TOKEN")
        if not internal_token:
            raise RuntimeError("INTERNAL_API_SHARED_TOKEN is required for child dispatch")
        dispatch_tokens = {
            str(sc["id"]): hmac.new(
                internal_token.encode("utf-8"),
                f"{request_data.orchestration_id}:{sc['id']}".encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            for sc in spawned_sub_chats
        }
        batch_id = str(uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"openmates:sub-chat-batch:{request_data.orchestration_id}:"
            + ":".join(sorted(dispatch_tokens)),
        ))
        await service.execute("prepare_batch", {
            "protocol_version": 1,
            "orchestration_id": request_data.orchestration_id,
            "hashed_user_id": request_data.user_id_hash,
            "batch_id": batch_id,
            "parent_chat_id": request_data.chat_id,
            "parent_depth": request_data.sub_chat_depth,
            "is_continuation": False,
            "children": [
                {
                    "child_chat_id": str(sc["id"]),
                    "user_message_id": str(sc["user_message_id"]),
                    "dispatch_token": dispatch_tokens[str(sc["id"])],
                    "budget_limit": sc.get("budget_limit"),
                }
                for sc in spawned_sub_chats
            ],
        })
        logger.info(
            "%s [SUB_CHAT] Prepared batch with %d child chat record(s)",
            log_prefix,
            len(spawned_sub_chats),
        )
        return dispatch_tokens
    except Exception as sc_err:
        logger.error("%s [SUB_CHAT] Error preparing sub-chat batch: %s", log_prefix, sc_err, exc_info=True)
        raise RuntimeError("Sub-chat child persistence failed") from sc_err


async def create_orchestration_root(directus_service: Any, request_data: Any) -> dict[str, Any]:
    """Persist the automatic root envelope before approval or billable dispatch."""
    if not directus_service:
        raise RuntimeError("Sub-chat root persistence requires Directus")
    ensure_orchestration_envelope(request_data)
    if request_data.sub_chat_depth != 0:
        raise RuntimeError("Only a root request can create an orchestration root")
    return await SubChatOrchestrationService(directus_service).execute("create_root", {
        "protocol_version": 1,
        "orchestration_id": request_data.orchestration_id,
        "hashed_user_id": request_data.user_id_hash,
        "hashed_team_id": request_data.team_id_hash,
        "root_chat_id": request_data.root_chat_id,
        "root_turn_id": request_data.root_turn_id,
        "descendant_limit": MAX_AUTO_SUB_CHATS_PER_TURN,
        "credit_limit": MAX_AUTO_SUB_CHAT_CREDITS,
    })


async def dispatch_sub_chat_task(
    *,
    request_data: Any,
    skill_config_dict: dict[str, Any] | None,
    sub_chat: dict[str, Any],
    log_prefix: str,
    prompt_override: str | None = None,
    dispatch_token: str | None = None,
) -> str | None:
    from backend.apps.ai.tasks.ask_skill_task import process_ai_skill_ask_task

    try:
        if not dispatch_token:
            raise RuntimeError("Prepared child dispatch token is required")
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
            "orchestration_id": request_data.orchestration_id,
            "root_chat_id": request_data.root_chat_id,
            "root_turn_id": request_data.root_turn_id,
            "sub_chat_depth": request_data.sub_chat_depth + 1,
            "orchestration_dispatch_token": dispatch_token,
            "orchestration_descendant_limit": request_data.orchestration_descendant_limit,
            "orchestration_credit_limit": request_data.orchestration_credit_limit,
            "orchestration_approved": request_data.orchestration_approved,
            "is_anonymous": bool(getattr(request_data, "is_anonymous", False)),
            "anonymous_reservation_id": getattr(request_data, "anonymous_reservation_id", None),
            "is_incognito": request_data.is_incognito,
            "is_external": request_data.is_external,
            "mate_id": "george",
            "active_focus_id": request_data.active_focus_id,
            "user_preferences": request_data.user_preferences or {},
            "budget_limit": sub_chat.get("budget_limit"),
        }

        stable_task_id = str(uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"openmates:sub-chat-dispatch:{request_data.orchestration_id}:{sc_id}",
        ))
        task_result = process_ai_skill_ask_task.apply_async(
            kwargs={
                "request_data_dict": child_request_data,
                "skill_config_dict": skill_config_dict or {},
            },
            task_id=stable_task_id,
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
    dispatch_tokens = await create_sub_chat_records(
        directus_service=directus_service,
        request_data=request_data,
        spawned_sub_chats=spawned_sub_chats,
        log_prefix=log_prefix,
    )
    for sub_chat in spawned_sub_chats:
        task_id = await dispatch_sub_chat_task(
            request_data=request_data,
            skill_config_dict=skill_config_dict,
            sub_chat=sub_chat,
            log_prefix=log_prefix,
            dispatch_token=dispatch_tokens[str(sub_chat["id"])],
        )
        if not task_id:
            raise RuntimeError(f"Sub-chat child {sub_chat['id']} dispatch failed")
