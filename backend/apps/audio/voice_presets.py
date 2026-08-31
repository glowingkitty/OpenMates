# backend/apps/audio/voice_presets.py
#
# Curated server-side ElevenLabs voice preset mapping.
# This module is deliberately dependency-free so internal audio workers can
# resolve fixed profiles without importing app-skill safety or provider clients.
# Raw provider identifiers must not cross backend audio boundaries.

from __future__ import annotations


VOICE_PRESET_TO_ELEVENLABS_ID = {
    "warm_neutral": "21m00Tcm4TlvDq8ikWAM",
    "bright_neutral": "EXAVITQu4vr4xnSDxMaL",
    "calm_narrator": "pNInz6obpgDQGcFmaJgB",
}
