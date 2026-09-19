"""Shared Gemini transcript correction used by batch and realtime audio flows."""

from __future__ import annotations

import re
from typing import Optional

import httpx

GEMINI_CORRECTION_MODEL = "gemini-3.5-flash"
GEMINI_TRANSCRIPT_TOOL_NAME = "finalize_transcript"
TRANSCRIPT_TITLE_MAX_LENGTH = 80


def clean_transcript_title(title: Optional[str]) -> str:
    """Return a compact, single-line title for a recording transcript."""
    cleaned = re.sub(r"\s+", " ", (title or "").strip().strip("\"'")).strip(" .")
    if not cleaned:
        return "Voice note"
    if len(cleaned) > TRANSCRIPT_TITLE_MAX_LENGTH:
        return cleaned[:TRANSCRIPT_TITLE_MAX_LENGTH].rstrip()
    return cleaned


async def correct_transcript_with_gemini(
    raw_transcript: str,
    google_api_key: str,
    detected_language: Optional[str] = None,
) -> dict[str, str]:
    """Clean a raw speech transcript while preserving intent and language."""
    if not raw_transcript.strip():
        raise ValueError("Cannot correct an empty transcript")

    language_context = (
        f"Detected or requested transcript language: {detected_language}.\n"
        if detected_language
        else "No language hint was provided; infer the language from the transcript.\n"
    )
    prompt = (
        "You are correcting a raw speech-to-text transcript from an audio recording.\n"
        "Your goal is to output a clean, coherent written instruction or message while "
        "preserving the speaker's original intent, meaning, and informal tone.\n"
        f"{language_context}"
        "Keep the output in the same language as the input. Do not translate. "
        "This includes German, English, mixed-language messages, and dialectal phrasing.\n\n"
        "Rules:\n"
        "1. Remove speech disfluencies and fillers (e.g., 'umm', 'uhh', 'ahh', 'like', 'ehh').\n"
        "2. Resolve verbal self-corrections and rambling where the speaker changed their mind.\n"
        "3. Correct obvious phonetic mistranscriptions or spelling of technical terms.\n"
        "4. Add capitalization and natural punctuation.\n"
        "5. Do not invent claims or change the original meaning.\n"
        "6. For long or confusing recordings, keep every concrete requirement; use short "
        "sentences or bullets only when useful.\n"
        "7. If the input is already clean, only adjust punctuation or formatting.\n\n"
        "Call the finalize_transcript function with the final title and corrected transcript.\n"
        "Keep the title in the transcript language, 3 to 8 words when possible, without "
        "quotes, markdown, or invented facts. Use 'Voice note' when the recording is unclear."
    )
    body = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": prompt},
                    {"text": f'Raw Transcript:\n"{raw_transcript}"'},
                ],
            }
        ],
        "tools": [
            {
                "functionDeclarations": [
                    {
                        "name": GEMINI_TRANSCRIPT_TOOL_NAME,
                        "description": "Return the cleaned transcript and compact display title.",
                        "parameters": {
                            "type": "OBJECT",
                            "required": ["title", "corrected_transcript"],
                            "properties": {
                                "title": {"type": "STRING"},
                                "corrected_transcript": {"type": "STRING"},
                            },
                        },
                    }
                ]
            }
        ],
        "toolConfig": {
            "functionCallingConfig": {
                "mode": "ANY",
                "allowedFunctionNames": [GEMINI_TRANSCRIPT_TOOL_NAME],
            }
        },
        "generationConfig": {"temperature": 0.1},
    }
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_CORRECTION_MODEL}:generateContent"
    )
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, params={"key": google_api_key}, json=body)
        if response.status_code != 200:
            raise RuntimeError(
                f"Gemini correction API failed: {response.status_code} {response.text[:500]}"
            )
        parts = (
            response.json()
            .get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [])
        )
        for part in parts:
            function_call = part.get("functionCall") if isinstance(part, dict) else None
            if (
                not isinstance(function_call, dict)
                or function_call.get("name") != GEMINI_TRANSCRIPT_TOOL_NAME
            ):
                continue
            args = function_call.get("args")
            if not isinstance(args, dict):
                raise RuntimeError("Gemini transcript tool call did not contain args")
            corrected = str(args.get("corrected_transcript") or "").strip()
            if not corrected:
                raise RuntimeError(
                    "Gemini transcript tool call did not contain corrected_transcript"
                )
            return {
                "title": clean_transcript_title(str(args.get("title") or "")),
                "corrected_transcript": corrected,
            }
        raise RuntimeError(
            f"Gemini correction did not call {GEMINI_TRANSCRIPT_TOOL_NAME}"
        )
    except Exception as exc:
        raise RuntimeError(f"Failed to run Gemini correction: {exc}") from exc
