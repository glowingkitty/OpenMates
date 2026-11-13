"""Safety check shared by every caller that turns text into speech (audio.speak, assistant speech, composed videos).

Deterministic media rules first, then the safeguard model. Lives outside the skill module so other apps can
import it without depending on a skill.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.shared.providers.groq.safeguard import get_safeguard_client
from backend.shared.python_utils.media_generation_safety import validate_media_generation_request


@dataclass(frozen=True)
class AudioSpeechSafetyDecision:
    """OpenMates-safe audio.speak approval result."""

    approved: bool
    category: str = ""
    user_facing_message: str = "Speech safety check is temporarily unavailable."


async def classify_audio_speech_safety(
    *,
    text: str,
    voice: str,
    accent: str,
    style: str,
    secrets_manager=None,
    trusted_narration: bool = False,
) -> AudioSpeechSafetyDecision:
    """Run deterministic and GPT OSS safety checks before TTS provider use."""

    deterministic = validate_media_generation_request(
        media_type="speech",
        prompt=text,
        request_count=1,
        style=style,
        trusted_narration=trusted_narration,
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
        trusted_narration=trusted_narration,
    )
    return AudioSpeechSafetyDecision(
        approved=result.approved,
        category=result.category,
        user_facing_message=result.user_facing_message or "I can't create that speech audio.",
    )
