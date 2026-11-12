# backend/apps/videos/skills/generate_skill.py
#
# videos.generate skill: validate the call and queue it on the videos worker.
#
# One skill makes every video: per request either a generative clip (Gemini Omni / H3)
# or a composed, code-rendered video (decided by the request's mode or by the
# routing model in the task). ``images`` holds exact embed_refs of the
# conversation: pictures, single search results (their picture when they have
# one, always their text) and whole searches (the search's own embed_ref, which
# the worker expands to its results). They resolve through the file index
# (earlier results and searches also through their indexed search parent); a
# reference that is not in the conversation fails explicitly and nothing is
# queued or charged. The worker reads every input server-side, so no picture
# or result text travels through the broker.

import hashlib
import logging
import uuid
from typing import Any, Dict, List, Mapping, Optional

from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill
from backend.apps.videos.generate_request import (
    DEFAULT_MODEL,
    DEFAULT_RESOLUTION,
    H3_MODEL,
    MODE_GENERATIVE,
    VALID_MODELS,
    GenerateRequestError,
    check_external_request,
    generative_model,
    parse_generate_request,
    task_arguments,
)
from backend.shared.python_utils.app_skill_helpers import execute_skill_via_celery
from backend.shared.python_utils.media_generation_safety import validate_media_generation_request

logger = logging.getLogger(__name__)

__all__ = ["DEFAULT_MODEL", "H3_MODEL", "VALID_MODELS", "GenerateSkill", "VideoGenerationRequest",
           "VideoGenerationRequestItem", "VideoGenerationResponse"]

NOT_IN_CHAT_MESSAGE = (
    "is not a picture, search result or video in this conversation. Pass the exact embed_ref of an uploaded or "
    "generated image, a vector graphic, a search result (image, web, news or video search, with or without a "
    "picture), a whole search, or (as source_video) a video made by videos.generate."
)


class VideoGenerationRequestItem(BaseModel):
    """A single video request (the REST/OpenAPI shape; the chat tool schema lives in app.yml)."""

    id: Optional[Any] = Field(default=None)
    instructions: Optional[str] = Field(default=None, description="Natural-language description of the video.")
    prompt: Optional[str] = Field(default=None, description="Former name of instructions.")
    mode: str = Field(default="auto", description="auto, generative or composed. REST supports generative only.")
    aspect_ratio: str = Field(default="16:9", description="16:9 or 9:16 (generative); composed also 1:1.")
    duration_seconds: Optional[int] = Field(default=None, ge=2, le=60,
                                            description="Gemini Omni clips last 3 to 15 seconds (default 8).")
    resolution: Optional[str] = Field(default=None,
                                      description="Gemini Omni: 360p, 720p, 1080p or 4k (default 720p). H3: 480p.")
    input_embed_ids: List[str] = Field(default_factory=list, max_length=1,
                                       description="Optional first-frame image embed UUID (chat context only).")
    seed: Optional[int] = Field(default=None)
    model: Optional[str] = Field(default=None)


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


def _error(message: str, code: str) -> Dict[str, Any]:
    return {"error": message, "error_code": code}


