"""Bounded, explicitly gated Eleven v4 Turbo incremental provider proof.

Run only when the active task's coordinator authorizes this paid attempt:
python -m backend.scripts.test_elevenlabs_realtime_incremental --execute-paid-probe
Uses existing Vault credentials and one curated voice. Never writes audio, IDs,
text, keys, provider responses or alignment characters. No automatic retries.
"""
# contract-test-file: tooling
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from contextlib import suppress
from time import monotonic

import aiohttp

from backend.apps.audio.assistant_speech.voice_profiles import ASSISTANT_VOICE_PROVIDER_IDS
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.providers.elevenlabs.realtime import (
    ELEVENLABS_REALTIME_MODEL, ElevenLabsRealtimeError, ElevenLabsRealtimeSession,
)


async def run() -> None:
    logging.disable(logging.CRITICAL)  # Probe output is the explicit content-free receipt only.
    secrets = SecretsManager()
    session = None
    result = {"model": ELEVENLABS_REALTIME_MODEL, "success": False, "model_available": False,
              "first_audio_before_second_input": False, "audio_chunks": 0, "final": False,
              "alignment_chunks": 0, "first_alignment_chunks": []}
    try:
        await secrets.initialize()
        key = await secrets.get_secret(secret_path="kv/data/providers/elevenlabs", secret_key="api_key")
        if not isinstance(key, str) or not key:
            raise ElevenLabsRealtimeError("credentials_unavailable")
        # This free availability check does not establish WebSocket capability;
        # the gated two-input synthesis below proves the actual v4 handshake.
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as http:
            async with http.get("https://api.elevenlabs.io/v1/models", headers={"xi-api-key": key}) as response:
                if response.status != 200:
                    raise ElevenLabsRealtimeError("model_availability_failed")
                if response.content_length is not None and response.content_length > 1024 * 1024:
                    raise ElevenLabsRealtimeError("model_availability_failed")
                raw = bytearray()
                async for chunk in response.content.iter_chunked(16384):
                    if len(raw) + len(chunk) > 1024 * 1024:
                        raise ElevenLabsRealtimeError("model_availability_failed")
                    raw.extend(chunk)
                models = json.loads(raw)
                result["model_available"] = isinstance(models, list) and any(
                    isinstance(model, dict) and model.get("model_id") == ELEVENLABS_REALTIME_MODEL
                    and model.get("can_do_text_to_speech") is True for model in models)
        if not result["model_available"]:
            raise ElevenLabsRealtimeError("model_unavailable")
        session = ElevenLabsRealtimeSession(api_key=key, voice_id=ASSISTANT_VOICE_PROVIDER_IDS["george"],
                                           receive_timeout_seconds=12, max_session_seconds=30,
                                           max_input_characters=150, max_input_count=2, max_audio_bytes=1024 * 1024)
        key = None
        started = monotonic()
        first_audio = asyncio.Event()
        second_sent = False
        await session.open()

        async def reader() -> None:
            async for event in session.audio_events():
                if event.audio_bytes:
                    result["audio_chunks"] += 1
                    if not first_audio.is_set():
                        result["first_audio_before_second_input"] = not second_sent
                        result["first_audio_ms"] = round((monotonic() - started) * 1000)
                        first_audio.set()
                if event.alignment:
                    result["alignment_chunks"] += 1
                    if len(result["first_alignment_chunks"]) < 2:
                        item = event.alignment
                        result["first_alignment_chunks"].append({
                            "character_count": len(item.chars),
                            "first_start_ms": item.char_start_times_ms[0],
                            "last_end_ms": item.char_start_times_ms[-1] + item.char_durations_ms[-1],
                        })
                if event.final:
                    result["final"] = True

        async with asyncio.timeout(30):
            task = asyncio.create_task(reader())
            try:
                await session.append_text("Hello. This is a short test of a live spoken reply. ")
                await session.flush()
                waiter = asyncio.create_task(first_audio.wait())
                try:
                    done, _ = await asyncio.wait((task, waiter), timeout=12, return_when=asyncio.FIRST_COMPLETED)
                    if task in done:
                        await task
                    if not first_audio.is_set():
                        raise ElevenLabsRealtimeError("first_audio_timeout")
                finally:
                    waiter.cancel()
                    await asyncio.gather(waiter, return_exceptions=True)
                second_sent = True
                await session.append_text("Thank you. The test is complete.")
                await session.flush()
                await session.finish_input()
                await task
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        result["elapsed_ms"] = round((monotonic() - started) * 1000)
        result["input_count"] = session.input_count
        result["submitted_characters"] = session.submitted_characters
        chunks = result["first_alignment_chunks"]
        # Only an observation; don't infer precise MP3 turn boundaries/timebase.
        result["second_alignment_starts_after_first_end"] = (
            chunks[1]["first_start_ms"] >= chunks[0]["last_end_ms"] if len(chunks) == 2 else None)
        result["success"] = bool(result["final"] and result["first_audio_before_second_input"] and session.input_count == 2)
    except Exception as error:
        # Fixed content-free categories only; never an upstream body/message.
        result["failure"] = True
        safe_codes = {"invalid_configuration", "credentials_unavailable", "invalid_state", "handshake_failed",
                      "send_failed", "session_timeout", "invalid_input", "input_limit", "keepalive_failed",
                      "invalid_event", "provider_error", "audio_limit", "invalid_audio", "invalid_alignment",
                      "unexpected_final", "concurrent_receive", "cancelled", "truncated_stream", "receive_timeout",
                      "transport_failed", "model_availability_failed", "model_unavailable", "first_audio_timeout"}
        result["failure_code"] = error.code if isinstance(error, ElevenLabsRealtimeError) and error.code in safe_codes else "probe_failed"
        if session is not None:
            result["last_event_shape"] = session.last_event_shape
        if isinstance(error, ElevenLabsRealtimeError):
            for code in ("invalid_alignment", "receive_timeout", "handshake_failed", "model_unavailable", "first_audio_timeout"):
                result["failed_" + code] = error.code == code
    finally:
        if session is not None:
            await session.cancel()
        close = getattr(secrets, "close", None)
        if close is not None:
            with suppress(Exception):
                await close()
        print(json.dumps(result, allow_nan=False), flush=True)
    if not result["success"]:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="One bounded paid synthetic-text provider proof")
    parser.add_argument("--execute-paid-probe", action="store_true", required=True)
    parser.parse_args()
    asyncio.run(run())
