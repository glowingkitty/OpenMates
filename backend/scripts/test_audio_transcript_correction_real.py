#!/usr/bin/env python3
"""
Purpose: Run real Gemini transcript-correction probes for audio transcripts.
Architecture: Executes inside the api container with Vault-backed provider secrets.
Data sources: Fixed synthetic raw transcript examples in English and German.
Tests: Calls TranscribeSkill._correct_transcript_with_gemini with real inference.
Usage: docker exec api python /app/backend/scripts/test_audio_transcript_correction_real.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

from backend.apps.audio.skills.transcribe_skill import (
    GEMINI_CORRECTION_MODEL,
    TranscribeSkill,
)
from backend.core.api.app.utils.secrets_manager import SecretsManager


SAMPLES: list[dict[str, str]] = [
    {
        "id": "en_self_correction_search",
        "language": "en",
        "raw": (
            "um can you search for yellow storage boxes actually no wait green storage boxes "
            "and show me the cheapest ones under fifty euros with delivery by friday"
        ),
    },
    {
        "id": "en_long_rambling_planning",
        "language": "en",
        "raw": (
            "okay so I need you to make a plan for next week um not like a full business plan "
            "just a simple schedule and I changed my mind do not include monday morning because I have a dentist appointment "
            "and also add two focus blocks for writing the investor update and one grocery reminder for thursday evening"
        ),
    },
    {
        "id": "de_self_correction_search",
        "language": "de",
        "raw": (
            "\u00e4hm such mal bitte nach gelben aufbewahrungsboxen nein warte gr\u00fcnen boxen "
            "und zeig mir die g\u00fcnstigsten unter f\u00fcnfzig euro mit lieferung bis freitag"
        ),
    },
    {
        "id": "de_long_rambling_planning",
        "language": "de",
        "raw": (
            "also ich brauche f\u00fcr n\u00e4chste woche so einen plan aber nicht zu detailliert "
            "\u00e4hm montag vormittag doch nicht weil zahnarzt und dann bitte zwei bl\u00f6cke "
            "f\u00fcr den investorenbericht einbauen und donnerstag abend einkaufen erinnern"
        ),
    },
]


async def run_sample(skill: TranscribeSkill, api_key: str, sample: dict[str, str]) -> dict[str, Any]:
    try:
        correction = await skill._correct_transcript_with_gemini(
            raw_transcript=sample["raw"],
            google_api_key=api_key,
            detected_language=sample["language"],
        )
        return {
            "id": sample["id"],
            "language": sample["language"],
            "status": "pass",
            "model": GEMINI_CORRECTION_MODEL,
            "title": correction["title"],
            "before": sample["raw"],
            "after": correction["corrected_transcript"],
        }
    except Exception as exc:
        return {
            "id": sample["id"],
            "language": sample["language"],
            "status": "fail",
            "model": GEMINI_CORRECTION_MODEL,
            "before": sample["raw"],
            "error": str(exc),
        }


async def main() -> int:
    secrets_manager = SecretsManager()
    await secrets_manager.initialize()
    try:
        google_api_key = await secrets_manager.get_secret(
            secret_path="kv/data/providers/google_ai_studio",
            secret_key="api_key",
        )
        if not google_api_key:
            print(json.dumps({"status": "fail", "error": "Google AI Studio API key not configured"}))
            return 1

        skill = object.__new__(TranscribeSkill)
        results = []
        for sample in SAMPLES:
            results.append(await run_sample(skill, google_api_key, sample))

        status = "pass" if all(result["status"] == "pass" for result in results) else "fail"
        print(json.dumps({"status": status, "results": results}, ensure_ascii=False, indent=2))
        return 0 if status == "pass" else 1
    finally:
        await secrets_manager.aclose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
