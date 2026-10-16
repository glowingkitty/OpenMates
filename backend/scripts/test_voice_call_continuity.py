#!/usr/bin/env python3
# contract-test-file: tooling
"""Bounded real-provider check of the shipped voice adapter's saved context.

Run in the dev API container. Uses the existing Gemini Live model without an
inference override; keeps all audio/transcript data in memory and reports only
checks and byte counts. The conversation contains fictional test facts.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging

from backend.apps.ai.utils.instruction_loader import load_base_instructions
from backend.apps.ai.utils.mate_utils import load_mates_config
from backend.apps.ai.utils.voice_mate import mate_voice_configuration
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.providers.gemini_live_voice import GeminiLiveVoiceSession


async def main() -> int:
    logging.disable(logging.CRITICAL)
    manager = SecretsManager()
    provider = None
    try:
        await manager.initialize()
        key = await manager.get_secret("kv/data/providers/google_ai_studio", "api_key")
        if not key:
            raise RuntimeError("Provider key unavailable")
        mate = next(mate for mate in load_mates_config() if mate.category == "software_development")
        configuration = mate_voice_configuration(mate)
        provider = GeminiLiveVoiceSession(key)
        async with asyncio.timeout(30):
            await provider.open(summary="", messages=[
                {"role": "user", "text": "My fictional project Lantern has the test phrase cerulean hazelnut."},
                {"role": "assistant", "text": "Understood. I will keep Lantern's test phrase in mind."},
            ], base_instruction=load_base_instructions()["base_ethics_instruction"],
                mate_instruction=configuration["mate_instruction"], voice_name=configuration["voice_name"])
            await provider.send_text("What is Lantern's test phrase from our earlier conversation? Also tell me your mate name, in one short sentence.")
            transcript = []
            audio_bytes = 0
            complete = False
            while not complete:
                event = await provider.receive()
                if event.get("toolCall"):
                    raise RuntimeError("Unexpected tool call")
                content = event.get("serverContent") or {}
                text = (content.get("outputTranscription") or {}).get("text")
                if isinstance(text, str):
                    transcript.append(text)
                for part in (content.get("modelTurn") or {}).get("parts") or []:
                    inline = part.get("inlineData") or {}
                    if str(inline.get("mimeType", "")).startswith("audio/"):
                        audio_bytes += len(base64.b64decode(inline["data"], validate=True))
                complete = content.get("turnComplete") is True
        normalized = "".join(character.lower() for character in "".join(transcript) if character.isalnum())
        recalled = "ceruleanhazelnut" in normalized
        identity = mate.name.lower() in normalized
        result = {"status": "pass" if recalled and identity and audio_bytes > 0 else "fail",
                  "model": provider.model, "history_fact_recalled": recalled,
                  "canonical_mate_identified": identity, "audio_bytes": audio_bytes,
                  "turn_complete": complete, "transcript_saved": False}
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] == "pass" else 1
    except Exception as error:
        print(json.dumps({"status": "fail", "error_type": type(error).__name__}))
        return 1
    finally:
        if provider:
            await provider.close()
        await manager.aclose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
