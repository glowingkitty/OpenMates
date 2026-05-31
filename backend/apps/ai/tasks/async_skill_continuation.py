# backend/apps/ai/tasks/async_skill_continuation.py
#
# Generic continuation helpers for asynchronous skill completions.
# Long-running app skills update embeds from worker tasks; these helpers let the
# completed result re-enter the normal AI ask pipeline with the original chat
# history instead of sending a hardcoded app-specific follow-up message.

from __future__ import annotations

import logging
import asyncio
import json
import time
import os
from typing import Any, Optional

import yaml

try:
    from toon_format import encode as toon_encode
except ImportError:  # pragma: no cover - test environments may not install optional TOON package
    def toon_encode(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False)

from backend.apps.ai.skills.ask_skill import AskSkillRequest
from backend.core.api.app.schemas.chat import AIHistoryMessage

logger = logging.getLogger(__name__)

ASYNC_SKILL_CONTINUATION_TTL_SECONDS = 60 * 60 * 24
ASYNC_SKILL_CONTINUATION_KEY_PREFIX = "async_skill_continuation"
ASYNC_SKILL_COMPLETION_KEY_PREFIX = "async_skill_completion"
ASYNC_EMBED_REFERENCE_INSTRUCTION = (
    "When referencing a specific completed result that has an embed_ref field, "
    "link it with Markdown like [human-readable title](embed:the_embed_ref). "
    "Use the result title or a short description as the link text; never use the embed_ref itself as the visible text."
)
celery_app = None


def async_skill_continuation_key(task_id: str) -> str:
    """Return the cache key used to resume interpretation for an async skill task."""
    return f"{ASYNC_SKILL_CONTINUATION_KEY_PREFIX}:{task_id}"


def async_skill_completion_key(task_id: str) -> str:
    """Return the cache key used by inline waits for completed async skill results."""
    return f"{ASYNC_SKILL_COMPLETION_KEY_PREFIX}:{task_id}"


async def cache_async_skill_continuation_context(
    *,
    cache_service: Any,
    async_task_id: str,
    request_data: AskSkillRequest,
    skill_config_dict: Optional[dict[str, Any]] = None,
    app_id: str,
    skill_id: str,
    tool_name: str,
    tool_arguments: dict[str, Any],
    inline_wait_deadline: Optional[float] = None,
) -> None:
    """Store the original ask context for a later async skill completion."""
    if not cache_service or not async_task_id:
        return

    context = {
        "request_data": request_data.model_dump(mode="json"),
        "skill_config_dict": skill_config_dict or {},
        "app_id": app_id,
        "skill_id": skill_id,
        "tool_name": tool_name,
        "tool_arguments": tool_arguments,
        "cached_at": int(time.time()),
    }
    if inline_wait_deadline is not None:
        context["inline_wait_deadline"] = inline_wait_deadline
    await cache_service.set(
        async_skill_continuation_key(async_task_id),
        context,
        ttl=ASYNC_SKILL_CONTINUATION_TTL_SECONDS,
    )


