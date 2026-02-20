# backend/core/api/app/tasks/default_inspiration_tasks.py
#
# Celery tasks for managing "Suggested Daily Inspirations" (admin-curated defaults).
#
# Two tasks:
#
# 1. generate_default_inspiration_content_task
#    Triggered by admin clicking "Generate Content" on a pending suggestion.
#    Calls Gemini Flash to produce: category, CTA phrase (English), assistant_response (English).
#    Updates status: generating → pending_review (or generation_failed on error).
#    Sends `default_inspiration_updated` WebSocket event to admin.
#
# 2. translate_default_inspiration_task
#    Triggered by admin clicking "Accept" (confirm) on a pending_review suggestion.
#    Translates phrase + assistant_response into all 20 target languages.
#    Reports progress via `default_inspiration_progress` WebSocket events (same pattern as demo_chat_progress).
#    On completion: status → published, Redis public cache cleared, WS event to admin.
#    Max 3 published entries enforced; oldest is deactivated if exceeded.
#
# Follows patterns from demo_tasks.py (translation batching, WS progress) and
# the Celery task structure from demo_tasks.py / daily_inspiration_tasks.py.

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.apps.ai.llm_providers.google_client import invoke_google_ai_studio_chat_completions

logger = logging.getLogger(__name__)

# Languages to translate into (same 20 as demo_tasks.py)
TARGET_LANGUAGES = [
    "en", "de", "zh", "es", "fr", "pt", "ru", "ja", "ko", "it",
    "tr", "vi", "id", "pl", "nl", "ar", "hi", "th", "cs", "sv",
]

# Redis cache key pattern for the public default-inspirations endpoint
_PUBLIC_CACHE_KEY_PREFIX = "public:default_inspirations:"
_PUBLIC_CACHE_TTL = 3600  # 1 hour


# ─────────────────────────────────────────────────────────────────────────────
# Task 1: Generate AI content for a pending suggestion
# ─────────────────────────────────────────────────────────────────────────────

@app.task(name="default_inspiration.generate_content", base=BaseServiceTask, bind=True)
def generate_default_inspiration_content_task(self, inspiration_id: str, admin_user_id: str):
    """
    Celery task: generate category, CTA phrase, and assistant_response for a pending suggestion.

    Args:
        inspiration_id: UUID of the suggested_daily_inspirations record
        admin_user_id: UUID of the admin triggering this action (for WS notification)
    """
    logger.info(
        f"[DefaultInspiration][generate] Starting for inspiration_id={inspiration_id}, "
        f"admin={admin_user_id[:8]}..."
    )
    loop = None
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(
            _async_generate_content(self, inspiration_id, admin_user_id)
        )
    except Exception as e:
        logger.error(
            f"[DefaultInspiration][generate] Task error for inspiration_id={inspiration_id}: {e}",
            exc_info=True,
        )
        if loop:
            loop.run_until_complete(
                _update_status_and_notify(
                    self, inspiration_id, "generation_failed", admin_user_id
                )
            )
        raise
    finally:
        if loop:
            loop.close()


