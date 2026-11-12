# backend/apps/audio/pricing.py
#
# OpenMates credit pricing helpers for audio app skills.
# REST, chat orchestration, and skill implementations share these constants so
# budget preflight and successful-result charges stay aligned without importing
# provider or safeguard clients in lightweight tests. Rates come from the
# cost-plus catalog prices stored in backend/providers and backend/apps.

from __future__ import annotations

import math
from decimal import Decimal

from backend.shared.python_utils.catalog_unit_prices import model_price, skill_price, whole_credits

DEFAULT_SOUND_EFFECT_DURATION_SECONDS = 1.0
SOUND_EFFECT_CREDITS_PER_SECOND = model_price("elevenlabs/eleven_text_to_sound_v2", "per_second")
LOW_COST_SPEECH_MODEL = "eleven_flash_v2_5"
MULTILINGUAL_SPEECH_MODEL = "eleven_multilingual_v2"
ELEVEN_V3_SPEECH_MODEL = "eleven_v3"
ELEVEN_V3_CONVERSATIONAL_SPEECH_MODEL = "eleven_v3_conversational"
ELEVEN_V4_SPEECH_MODEL = "eleven_v4"
ELEVEN_V4_TURBO_SPEECH_MODEL = "eleven_v4_turbo"
PREMIUM_SPEECH_MODEL = ELEVEN_V3_SPEECH_MODEL
DEFAULT_SPEECH_MODEL = PREMIUM_SPEECH_MODEL
ASSISTANT_RESPONSE_SPEECH_MODEL = "voxtral-mini-tts-3-0"
# Catalog price per 1M characters with cumulative message-level rounding.
# Retain old manifest prices so in-flight work settles under its original model.
ASSISTANT_SPEECH_CREDITS_PER_CHARACTER = {
    ASSISTANT_RESPONSE_SPEECH_MODEL: model_price(
        f"mistral/{ASSISTANT_RESPONSE_SPEECH_MODEL}", "per_million_characters") / 1_000_000,
    ELEVEN_V4_TURBO_SPEECH_MODEL: Decimal("0.04"),
    ELEVEN_V3_CONVERSATIONAL_SPEECH_MODEL: Decimal(1) / Decimal(14),
}
SECONDS_PER_MINUTE = 60
ELEVENLABS_APPROX_CHARS_PER_MINUTE = 1000
BATCH_TRANSCRIPTION_CREDITS_PER_STARTED_MINUTE = whole_credits(skill_price("audio", "transcribe", "per_minute"))
REALTIME_TRANSCRIPTION_MODEL_REF = "mistral/voxtral-mini-transcribe-realtime-3-0"
# Whole credits per minute from the catalog; settlement prorates measured
# seconds and rounds the final credit total only once.
REALTIME_TRANSCRIPTION_CREDITS_PER_MINUTE = whole_credits(model_price(REALTIME_TRANSCRIPTION_MODEL_REF, "per_minute"))
REALTIME_TRANSCRIPTION_MINIMUM_CREDITS = 1
SPEECH_MODEL_CREDITS_PER_SECOND = {
    model: model_price(f"elevenlabs/{model}", "per_second")
    for model in (LOW_COST_SPEECH_MODEL, MULTILINGUAL_SPEECH_MODEL, ELEVEN_V3_SPEECH_MODEL,
                  ELEVEN_V4_SPEECH_MODEL, ELEVEN_V4_TURBO_SPEECH_MODEL)
}


def _duration_credits(*, duration_seconds: float, credits_per_second: Decimal) -> int:
    if duration_seconds <= 0:
        return 0
    return max(1, math.ceil(Decimal(str(duration_seconds)) * credits_per_second))


def calculate_realtime_transcription_credits(*, duration_seconds: float) -> int:
    """Prorate the published minute rate without rounding up audio duration."""
    if not math.isfinite(duration_seconds):
        raise ValueError("Transcription duration must be finite")
    if duration_seconds <= 0:
        return 0
    return max(
        REALTIME_TRANSCRIPTION_MINIMUM_CREDITS,
        math.ceil(
            Decimal(str(duration_seconds))
            * REALTIME_TRANSCRIPTION_CREDITS_PER_MINUTE
            / SECONDS_PER_MINUTE
        ),
    )


def calculate_sound_effect_credits(*, duration_seconds: float) -> int:
    return _duration_credits(
        duration_seconds=duration_seconds,
        credits_per_second=SOUND_EFFECT_CREDITS_PER_SECOND,
    )


def estimate_speech_duration_seconds(text: str) -> float:
    return max(0.1, (len(text) / ELEVENLABS_APPROX_CHARS_PER_MINUTE) * SECONDS_PER_MINUTE)


def calculate_speech_credits(*, model: str, duration_seconds: float) -> int:
    credits_per_second = SPEECH_MODEL_CREDITS_PER_SECOND[model]
    return _duration_credits(duration_seconds=duration_seconds, credits_per_second=credits_per_second)


def calculate_assistant_response_speech_credits(*, submitted_characters: int,
                                              model: str = ASSISTANT_RESPONSE_SPEECH_MODEL) -> int:
    """Price one complete assistant message with one character-rounding step."""
    if submitted_characters <= 0:
        return 0
    return max(1, math.ceil(Decimal(submitted_characters) * ASSISTANT_SPEECH_CREDITS_PER_CHARACTER[model]))
