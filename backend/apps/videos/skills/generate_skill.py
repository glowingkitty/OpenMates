# backend/apps/videos/skills/generate_skill.py
#
# Video generation skill implementation.
# Dispatches long-running Google Veo generation to the videos Celery worker and
# returns processing embed IDs immediately for chat and REST clients.

import logging
import uuid
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from backend.shared.python_utils.app_skill_helpers import execute_skill_via_celery
from backend.apps.base_skill import BaseSkill
from backend.shared.python_utils.media_generation_safety import validate_media_generation_request

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "veo-3.1-generate-preview"
VALID_MODELS = {"veo-3.1-generate-preview", "veo-3.1-fast-generate-preview", "veo-3.0-generate-001"}


class VideoGenerationRequestItem(BaseModel):
    """A single video generation request."""

    id: Optional[Any] = Field(default=None)
    prompt: str = Field(description="Text description of the video to generate.")
    aspect_ratio: str = Field(default="16:9", description="Video aspect ratio: 16:9 or 9:16.")
    duration_seconds: int = Field(default=8, ge=4, le=8)
    resolution: str = Field(default="720p", description="720p, 1080p, or 4k.")
    seed: Optional[int] = Field(default=None)
    model: str = Field(default=DEFAULT_MODEL)


class VideoGenerationRequest(BaseModel):
    """Request model for video generation."""

    requests: List[VideoGenerationRequestItem]


class VideoGenerationResponse(BaseModel):
    """Response model for asynchronous video generation."""

    task_id: Optional[str] = None
    embed_id: Optional[str] = None
    task_ids: Optional[List[str]] = None
    embed_ids: Optional[List[str]] = None
    status: str = "processing"
    error: Optional[str] = None


class GenerateSkill(BaseSkill):
    """Generate short videos from text prompts using Google Veo."""

    async def execute(self, requests: List[Dict[str, Any]], **kwargs: Any) -> Dict[str, Any]:
        if not self.celery_producer:
            logger.error("Celery producer not available in videos.GenerateSkill")
            return {"error": "Video generation service temporarily unavailable"}

        batch_decision = validate_media_generation_request(
            media_type="video",
            prompt="",
            request_count=len(requests),
        )
        if not batch_decision.allowed:
            return batch_decision.to_rejection_payload()

        user_id = kwargs.get("user_id")
        placeholder_embed_ids = kwargs.get("placeholder_embed_ids", [])
        results: List[Dict[str, str]] = []

        for idx, req in enumerate(requests):
            prompt = str(req.get("prompt") or "").strip()
            if not prompt:
                logger.warning("Skipping video generation request without prompt: %s", req)
                continue

            prompt_decision = validate_media_generation_request(
                media_type="video",
                prompt=prompt,
                request_count=1,
            )
            if not prompt_decision.allowed:
                logger.warning(
                    "Video generation request rejected by media safety gate: %s",
                    prompt_decision.category,
                )
                return prompt_decision.to_rejection_payload()

            embed_id = (
                placeholder_embed_ids[idx]
                if idx < len(placeholder_embed_ids) and placeholder_embed_ids[idx]
                else str(uuid.uuid4())
            )
            model = str(req.get("model") or DEFAULT_MODEL)
            if model not in VALID_MODELS:
                model = DEFAULT_MODEL

            task_args = {
                "prompt": prompt,
                "aspect_ratio": req.get("aspect_ratio", "16:9"),
                "duration_seconds": int(req.get("duration_seconds") or 8),
                "resolution": req.get("resolution", "720p"),
                "seed": req.get("seed"),
                "model": model,
                "user_id": user_id,
                "chat_id": self._current_chat_id,
                "message_id": self._current_message_id,
                "external_request": kwargs.get("external_request", False),
                "app_id": self.app_id,
                "skill_id": self.skill_id,
                "full_model_reference": f"google/{model}",
                "embed_id": embed_id,
            }
            try:
                task_id = await execute_skill_via_celery(
                    app_id=self.app_id,
                    skill_id=self.skill_id,
                    arguments=task_args,
                    celery_producer=self.celery_producer,
                )
                results.append({"task_id": task_id, "embed_id": embed_id})
            except Exception as exc:
                logger.error("Failed to dispatch video generation task: %s", exc, exc_info=True)
                if not results:
                    return {"error": f"Failed to start video generation: {exc}"}

        if not results:
            return {"error": "No valid video generation prompts provided"}
        if len(results) == 1:
            return {"task_id": results[0]["task_id"], "embed_id": results[0]["embed_id"], "status": "processing"}
        return {
            "task_ids": [item["task_id"] for item in results],
            "embed_ids": [item["embed_id"] for item in results],
            "status": "processing",
        }
