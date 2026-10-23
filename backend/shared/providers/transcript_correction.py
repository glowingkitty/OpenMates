"""Provider-neutral audio correction with a bounded Mercury attempt and Gemini fallback."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from backend.shared.providers.gemini_transcript_correction import (
    GEMINI_CORRECTION_MODEL,
    GEMINI_TRANSCRIPT_TOOL_NAME,
    build_transcript_correction_prompt,
    clean_transcript_title,
    correct_transcript_with_gemini,
)
from backend.shared.providers.inception import InceptionClient, InceptionRequest, resolve_api_key

logger = logging.getLogger(__name__)
MERCURY_CORRECTION_MODEL = "mercury-3"
MERCURY_CORRECTION_TIMEOUT_SECONDS = 5.0


def mercury_correction_enabled() -> bool:
    """Enable user transcript processing only after account training opt-out is verified."""
    return os.getenv("INCEPTION_TRANSCRIPT_CORRECTION_ENABLED", "").strip().lower() in {
        "1", "true", "yes",
    }


async def correct_transcript_with_mercury(
    raw_transcript: str,
    api_key: str,
    detected_language: str | None = None,
) -> dict[str, str]:
    """Return the same title/text contract as Gemini without exposing provider bodies."""
    if not raw_transcript.strip():
        raise ValueError("Cannot correct an empty transcript")
    request = InceptionRequest(
        model=MERCURY_CORRECTION_MODEL,
        messages=[
            {"role": "system", "content": build_transcript_correction_prompt(detected_language)},
            {"role": "user", "content": f'Raw Transcript:\n"{raw_transcript}"'},
        ],
        temperature=0.5,
        reasoning_effort="low",
        max_completion_tokens=8192,
        tools=[{
            "type": "function",
            "function": {
                "name": GEMINI_TRANSCRIPT_TOOL_NAME,
                "description": "Return the cleaned transcript and compact display title.",
                "parameters": {
                    "type": "object",
                    "properties": {"title": {"type": "string"}, "corrected_transcript": {"type": "string"}},
                    "required": ["title", "corrected_transcript"],
                    "additionalProperties": False,
                },
            },
        }],
        tool_choice={"type": "function", "function": {"name": GEMINI_TRANSCRIPT_TOOL_NAME}},
    )
    # A total deadline also bounds any network activity and connection setup.
    async with asyncio.timeout(MERCURY_CORRECTION_TIMEOUT_SECONDS):
        result = await InceptionClient(
            api_key, timeout=MERCURY_CORRECTION_TIMEOUT_SECONDS, max_retries=0,
        ).complete(request)
    # Native nonstream Mercury may report "stop" for a completed forced function call.
    # Still reject truncated/blocked results before validating the sole tool and its fields.
    if len(result.choices) != 1 or result.choices[0].get("finish_reason") not in {"stop", "tool_calls"}:
        raise RuntimeError("Mercury correction did not finish with a transcript tool call")
    calls = result.choices[0].get("message", {}).get("tool_calls") or []
    if len(calls) != 1 or calls[0].get("function", {}).get("name") != GEMINI_TRANSCRIPT_TOOL_NAME:
        raise RuntimeError("Mercury correction returned an unexpected tool call")
    try:
        args = json.loads(calls[0]["function"]["arguments"])
    except (ValueError, TypeError, KeyError):
        raise RuntimeError("Mercury correction returned invalid transcript arguments") from None
    if (not isinstance(args, dict) or not isinstance(args.get("title"), str)
            or not isinstance(args.get("corrected_transcript"), str)
            or not args["corrected_transcript"].strip()):
        raise RuntimeError("Mercury correction returned invalid transcript fields")
    return {
        "title": clean_transcript_title(args["title"]),
        "corrected_transcript": args["corrected_transcript"].strip(),
    }


async def correct_transcript(
    raw_transcript: str,
    secrets_manager: Any,
    detected_language: str | None = None,
) -> dict[str, str]:
    """Correct once with Mercury when enabled, retaining the established Gemini fallback."""
    if not raw_transcript.strip():
        raise ValueError("Cannot correct an empty transcript")
    if mercury_correction_enabled():
        try:
            # Credential lookup shares the provider budget; an unavailable Vault
            # must not delay the established Gemini recovery indefinitely.
            async with asyncio.timeout(MERCURY_CORRECTION_TIMEOUT_SECONDS):
                key = await resolve_api_key(secrets_manager)
                result = await correct_transcript_with_mercury(raw_transcript, key, detected_language)
            return {**result, "model": MERCURY_CORRECTION_MODEL}
        except Exception as exc:
            logger.warning("Mercury transcript correction failed (%s); trying Gemini", type(exc).__name__)
    key = await secrets_manager.get_secret("kv/data/providers/google_ai_studio", "api_key")
    if not key:
        raise RuntimeError("Transcript correction is unavailable")
    result = await correct_transcript_with_gemini(raw_transcript, key, detected_language)
    return {**result, "model": GEMINI_CORRECTION_MODEL}