async def dispatch_async_skill_continuation(
    *,
    cache_service: Any,
    async_task_id: str,
    completed_results: list[dict[str, Any]],
    result_status: str = "finished",
    request_metadata: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    """Dispatch a normal AI ask task to interpret completed async skill results."""
    if not cache_service or not async_task_id:
        return None

    cache_key = async_skill_continuation_key(async_task_id)
    context = await cache_service.get(cache_key)
    if not isinstance(context, dict):
        logger.warning("Async skill continuation context missing for task %s", async_task_id)
        return None

    inline_wait_deadline = context.get("inline_wait_deadline")
    if isinstance(inline_wait_deadline, (int, float)) and time.time() <= inline_wait_deadline:
        await cache_service.set(
            async_skill_completion_key(async_task_id),
            _build_completed_tool_result_payload(
                context=context,
                completed_results=completed_results,
                result_status=result_status,
                request_metadata=request_metadata or {},
            ),
            ttl=ASYNC_SKILL_CONTINUATION_TTL_SECONDS,
        )
        logger.info("Cached async skill completion for inline wait: %s", async_task_id)
        return None

    request_payload = context.get("request_data")
    if not isinstance(request_payload, dict):
        logger.warning("Async skill continuation context has invalid request_data for task %s", async_task_id)
        return None

    original_request = AskSkillRequest(**request_payload)
    skill_config_payload = context.get("skill_config_dict")
    if not isinstance(skill_config_payload, dict):
        logger.warning("Async skill continuation context has invalid skill_config_dict for task %s", async_task_id)
        skill_config_payload = {}
    if not skill_config_payload.get("default_llms"):
        logger.warning("Async skill continuation context missing ask skill config for task %s; loading app.yml fallback", async_task_id)
        skill_config_payload = _load_ask_skill_config_from_app_yml()

    continuation_history = [
        AIHistoryMessage(**(message.model_dump(mode="json") if hasattr(message, "model_dump") else message))
        for message in original_request.message_history
    ]
    continuation_history.append(
        AIHistoryMessage(
            role="system",
            content=_build_completed_tool_result_message(
                context=context,
                completed_results=completed_results,
                result_status=result_status,
                request_metadata=request_metadata or {},
            ),
            created_at=int(time.time()),
        )
    )

    continuation_request = AskSkillRequest(
        chat_id=original_request.chat_id,
        message_id=original_request.message_id,
        user_id=original_request.user_id,
        user_id_hash=original_request.user_id_hash,
        message_history=continuation_history,
        chat_has_title=original_request.chat_has_title,
        current_chat_title=original_request.current_chat_title,
        is_incognito=original_request.is_incognito,
        is_external=original_request.is_external,
        mate_id=original_request.mate_id,
        active_focus_id=original_request.active_focus_id,
        user_preferences=original_request.user_preferences,
        app_settings_memories_metadata=original_request.app_settings_memories_metadata,
        mentioned_settings_memories_cleartext=original_request.mentioned_settings_memories_cleartext,
        embed_file_path_index=original_request.embed_file_path_index,
        is_sub_chat_continuation=original_request.is_sub_chat_continuation,
    )

    app = _get_celery_app()
    task_result = app.send_task(
        name="apps.ai.tasks.skill_ask",
        kwargs={
            "request_data_dict": continuation_request.model_dump(mode="json"),
            "skill_config_dict": skill_config_payload,
        },
        queue="app_ai",
    )
    await cache_service.delete(cache_key)
    logger.info("Dispatched async skill continuation task %s for completed task %s", task_result.id, async_task_id)
    return task_result.id


async def wait_for_async_skill_completion(
    *,
    cache_service: Any,
    async_task_ids: list[str],
    timeout_seconds: float,
    poll_interval_seconds: float = 0.25,
) -> Optional[dict[str, Any]]:
    """Wait briefly for an async worker to publish completed results for inline use."""
    if not cache_service or not async_task_ids or timeout_seconds <= 0:
        return None

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() <= deadline:
        for async_task_id in async_task_ids:
            cache_key = async_skill_completion_key(async_task_id)
            completion = await cache_service.get(cache_key)
            if isinstance(completion, dict):
                await cache_service.delete(cache_key)
                await cache_service.delete(async_skill_continuation_key(async_task_id))
                return completion
        await asyncio.sleep(poll_interval_seconds)

    return None


def _get_celery_app() -> Any:
    global celery_app
    if celery_app is None:
        from backend.core.api.app.tasks.celery_config import app as configured_app

        celery_app = configured_app
    return celery_app


def _load_ask_skill_config_from_app_yml() -> dict[str, Any]:
    """Load the ask skill config needed to run continuation tasks safely."""
    app_yml_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.yml")
    try:
        with open(app_yml_path, "r", encoding="utf-8") as file:
            app_config = yaml.safe_load(file) or {}
    except Exception as exc:
        logger.error("Failed to load ask skill config from %s: %s", app_yml_path, exc, exc_info=True)
        return {}

    for skill in app_config.get("skills", []):
        if skill.get("id") == "ask":
            default_config = skill.get("skill_config")
            return default_config if isinstance(default_config, dict) else {}
    logger.error("Ask skill config not found in %s", app_yml_path)
    return {}


def _build_completed_tool_result_message(
    *,
    context: dict[str, Any],
    completed_results: list[dict[str, Any]],
    result_status: str,
    request_metadata: dict[str, Any],
) -> str:
    payload = _build_completed_tool_result_payload(
        context=context,
        completed_results=completed_results,
        result_status=result_status,
        request_metadata=request_metadata,
    )
    return (
        "An asynchronous tool call requested earlier in this conversation has completed. "
        "Use these completed tool results and the prior chat history to answer the user's original request now. "
        "Do not ask the user to wait for this same tool result. "
        f"{ASYNC_EMBED_REFERENCE_INSTRUCTION}\n\n"
        f"Completed tool result (TOON):\n{toon_encode(payload)}"
    )


def _build_completed_tool_result_payload(
    *,
    context: dict[str, Any],
    completed_results: list[dict[str, Any]],
    result_status: str,
    request_metadata: dict[str, Any],
) -> dict[str, Any]:
    tool_name = context.get("tool_name") or f"{context.get('app_id')}-{context.get('skill_id')}"
    return {
        "status": result_status,
        "tool_name": tool_name,
        "arguments": context.get("tool_arguments") or {},
        "request_metadata": request_metadata,
        "results": completed_results,
    }
