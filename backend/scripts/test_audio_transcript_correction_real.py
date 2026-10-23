#!/usr/bin/env python3
"""
Purpose: Check real composer transcript cleanup and final-intent preservation.
Architecture: Executes inside the api container with Vault-backed provider secrets.
Data sources: User-supplied landing-page sample and synthetic English/German speech.
Tests: Calls the shared correction policy with default routing and semantic checks.
Usage: docker exec api python /app/backend/scripts/test_audio_transcript_correction_real.py
"""
# contract-test-file: tooling

from __future__ import annotations

import asyncio
import json
import re
import sys
from typing import Any

from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.providers.transcript_correction import correct_transcript


SAMPLES: list[dict[str, Any]] = [
    {
        "id": "en_self_correction_search",
        "language": "en",
        "raw": (
            "um can you search for yellow storage boxes actually no wait green storage boxes "
            "and show me the cheapest ones under fifty euros with delivery by friday"
        ),
        "required": [r"\bgreen\b", r"\b(?:fifty|50)\b", r"\bfriday\b", r"\bdeliver\w*\b"],
        "forbidden": [r"\byellow\b", r"\bactually\b", r"\bno wait\b"],
    },
    {
        "id": "en_long_rambling_planning",
        "language": "en",
        "raw": (
            "okay so I need you to make a plan for next week um not like a full business plan "
            "just a simple schedule and I changed my mind do not include monday morning because I have a dentist appointment "
            "and also add two focus blocks for writing the investor update and one grocery reminder for thursday evening"
        ),
        "required": [r"\bnext week\b", r"\bmonday morning\b", r"\bdentist\b",
                     r"\b(?:two|2)\b", r"\binvestor update\b", r"\bthursday evening\b",
                     r"\b(?:grocery|groceries)\b", r"\b(?:not|no|exclude|except|avoid|leave out|skip)\b"],
    },
    {
        "id": "de_self_correction_search",
        "language": "de",
        "raw": (
            "\u00e4hm such mal bitte nach gelben aufbewahrungsboxen nein warte gr\u00fcnen boxen "
            "und zeig mir die g\u00fcnstigsten unter f\u00fcnfzig euro mit lieferung bis freitag"
        ),
        "required": [r"\bgr\u00fcn\w*\b", r"\b(?:f\u00fcnfzig|50)\b", r"\bfreitag\b", r"\bliefer\w*\b"],
        "forbidden": [r"\bgelb\w*\b", r"\bnein warte\b"],
    },
    {
        "id": "de_long_rambling_planning",
        "language": "de",
        "raw": (
            "also ich brauche f\u00fcr n\u00e4chste woche so einen plan aber nicht zu detailliert "
            "\u00e4hm montag vormittag doch nicht weil zahnarzt und dann bitte zwei bl\u00f6cke "
            "f\u00fcr den investorenbericht einbauen und donnerstag abend einkaufen erinnern"
        ),
        "required": [r"\bn\u00e4chste\w* woche\b", r"\bmontag\w*\b", r"\b(?:montags?)?vormittag\w*\b",
                     r"\bzahnarzt\w*\b", r"\b(?:zwei|2)\b", r"\binvestorenbericht\w*\b",
                     r"\bdonnerstag\w*\b", r"\b(?:donnerstags?)?abend\w*\b", r"\beinkauf\w*\b",
                     r"\b(?:nicht|kein\w*|au\u00dfer|ausgenommen)\b"],
    },
    {
        "id": "en_landing_page_concise",
        "language": "en",
        "raw": (
            "Also, I realized that the landing page still shows the old embed preview style. "
            "We must also fix that, so that this example embed preview that animates at the top "
            "is showing the correct new layout. And ideally, we implement a long-term "
            "implementation where the UI is automatically synchronized, so it will never be "
            "out of date with the web app. And yeah, and of course, the embed preview shown on "
            "the landing page must also show, like, an actual event image. We can use, like, a "
            "real example chat event for that, for example, or we can make up one. Also works."
        ),
        "required": [r"\blanding page\b", r"\bembed preview\b", r"\banimat\w*\b",
                     r"\btop\b", r"\bnew layout\b", r"\bideally\b", r"\bautomatic\w*\b",
                     r"\bsync\w*\b", r"\bweb app\b", r"\bevent image\b",
                     r"\breal\b", r"\bexample chat\b", r"\b(?:make (?:one )?up|made.up|invent\w*|fictional)\b"],
        "forbidden": [r"\blong-term implementation\b", r"\byeah\b", r"\blike,"],
        "max_words": 90,
    },
    {
        "id": "en_final_date_and_recipient",
        "language": "en",
        "raw": (
            "Um schedule the review for Tuesday at nine, actually Thursday at ten. "
            "Invite Alice, sorry, invite Bob instead. Keep it online and don't send invites yet."
        ),
        "required": [r"\bthursday\b", r"\b(?:ten|10)\b", r"\bbob\b", r"\bonline\b",
                     r"\b(?:don['\u2019]t|do not|not|no)\b.*\bsend\w*\b.*\binvit\w*\b"],
        "forbidden": [r"\btuesday\b", r"\b(?:nine|9)\b", r"\balice\b", r"\bactually\b", r"\bsorry\b", r"\binstead\b"],
    },
    {
        "id": "en_final_action",
        "language": "en",
        "raw": (
            "Um delete the draft, no, actually archive the draft instead. "
            "Keep the published report unchanged."
        ),
        "required": [r"\barchiv\w*\b", r"\bdraft\b", r"\bpublished report\b", r"\bunchanged\b"],
        "forbidden": [r"\bdelet\w*\b", r"\bactually\b", r"\binstead\b"],
    },
    {
        "id": "en_preserve_contrast_and_alternatives",
        "language": "en",
        "raw": (
            "Don't cancel the meeting; reschedule it. Ideally use Thursday, but Friday "
            "also works. Keep the room booking."
        ),
        "required": [r"\b(?:don['\u2019]t|do not) cancel\b", r"\breschedule\b", r"\bideally\b",
                     r"\bthursday\b", r"\bfriday\b", r"\broom booking\b"],
    },
]


