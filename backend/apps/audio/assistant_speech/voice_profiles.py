# backend/apps/audio/assistant_speech/voice_profiles.py
#
# Server-only provider resolution for assistant-response speech.
# Mate frontmatter stores stable, provider-neutral keys and versions only.
# ElevenLabs identifiers remain confined to this backend audio module and are
# never emitted in client metadata, worker results, or app-skill responses.

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from backend.apps.audio.pricing import ASSISTANT_RESPONSE_SPEECH_MODEL
DEFAULT_OUTPUT_FORMAT = "mp3_44100_128"
DEFAULT_VOICE_SETTINGS = MappingProxyType({"speed": 1.0})
ASSISTANT_VOICE_PROVIDER_IDS = MappingProxyType(
    {
        "ace": "aMSt68OGf4xUZAnLpTU8",
        "burton": "repzAAjoKlgcT2oOAIWt",
        "colin": "FTNCalFNG5bRnkkaP5Ug",
        "denise": "ZF6FPAbjXT4488VcRRnw",
        "elton": "TumdjBNWanlT3ysvclWh",
        "finn": "NFG5qt843uXKj4pFvR7C",
        "george": "XjLkpWUlnhS8i7gGz3lZ",
        "hiro": "3JDquces8E8bkmvbh6Bc",
        "leon": "BtWabtumIemAotTjP5sk",
        "lisa": "pjcYQlDFKMbcOUp6F5GD",
        "makani": "eBvoGh8YGJn1xokno71w",
        "mark": "dXtC3XhB9GtPusIpNtQx",
        "melvin": "bPMKpgEe88vKSwusXTMU",
        "monika": "56AoDkrOh6qfVPDXZ7Pt",
        "scarlett": "XfNU2rGpBa01ckF309OY",
        "sophia": "4CrZuIW9am7gYAxgo2Af",
        "suki": "0ZOhGcBopt9S6GBK8tnj",
    }
)


@dataclass(frozen=True)
class ResolvedAssistantVoiceProfile:
    """Provider-safe profile metadata with an internal ElevenLabs request mapping."""

    key: str
    version: int
    provider: str
    model: str
    output_format: str
    voice_settings: Mapping[str, float]
    _elevenlabs_voice_id: str

    def elevenlabs_request(self) -> dict[str, object]:
        """Return provider input for backend task execution only."""
        return {
            "voice_id": self._elevenlabs_voice_id,
            "model": self.model,
            "output_format": self.output_format,
            "voice_settings": dict(self.voice_settings),
        }


def _profile(key: str) -> ResolvedAssistantVoiceProfile:
    return ResolvedAssistantVoiceProfile(
        key=key,
        version=1,
        provider="elevenlabs",
        model=ASSISTANT_RESPONSE_SPEECH_MODEL,
        output_format=DEFAULT_OUTPUT_FORMAT,
        voice_settings=DEFAULT_VOICE_SETTINGS,
        _elevenlabs_voice_id=ASSISTANT_VOICE_PROVIDER_IDS[key],
    )


_VOICE_PROFILES = {key: _profile(key) for key in ASSISTANT_VOICE_PROVIDER_IDS}


def resolve_assistant_voice_profile(key: str, *, version: int) -> ResolvedAssistantVoiceProfile:
    """Resolve an exact configured profile or fail before provider dispatch."""
    profile = _VOICE_PROFILES.get(key)
    if profile is None or profile.version != version:
        raise ValueError("Assistant voice profile is unavailable.")
    return profile
