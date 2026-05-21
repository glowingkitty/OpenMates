# backend/apps/social_media/skills/get_posts.py
#
# Social Media Get Posts skill.
# Fetches normalized social posts from supported platforms and optionally includes
# comments. It supports no-key providers first so the daily social listening
# workflow can run without platform contracts or user credentials.
#
# Architecture: docs/architecture/apps/social-media.md

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from backend.apps.base_skill import BaseSkill
from backend.apps.ai.processing.celery_helpers import execute_skill_via_celery
from backend.apps.social_media.collection import GetPostsRequestItem, GetPostsResponse

logger = logging.getLogger(__name__)


class GetPostsSkill(BaseSkill):
    """Fetch normalized posts and comments from supported social platforms."""

    def __init__(
        self,
        app,
        app_id: str,
        skill_id: str,
        skill_name: str,
        skill_description: str,
        stage: str = "development",
        full_model_reference: Optional[str] = None,
        pricing_config: Optional[dict[str, Any]] = None,
        **kwargs,
    ):
        super().__init__(
            app=app,
            app_id=app_id,
            skill_id=skill_id,
            skill_name=skill_name,
            skill_description=skill_description,
            stage=stage,
            full_model_reference=full_model_reference,
            pricing_config=pricing_config,
            celery_producer=kwargs.get("celery_producer"),
            skill_operational_defaults=kwargs.get("skill_operational_defaults"),
        )

    async def execute(
        self,
        requests: list[dict[str, Any]],
        user_id: Optional[str] = None,
        cache_service=None,
        **kwargs,
    ) -> GetPostsResponse:
        """Dispatch social post collection to the app worker."""
        if not self.celery_producer:
            logger.error("Celery producer not available in GetPostsSkill")
            return GetPostsResponse(error="Social media collection service temporarily unavailable")

        try:
            request_items = [GetPostsRequestItem(**item).model_dump(mode="json") for item in requests]
            placeholder_embed_ids = kwargs.get("placeholder_embed_ids") or []
            task_ids: list[str] = []
            embed_ids: list[str] = []

            for index, request_item in enumerate(request_items):
                embed_id = placeholder_embed_ids[index] if index < len(placeholder_embed_ids) else str(uuid.uuid4())
                task_args = {
                    "requests": [request_item],
                    "user_id": user_id,
                    "chat_id": self._current_chat_id,
                    "message_id": self._current_message_id,
                    "app_id": self.app_id,
                    "skill_id": self.skill_id,
                    "embed_id": embed_id,
                    "user_vault_key_id": kwargs.get("user_vault_key_id"),
                    "external_request": kwargs.get("external_request", False),
                }
                task_id = await execute_skill_via_celery(
                    app_id=self.app_id,
                    skill_id=self.skill_id,
                    arguments=task_args,
                    celery_producer=self.celery_producer,
                )
                task_ids.append(task_id)
                embed_ids.append(embed_id)
                logger.info("Dispatched social media get-posts task %s (embed: %s)", task_id, embed_id)

            if not task_ids:
                return GetPostsResponse(error="No social media requests provided")

            if len(task_ids) == 1:
                return GetPostsResponse(task_id=task_ids[0], embed_id=embed_ids[0], status="processing")
            return GetPostsResponse(task_ids=task_ids, embed_ids=embed_ids, status="processing")
        except Exception as exc:
            logger.error("GetPostsSkill error: %s", exc, exc_info=True)
            return GetPostsResponse(error=str(exc))
