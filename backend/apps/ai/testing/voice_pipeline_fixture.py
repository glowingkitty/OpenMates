"""Isolated CI provider substitutes for admitted ordinary voice chat turns.

Only external decisions/text/audio are synthetic. Ordinary admission, automatic
model selection, skill execution, embeds, encryption and persistence still run.
"""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
from functools import wraps
import json
import re
from typing import Any, Mapping

from backend.shared.testing.voice_call_fixture import VOICE_RICH_SOURCE_URL, isolated_voice_fixture_enabled


RAMEN_REQUEST = "How do I make ramen?"
RAMEN_RESPONSE = "For ramen, simmer the broth and cook the noodles."
RICH_REQUEST = "Show voice rich results"
RICH_RESPONSE = (
    "# Results\n\nHere are the images I found. See "
    f"[the source]({VOICE_RICH_SOURCE_URL}).\n\n"
)
GERMAN_REQUEST = "Bitte prüfe das gründlich"
GERMAN_RESPONSE = "Ich habe das geprüft. Hier ist das Ergebnis."
GERMAN_RESPONSE_DELAY_SECONDS = 3.5
RICH_RESPONSE_DELAY_SECONDS = 3.0

_voice_request: ContextVar[Any] = ContextVar("isolated_voice_pipeline_request", default=None)


def active(request: Any) -> bool:
    """The request flag has already been validated against the live call registry."""
    return isolated_voice_fixture_enabled() and getattr(request, "voice_mode", False) is True


def request_text(request: Any) -> str:
    content = getattr(request, "current_user_content", None)
    if isinstance(content, str) and content:
        return content.strip()
    for message in reversed(getattr(request, "message_history", []) or []):
        if isinstance(message, Mapping) and message.get("role") == "user":
            return str(message.get("content") or "").strip()
    return ""


def voice_preprocessing_scope(function):
    """Keep deterministic Jev decisions local to this request and its awaits."""
    @wraps(function)
    async def wrapped(*args, **kwargs):
        request = kwargs.get("request_data") if "request_data" in kwargs else args[0]
        token = _voice_request.set(request if active(request) else None)
        try:
            return await function(*args, **kwargs)
        finally:
            _voice_request.reset(token)
    return wrapped


def jev_response(*, questions: Mapping[str, Mapping[str, Any]], model: str):
    """Answer ordinary preprocessing questions; the real router validates them."""
    request = _voice_request.get()
    if not active(request) or not questions:
        return None
    from backend.shared.providers.typesafe.models import DecisionResponse

    text = request_text(request)
    rich = text == RICH_REQUEST
    preferred = {
        "reasoning_level": "low", "complexity": "low", "task_area": "general",
        "topic_area": "general_misc", "topic_shift": "noticeable_shift",
        "temperature": "balanced", "language": "de" if text == GERMAN_REQUEST else "en",
        "preview": "none", "icon": "message-circle", "project_target": "none",
    }
    answers = {}
    for key, question in questions.items():
        kind = question.get("type")
        if kind == "noul":
            instructions = question.get("instructions")
            candidate = instructions.get("candidate_id") if isinstance(instructions, Mapping) else None
            selected = rich and ((key.startswith("app_") and candidate == "images")
                                 or (key.startswith("skill_") and candidate == "images-search"))
            answers[key] = {"type": kind, "noul": float(selected)}
        elif kind == "choice" and isinstance(criteria := question.get("criteria"), Mapping) and criteria:
            chosen = preferred.get(key)
            chosen = chosen if chosen in criteria else next(iter(criteria))
            answers[key] = {"type": kind, "choice": chosen, "confidence": 1.0,
                            "probabilities": {str(value): float(value == chosen) for value in criteria}}
        else:
            return None
    return DecisionResponse.model_validate({"provider": "isolated_voice_fixture", "model": model,
        "answers": answers, "usage": {"input_tokens": 100, "output_tokens": len(answers)}})


def _image_preview_results(tool_results: list[dict]) -> list[dict]:
    """Read the real returned image refs, including normal flattened TOON input."""
    from toon_format import decode

    results: list[dict] = []

    def visit(value: Any) -> None:
        if isinstance(value, list):
            for row in value:
                visit(row)
        elif isinstance(value, dict):
            ref = value.get("embed_ref")
            if (value.get("title") == "Sunset ocean fixture" and isinstance(ref, str)
                    and re.fullmatch(r"[A-Za-z0-9._-]{1,512}", ref)
                    and value.get("source_page_url") == VOICE_RICH_SOURCE_URL
                    and not any(row["embed_ref"] == ref for row in results)):
                results.append(value)
            visit(value.get("results"))

    for message in tool_results:
        if message.get("name") != "images-search":
            continue
        content = message.get("content")
        if not isinstance(content, str):
            continue
        try:
            payload = json.loads(content)
        except ValueError:
            try:
                payload = decode(content)
            except (ValueError, TypeError):
                continue
        visit(payload)
    return results


