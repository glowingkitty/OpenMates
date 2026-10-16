#!/usr/bin/env python3
# contract-test-file: tooling
"""Bounded real-Gemini diagnostic for the deployed voice-only adapter.

Run only in the authorized dev API container after candidate deployment. Two
short sessions generate a synthetic question, then exercise speech and typed
input with existing-chat context. Audio and transcripts remain in memory; the
printed receipt contains only counts, booleans and provider cost.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import struct
import sys
from typing import Any

from backend.core.api.app.routes.video_call_experiment import UsageLedger
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.providers.gemini_live_voice import GeminiLiveVoiceSession


async def receive_turn(session: GeminiLiveVoiceSession) -> dict[str, Any]:
    ledger = UsageLedger()
    audio = bytearray()
    input_seen = output_seen = False
    context_seen = False
    async with asyncio.timeout(25):
        while True:
            event = await session.receive()
            if event.get("toolCall"):
                raise RuntimeError("Unexpected tool call in voice-only diagnostic")
            ledger.observe_gemini_output(event)
            if isinstance(event.get("usageMetadata"), dict):
                ledger.stage_gemini(event["usageMetadata"])
            content = event.get("serverContent") or {}
            input_seen |= bool((content.get("inputTranscription") or {}).get("text"))
            transcript = (content.get("outputTranscription") or {}).get("text", "")
            output_seen |= bool(transcript)
            context_seen |= "ramen" in transcript.lower()
            for part in (content.get("modelTurn") or {}).get("parts") or []:
                inline = part.get("inlineData") or {}
                if str(inline.get("mimeType", "")).startswith("audio/") and inline.get("data"):
                    audio.extend(base64.b64decode(inline["data"], validate=True))
                    if len(audio) > 2 * 1024 * 1024:
                        raise RuntimeError("Diagnostic audio exceeded its bound")
            if content.get("turnComplete"):
                ledger.commit_gemini_turn()
                return {"audio": bytes(audio), "input_transcript": input_seen,
                        "output_transcript": output_seen, "context_recognized": context_seen,
                        "cost_usd": float(ledger.gemini_cost),
                        "input_tokens": ledger.prompt_tokens, "output_tokens": ledger.response_tokens}


def pcm24_to_16(audio: bytes) -> bytes:
    samples = struct.unpack(f"<{len(audio) // 2}h", audio)
    result = bytearray()
    for index in range(0, len(samples) - 2, 3):
        result.extend(struct.pack("<hh", samples[index], (samples[index + 1] + samples[index + 2]) // 2))
    return bytes(result)


async def main() -> int:
    secrets = SecretsManager()
    preparation = call = None
    try:
        await secrets.initialize()
        key = await secrets.get_secret("kv/data/providers/google_ai_studio", "api_key")
        if not key:
            raise RuntimeError("Google credential unavailable")
        preparation = GeminiLiveVoiceSession(key)
        call = GeminiLiveVoiceSession(key)
        async with asyncio.timeout(65):
            await preparation.open(summary="", messages=[])
            await preparation.send_text("Speak exactly this short question and nothing else: How do I make ramen?")
            synthetic = await receive_turn(preparation)
            await preparation.close()
            if not synthetic["audio"] or not synthetic["output_transcript"]:
                raise RuntimeError("Synthetic speech preparation failed")
            await call.open(summary="The user is discussing vegetarian ramen.", messages=[
                {"role": "user", "text": "I want vegetarian ramen. Please keep every reply to one short sentence."},
                {"role": "assistant", "text": "We can discuss vegetarian ramen in short sentences."},
            ])
            pcm = pcm24_to_16(synthetic["audio"]) + b"\0\0" * 16_000
            for offset in range(0, len(pcm), 3200):
                await call.send_audio(base64.b64encode(pcm[offset:offset + 3200]).decode("ascii"))
                await asyncio.sleep(0.05)
            spoken = await receive_turn(call)
            await call.send_text("I pasted this ingredient list: mushrooms and ginger. Suggest one change to the ramen, in one sentence.")
            typed = await receive_turn(call)
            if not spoken["input_transcript"] or not spoken["output_transcript"] or not typed["output_transcript"]:
                raise RuntimeError("Speech or typed transcript missing")
            if not spoken["audio"] or not typed["audio"]:
                raise RuntimeError("Native output audio missing")
            print(json.dumps({"result": "passed", "model": call.model,
                "speech_input_transcript": spoken["input_transcript"],
                "speech_output_transcript": spoken["output_transcript"],
                "typed_output_transcript": typed["output_transcript"],
                "context_recognized": spoken["context_recognized"] or typed["context_recognized"],
                "speech_audio_bytes": len(spoken["audio"]), "typed_audio_bytes": len(typed["audio"]),
                "provider_cost_usd": sum(turn["cost_usd"] for turn in (synthetic, spoken, typed)),
                "saved_media_or_transcripts": False}, sort_keys=True))
            return 0
    except Exception as exc:
        print(json.dumps({"result": "failed", "error_type": type(exc).__name__,
                          "saved_media_or_transcripts": False}, sort_keys=True))
        return 1
    finally:
        if preparation is not None:
            await preparation.close()
        if call is not None:
            await call.close()
        await secrets.close()


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    sys.exit(asyncio.run(main()))
