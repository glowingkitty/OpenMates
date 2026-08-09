# backend/apps/audio/skills/speak_skill.py
#
# audio.speak app skill for explicit text-to-speech/read-aloud requests.
# The skill accepts only OpenMates voice presets, runs deterministic checks and
# the GPT OSS safeguard before ElevenLabs, and returns direct playable audio only
# after the safeguard explicitly approves the text.

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.apps.base_skill import BaseSkill
from backend.shared.providers.elevenlabs import ElevenLabsClient
from backend.shared.providers.groq.safeguard import get_safeguard_client
from backend.shared.python_utils.media_generation_safety import validate_media_generation_request

logger = logging.getLogger(__name__)

DEFAULT_PROVIDER = "elevenlabs"
DEFAULT_MODEL = "eleven_flash_v2_5"
DEFAULT_OUTPUT_FORMAT = "mp3_44100_128"
VOICE_PRESET_TO_ELEVENLABS_ID = {
    "warm_neutral": "21m00Tcm4TlvDq8ikWAM",
    "bright_neutral": "EXAVITQu4vr4xnSDxMaL",
    "calm_narrator": "pNInz6obpgDQGcFmaJgB",
}
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
    model: Literal["eleven_flash_v2_5"] = DEFAULT_MODEL

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
    status: Literal["finished", "error"]
    text_preview: str
    generation_type: Literal["speech"] = "speech"
    voice: str
    accent: str
    style: str
    provider: str = "ElevenLabs"
    model: str = DEFAULT_MODEL
    mime_type: str = "audio/mpeg"
    duration_seconds: Optional[float] = None
    byte_length: int
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
        secrets_manager=None,
        **_kwargs: Any,
    ) -> AudioSpeakResponse:
        batch_decision = validate_media_generation_request(
            media_type="speech",
            prompt="",
            request_count=len(request.requests),
        )
        if not batch_decision.allowed:
            return AudioSpeakResponse(error=batch_decision.user_facing_message)

        client = ElevenLabsClient(secrets_manager=secrets_manager)
        results: list[AudioSpeakResult] = []
        for index, item in enumerate(request.requests, start=1):
            item_id = item.id if item.id is not None else index
            text_preview = _text_preview(item.text)

            safety = await classify_audio_speech_safety(
                text=item.text,
                voice=item.voice,
                accent=item.accent,
                style=item.style,
                secrets_manager=secrets_manager,
            )
            if not safety.approved:
                logger.info("audio.speak rejected before provider call: %s", safety.category)
                results.append(
                    AudioSpeakResult(
                        id=item_id,
                        status="error",
                        text_preview=text_preview,
                        voice=item.voice,
                        accent=item.accent,
                        style=item.style,
                        byte_length=0,
                        credits_charged=None,
                        error=safety.user_facing_message,
                    )
                )
                continue

            try:
                voice_id = VOICE_PRESET_TO_ELEVENLABS_ID[item.voice]
                generated = await client.text_to_speech(
                    text=item.text,
                    voice_id=voice_id,
                    model=item.model,
                    output_format=item.output_format,
                    speed=item.speed,
                )
                credits = await self.calculate_skill_credits(units_processed=len(item.text))
                results.append(
                    AudioSpeakResult(
                        id=item_id,
                        status="finished",
                        text_preview=text_preview,
                        voice=item.voice,
                        accent=item.accent,
                        style=item.style,
                        model=generated.model,
                        mime_type=generated.mime_type or "audio/mpeg",
                        duration_seconds=generated.duration_seconds,
                        byte_length=generated.byte_length,
                        audio_base64=base64.b64encode(generated.audio_bytes).decode("ascii"),
                        credits_charged=credits,
                        error=None,
                    )
                )
            except KeyError:
                results.append(
                    AudioSpeakResult(
                        id=item_id,
                        status="error",
                        text_preview=text_preview,
                        voice=item.voice,
                        accent=item.accent,
                        style=item.style,
                        byte_length=0,
                        credits_charged=None,
                        error="Selected voice preset is temporarily unavailable.",
                    )
                )
            except Exception as exc:
                logger.error("audio.speak provider error: %s", exc, exc_info=True)
                results.append(
                    AudioSpeakResult(
                        id=item_id,
                        status="error",
                        text_preview=text_preview,
                        voice=item.voice,
                        accent=item.accent,
                        style=item.style,
                        byte_length=0,
                        credits_charged=None,
                        error="Speech generation is temporarily unavailable.",
                    )
                )

        return AudioSpeakResponse(results=results)