async def _async_generate_content(
    task: BaseServiceTask, inspiration_id: str, admin_user_id: str
) -> None:
    """
    Async implementation of content generation.

    Calls Gemini Flash to produce:
    - category: short topic label (e.g. "productivity", "science")
    - phrase: an engaging English CTA phrase for the banner (≤ 10 words)
    - assistant_response: a 1-2 sentence English context / teaser

    Transitions status: generating → pending_review (or generation_failed on error).
    """
    await task.initialize_services()
    directus = task._directus_service

    # Mark as generating
    await directus.suggested_inspiration.update_status(inspiration_id, "generating")
    await _notify_admin(task, inspiration_id, admin_user_id, "generating")

    # Fetch the suggestion record
    record = await directus.suggested_inspiration.get_by_id(inspiration_id)
    if not record:
        logger.error(
            f"[DefaultInspiration][generate] Record not found: inspiration_id={inspiration_id}"
        )
        await _update_status_and_notify(task, inspiration_id, "generation_failed", admin_user_id)
        return

    video_title = record.get("video_title") or ""
    video_channel = record.get("video_channel_name") or ""
    video_url = record.get("video_url") or ""

    # Build the Gemini prompt using structured function calling
    generation_tool = {
        "type": "function",
        "function": {
            "name": "return_inspiration_content",
            "description": (
                "Return AI-generated Daily Inspiration content for a YouTube video. "
                "All fields must be in English."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": (
                            "A short, single-word or two-word topic label for the video "
                            "(e.g. 'productivity', 'science', 'creativity', 'well-being'). "
                            "Lowercase only."
                        ),
                    },
                    "phrase": {
                        "type": "string",
                        "description": (
                            "An engaging, inviting CTA phrase for the Daily Inspiration banner. "
                            "Maximum 10 words. Does not start with 'Watch', 'See', or 'Check'. "
                            "Sounds inspiring and curious, not like clickbait."
                        ),
                    },
                    "assistant_response": {
                        "type": "string",
                        "description": (
                            "A 1-2 sentence teaser that gives viewers a sense of what they will "
                            "learn or experience. Friendly, enthusiastic, no spoilers."
                        ),
                    },
                },
                "required": ["category", "phrase", "assistant_response"],
            },
        },
    }

    messages = [
        {
            "role": "system",
            "content": (
                "You generate Daily Inspiration content for an AI assistant app. "
                "The daily inspiration section shows users a curated YouTube video to inspire them. "
                "Create a category label, a short engaging CTA phrase, and a brief teaser. "
                "All output must be in English."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Generate Daily Inspiration content for this YouTube video:\n\n"
                f"Title: {video_title}\n"
                f"Channel: {video_channel}\n"
                f"URL: {video_url}\n\n"
                "Return a category, phrase, and assistant_response."
            ),
        },
    ]

    try:
        response = await invoke_google_ai_studio_chat_completions(
            task_id=f"default_inspiration_generate_{inspiration_id[:8]}",
            model_id="gemini-3-flash-preview",
            messages=messages,
            secrets_manager=task.secrets_manager,
            tools=[generation_tool],
            tool_choice="required",
            temperature=0.7,
            max_tokens=512,
            stream=False,
        )

        if not response.success or not response.tool_calls_made:
            err = getattr(response, "error_message", "No tool call returned")
            logger.error(
                f"[DefaultInspiration][generate] Gemini call failed for {inspiration_id}: {err}"
            )
            await _update_status_and_notify(
                task, inspiration_id, "generation_failed", admin_user_id
            )
            return

        # Extract generated fields
        generated: Dict[str, str] = {}
        for call in response.tool_calls_made:
            if call.function_name == "return_inspiration_content":
                generated = call.function_arguments_parsed or {}
                break

        category = generated.get("category", "")
        phrase = generated.get("phrase", "")
        assistant_response = generated.get("assistant_response", "")

        if not phrase or not assistant_response:
            logger.error(
                f"[DefaultInspiration][generate] Incomplete generation for {inspiration_id}: {generated}"
            )
            await _update_status_and_notify(
                task, inspiration_id, "generation_failed", admin_user_id
            )
            return

        # Store generated content and transition to pending_review
        await directus.suggested_inspiration.set_generated_content(
            inspiration_id=inspiration_id,
            category=category,
            phrase=phrase,
            assistant_response=assistant_response,
        )

        logger.info(
            f"[DefaultInspiration][generate] Content generated for inspiration_id={inspiration_id}: "
            f"category={category!r}, phrase={phrase!r}"
        )

        # Notify admin of new state
        await _notify_admin(task, inspiration_id, admin_user_id, "pending_review")

    except Exception as e:
        logger.error(
            f"[DefaultInspiration][generate] Exception during Gemini call for {inspiration_id}: {e}",
            exc_info=True,
        )
        await _update_status_and_notify(task, inspiration_id, "generation_failed", admin_user_id)
        raise


# ─────────────────────────────────────────────────────────────────────────────
# Task 2: Translate confirmed inspiration into all target languages
# ─────────────────────────────────────────────────────────────────────────────

@app.task(name="default_inspiration.translate", base=BaseServiceTask, bind=True)
def translate_default_inspiration_task(self, inspiration_id: str, admin_user_id: str):
    """
    Celery task: translate phrase + assistant_response into all 20 target languages.

    Triggered after admin confirms (Accept) a pending_review suggestion.
    Reports progress via `default_inspiration_progress` WebSocket events.
    On completion: status → published, Redis public cache invalidated.

    Args:
        inspiration_id: UUID of the suggested_daily_inspirations record
        admin_user_id: UUID of the admin (for WS progress notifications)
    """
    logger.info(
        f"[DefaultInspiration][translate] Starting for inspiration_id={inspiration_id}, "
        f"admin={admin_user_id[:8]}..."
    )
    loop = None
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(
            _async_translate_inspiration(self, inspiration_id, admin_user_id)
        )
    except Exception as e:
        logger.error(
            f"[DefaultInspiration][translate] Task error for inspiration_id={inspiration_id}: {e}",
            exc_info=True,
        )
        if loop:
            loop.run_until_complete(
                _update_status_and_notify(
                    task=self,
                    inspiration_id=inspiration_id,
                    status="translation_failed",
                    admin_user_id=admin_user_id,
                )
            )
        raise
    finally:
        if loop:
            loop.close()


