"""Signed, isolated replay at Jev and provider boundaries for automatic routing.

The real preprocessor chooses the model and the main processor handles failure.
Only the synthetic requests below are admitted; no recorded model labels or
WebSocket output are substituted. Production and non-replay contexts stay inert.
Failure witnesses are bounded, task-scoped, and consumed by the fallback packet.
"""
from __future__ import annotations

from collections import OrderedDict
import json
import os
from typing import Any, Mapping

from backend.apps.ai.processing.model_routing import LOW_FALLBACK_MODEL, MERCURY_MODEL
from backend.shared.providers.inception import InceptionError
from backend.shared.providers.typesafe.models import DecisionResponse
from backend.shared.testing.mock_context import get_mock_group, mock_mode_var, record_cache_hit

GROUP = "mercury_auto_low"
SUCCESS_PROMPT = "What is 2 + 2? MERCURY_ROUTING_E2E:success"
FALLBACK_PROMPT = "What is 3 + 3? MERCURY_ROUTING_E2E:fallback"
DISABLED_PROMPT = "What is 4 + 4? MERCURY_ROUTING_E2E:disabled"
GEMINI_RETRY_PROMPT = "Compare the available evidence. MERCURY_ROUTING_E2E:gemini_retry"
CHEAP_FALLBACK_PROMPT = "Summarize the available evidence. MERCURY_ROUTING_E2E:cheap_fallback"
SUCCESS_RESPONSE = "The answer is 4. Automatic routing completed successfully."
FALLBACK_RESPONSE = "The answer is 6. Automatic routing recovered successfully."
DISABLED_RESPONSE = "The answer is 8. Your disabled model was respected."
GEMINI_RETRY_RESPONSE = "Gemini completed the answer on its first clean retry."
CHEAP_FALLBACK_RESPONSE = "Mercury completed the answer as the inexpensive last resort."
PROTOCOL_TEXT = "```toon\napp_id: web\nskill_id: search\nstatus: finished\n```"
PROMPTS = (SUCCESS_PROMPT, FALLBACK_PROMPT, DISABLED_PROMPT, GEMINI_RETRY_PROMPT, CHEAP_FALLBACK_PROMPT)
MAX_FAILURE_WITNESSES = 128
# wait_for() consumes Mercury's first chunk in a child task, so a ContextVar set
# there would not reach the fallback task. Store only opaque task IDs, bounded.
_failed_tasks: OrderedDict[str, None] = OrderedDict()
_protocol_failures: OrderedDict[str, int] = OrderedDict()


def active() -> bool:
    return (mock_mode_var.get() == "mock" and get_mock_group() == GROUP
            and os.getenv("MOCK_EXTERNAL_APIS") == "true"
            and os.getenv("CI") == "true" and os.getenv("OPENMATES_CI_ISOLATED") == "1"
            and os.getenv("OPENMATES_CI_AI_FIXTURES") == "1"
            and os.getenv("SERVER_ENVIRONMENT", "production").strip().lower()
            not in {"production", "prod"})


def _prompt(messages: Any) -> str | None:
    if not isinstance(messages, list):
        return None
    for message in reversed(messages):
        if isinstance(message, dict) and message.get("role") == "user":
            content = str(message.get("content") or "")
            # Recovery appends this exact instruction after the original
            # request when a safe prefix has already reached the user.
            if content == ("Continue the answer immediately after the already-published prefix. "
                           "Do not repeat or paraphrase any published text."):
                continue
            return next((prompt for prompt in PROMPTS if prompt in content), None)
    return None


def jev_response(state: Any, questions: Mapping[str, Mapping[str, Any]], model: str) -> DecisionResponse | None:
    if not active() or not isinstance(state, Mapping) or not questions:
        return None
    if not (_prompt(state.get("messages")) or any(
            prompt in str(state.get("user_message") or "") for prompt in PROMPTS)):
        return None
    medium = any(prompt in str(state) for prompt in (GEMINI_RETRY_PROMPT, CHEAP_FALLBACK_PROMPT))
    preferred = {"complexity": "medium" if medium else "low", "task_area": "general", "topic_shift": "noticeable_shift",
                 "temperature": "precise", "preview": "none", "language": "en", "icon": "calculator",
                 "project_target": "none", "topic_area": "general_misc"}
    answers: dict[str, dict[str, Any]] = {}
    for question_id, question in questions.items():
        kind = question.get("type")
        if kind == "noul":
            answers[question_id] = {"type": kind, "noul": 0.0}
        elif kind == "choice" and isinstance(criteria := question.get("criteria"), Mapping) and criteria:
            chosen = preferred.get(question_id)
            # Routing itself must fail closed if its approved classifier changes.
            if question_id == "complexity" and chosen not in criteria:
                return None
            chosen = chosen if chosen in criteria else next(iter(criteria))
            answers[question_id] = {"type": kind, "choice": chosen, "confidence": 1.0,
                                    "probabilities": {str(key): float(key == chosen) for key in criteria}}
        elif kind == "score" and question_id == "harmful_response" and question.get("criteria"):
            legend = {str(index): str(label) for index, label in enumerate(question["criteria"])}
            answers[question_id] = {"type": kind, "score": 0.0, "legend": legend, "confidence": 1.0,
                                    "probabilities": {key: float(key == "0") for key in legend}}
        else:
            return None
    return DecisionResponse.model_validate({"provider": "mercury_routing_fixture", "model": model,
        "answers": answers, "usage": {"input_tokens": 100, "output_tokens": len(answers)}})


