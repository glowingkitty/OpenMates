# backend/apps/social_media/tasks/search_task.py
#
# Celery task for Social Media search.
# Runs topic search across selected providers in the background and updates the
# processing parent embed plus one child embed per returned public post.
#
# Architecture: docs/architecture/apps/social-media.md

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Dict

from backend.apps.ai.processing.external_result_sanitizer import sanitize_long_text_fields_in_payload
from backend.apps.ai.tasks.async_skill_continuation import dispatch_async_skill_continuation
from backend.apps.social_media.search_collection import SearchResponseItem, collect_search_results
from backend.apps.social_media.tasks.get_posts_task import (
    WEBSHARE_UNAVAILABLE_WARNING,
    _annotate_post_embed_refs,
    _get_webshare_proxy_url,
    _send_embed,
)
from backend.apps.social_media.result_payload import build_social_media_task_result
from backend.core.api.app.services.embed_service import EmbedService
from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.core.api.app.tasks.celery_config import app

logger = logging.getLogger(__name__)


@app.task(
    bind=True,
    name="apps.social_media.tasks.skill_search",
    base=BaseServiceTask,
    queue="app_social_media",
    soft_time_limit=300,
    time_limit=360,
)
def search_task(self, app_id: str, skill_id: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Run social media topic search asynchronously."""
    return asyncio.run(_async_search(self, app_id, skill_id, arguments))


async def _async_search(task: BaseServiceTask, app_id: str, skill_id: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    task_id = task.request.id
    embed_id = arguments.get("embed_id")
    user_id = arguments.get("user_id")
    chat_id = arguments.get("chat_id")
    message_id = arguments.get("message_id")
    external_request = bool(arguments.get("external_request"))
    log_prefix = f"[social_media.search] [task:{task_id[:8]}] [embed:{str(embed_id)[:8]}]"

    try:
        await task.initialize_services()
        user_vault_key_id = arguments.get("user_vault_key_id")
        chat_embed_mode = bool(embed_id and user_id and chat_id and message_id and user_vault_key_id and not external_request)
        if not external_request and not chat_embed_mode:
            raise ValueError("Missing required task context for social media search embed update")

        started = datetime.now(timezone.utc)
        reddit_proxy_url = await _get_webshare_proxy_url(task)
        results = await collect_search_results(
            arguments.get("requests") or [],
            secrets_manager=task._secrets_manager,
            reddit_proxy_url=reddit_proxy_url,
            reddit_proxy_warning=None if reddit_proxy_url else WEBSHARE_UNAVAILABLE_WARNING,
        )
        elapsed_seconds = (datetime.now(timezone.utc) - started).total_seconds()
        total_requests = sum(item.request_count for item in results)
        post_results = _flatten_search_results(results)
        post_results = await sanitize_long_text_fields_in_payload(
            payload=post_results,
            task_id=f"social_search_{task_id}",
            secrets_manager=task._secrets_manager,
            cache_service=task._cache_service,
            min_chars=40,
            max_parallel=3,
            always_sanitize_field_names={"title", "body"},
        )
        post_results = await _annotate_post_embed_refs(task._cache_service, app_id, skill_id, post_results, log_prefix)
        providers = sorted({item.provider for item in results if item.provider})

        request_metadata = {
            "query": _request_label(results),
            "provider": ", ".join(providers) if providers else "Social Media",
            "request_count": total_requests,
            "elapsed_seconds": round(elapsed_seconds, 2),
        }
        result_payload = build_social_media_task_result(
            app_id=app_id,
            skill_id=skill_id,
            result_type="social_search",
            status="finished",
            results=results,
            post_results=post_results,
            request_metadata=request_metadata,
            elapsed_seconds=elapsed_seconds,
            task_id=task_id,
            embed_id=embed_id if chat_embed_mode else None,
        )

        if not chat_embed_mode:
            logger.info("%s Completed REST/CLI task with %s result groups and %s provider requests", log_prefix, len(results), total_requests)
            return result_payload

        embed_service = EmbedService(
            cache_service=task._cache_service,
            directus_service=task._directus_service,
            encryption_service=task._encryption_service,
        )
        await embed_service.update_embed_with_results(
            embed_id=embed_id,
            app_id=app_id,
            skill_id=skill_id,
            results=post_results,
            chat_id=chat_id,
            message_id=message_id,
            user_id=user_id,
            user_id_hash=hashlib.sha256(user_id.encode()).hexdigest(),
            user_vault_key_id=user_vault_key_id,
            task_id=task_id,
            log_prefix=log_prefix,
            request_metadata=request_metadata,
        )
        continuation_task_id = await dispatch_async_skill_continuation(
            cache_service=task._cache_service,
            async_task_id=task_id,
            completed_results=post_results,
            request_metadata=request_metadata,
        )
        logger.info("%s Completed with %s result groups and %s provider requests", log_prefix, len(results), total_requests)
        result_payload["continuation_task_id"] = continuation_task_id
        return result_payload
    except Exception as exc:
        logger.error("%s Failed: %s", log_prefix, exc, exc_info=True)
        if embed_id and user_id and chat_id and message_id:
            try:
                await task.initialize_services()
                await _send_embed(
                    task,
                    embed_id,
                    chat_id,
                    message_id,
                    user_id,
                    {
                        "app_id": app_id,
                        "skill_id": skill_id,
                        "type": "social_search",
                        "status": "error",
                        "error": "Social media search failed. Please try again.",
                    },
                    "error",
                    f"{log_prefix} [ERROR_EMBED]",
                )
            except Exception as embed_exc:
                logger.error("%s Failed to send error embed: %s", log_prefix, embed_exc, exc_info=True)
        raise
    finally:
        await task.cleanup_services()


def _flatten_search_results(results: list[SearchResponseItem]) -> list[dict[str, Any]]:
    """Convert provider result groups into one child embed payload per post."""
    posts: list[dict[str, Any]] = []
    for group in results:
        group_errors = list(group.errors)
        group_warnings = list(group.warnings)
        for post in group.posts:
            payload = post.model_dump(mode="json")
            payload.setdefault("platform", group.platform)
            payload.setdefault("page", group.query)
            payload["provider"] = group.provider
            payload["query"] = group.query
            if group_errors:
                payload["errors"] = group_errors
            if group_warnings:
                payload["warnings"] = group_warnings
            posts.append(payload)
    return posts


def _request_label(results: list[SearchResponseItem]) -> str:
    labels = [item.query for item in results if item.query]
    if not labels:
        return "Social media search"
    unique_labels = list(dict.fromkeys(labels))
    if len(unique_labels) == 1:
        return unique_labels[0]
    return f"{len(unique_labels)} social media searches"
