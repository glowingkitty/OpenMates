"""Fast correction of workflow voice instructions via existing providers."""

from __future__ import annotations

import json
from typing import Optional

import httpx

GROQ_WORKFLOW_CORRECTION_MODEL = "openai/gpt-oss-20b"
GROQ_WORKFLOW_CORRECTION_URL = "https://api.groq.com/openai/v1/chat/completions"
CEREBRAS_WORKFLOW_CORRECTION_MODEL = "gpt-oss-120b"
CEREBRAS_WORKFLOW_CORRECTION_URL = "https://api.cerebras.ai/v1/chat/completions"


async def correct_workflow_transcript_with_groq(
    raw_transcript: str,
    api_key: str,
    detected_language: Optional[str] = None,
) -> dict[str, str]:
    return await _correct_workflow_transcript(
        raw_transcript,
        api_key,
        detected_language,
        model=GROQ_WORKFLOW_CORRECTION_MODEL,
        url=GROQ_WORKFLOW_CORRECTION_URL,
        reasoning_effort="low",
    )


async def correct_workflow_transcript_with_cerebras(
    raw_transcript: str,
    api_key: str,
    detected_language: Optional[str] = None,
) -> dict[str, str]:
    return await _correct_workflow_transcript(
        raw_transcript,
        api_key,
        detected_language,
        model=CEREBRAS_WORKFLOW_CORRECTION_MODEL,
        url=CEREBRAS_WORKFLOW_CORRECTION_URL,
    )


async def _correct_workflow_transcript(
    raw_transcript: str,
    api_key: str,
    detected_language: Optional[str],
    *,
    model: str,
    url: str,
    reasoning_effort: Optional[str] = None,
) -> dict[str, str]:
    """Remove speech disfluencies while retaining the speaker's final requirements."""
    if not raw_transcript.strip():
        raise ValueError("Cannot correct an empty transcript")

    language_hint = (
        f"Detected language: {detected_language}. " if detected_language else ""
    )
    body = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Clean the user's raw speech transcript into a written workflow "
                    "instruction. Remove fillers and superseded statements. Preserve "
                    "every final requirement, especially corrections to times, days, "
                    "locations and topics. Correct obvious speech-to-text mistakes. "
                    "Keep the original language, including mixed-language input. "
                    "Do not translate or invent details. "
                    f"{language_hint}"
                    "Return only a JSON object with one key, corrected_transcript."
                ),
            },
            {"role": "user", "content": raw_transcript},
        ],
        "temperature": 0.1,
        "max_completion_tokens": min(
            4096, max(300, len(raw_transcript.split()) * 3 + 128)
        ),
        "response_format": {"type": "json_object"},
    }
    if reasoning_effort:
        body["reasoning_effort"] = reasoning_effort
    async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=2.0)) as client:
        response = await client.post(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            json=body,
        )
    response.raise_for_status()
    message = response.json()["choices"][0]["message"]
    result = json.loads(message["content"])
    corrected = result.get("corrected_transcript")
    if not isinstance(corrected, str) or not corrected.strip():
        raise ValueError("Workflow correction returned no transcript")
    return {"corrected_transcript": corrected.strip()}