def _packet(model: str, answer: str) -> dict[str, Any]:
    google = "gemini" in model
    usage = ({"prompt_token_count": 100, "candidates_token_count": 20, "total_token_count": 120}
             if google else {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120})
    return {"response": {"type": "mixed_stream", "chunks": [
        {"kind": "text", "value": answer},
        {"kind": "pydantic", "module": "backend.apps.ai.llm_providers.google_client" if google
         else "backend.apps.ai.llm_providers.openai_shared", "class": "GoogleUsageMetadata" if google
         else "OpenAIUsageMetadata", "value": usage},
    ]}}


def llm_fixture(category: str, kwargs: dict[str, Any]) -> dict[str, Any] | None:
    """Require a Mercury attempt for outage recovery, and none for disabled-model routing."""
    if not active() or not (prompt := _prompt(kwargs.get("messages"))):
        return None
    model = str(kwargs.get("model") or kwargs.get("model_id") or "")
    task_id = kwargs.get("task_id")
    if not isinstance(task_id, str) or not task_id:
        return None
    names = {function.get("name") for tool in kwargs.get("tools") or [] if isinstance(tool, dict)
             if isinstance(function := tool.get("function"), dict)}
    if (category == f"llm_non_stream/{model}" and names == {"generate_suggestions_and_metadata"}
            and kwargs.get("tool_choice") == "required"):
        args = {"follow_up_app_skill_suggestions": [], "follow_up_general_suggestions": [],
                "new_chat_app_skill_suggestions": [], "new_chat_general_suggestions": [],
                "chat_summary": "Answered a simple arithmetic question.", "chat_tags": ["arithmetic"],
                "share_cta_text": "Arithmetic answer", "updated_chat_title": "Arithmetic answer",
                "daily_inspiration_topic_suggestions": [], "quick_tip_slug": ""}
        return {"response": {"type": "non_stream", "value": {"kind": "pydantic",
            "module": "backend.apps.ai.llm_providers.openai_shared", "class": "UnifiedOpenAIResponse",
            "value": {"task_id": task_id, "model_id": model, "success": True, "tool_calls_made": [{
                "tool_call_id": "mercury-routing-metadata", "function_name": "generate_suggestions_and_metadata",
                "function_arguments_raw": json.dumps(args), "function_arguments_parsed": args,
                "parsing_error": None}]}}}}
    if category != f"llm/{model}" or kwargs.get("stream") is False:
        return None
    if prompt in {GEMINI_RETRY_PROMPT, CHEAP_FALLBACK_PROMPT}:
        if model == LOW_FALLBACK_MODEL.split("/", 1)[1]:
            failures = _protocol_failures.get(task_id, 0)
            if failures:
                from backend.apps.ai.utils.answer_recovery import ANSWER_RECOVERY_INSTRUCTION
                system = "\n".join(str(message.get("content") or "") for message in kwargs.get("messages") or []
                                   if isinstance(message, dict) and message.get("role") == "system")
                if names or kwargs.get("tool_choice") != "none" or ANSWER_RECOVERY_INSTRUCTION not in system:
                    raise AssertionError("Gemini retry must use a clean answer-only request")
                if "Simply decide which tool to call" in system:
                    raise AssertionError("Recovery still includes tool-selection instructions")
                if prompt == GEMINI_RETRY_PROMPT:
                    del _protocol_failures[task_id]
                    return _packet(model, GEMINI_RETRY_RESPONSE)
            _protocol_failures[task_id] = failures + 1
            _protocol_failures.move_to_end(task_id)
            while len(_protocol_failures) > MAX_FAILURE_WITNESSES:
                _protocol_failures.popitem(last=False)
            return _packet(model, ("Verified prefix.\n\n" if failures == 0 else "") + PROTOCOL_TEXT)
        if model == MERCURY_MODEL.split("/", 1)[1] and prompt == CHEAP_FALLBACK_PROMPT:
            if _protocol_failures.pop(task_id, None) != 2 or kwargs.get("reasoning_effort") != "low":
                raise AssertionError("Mercury must follow exactly one clean Gemini retry at LOW")
            return _packet(model, CHEAP_FALLBACK_RESPONSE)
        raise AssertionError("Automatic recovery dispatched an unapproved or older model")
    if model == MERCURY_MODEL.split("/", 1)[1]:
        if prompt == DISABLED_PROMPT:
            raise AssertionError("A disabled Mercury model must never reach its provider")
        if kwargs.get("reasoning_effort") != "low":
            return None
        if prompt == SUCCESS_PROMPT:
            return _packet(model, SUCCESS_RESPONSE)
        _failed_tasks[task_id] = None
        _failed_tasks.move_to_end(task_id)
        while len(_failed_tasks) > MAX_FAILURE_WITNESSES:
            _failed_tasks.popitem(last=False)
        record_cache_hit()
        raise InceptionError("Synthetic Mercury HTTP 503 before first output")
    if model == LOW_FALLBACK_MODEL.split("/", 1)[1] and prompt == FALLBACK_PROMPT and task_id in _failed_tasks:
        del _failed_tasks[task_id]
        return _packet(model, FALLBACK_RESPONSE)
    if model == LOW_FALLBACK_MODEL.split("/", 1)[1] and prompt == DISABLED_PROMPT:
        return _packet(model, DISABLED_RESPONSE)
    return None
