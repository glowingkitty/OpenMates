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
from backend.shared.providers.transcript_correction_accounting import (
    admitted_correction, correction_output_limit, settle_correction, CorrectionAccountingError, correction_dispatch_transport,
)
from backend.shared.providers.inception import InceptionClient, InceptionRequest, resolve_api_key

logger = logging.getLogger(__name__)
MERCURY_CORRECTION_MODEL = "mercury-3"
MERCURY_CORRECTION_TIMEOUT_SECONDS = 5.0
MERCURY_DICTATION_EDIT_GUIDANCE = (
    "Resolve spoken edits before polishing the text. Read the whole transcript part and "
    "identify what each later correction replaces. A correction can replace an entire "
    "earlier proposal across sentence boundaries. When the speaker settles on a different "
    "way to achieve the same goal, remove the abandoned approach and merge the original goal "
    "into the final request. Before returning text, check that every detail still in force "
    "is present, including the purpose, recipients, restrictions, quoted wording, and exact "
    "identifiers. Preserve independent instructions, genuine alternatives, and uncertainty. "
    "Remove a correction cue only when it is being used to edit the speaker's words.\n\n"
    "Example: \"Let's keep a file of approved domains. Wait, I need a way to add domains for "
    "testing. We could have a file, no actually add a command to the admin CLI to approve "
    "domains, starting with example.org.\" → \"Add an admin CLI command to approve domains "
    "for testing, starting with example.org.\"\n"
    "Example: \"Ask Sam for the report by Tuesday, actually Thursday, and keep the original "
    "charts. Maybe email it, or post it in the channel.\" → \"Ask Sam for the report by "
    "Thursday and keep the original charts. Email it or post it in the channel.\"\n\n"
)


def mercury_correction_enabled() -> bool:
    """Enable user transcript processing only after account training opt-out is verified."""
    return os.getenv("INCEPTION_TRANSCRIPT_CORRECTION_ENABLED", "").strip().lower() in {
        "1", "true", "yes",
    }


async def correct_transcript_with_mercury(
    raw_transcript: str,
    api_key: str,
    detected_language: str | None = None,
    *,
    include_title: bool = True,
) -> dict[str, str]:
    """Return corrected text and, for saved recordings, its display title."""
    if not raw_transcript.strip():
        raise ValueError("Cannot correct an empty transcript")
    prompt = build_transcript_correction_prompt(detected_language, include_title=include_title)
    if not include_title:
        prompt = MERCURY_DICTATION_EDIT_GUIDANCE + prompt
    properties = {"title": {"type": "string"}} if include_title else {}
    properties["corrected_transcript"] = {"type": "string"}
    request = InceptionRequest(
        model=MERCURY_CORRECTION_MODEL,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": f'Raw Transcript:\n"{raw_transcript}"'},
        ],
        temperature=0.5,
        reasoning_effort="low",
        max_completion_tokens=correction_output_limit(8192),
        tools=[{
            "type": "function",
            "function": {
                "name": GEMINI_TRANSCRIPT_TOOL_NAME,
                "description": (
                    "Return the cleaned transcript and compact display title."
                    if include_title else "Return the cleaned transcript."
                ),
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": list(properties),
                    "additionalProperties": False,
                },
            },
        }],
        tool_choice={"type": "function", "function": {"name": GEMINI_TRANSCRIPT_TOOL_NAME}},
    )
    # A total deadline also bounds any network activity and connection setup.
    async with admitted_correction(
        MERCURY_CORRECTION_MODEL,
        len(prompt.encode("utf-8")) + len(raw_transcript.encode("utf-8")) + 8192,
        request.max_completion_tokens,
    ) as accounting:
        async with asyncio.timeout(MERCURY_CORRECTION_TIMEOUT_SECONDS):
            client = InceptionClient(
                api_key, timeout=MERCURY_CORRECTION_TIMEOUT_SECONDS, max_retries=0,
                **({"transport": correction_dispatch_transport(accounting)} if accounting is not None else {}),
            )
            result = await client.complete(request)
        if accounting is not None:
            usage = result.usage
            await settle_correction(accounting, getattr(usage, "prompt_tokens", None), getattr(usage, "completion_tokens", None))
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
    if (not isinstance(args, dict) or (include_title and not isinstance(args.get("title"), str))
            or not isinstance(args.get("corrected_transcript"), str)
            or not args["corrected_transcript"].strip()):
        raise RuntimeError("Mercury correction returned invalid transcript fields")
    transcript = {"corrected_transcript": args["corrected_transcript"].strip()}
    if include_title:
        transcript["title"] = clean_transcript_title(args["title"])
    return transcript


async def correct_transcript(
    raw_transcript: str,
    secrets_manager: Any,
    detected_language: str | None = None,
    *,
    include_title: bool = True,
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
                result = await correct_transcript_with_mercury(
                    raw_transcript, key, detected_language, include_title=include_title
                )
            return {**result, "model": MERCURY_CORRECTION_MODEL}
        except CorrectionAccountingError:
            raise
        except Exception as exc:
            logger.warning("Mercury transcript correction failed (%s); trying Gemini", type(exc).__name__)
    key = await secrets_manager.get_secret("kv/data/providers/google_ai_studio", "api_key")
    if not key:
        raise RuntimeError("Transcript correction is unavailable")
    result = await correct_transcript_with_gemini(
        raw_transcript, key, detected_language, include_title=include_title
    )
    return {**result, "model": GEMINI_CORRECTION_MODEL}
