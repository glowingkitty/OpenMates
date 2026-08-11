# backend/apps/audio/skills/generate_skill.py
#
# audio.generate app skill for short non-speech sound effects.
# This skill validates the OpenMates contract, applies deterministic generated
# media safety before provider use, dispatches ElevenLabs work asynchronously,
# and returns task/embed references without logging secrets or inline audio bytes.

from __future__ import annotations

import logging
import uuid
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.apps.base_skill import BaseSkill
from backend.shared.python_utils.app_skill_helpers import execute_skill_via_celery
from backend.shared.python_utils.media_generation_safety import validate_media_generation_request

logger = logging.getLogger(__name__)

DEFAULT_PROVIDER = "elevenlabs"
DEFAULT_MODEL = "eleven_text_to_sound_v2"
DEFAULT_OUTPUT_FORMAT = "mp3_44100_128"
VALID_OUTPUT_FORMATS = (
    "mp3_22050_32",
    "mp3_24000_48",
    "mp3_44100_32",
    "mp3_44100_64",
    "mp3_44100_96",
    "mp3_44100_128",
    "mp3_44100_192",
)
IGNORE_FIELDS_FOR_INFERENCE = ["audio_base64", "aes_key", "aes_nonce", "vault_wrapped_aes_key"]


class AudioGenerateRequestItem(BaseModel):
    """One sound-effect generation request."""

    model_config = ConfigDict(extra="forbid")

    id: Optional[Any] = None
    prompt: str = Field(..., min_length=1, max_length=400)
    provider: Literal["elevenlabs"] = DEFAULT_PROVIDER
    duration_seconds: float = Field(default=1.0, ge=0.5, le=2.0)
    prompt_influence: float = Field(default=0.3, ge=0.0, le=1.0)
    loop: bool = False
    output_format: Literal[
        "mp3_22050_32",
        "mp3_24000_48",
        "mp3_44100_32",
        "mp3_44100_64",
        "mp3_44100_96",
        "mp3_44100_128",
        "mp3_44100_192",
    ] = DEFAULT_OUTPUT_FORMAT
    model: Literal["eleven_text_to_sound_v2"] = DEFAULT_MODEL

    @field_validator("prompt")
    @classmethod
    def _strip_prompt(cls, value: str) -> str:
        prompt = value.strip()
        if not prompt:
            raise ValueError("prompt must not be blank")
        return prompt


class AudioGenerateRequest(BaseModel):
    """Request model for audio.generate."""

    model_config = ConfigDict(extra="forbid")

    requests: List[AudioGenerateRequestItem] = Field(..., min_length=1, max_length=5)


class AudioGenerateResult(BaseModel):
    """Result for one sound-effect generation request."""

    id: Any
    status: Literal["processing", "finished", "error"]
    prompt: str
    generation_type: Literal["sound_effect"] = "sound_effect"
    provider: str = "ElevenLabs"
    model: str = DEFAULT_MODEL
    mime_type: str = "audio/mpeg"
    duration_seconds: Optional[float] = None
    byte_length: Optional[int] = None
    task_id: Optional[str] = None
    embed_id: Optional[str] = None
    audio_base64: Optional[str] = None
    files: Optional[dict[str, Any]] = None
    s3_base_url: Optional[str] = None
    aes_key: Optional[str] = None
    aes_nonce: Optional[str] = None
    vault_wrapped_aes_key: Optional[str] = None
    credits_charged: Optional[int] = None
    error: Optional[str] = None


class AudioGenerateResponse(BaseModel):
    """Response model for audio.generate."""

    status: Literal["processing", "finished", "error"] = "processing"
    task_id: Optional[str] = None
    embed_id: Optional[str] = None
    task_ids: Optional[List[str]] = None
    embed_ids: Optional[List[str]] = None
    results: List[AudioGenerateResult] = Field(default_factory=list)
    provider: str = "ElevenLabs"
    error: Optional[str] = None
    ignore_fields_for_inference: List[str] = Field(default_factory=lambda: list(IGNORE_FIELDS_FOR_INFERENCE))