async def _async_translate_inspiration(
    task: BaseServiceTask, inspiration_id: str, admin_user_id: str
) -> None:
    """
    Async implementation of the translation task.

    Translates `phrase` and `assistant_response` into all TARGET_LANGUAGES.
    Stores results in suggested_daily_inspiration_translations.
    Then publishes the inspiration and clears the Redis public cache.
    """
    await task.initialize_services()
    directus = task._directus_service

    # Fetch the record
    record = await directus.suggested_inspiration.get_by_id(inspiration_id)
    if not record:
        logger.error(
            f"[DefaultInspiration][translate] Record not found: inspiration_id={inspiration_id}"
        )
        await _update_status_and_notify(task, inspiration_id, "translation_failed", admin_user_id)
        return

    phrase_en = record.get("phrase") or ""
    assistant_response_en = record.get("assistant_response") or ""

    if not phrase_en:
        logger.error(
            f"[DefaultInspiration][translate] No phrase found for inspiration_id={inspiration_id}"
        )
        await _update_status_and_notify(task, inspiration_id, "translation_failed", admin_user_id)
        return

    total_languages = len(TARGET_LANGUAGES)
    completed = 0

    # ── Store English originals first ────────────────────────────────────────
    await directus.suggested_inspiration.upsert_translation(
        inspiration_id=inspiration_id,
        language="en",
        phrase=phrase_en,
        assistant_response=assistant_response_en,
    )
    completed += 1
    await _send_progress(task, inspiration_id, admin_user_id, completed, total_languages, "en")

    # ── Translate remaining languages in batches of 5 ──────────────────────
    non_english = [lang for lang in TARGET_LANGUAGES if lang != "en"]
    batch_size = 5

    for batch_start in range(0, len(non_english), batch_size):
        batch_langs = non_english[batch_start : batch_start + batch_size]

        try:
            translations = await _translate_inspiration_texts_batch(
                task=task,
                phrase=phrase_en,
                assistant_response=assistant_response_en,
                target_languages=batch_langs,
            )
        except Exception as e:
            logger.error(
                f"[DefaultInspiration][translate] Batch error for {batch_langs}: {e}",
                exc_info=True,
            )
            # Fall back to English for this batch
            translations = {
                lang: {"phrase": phrase_en, "assistant_response": assistant_response_en}
                for lang in batch_langs
            }

        for lang in batch_langs:
            lang_data = translations.get(lang, {})
            await directus.suggested_inspiration.upsert_translation(
                inspiration_id=inspiration_id,
                language=lang,
                phrase=lang_data.get("phrase") or phrase_en,
                assistant_response=lang_data.get("assistant_response") or assistant_response_en,
            )
            completed += 1
            await _send_progress(task, inspiration_id, admin_user_id, completed, total_languages, lang)

    # ── Publish and enforce max ───────────────────────────────────────────────
    await directus.suggested_inspiration.publish_inspiration(inspiration_id)
    await directus.suggested_inspiration.enforce_max_published()

    # ── Invalidate public Redis cache for all languages ───────────────────────
    await _invalidate_public_cache(task)

    logger.info(
        f"[DefaultInspiration][translate] Completed for inspiration_id={inspiration_id}. "
        f"Translated {completed}/{total_languages} languages."
    )

    # Notify admin: published
    await _notify_admin(task, inspiration_id, admin_user_id, "published")


