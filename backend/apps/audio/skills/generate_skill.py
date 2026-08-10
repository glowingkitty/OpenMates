# backend/apps/audio/skills/generate_skill.py
#
# audio.generate app skill for short non-speech sound effects.
# This skill validates the OpenMates contract, applies deterministic generated
# media safety before provider use, calls ElevenLabs through the shared provider
# wrapper, and returns playable direct audio metadata without logging secrets.

from __future__ import annotations

import base64
import logging
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.apps.base_skill import BaseSkill
from backend.shared.providers.elevenlabs import ElevenLabsClient
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
    status: Literal["finished", "error"]
    prompt: str
    generation_type: Literal["sound_effect"] = "sound_effect"
    provider: str = "ElevenLabs"
    model: str = DEFAULT_MODEL
    mime_type: str = "audio/mpeg"
    duration_seconds: float
    byte_length: int
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

    results: List[AudioGenerateResult] = Field(default_factory=list)
    provider: str = "ElevenLabs"
    error: Optional[str] = None
    ignore_fields_for_inference: List[str] = Field(default_factory=lambda: list(IGNORE_FIELDS_FOR_INFERENCE))


class GenerateSkill(BaseSkill):
    """Generate short non-speech sound effects using ElevenLabs."""

    async def execute(
        self,
        request: AudioGenerateRequest,
        secrets_manager=None,
        **_kwargs: Any,
    ) -> AudioGenerateResponse:
        batch_decision = validate_media_generation_request(
            media_type="sound_effect",
            prompt="",
            request_count=len(request.requests),
        )
        if not batch_decision.allowed:
            return AudioGenerateResponse(error=batch_decision.user_facing_message)

        client = ElevenLabsClient(secrets_manager=secrets_manager)
        results: list[AudioGenerateResult] = []
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

            try:
                generated = await client.generate_sound_effect(
                    prompt=item.prompt,
                    duration_seconds=item.duration_seconds,
                    prompt_influence=item.prompt_influence,
                    loop=item.loop,
                    output_format=item.output_format,
                    model=item.model,
                )
                credits = await self.calculate_skill_credits(duration_seconds=item.duration_seconds)
                results.append(
                    AudioGenerateResult(
                        id=item_id,
                        status="finished",
                        prompt=item.prompt,
                        model=generated.model,
                        mime_type=generated.mime_type or "audio/mpeg",
                        duration_seconds=generated.duration_seconds or item.duration_seconds,
                        byte_length=generated.byte_length,
                        audio_base64=base64.b64encode(generated.audio_bytes).decode("ascii"),
                        credits_charged=credits,
                        error=None,
                    )
                )
            except Exception as exc:
                logger.error("audio.generate provider error: %s", exc, exc_info=True)
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

        return AudioGenerateResponse(results=results)