def quality_failures(sample: dict[str, Any], corrected: str) -> list[str]:
    """Reject stale requests, missing concrete details and unremoved repetition."""
    failures = [f"missing: {pattern}" for pattern in sample.get("required", [])
                if not re.search(pattern, corrected, re.IGNORECASE | re.DOTALL)]
    failures.extend(f"superseded_or_filler: {pattern}" for pattern in sample.get("forbidden", [])
                    if re.search(pattern, corrected, re.IGNORECASE | re.DOTALL))
    if sample.get("max_words") and len(corrected.split()) > sample["max_words"]:
        failures.append("redundant_wording_not_condensed")
    return failures


async def run_sample(secrets_manager: SecretsManager, sample: dict[str, Any]) -> dict[str, Any]:
    try:
        correction = await correct_transcript(
            raw_transcript=sample["raw"],
            secrets_manager=secrets_manager,
            detected_language=sample["language"],
        )
        failures = quality_failures(sample, correction["corrected_transcript"])
        return {
            "id": sample["id"],
            "language": sample["language"],
            "status": "fail" if failures else "pass",
            "failures": failures,
            "model": correction["model"],
            "title": correction["title"],
            "before": sample["raw"],
            "after": correction["corrected_transcript"],
        }
    except Exception as exc:
        return {
            "id": sample["id"],
            "language": sample["language"],
            "status": "fail",
            "before": sample["raw"],
            "error": type(exc).__name__,
        }


async def main() -> int:
    secrets_manager = SecretsManager()
    await secrets_manager.initialize()
    try:
        results = []
        for sample in SAMPLES:
            results.append(await run_sample(secrets_manager, sample))

        status = "pass" if all(result["status"] == "pass" for result in results) else "fail"
        print(json.dumps({"status": status, "results": results}, ensure_ascii=False, indent=2))
        return 0 if status == "pass" else 1
    finally:
        await secrets_manager.aclose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
