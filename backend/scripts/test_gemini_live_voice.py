#!/usr/bin/env python3
# contract-test-file: tooling
"""Manual Gemini Live voice probe for the video-call experiment.

Runs inside the API container with its Vault-backed Google key. Opens one
connection for at most 20 seconds, sends one benign text turn, and checks that
the production setup produces native audio and modality-level usage. It never
submits a fal request or writes provider media or transcripts to disk.
Usage: docker exec api python /app/backend/scripts/test_gemini_live_voice.py
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import sys
from typing import Any

import aiohttp

from backend.core.api.app.routes.video_call_experiment import GEMINI_MODEL, GEMINI_URL, UsageLedger, _decode_gemini_event, _gemini_setup
from backend.core.api.app.utils.secrets_manager import SecretsManager


def _modalities(details: Any) -> dict[str, int]:
    if not isinstance(details, list):
        raise ValueError("modality usage missing")
    counts: dict[str, int] = {}
    for item in details:
        if not isinstance(item, dict) or not isinstance(item.get("modality"), str):
            raise ValueError("modality usage invalid")
        modality = item["modality"].upper()
        count = int(item.get("tokenCount") or 0)
        if count < 0:
            raise ValueError("modality usage invalid")
        counts[modality] = counts.get(modality, 0) + count
    return counts


async def _probe(key: str) -> dict[str, Any]:
    ledger = UsageLedger()
    audio_bytes = 0
    transcript_present = False
    turn_complete = False
    last_usage: dict[str, Any] | None = None
    setup = _gemini_setup()
    # GenerationConfig supports maxOutputTokens in Live; keep this one turn
    # small without changing the route's production setup contract.
    setup["setup"]["generationConfig"]["maxOutputTokens"] = 256
    async with asyncio.timeout(20):
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None, sock_connect=5)) as session:
            async with session.ws_connect(
                GEMINI_URL, headers={"x-goog-api-key": key}, heartbeat=10,
                max_msg_size=3 * 1024 * 1024,
            ) as socket:
                await socket.send_json(setup)
                reply = _decode_gemini_event(await socket.receive())
                if not isinstance(reply, dict) or "setupComplete" not in reply:
                    raise RuntimeError("setup was not accepted")
                await socket.send_json({"clientContent": {
                    "turns": [{"role": "user", "parts": [{"text": "Say hello briefly."}]}],
                    "turnComplete": True,
                }})
                while not turn_complete:
                    message = await socket.receive()
                    event = _decode_gemini_event(message)
                    if event.get("toolCall"):
                        raise RuntimeError("Unexpected visual tool call")
                    usage = event.get("usageMetadata")
                    if isinstance(usage, dict):
                        last_usage = usage
                        ledger.stage_gemini(usage)
                    content = event.get("serverContent") or {}
                    if isinstance(content, dict):
                        transcript = content.get("outputTranscription") or {}
                        transcript_present |= isinstance(transcript, dict) and bool(transcript.get("text"))
                        turn = content.get("modelTurn") or {}
                        for part in turn.get("parts") or []:
                            inline = part.get("inlineData") if isinstance(part, dict) else None
                            if isinstance(inline, dict) and str(inline.get("mimeType") or "").startswith("audio/"):
                                encoded = inline.get("data")
                                if not isinstance(encoded, str):
                                    raise ValueError("Audio chunk is invalid")
                                audio_bytes += len(base64.b64decode(encoded, validate=True))
                        turn_complete = bool(content.get("turnComplete"))
                ledger.commit_gemini_turn()
    if not last_usage or audio_bytes == 0 or not turn_complete:
        raise RuntimeError("Audio or usage was missing")
    return {
        "status": "pass",
        "provider": "google_ai_studio",
        "model": GEMINI_MODEL,
        "setup_accepted": True,
        "turn_complete": turn_complete,
        "audio_bytes": audio_bytes,
        "transcript_present": transcript_present,
        "input_modalities": _modalities(last_usage.get("promptTokensDetails")),
        "output_modalities": _modalities(last_usage.get("responseTokensDetails")),
        "tool_use_modalities": _modalities(last_usage.get("toolUsePromptTokensDetails") or []),
        "prompt_tokens": ledger.prompt_tokens,
        "output_tokens": ledger.response_tokens,
        "tool_use_prompt_tokens": ledger.tool_use_prompt_tokens,
        "provider_cost_usd": str(ledger.gemini_cost),
        "credits_at_1_2x": str(ledger.accrued_credits),
    }


async def main() -> int:
    logging.disable(logging.CRITICAL)
    manager = SecretsManager()
    try:
        await manager.initialize()
        key = await manager.get_secret("kv/data/providers/google_ai_studio", "api_key")
        if not key:
            raise RuntimeError("Google key unavailable")
        result = await _probe(key)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        # Provider payloads and credentials can appear in exception messages.
        print(json.dumps({"status": "fail", "provider": "google_ai_studio", "error_type": type(exc).__name__}))
        return 1
    finally:
        await manager.aclose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
