# backend/apps/music/skills/generate_skill.py
#
# Music generation skill implementation.
# Dispatches long-running Google Lyria generation to the music Celery worker
# and returns processing embed IDs immediately for WebSocket/REST clients.

import logging
import uuid
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from backend.apps.ai.processing.celery_helpers import execute_skill_via_celery
from backend.apps.base_skill import BaseSkill

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "lyria-3-pro-preview"
VALID_MODELS = {"lyria-3-pro-preview", "lyria-3-clip-preview", "lyria-002"}
VALID_MODES = {"song", "instrumental", "background", "loop", "jingle"}


class MusicGenerationRequestItem(BaseModel):
    """A single music generation request."""

    id: Optional[Any] = Field(default=None)
    prompt: str = Field(description="Text description of the music to generate.")
    mode: str = Field(default="background", description="song, instrumental, background, loop, or jingle.")
    lyrics: Optional[str] = Field(default=None, description="Optional lyrics for vocal/song generation.")
    style: Optional[str] = Field(default=None, description="Optional genre, mood, or instrumentation guidance.")
    duration_seconds: int = Field(default=30, ge=3, le=184)
    negative_prompt: Optional[str] = Field(default=None)
    seed: Optional[int] = Field(default=None)
    model: str = Field(default=DEFAULT_MODEL)


class MusicGenerationRequest(BaseModel):
    """Request model for music generation."""

    requests: List[MusicGenerationRequestItem]


class MusicGenerationResponse(BaseModel):
    """Response model for asynchronous music generation."""

    task_id: Optional[str] = None
    embed_id: Optional[str] = None
    task_ids: Optional[List[str]] = None
    embed_ids: Optional[List[str]] = None
    status: str = "processing"
    error: Optional[str] = None


class GenerateSkill(BaseSkill):
    """Generate music tracks from text prompts using Google Lyria."""

    async def execute(
        self,
        requests: List[Dict[str, Any]],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        if not self.celery_producer:
            logger.error("Celery producer not available in music.GenerateSkill")
            return {"error": "Music generation service temporarily unavailable"}

        user_id = kwargs.get("user_id")
        placeholder_embed_ids = kwargs.get("placeholder_embed_ids", [])
        results: List[Dict[str, str]] = []

        for idx, req in enumerate(requests):
            prompt = str(req.get("prompt") or "").strip()
            if not prompt:
                logger.warning("Skipping music generation request without prompt: %s", req)
                continue

            embed_id = (
                placeholder_embed_ids[idx]
                if idx < len(placeholder_embed_ids) and placeholder_embed_ids[idx]
                else str(uuid.uuid4())
            )

            mode = str(req.get("mode") or "background").lower()
            if mode not in VALID_MODES:
                mode = "background"

            model = str(req.get("model") or DEFAULT_MODEL)
            if model not in VALID_MODELS:
                model = DEFAULT_MODEL

            duration_seconds = int(req.get("duration_seconds") or 30)
            duration_seconds = max(3, min(duration_seconds, 184))

            task_args = {
                "prompt": prompt,
                "mode": mode,
                "lyrics": req.get("lyrics"),
                "style": req.get("style"),
                "duration_seconds": duration_seconds,
                "negative_prompt": req.get("negative_prompt"),
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
                logger.info("Dispatched music generation task %s (embed=%s, model=%s)", task_id, embed_id, model)
            except Exception as exc:
                logger.error("Failed to dispatch music generation task: %s", exc, exc_info=True)
                if not results:
                    return {"error": f"Failed to start music generation: {exc}"}

        if not results:
            return {"error": "No valid music generation prompts provided"}

        if len(results) == 1:
            return {"task_id": results[0]["task_id"], "embed_id": results[0]["embed_id"], "status": "processing"}
        return {
            "task_ids": [item["task_id"] for item in results],
            "embed_ids": [item["embed_id"] for item in results],
            "status": "processing",
        }
