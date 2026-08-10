# backend/shared/providers/elevenlabs/models.py
#
# Normalized provider response models for ElevenLabs audio generation.
# These types intentionally contain only provider-output metadata and raw bytes;
# app skills decide whether bytes are returned directly or encrypted into an
# OpenMates generated-asset embed.

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ElevenLabsAudioResult:
    """Normalized ElevenLabs audio response."""

    audio_bytes: bytes
    mime_type: str
    model: str
    duration_seconds: Optional[float] = None

    @property
    def byte_length(self) -> int:
        return len(self.audio_bytes or b"")