class GenerateSkill(BaseSkill):
    """Make short videos: generative clips (Gemini Omni / H3) or composed, code-rendered videos."""

    async def _resolve_earlier_results(self, refs: List[str], file_path_index: Mapping[str, str],
                                       kwargs: Mapping[str, Any]) -> Dict[str, str]:
        """Exact refs of search results from earlier turns (only their search parent is indexed)."""
        user_id = kwargs.get("user_id")
        vault_key_id = kwargs.get("user_vault_key_id")
        if not refs or not user_id or not vault_key_id or not file_path_index:
            return {}
        from backend.core.api.app.services.cache import CacheService
        from backend.core.api.app.utils.encryption import EncryptionService
        from backend.shared.python_utils.result_pictures import resolve_result_refs, vault_content_reader

        cache = CacheService()
        reader = vault_content_reader(cache_service=cache, encryption_service=EncryptionService(cache_service=cache),
                                      user_vault_key_id=str(vault_key_id))
        return await resolve_result_refs(refs, file_path_index, read_content=reader,
                                         owner_hash=hashlib.sha256(str(user_id).encode("utf-8")).hexdigest())

    async def execute(self, requests: List[Dict[str, Any]], **kwargs: Any) -> Dict[str, Any]:
        if not self.celery_producer:
            logger.error("Celery producer not available in videos.GenerateSkill")
            return _error("Video generation service temporarily unavailable", "unavailable")
        if not isinstance(requests, list) or not requests:
            return _error("requests must list at least one video", "invalid_request")

        batch_decision = validate_media_generation_request(media_type="video", prompt="", request_count=len(requests))
        if not batch_decision.allowed:
            return batch_decision.to_rejection_payload()

        external_request = bool(kwargs.get("external_request"))
        file_path_index: Mapping[str, str] = kwargs.get("file_path_index") or {}
        parsed = []
        for item in requests:
            try:
                request = parse_generate_request(item)
                if external_request:
                    check_external_request(request)
            except GenerateRequestError as exc:
                return _error(str(exc), exc.code)
            decision = validate_media_generation_request(media_type="video", prompt=request.instructions,
                                                         request_count=1)
            if not decision.allowed:
                logger.warning("Video generation request rejected by media safety gate: %s", decision.category)
                return decision.to_rejection_payload()
            parsed.append(request)

        missing = [ref for request in parsed
                   for ref in (*request.images, *((request.source_video,) if request.source_video else ()))
                   if ref not in file_path_index]
        earlier = await self._resolve_earlier_results(missing, file_path_index, kwargs) if missing else {}
        index = {**earlier, **file_path_index}

        placeholder_embed_ids = kwargs.get("placeholder_embed_ids") or []
        parent_embed_id = next((value for value in placeholder_embed_ids if value), str(uuid.uuid4()))
        prepared_requests: List[Dict[str, Any]] = []
        for request in parsed:
            image_ids: List[str] = []
            for ref in request.images:
                embed_id = index.get(ref)
                if not embed_id:
                    return _error(f"'{ref}' {NOT_IN_CHAT_MESSAGE}", "invalid_input")
                image_ids.append(embed_id)
            source_video_id = None
            if request.source_video:
                source_video_id = index.get(request.source_video)
                if not source_video_id:
                    return _error(f"'{request.source_video}' {NOT_IN_CHAT_MESSAGE}", "invalid_input")
            is_generative = external_request or request.mode == MODE_GENERATIVE
            model = generative_model(request)
            task_args = {
                **task_arguments(request),
                # REST offers text-only generative video only; it is never routed.
                "mode": MODE_GENERATIVE if external_request else request.mode,
                "model": model if is_generative else request.model,
                "duration_seconds": 5 if is_generative and model == H3_MODEL else request.duration_seconds,
                "resolution": ("480p" if model == H3_MODEL else request.resolution or DEFAULT_RESOLUTION)
                if is_generative
                else request.resolution,
                "image_embed_ids": image_ids,
                "input_embed_ids": image_ids or list(request.first_frame_embed_ids),
                "source_video_embed_id": source_video_id,
                "user_id": kwargs.get("user_id"),
                "user_vault_key_id": kwargs.get("user_vault_key_id"),
                "api_key_hash": kwargs.get("api_key_hash"),
                "device_hash": kwargs.get("device_hash"),
                "chat_id": self._current_chat_id,
                "message_id": self._current_message_id,
                "external_request": external_request,
                **({"team_id": kwargs["team_id"]} if kwargs.get("team_id") else {}),
                "app_id": self.app_id,
                "skill_id": self.skill_id,
                "full_model_reference": (f"fal/{model}" if model == H3_MODEL else f"google/{model}")
                if is_generative else None,
                "embed_id": parent_embed_id,
            }
            prepared_requests.append(task_args)

        # Dispatch failures (including RequiredRecoveryOutputError for a turn without
        # output admission) propagate to the skill executor unchanged.
        task_id = await execute_skill_via_celery(
            app_id=self.app_id, skill_id=self.skill_id,
            arguments={**prepared_requests[0], "embed_id": parent_embed_id,
                       **({"same_turn_batch_id": kwargs["same_turn_batch_id"]} if kwargs.get("same_turn_batch_id")
                          else {}),
                       "requests": prepared_requests},
            celery_producer=self.celery_producer,
        )
        return {"task_id": task_id, "embed_id": parent_embed_id, "status": "processing"}
