"""Live Voxtral call-adapter check using public synthetic speech, never account chats.

Runs inside api with Vault credentials. Exercises real STT turn events, trailing
deltas and pause/resume plus the shared TTS provider. Emits content-free metrics.
Usage: docker exec api python /app/backend/scripts/test_voxtral_voice.py
"""
from __future__ import annotations

# contract-test-file: tooling

import array
import asyncio
import base64
import json
from pathlib import Path
import sys
import time
import wave

from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.providers.mistral_speech import MistralSpeechClient
from backend.shared.providers.voxtral_voice import VoxtralVoiceSession


async def main() -> None:
    secrets = SecretsManager()
    await secrets.initialize()
    session = None
    try:
        key = await secrets.get_secret("kv/data/providers/mistral_ai", "api_key")
        if not key:
            raise RuntimeError("Mistral credentials unavailable")
        speech = await MistralSpeechClient(api_key=key).text_to_speech(
            text="Hello, your message is ready.", voice_id="voice_3150",
        )
        print(json.dumps({"tts_model": "voxtral-mini-tts-3-0", "audio_bytes": len(speech.audio_bytes)}), flush=True)
        fixture = Path(__file__).resolve().parents[1] / "tests/fixtures/realtime_transcription_speech.wav"
        with wave.open(str(fixture)) as wav:
            assert wav.getnchannels() == 1 and wav.getsampwidth() == 2
            assert wav.getframerate() == 48000
            pcm = array.array("h", wav.readframes(wav.getnframes()))
        if sys.byteorder != "little":
            pcm.byteswap()
        pcm16k = pcm[::3].tobytes()
        session = VoxtralVoiceSession(key)
        await session.open()
        for turn in range(2):
            started = time.monotonic()
            types: dict[str, int] = {}
            first_delta = None

            async def send() -> None:
                for offset in range(0, len(pcm16k), 3200):
                    await session.send_audio(base64.b64encode(pcm16k[offset:offset + 3200]).decode("ascii"))
                    await asyncio.sleep(0.1)
                await session.end_audio()

            sender = asyncio.create_task(send())
            try:
                async with asyncio.timeout(25):
                    while True:
                        event = await session.receive()
                        kind = str(event.get("type"))
                        types[kind] = types.get(kind, 0) + 1
                        if kind == "transcription.text.delta" and first_delta is None:
                            first_delta = round(time.monotonic() - started, 3)
                        if kind == "turn.end":
                            break
                    await sender
                assert types.get("turn.start") and types.get("transcription.text.delta") and types.get("turn.end")
                # Drain the documented trailing-delta window before resuming.
                deadline = time.monotonic() + 0.3
                while (remaining := deadline - time.monotonic()) > 0:
                    try:
                        event = await asyncio.wait_for(session.receive(), remaining)
                        kind = str(event.get("type"))
                        types[kind] = types.get(kind, 0) + 1
                    except TimeoutError:
                        break
                print(json.dumps({"stt_model": session.model, "turn": turn + 1,
                    "events": types, "first_delta_seconds": first_delta,
                    "elapsed_seconds": round(time.monotonic() - started, 3)}), flush=True)
            finally:
                sender.cancel()
                await asyncio.gather(sender, return_exceptions=True)
    finally:
        if session is not None:
            await session.close()
        await secrets.close()


if __name__ == "__main__":
    asyncio.run(main())
