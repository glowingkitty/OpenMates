# backend/apps/videos/skills/generate_skill.py
#
# Video generation skill implementation.
# Dispatches long-running video generation to the videos Celery worker and
# returns processing embed IDs immediately for chat and REST clients.

import logging
import uuid
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from backend.shared.python_utils.app_skill_helpers import execute_skill_via_celery
from backend.apps.base_skill import BaseSkill
from backend.shared.python_utils.media_generation_safety import validate_media_generation_request

logger = logging.getLogger(__name__)

H3_MODEL = "minimax/h3-max-turbo/image-to-video"
DEFAULT_MODEL = "veo-3.1-generate-preview"
VALID_MODELS = {H3_MODEL, "veo-3.1-generate-preview", "veo-3.1-fast-generate-preview", "veo-3.0-generate-001"}


class VideoGenerationRequestItem(BaseModel):
    """A single video generation request."""

    id: Optional[Any] = Field(default=None)
    prompt: str = Field(description="Text description of the video to generate.")
    aspect_ratio: str = Field(default="16:9", description="Video aspect ratio: 16:9 or 9:16.")
    duration_seconds: int = Field(default=8, ge=4, le=8)
    resolution: str = Field(default="720p", description="Veo: 720p, 1080p, or 4k. H3: fixed 480p.")
    input_embed_ids: List[str] = Field(default_factory=list, max_length=1, description="Optional first-frame image embed UUID; H3 only.")
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
    """Generate short videos with Veo or first-frame H3 Max Turbo."""

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
        prepared_requests: List[Dict[str, Any]] = []
        parent_embed_id = placeholder_embed_ids[0] if placeholder_embed_ids else str(uuid.uuid4())

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

            embed_id = parent_embed_id
            model = str(req.get("model") or DEFAULT_MODEL)
            if model not in VALID_MODELS:
                model = DEFAULT_MODEL

            input_embed_ids = req.get("input_embed_ids") or []
            if not isinstance(input_embed_ids, list) or len(input_embed_ids) > 1:
                return {"error": "Provide at most one first-frame input_embed_ids image"}
            try:
                input_embed_ids = [str(uuid.UUID(value)) for value in input_embed_ids]
            except (ValueError, TypeError, AttributeError):
                return {"error": "First-frame input_embed_ids must contain image embed UUIDs"}
            if model == H3_MODEL and kwargs.get("external_request"):
                return {"error": "H3 video generation is available in authenticated chats and calls; REST generation currently supports Veo only"}
            if input_embed_ids and model != H3_MODEL:
                return {"error": "First-frame input_embed_ids currently require the H3 video model"}

            task_args = {
                "prompt": prompt,
                "aspect_ratio": req.get("aspect_ratio", "16:9"),
                "duration_seconds": 5 if model == H3_MODEL else int(req.get("duration_seconds") or 8),
                "resolution": "480p" if model == H3_MODEL else req.get("resolution", "720p"),
                "seed": req.get("seed"),
                "model": model,
                "user_id": user_id,
                "chat_id": self._current_chat_id,
                "message_id": self._current_message_id,
                "external_request": kwargs.get("external_request", False),
                **({"team_id": kwargs["team_id"]} if kwargs.get("team_id") else {}),
                "app_id": self.app_id,
                "skill_id": self.skill_id,
                "full_model_reference": f"fal/{model}" if model == H3_MODEL else f"google/{model}",
                "input_embed_ids": input_embed_ids,
                "embed_id": embed_id,
            }
            prepared_requests.append(task_args)

        if not prepared_requests:
            return {"error": "No valid video generation prompts provided"}
        try:
            task_id = await execute_skill_via_celery(
                app_id=self.app_id, skill_id=self.skill_id,
                arguments={**prepared_requests[0], "embed_id": parent_embed_id,
                           **({"same_turn_batch_id": kwargs["same_turn_batch_id"]} if kwargs.get("same_turn_batch_id") else {}),
                           "requests": prepared_requests},
                celery_producer=self.celery_producer,
            )
        except Exception as exc:
            logger.error("Failed to dispatch video generation batch: %s", exc, exc_info=True)
            return {"error": f"Failed to start video generation: {exc}"}
        return {"task_id": task_id, "embed_id": parent_embed_id, "status": "processing"}
