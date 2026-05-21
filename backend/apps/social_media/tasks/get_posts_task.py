# backend/apps/social_media/tasks/get_posts_task.py
#
# Celery task for Social Media get-posts.
# Collects posts/comments in the background and updates the processing embed that
# the AI stream already placed in chat. This keeps broad Reddit/Bluesky collection
# from blocking the assistant response loop.
#
# Architecture: docs/architecture/apps/social-media.md

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict

from toon_format import encode as toon_encode

from backend.apps.ai.processing.external_result_sanitizer import sanitize_long_text_fields_in_payload
from backend.apps.ai.tasks.async_skill_continuation import dispatch_async_skill_continuation
from backend.apps.social_media.collection import GetPostsResponseItem, collect_posts
from backend.core.api.app.services.embed_service import EmbedService
from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.core.api.app.tasks.celery_config import app

logger = logging.getLogger(__name__)

WEBSHARE_SECRET_PATH = "kv/data/providers/webshare"
WEBSHARE_USERNAME_KEY = "proxy_username"
WEBSHARE_PASSWORD_KEY = "proxy_password"
WEBSHARE_USERNAME_ENV = "SECRET__WEBSHARE__PROXY_USERNAME"
WEBSHARE_PASSWORD_ENV = "SECRET__WEBSHARE__PROXY_PASSWORD"
WEBSHARE_PROXY_HOST = "p.webshare.io"
WEBSHARE_PROXY_PORT = 80
WEBSHARE_UNAVAILABLE_WARNING = "Webshare proxy credentials are unavailable; Reddit JSON request was not attempted."


