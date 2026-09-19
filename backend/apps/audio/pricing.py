# backend/apps/audio/pricing.py
#
# Dependency-free OpenMates credit pricing helpers for audio app skills.
# REST, chat orchestration, and skill implementations share these constants so
# budget preflight and successful-result charges stay aligned without importing
# provider or safeguard clients in lightweight tests.

from __future__ import annotations

import math
from decimal import Decimal

DEFAULT_SOUND_EFFECT_DURATION_SECONDS = 1.0
SOUND_EFFECT_CREDITS_PER_SECOND = 20
LOW_COST_SPEECH_MODEL = "eleven_flash_v2_5"
MULTILINGUAL_SPEECH_MODEL = "eleven_multilingual_v2"
ELEVEN_V3_SPEECH_MODEL = "eleven_v3"
ELEVEN_V3_CONVERSATIONAL_SPEECH_MODEL = "eleven_v3_conversational"
PREMIUM_SPEECH_MODEL = ELEVEN_V3_SPEECH_MODEL
DEFAULT_SPEECH_MODEL = PREMIUM_SPEECH_MODEL
ASSISTANT_RESPONSE_SPEECH_MODEL = ELEVEN_V3_CONVERSATIONAL_SPEECH_MODEL
ASSISTANT_RESPONSE_SPEECH_CHARACTERS_PER_CREDIT = 14
SECONDS_PER_MINUTE = 60
ELEVENLABS_APPROX_CHARS_PER_MINUTE = 1000
BATCH_TRANSCRIPTION_CREDITS_PER_STARTED_MINUTE = 3
REALTIME_TRANSCRIPTION_PROVIDER_COST_USD_PER_MINUTE = Decimal("0.006")
REALTIME_TRANSCRIPTION_PRICE_MULTIPLIER = Decimal("1.20")
USD_PER_CREDIT = Decimal("0.001")
# Billing accepts whole credits. $0.006 × 1.20 = $0.0072, so round up to
# eight credits per started minute to avoid pricing below cost + 20%.
REALTIME_TRANSCRIPTION_CREDITS_PER_STARTED_MINUTE = math.ceil(
    REALTIME_TRANSCRIPTION_PROVIDER_COST_USD_PER_MINUTE
    * REALTIME_TRANSCRIPTION_PRICE_MULTIPLIER
    / USD_PER_CREDIT
)
SPEECH_MODEL_CREDITS_PER_SECOND = {
    LOW_COST_SPEECH_MODEL: 2,
    MULTILINGUAL_SPEECH_MODEL: 4,
    ELEVEN_V3_SPEECH_MODEL: 4,
}


def _duration_credits(*, duration_seconds: float, credits_per_second: int) -> int:
    if duration_seconds <= 0:
        return 0
    return max(1, math.ceil(duration_seconds * credits_per_second))


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


def calculate_assistant_response_speech_credits(*, submitted_characters: int) -> int:
    """Price one complete assistant message with one character-rounding step."""
    if submitted_characters <= 0:
        return 0
    return max(1, math.ceil(submitted_characters / ASSISTANT_RESPONSE_SPEECH_CHARACTERS_PER_CREDIT))
