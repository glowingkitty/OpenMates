# backend/apps/audio/skills/speak_skill.py
#
# audio.speak app skill for explicit text-to-speech generation requests.
# The skill accepts only OpenMates voice presets, validates dispatch requests,
# and sends provider/safeguard work to Celery so generated speech is stored as
# encrypted generated assets instead of inline audio bytes.

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.apps.base_skill import BaseSkill
from backend.apps.audio.pricing import (
    DEFAULT_SPEECH_MODEL,
    PREMIUM_SPEECH_MODEL,
)
from backend.shared.providers.groq.safeguard import get_safeguard_client
from backend.shared.python_utils.app_skill_helpers import execute_skill_via_celery
from backend.shared.python_utils.media_generation_safety import validate_media_generation_request

logger = logging.getLogger(__name__)

DEFAULT_PROVIDER = "elevenlabs"
DEFAULT_MODEL = DEFAULT_SPEECH_MODEL
PREMIUM_MODEL = PREMIUM_SPEECH_MODEL
DEFAULT_OUTPUT_FORMAT = "mp3_44100_128"
IGNORE_FIELDS_FOR_INFERENCE = ["audio_base64", "aes_key", "aes_nonce", "vault_wrapped_aes_key"]


@dataclass(frozen=True)
class AudioSpeechSafetyDecision:
    """OpenMates-safe audio.speak approval result."""

    approved: bool
    category: str = ""
    user_facing_message: str = "Speech safety check is temporarily unavailable."


class AudioSpeakRequestItem(BaseModel):
    """One text-to-speech request."""

    model_config = ConfigDict(extra="forbid")

    id: Optional[Any] = None
    text: str = Field(..., min_length=1, max_length=2000)
    provider: Literal["elevenlabs"] = DEFAULT_PROVIDER
    voice: Literal["warm_neutral", "bright_neutral", "calm_narrator"] = "warm_neutral"
    accent: Literal["en_us", "en_gb", "de_de", "es_es", "fr_fr"] = "en_us"
    style: Literal["natural", "calm", "friendly", "energetic"] = "natural"
    speed: float = Field(default=1.0, ge=0.7, le=1.2)
    output_format: Literal[
        "mp3_22050_32",
        "mp3_24000_48",
        "mp3_44100_32",
        "mp3_44100_64",
        "mp3_44100_96",
        "mp3_44100_128",
        "mp3_44100_192",
    ] = DEFAULT_OUTPUT_FORMAT
    model: Literal["eleven_v3", "eleven_multilingual_v2", "eleven_flash_v2_5"] = DEFAULT_MODEL

    @field_validator("text")
    @classmethod
    def _strip_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("text must not be blank")
        return text


class AudioSpeakRequest(BaseModel):
    """Request model for audio.speak."""

    model_config = ConfigDict(extra="forbid")

    requests: List[AudioSpeakRequestItem] = Field(..., min_length=1, max_length=3)


class AudioSpeakResult(BaseModel):
    """Result for one text-to-speech request."""

    id: Any
    status: Literal["processing", "finished", "error"]
    text_preview: str
    generation_type: Literal["speech"] = "speech"
    voice: str
    accent: str
    style: str
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


class AudioSpeakResponse(BaseModel):
    """Response model for audio.speak."""

    status: Literal["processing", "finished", "error"] = "processing"
    task_id: Optional[str] = None
    embed_id: Optional[str] = None
    task_ids: Optional[List[str]] = None
    embed_ids: Optional[List[str]] = None
    results: List[AudioSpeakResult] = Field(default_factory=list)
    provider: str = "ElevenLabs"
    error: Optional[str] = None
    ignore_fields_for_inference: List[str] = Field(default_factory=lambda: list(IGNORE_FIELDS_FOR_INFERENCE))


def _text_preview(text: str) -> str:
    compact = " ".join(text.split())
    return compact[:157].rstrip() + "..." if len(compact) > 160 else compact


async def classify_audio_speech_safety(
    *,
    text: str,
    voice: str,
    accent: str,
    style: str,
    secrets_manager=None,
) -> AudioSpeechSafetyDecision:
    """Run deterministic and GPT OSS safety checks before TTS provider use."""

    deterministic = validate_media_generation_request(
        media_type="speech",
        prompt=text,
        request_count=1,
        style=style,
    )
    if not deterministic.allowed:
        return AudioSpeechSafetyDecision(
            approved=False,
            category=deterministic.category or "audio_speech_rejected",
            user_facing_message=deterministic.user_facing_message or "I can't create that speech audio.",
        )

    safeguard = get_safeguard_client()
    if secrets_manager:
        await safeguard.initialize(secrets_manager)
    result = await safeguard.classify_audio_speech(
        text=text,
        voice=voice,
        accent=accent,
        style=style,
    )
    return AudioSpeechSafetyDecision(
        approved=result.approved,
        category=result.category,
        user_facing_message=result.user_facing_message or "I can't create that speech audio.",
    )


class SpeakSkill(BaseSkill):
    """Generate explicit short speech audio using ElevenLabs after safeguard approval."""

    async def execute(
        self,
        request: AudioSpeakRequest,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if not self.celery_producer:
            logger.error("Celery producer not available in audio.SpeakSkill")
            return AudioSpeakResponse(
                status="error",
                error="Speech generation service is temporarily unavailable.",
            ).model_dump(exclude_none=True)

        batch_decision = validate_media_generation_request(
            media_type="speech",
            prompt="",
            request_count=len(request.requests),
        )
        if not batch_decision.allowed:
            return AudioSpeakResponse(
                status="error",
                error=batch_decision.user_facing_message,
            ).model_dump(exclude_none=True)

        results: list[AudioSpeakResult] = []
        task_ids: list[str] = []
        embed_ids: list[str] = []
        placeholder_embed_ids = kwargs.get("placeholder_embed_ids") or []
        user_id = kwargs.get("user_id")
        for index, item in enumerate(request.requests, start=1):
            item_id = item.id if item.id is not None else index
            text_preview = _text_preview(item.text)

            embed_id = (
                placeholder_embed_ids[index - 1]
                if index - 1 < len(placeholder_embed_ids) and placeholder_embed_ids[index - 1]
                else str(uuid.uuid4())
            )
            task_args = {
                "request_id": item_id,
                "text": item.text,
                "text_preview": text_preview,
                "voice": item.voice,
                "accent": item.accent,
                "style": item.style,
                "speed": item.speed,
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
                    AudioSpeakResult(
                        id=item_id,
                        status="processing",
                        text_preview=text_preview,
                        voice=item.voice,
                        accent=item.accent,
                        style=item.style,
                        model=item.model,
                        task_id=task_id,
                        embed_id=embed_id,
                    )
                )
            except Exception as exc:
                logger.error("audio.speak task dispatch error: %s", exc, exc_info=True)
                results.append(
                    AudioSpeakResult(
                        id=item_id,
                        status="error",
                        text_preview=text_preview,
                        voice=item.voice,
                        accent=item.accent,
                        style=item.style,
                        model=item.model,
                        byte_length=0,
                        credits_charged=None,
                        error="Speech generation is temporarily unavailable.",
                    )
                )

        if not task_ids:
            return AudioSpeakResponse(
                status="error",
                results=results,
                error="No speech generation tasks could be started.",
            ).model_dump(exclude_none=True)

        return AudioSpeakResponse(
            status="processing",
            task_id=task_ids[0] if len(task_ids) == 1 else None,
            embed_id=embed_ids[0] if len(embed_ids) == 1 else None,
            task_ids=task_ids,
            embed_ids=embed_ids,
            results=results,
        ).model_dump(exclude_none=True)