async def _translate_inspiration_texts_batch(
    task: BaseServiceTask,
    phrase: str,
    assistant_response: str,
    target_languages: List[str],
) -> Dict[str, Dict[str, str]]:
    """
    Translate phrase and assistant_response into multiple languages in one Gemini call.

    Returns a dict mapping language code → {"phrase": ..., "assistant_response": ...}
    """
    # Build properties dynamically for the tool schema
    properties: Dict[str, Any] = {}
    for lang in target_languages:
        properties[lang] = {
            "type": "object",
            "properties": {
                "phrase": {"type": "string"},
                "assistant_response": {"type": "string"},
            },
            "required": ["phrase", "assistant_response"],
        }

    translation_tool = {
        "type": "function",
        "function": {
            "name": "return_translations",
            "description": (
                "Return translations of the phrase and assistant_response into all requested languages."
            ),
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": target_languages,
            },
        },
    }

    messages = [
        {
            "role": "system",
            "content": (
                "You are a professional translator. Translate the given texts into all requested languages. "
                "The 'phrase' is a short CTA for a Daily Inspiration banner (max 10 words). "
                "The 'assistant_response' is a 1-2 sentence teaser. "
                "Preserve the tone, enthusiasm, and meaning. "
                "When a language has formal/informal 'you', use the friendly informal register "
                "(e.g. 'du' in German, 'tu' in French, 'tú' in Spanish)."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Translate these two English strings into all target languages.\n\n"
                f"phrase: {phrase}\n"
                f"assistant_response: {assistant_response}"
            ),
        },
    ]

    response = await invoke_google_ai_studio_chat_completions(
        task_id=f"default_inspiration_translate_{hash(phrase) % 10000}",
        model_id="gemini-3-flash-preview",
        messages=messages,
        secrets_manager=task.secrets_manager,
        tools=[translation_tool],
        tool_choice="required",
        temperature=0.3,
        max_tokens=4000,
        stream=False,
    )

    if not response.success or not response.tool_calls_made:
        err = getattr(response, "error_message", "No tool call")
        logger.error(f"[DefaultInspiration][translate] Gemini batch failed for {target_languages}: {err}")
        # Return English fallbacks
        return {
            lang: {"phrase": phrase, "assistant_response": assistant_response}
            for lang in target_languages
        }

    result: Dict[str, Dict[str, str]] = {}
    for call in response.tool_calls_made:
        if call.function_name == "return_translations":
            parsed = call.function_arguments_parsed or {}
            for lang in target_languages:
                lang_data = parsed.get(lang, {})
                result[lang] = {
                    "phrase": lang_data.get("phrase") or phrase,
                    "assistant_response": lang_data.get("assistant_response") or assistant_response,
                }
            break

    # Fill any missing languages with English fallback
    for lang in target_languages:
        if lang not in result:
            result[lang] = {"phrase": phrase, "assistant_response": assistant_response}

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _notify_admin(
    task: BaseServiceTask,
    inspiration_id: str,
    admin_user_id: str,
    status: str,
) -> None:
    """Send a `default_inspiration_updated` WebSocket event to the admin."""
    try:
        await task.publish_websocket_event(
            user_id_hash=admin_user_id,
            event="default_inspiration_updated",
            payload={
                "user_id": admin_user_id,
                "inspiration_id": inspiration_id,
                "status": status,
            },
        )
    except Exception as e:
        logger.warning(
            f"[DefaultInspiration] Failed to send WS update event for {inspiration_id}: {e}"
        )


async def _send_progress(
    task: BaseServiceTask,
    inspiration_id: str,
    admin_user_id: str,
    completed: int,
    total: int,
    current_language: str,
) -> None:
    """Send a `default_inspiration_progress` WebSocket event to the admin."""
    try:
        progress_pct = round((completed / total) * 100) if total else 100
        await task.publish_websocket_event(
            user_id_hash=admin_user_id,
            event="default_inspiration_progress",
            payload={
                "user_id": admin_user_id,
                "inspiration_id": inspiration_id,
                "stage": "translating",
                "progress_percentage": progress_pct,
                "current_language": current_language,
                "message": f"Translated {completed}/{total} languages",
            },
        )
    except Exception as e:
        logger.warning(
            f"[DefaultInspiration] Failed to send progress event for {inspiration_id}: {e}"
        )


async def _update_status_and_notify(
    task: BaseServiceTask,
    inspiration_id: str,
    status: str,
    admin_user_id: str,
) -> None:
    """Update status and notify admin via WebSocket (used in error paths)."""
    try:
        await task.initialize_services()
        await task._directus_service.suggested_inspiration.update_status(
            inspiration_id, status
        )
    except Exception as e:
        logger.error(
            f"[DefaultInspiration] Failed to update status={status} for {inspiration_id}: {e}"
        )
    await _notify_admin(task, inspiration_id, admin_user_id, status)


async def _invalidate_public_cache(task: BaseServiceTask) -> None:
    """
    Invalidate all per-language Redis cache entries for the public default-inspirations endpoint.
    Cache keys follow the pattern: public:default_inspirations:{lang}
    """
    try:
        cache = task._cache_service
        if not cache:
            return
        client = await cache.client
        if not client:
            return

        # Scan for all cache keys matching the public inspirations pattern
        pattern = f"{_PUBLIC_CACHE_KEY_PREFIX}*"
        cursor = 0
        deleted = 0
        while True:
            cursor, keys = await client.scan(cursor, match=pattern, count=50)
            for key in keys:
                await client.delete(key)
                deleted += 1
            if cursor == 0:
                break

        logger.info(
            f"[DefaultInspiration] Invalidated {deleted} public cache entries "
            f"(pattern={pattern})"
        )
    except Exception as e:
        logger.warning(
            f"[DefaultInspiration] Failed to invalidate public cache: {e}"
        )