@app.task(
    bind=True,
    name="apps.social_media.tasks.skill_get-posts",
    base=BaseServiceTask,
    queue="app_social_media",
    soft_time_limit=300,
    time_limit=360,
)
def get_posts_task(self, app_id: str, skill_id: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Run social media post collection asynchronously."""
    return asyncio.run(_async_get_posts(self, app_id, skill_id, arguments))


async def _async_get_posts(task: BaseServiceTask, app_id: str, skill_id: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    task_id = task.request.id
    embed_id = arguments.get("embed_id")
    user_id = arguments.get("user_id")
    chat_id = arguments.get("chat_id")
    message_id = arguments.get("message_id")
    log_prefix = f"[social_media.get-posts] [task:{task_id[:8]}] [embed:{str(embed_id)[:8]}]"

    try:
        await task.initialize_services()
        if not (embed_id and user_id and chat_id and message_id):
            raise ValueError("Missing required task context for social media embed update")
        user_vault_key_id = arguments.get("user_vault_key_id")
        if not user_vault_key_id:
            raise ValueError("Missing user_vault_key_id for social media embed encryption")

        started = datetime.now(timezone.utc)
        reddit_proxy_url = await _get_webshare_proxy_url(task)
        results = await collect_posts(
            arguments.get("requests") or [],
            reddit_proxy_url=reddit_proxy_url,
            reddit_proxy_warning=None if reddit_proxy_url else WEBSHARE_UNAVAILABLE_WARNING,
        )
        elapsed_seconds = (datetime.now(timezone.utc) - started).total_seconds()
        total_requests = sum(item.request_count for item in results)
        post_results = _flatten_post_results(results)
        post_results = await sanitize_long_text_fields_in_payload(
            payload=post_results,
            task_id=f"social_posts_{task_id}",
            secrets_manager=task._secrets_manager,
            cache_service=task._cache_service,
            min_chars=40,
            max_parallel=3,
            always_sanitize_field_names={"title", "body"},
        )
        providers = sorted({item.provider for item in results if item.provider})

        embed_service = EmbedService(
            cache_service=task._cache_service,
            directus_service=task._directus_service,
            encryption_service=task._encryption_service,
        )
        request_metadata = {
            "query": _request_label(results),
            "provider": ", ".join(providers) if providers else "Social Media",
            "request_count": total_requests,
            "elapsed_seconds": round(elapsed_seconds, 2),
        }
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
        return {
            "embed_id": embed_id,
            "type": "social_posts",
            "status": "finished",
            "result_count": len(results),
            "post_count": len(post_results),
            "request_count": total_requests,
            "continuation_task_id": continuation_task_id,
        }
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
                        "type": "social_posts",
                        "status": "error",
                        "error": "Social media collection failed. Please try again.",
                    },
                    "error",
                    f"{log_prefix} [ERROR_EMBED]",
                )
            except Exception as embed_exc:
                logger.error("%s Failed to send error embed: %s", log_prefix, embed_exc, exc_info=True)
        raise
    finally:
        await task.cleanup_services()


async def _send_embed(
    task: BaseServiceTask,
    embed_id: str,
    chat_id: str,
    message_id: str,
    user_id: str,
    content: dict[str, Any],
    status: str,
    log_prefix: str,
) -> None:
    now_ts = int(datetime.now(timezone.utc).timestamp())
    user_id_hash = hashlib.sha256(user_id.encode()).hexdigest()
    embed_service = EmbedService(
        cache_service=task._cache_service,
        directus_service=task._directus_service,
        encryption_service=task._encryption_service,
    )
    await embed_service.send_embed_data_to_client(
        embed_id=embed_id,
        embed_type="app_skill_use",
        content_toon=toon_encode(content),
        chat_id=chat_id,
        message_id=message_id,
        user_id=user_id,
        user_id_hash=user_id_hash,
        status=status,
        encryption_mode="client",
        created_at=now_ts,
        updated_at=now_ts,
        log_prefix=log_prefix,
        check_cache_status=False,
    )


def _flatten_post_results(results: list[GetPostsResponseItem]) -> list[dict[str, Any]]:
    """Convert provider result groups into one child embed payload per post."""
    posts: list[dict[str, Any]] = []
    for group in results:
        group_errors = list(group.errors)
        group_warnings = list(group.warnings)
        for post in group.posts:
            payload = post.model_dump(mode="json")
            payload.setdefault("platform", group.platform)
            payload.setdefault("page", group.page)
            payload["provider"] = group.provider
            if group_errors:
                payload["errors"] = group_errors
            if group_warnings:
                payload["warnings"] = group_warnings
            posts.append(payload)
    return posts


def _request_label(results: list[GetPostsResponseItem]) -> str:
    labels = [f"{item.platform}: {item.page}" for item in results if item.page]
    if not labels:
        return "Social media posts"
    if len(labels) == 1:
        return labels[0]
    return f"{len(labels)} social media sources"


async def _get_webshare_proxy_url(task: BaseServiceTask) -> str | None:
    username = await _get_webshare_secret(task, WEBSHARE_USERNAME_KEY, WEBSHARE_USERNAME_ENV)
    password = await _get_webshare_secret(task, WEBSHARE_PASSWORD_KEY, WEBSHARE_PASSWORD_ENV)
    if not username or not password:
        logger.warning("Webshare proxy credentials are unavailable for social media Reddit JSON collection")
        return None
    return f"http://{username}-rotate:{password}@{WEBSHARE_PROXY_HOST}:{WEBSHARE_PROXY_PORT}/"


async def _get_webshare_secret(task: BaseServiceTask, key: str, env_var: str) -> str | None:
    if task._secrets_manager:
        try:
            value = await task._secrets_manager.get_secret(
                secret_path=WEBSHARE_SECRET_PATH,
                secret_key=key,
            )
            if value and value.strip():
                return value.strip()
        except Exception as exc:
            logger.warning("Failed to retrieve Webshare secret '%s' from Vault: %s", key, exc)

    env_value = os.environ.get(env_var, "").strip()
    if env_value and env_value != "IMPORTED_TO_VAULT":
        return env_value
    return None