class GenerateSkill(BaseSkill):
    """Generate short non-speech sound effects using ElevenLabs."""

    async def execute(
        self,
        request: AudioGenerateRequest,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if not self.celery_producer:
            logger.error("Celery producer not available in audio.GenerateSkill")
            return AudioGenerateResponse(
                status="error",
                error="Audio generation service is temporarily unavailable.",
            ).model_dump(exclude_none=True)

        batch_decision = validate_media_generation_request(
            media_type="sound_effect",
            prompt="",
            request_count=len(request.requests),
        )
        if not batch_decision.allowed:
            return AudioGenerateResponse(
                status="error",
                error=batch_decision.user_facing_message,
            ).model_dump(exclude_none=True)

        results: list[AudioGenerateResult] = []
        task_ids: list[str] = []
        embed_ids: list[str] = []
        placeholder_embed_ids = kwargs.get("placeholder_embed_ids") or []
        user_id = kwargs.get("user_id")
        for index, item in enumerate(request.requests, start=1):
            item_id = item.id if item.id is not None else index

            safety = validate_media_generation_request(
                media_type="sound_effect",
                prompt=item.prompt,
                request_count=1,
            )
            if not safety.allowed:
                results.append(
                    AudioGenerateResult(
                        id=item_id,
                        status="error",
                        prompt=item.prompt,
                        duration_seconds=item.duration_seconds,
                        byte_length=0,
                        credits_charged=None,
                        error=safety.user_facing_message or "This sound effect request could not be generated.",
                    )
                )
                continue

            embed_id = (
                placeholder_embed_ids[index - 1]
                if index - 1 < len(placeholder_embed_ids) and placeholder_embed_ids[index - 1]
                else str(uuid.uuid4())
            )
            task_args = {
                "request_id": item_id,
                "prompt": item.prompt,
                "duration_seconds": item.duration_seconds,
                "prompt_influence": item.prompt_influence,
                "loop": item.loop,
                "output_format": item.output_format,
                "model": item.model,
                "full_model_reference": f"elevenlabs/{item.model}",
                "user_id": user_id,
                "user_vault_key_id": kwargs.get("user_vault_key_id"),
                "chat_id": kwargs.get("chat_id") or self._current_chat_id,
                "message_id": kwargs.get("message_id") or self._current_message_id,
                "external_request": kwargs.get("external_request", False),
                "api_key_hash": kwargs.get("api_key_hash"),
                "device_hash": kwargs.get("device_hash"),
                "api_key_name": kwargs.get("api_key_name"),
                "embed_id": embed_id,
            }
            try:
                task_id = await execute_skill_via_celery(
                    app_id=self.app_id,
                    skill_id=self.skill_id,
                    arguments=task_args,
                    celery_producer=self.celery_producer,
                )
                task_ids.append(task_id)
                embed_ids.append(embed_id)
                results.append(
                    AudioGenerateResult(
                        id=item_id,
                        status="processing",
                        prompt=item.prompt,
                        model=item.model,
                        duration_seconds=item.duration_seconds,
                        task_id=task_id,
                        embed_id=embed_id,
                    )
                )
            except Exception as exc:
                logger.error("audio.generate task dispatch error: %s", exc, exc_info=True)
                results.append(
                    AudioGenerateResult(
                        id=item_id,
                        status="error",
                        prompt=item.prompt,
                        duration_seconds=item.duration_seconds,
                        byte_length=0,
                        credits_charged=None,
                        error="Audio generation is temporarily unavailable.",
                    )
                )

        if not task_ids:
            return AudioGenerateResponse(
                status="error",
                results=results,
                error="No sound effect generation tasks could be started.",
            ).model_dump(exclude_none=True)

        return AudioGenerateResponse(
            status="processing",
            task_id=task_ids[0] if len(task_ids) == 1 else None,
            embed_id=embed_ids[0] if len(embed_ids) == 1 else None,
            task_ids=task_ids,
            embed_ids=embed_ids,
            results=results,
        ).model_dump(exclude_none=True)