def _image_preview_refs(tool_results: list[dict]) -> list[str]:
    return [row["embed_ref"] for row in _image_preview_results(tool_results)]


def main_stream(request: Any, *, message_history: list[dict], tools: list[dict] | None,
                model_id: str, max_tokens: int | None, pre_dispatch_admission: Any):
    """Return provider-shaped chunks to the normal main processor, or no fixture."""
    if not active(request):
        return None

    async def stream():
        if pre_dispatch_admission is not None:
            await pre_dispatch_admission(model_id, max_tokens, tariff_snapshot=None, region=None)
        text = request_text(request)
        if text == GERMAN_REQUEST:
            await asyncio.sleep(GERMAN_RESPONSE_DELAY_SECONDS)
        if text == RICH_REQUEST:
            # Read the real tool turn before answering. The skill executor owns
            # image permission grants and the group/card placeholder transport.
            last_user = max((index for index, row in enumerate(message_history)
                             if row.get("role") == "user"), default=-1)
            tool_results = [row for row in message_history[last_user + 1:] if row.get("role") == "tool"]
            if not tool_results:
                names = {tool.get("function", {}).get("name") for tool in tools or []}
                if "images-search" not in names:
                    raise RuntimeError("Voice rich fixture requires the ordinary images-search tool")
                from backend.apps.images.skills.search_skill import E2E_IMAGE_FIXTURE_QUERY_TOKEN
                from backend.apps.ai.llm_providers.openai_shared import ParsedOpenAIToolCall
                arguments = {"requests": [{"query": E2E_IMAGE_FIXTURE_QUERY_TOKEN, "count": 1}]}
                yield ParsedOpenAIToolCall(tool_call_id="isolated-voice-image-search",
                    function_name="images-search", function_arguments_raw=json.dumps(arguments),
                    function_arguments_parsed=arguments)
                return
            image_results = _image_preview_results(tool_results)
            if not image_results:
                raise RuntimeError("Voice rich fixture did not receive a real image-search result with an embed reference")
            # The ordinary image-search prompt requires these preview links.
            # Reuse only the skill's returned refs; finalization still checks
            # them against successfully authored, permission-bound child embeds.
            source_url = image_results[0]["source_page_url"]
            # Model an upstream LLM that keeps writing after the first released
            # sentence. The ordinary audio owner must start native playback
            # during this interval; the browser test measures actual ordering.
            yield "# Results\n\nHere are the images I found. "
            await asyncio.sleep(RICH_RESPONSE_DELAY_SECONDS)
            prose = f"See [the source]({source_url}).\n\n"
            yield prose + "".join(f"[!](embed:{row['embed_ref']})\n" for row in image_results) + "\n"
        elif text == RAMEN_REQUEST:
            yield RAMEN_RESPONSE
        elif text == GERMAN_REQUEST:
            yield GERMAN_RESPONSE
        else:
            yield "I received your text: " + text
    return stream()


def postprocessing_fixture(*, voice_mode: bool, user_message: str,
                           current_chat_title: str | None, user_system_language: str) -> dict | None:
    if not voice_mode or not isolated_voice_fixture_enabled():
        return None
    title = ("Ramen gemeinsam einfach zubereiten" if user_system_language == "de"
             else "Making vegetarian ramen") if "ramen" in user_message.lower() else (
        "Sprachgespräch und Ergebnisse" if user_system_language == "de" else "Voice conversation and results")
    summary = ("Das Gespräch wurde mit der neuesten Frage und Antwort fortgesetzt."
               if user_system_language == "de" else "Continued the conversation with the latest finalized question and answer.")
    return {"updated_chat_title": title if current_chat_title != title else None,
            "chat_summary": summary, "chat_tags": ["voice"]}


def early_metadata_fixture(user_system_language: str) -> dict | None:
    """The early metadata task inherits only its admitted preprocessor context."""
    request = _voice_request.get()
    if not active(request):
        return None
    german = user_system_language == "de"
    ramen = "ramen" in request_text(request).lower()
    return {
        "title": ("Ramen gemeinsam einfach zubereiten" if german else "Making vegetarian ramen") if ramen else (
            "Sprachgespräch und Ergebnisse" if german else "Voice conversation and results"),
        "summary": ("Die Person fragt nach einer einfachen Anleitung für Ramen." if german else
                    "The user asks how to prepare ramen at home.") if ramen else (
                        "Die Person möchte die Unterhaltung mit einer neuen Frage fortsetzen." if german else
                        "The user wants to continue the conversation with a new request."),
    }


def speech_fixture_context(request: Any) -> dict[str, str]:
    """Reuse the existing worker's binary substitute and encrypted asset path."""
    if not active(request):
        return {}
    from backend.apps.audio.assistant_speech.live_mock import ASSISTANT_SPEECH_LIVE_MOCK_GROUP
    return {"live_mock_mode": "mock", "live_mock_group": ASSISTANT_SPEECH_LIVE_MOCK_GROUP,
            "live_mock_required": "true"}
