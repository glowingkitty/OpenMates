#!/usr/bin/env python3
"""
Generate the spoken user question of a real voice-call browser test.

Runs inside the API container so ElevenLabs credentials remain Vault-backed.
Reads its arguments from argv, prints one JSON line on stdout whose ``wav_base64``
is a 16 kHz mono 16-bit WAV: a short lead-in silence, the spoken text, then a
long trailing silence. Chromium plays that file in a loop as its fake microphone
(``--use-file-for-fake-audio-capture``), so the long silence keeps the question
from repeating before the test mutes the call.

Used by scripts/voice_call_web_real_test.py (dev only; never CI):
  docker exec -i api python - --text "..." < backend/scripts/generate_voice_call_speaker_audio.py
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import sys
import wave
from pathlib import Path

# Piped through stdin (``python -``) there is no script path; the container's code root is /app.
for candidate in (Path("/app"), *Path(globals().get("__file__", "/")).resolve().parents):
    if (candidate / "backend" / "shared").is_dir():
        if str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))
        break

from backend.core.api.app.utils.secrets_manager import SecretsManager  # noqa: E402 - path set above
from backend.shared.providers.elevenlabs.client import ElevenLabsClient  # noqa: E402 - path set above

SAMPLE_RATE = 16_000
OUTPUT_FORMAT = f"pcm_{SAMPLE_RATE}"
# ElevenLabs premade voice "Rachel": the test's user voice. It is neither a Mate
# voice nor the neutral system voice, so it can never be mistaken for a reply.
SPEAKER_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"
SPEAKER_MODEL = "eleven_multilingual_v2"


def wav_bytes(pcm: bytes, *, lead_seconds: float, tail_seconds: float) -> bytes:
    """Wrap raw 16-bit mono PCM with silence into a WAV file."""
    silence = lambda seconds: b"\0\0" * int(SAMPLE_RATE * seconds)  # noqa: E731 - tiny local helper
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(silence(lead_seconds) + pcm + silence(tail_seconds))
    return buffer.getvalue()


async def generate(text: str, lead_seconds: float, tail_seconds: float) -> dict:
    secrets_manager = SecretsManager()
    await secrets_manager.initialize()
    client = ElevenLabsClient(secrets_manager=secrets_manager)
    result = await client.text_to_speech(text=text, voice_id=SPEAKER_VOICE_ID, model=SPEAKER_MODEL,
                                         output_format=OUTPUT_FORMAT)
    pcm = result.audio_bytes
    if len(pcm) < SAMPLE_RATE:  # under half a second of speech: not a usable question
        raise RuntimeError("speaker audio too short")
    data = wav_bytes(pcm, lead_seconds=lead_seconds, tail_seconds=tail_seconds)
    return {"status": "ok", "speech_seconds": round(len(pcm) / (2 * SAMPLE_RATE), 2),
            "wav_base64": base64.b64encode(data).decode("ascii")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--text", required=True)
    parser.add_argument("--lead-seconds", type=float, default=1.5)
    parser.add_argument("--tail-seconds", type=float, default=60.0)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(generate(args.text, args.lead_seconds, args.tail_seconds))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
