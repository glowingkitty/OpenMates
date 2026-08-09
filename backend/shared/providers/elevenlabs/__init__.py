# backend/shared/providers/elevenlabs/__init__.py
#
# ElevenLabs provider boundary for OpenMates audio generation.
# The package exports only provider-level models and clients; app skills own
# request validation, OpenMates safety policy, billing, storage, and embed shape.

from .client import ElevenLabsClient
from .models import ElevenLabsAudioResult

__all__ = ["ElevenLabsAudioResult", "ElevenLabsClient"]
