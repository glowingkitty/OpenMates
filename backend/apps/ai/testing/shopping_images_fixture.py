"""Synthetic upstream responses for the signed shopping gallery regression.

The real shopping skill, REWE parser, embed encryption and client readers run.
These responses prove serialization, never provider inventory or vision quality.
"""
from __future__ import annotations

import json
import os
from typing import Any, Mapping
from toon_format import decode

from backend.shared.providers.typesafe.models import DecisionResponse
from backend.shared.testing.mock_context import get_mock_group, mock_mode_var

GROUP = "shopping_images_web"
PROMPT = "Find bio joghurt on REWE. SHOPPING_IMAGES_E2E:gallery"
REFERENCE_ERROR_PROMPT = "Find bio joghurt on REWE using my reference image. SHOPPING_IMAGES_E2E:reference-error"
REFERENCE_ERROR_ID = "reference-error"
REFERENCE_ERROR_MESSAGE = "A reference image could not be accessed. Use its exact reference from this chat or upload it again."
REFERENCE_ERROR_RESPONSE = "The reference image could not be accessed. Please upload it again or use its exact reference from this chat. The shopping search did not run."
GALLERY_RESPONSE = "The REWE search result is available in the shopping card. Exact composition was not supplied."
MISSING_GALLERY_GROUNDING_RESPONSE = "REGRESSION: the shopping tool lost its factual grounding notice."
GROUNDING_PROMPT = "Compare cotton fabric to my reference image. SHOPPING_IMAGES_E2E:grounding"
GROUNDING_RESPONSE = "The similarity score is 3.24 out of 4. All 2 candidate products were evaluated; none were unavailable. One evaluated product was filtered below the minimum score of 2. Exact composition was not supplied; a cotton title does not establish a fibre percentage."
MISSING_GROUNDING_METADATA_RESPONSE = "REGRESSION: the shopping tool lost its score scale, evaluation counts or factual grounding notice."
MISSING_ERROR_METADATA_RESPONSE = "REGRESSION: the shopping tool lost its reference failure metadata."
FORTY_QUERY = "synthetic forty candidate shopping test"
FORTY_PROMPT = "Find the late matching grocery product on REWE. SHOPPING_IMAGES_E2E:forty"
FORTY_CRITERIA = "synthetic late candidate 39"
FORTY_RESPONSE = "The late matching product from forty candidates is first; the shopping card contains three products."
MISSING_FORTY_RESPONSE = "REGRESSION: forty-candidate discovery did not preserve the late match and final limit."
_PROMPTS = (PROMPT, REFERENCE_ERROR_PROMPT, GROUNDING_PROMPT, FORTY_PROMPT)


def active() -> bool:
    return (mock_mode_var.get() == "mock" and get_mock_group() == GROUP
            and os.getenv("MOCK_EXTERNAL_APIS") == "true"
            and os.getenv("SERVER_ENVIRONMENT", "production").lower() not in {"production", "prod"})


def _matches(messages: Any) -> bool:
    if not isinstance(messages, list):
        return False
    return next((any(prompt in str(message.get("content") or "") for prompt in _PROMPTS)
                 for message in reversed(messages)
                 if isinstance(message, dict) and message.get("role") == "user"), False)


def jev_response(state: Any, questions: Mapping[str, Mapping[str, Any]], model: str) -> DecisionResponse | None:
    if not active() or not isinstance(state, Mapping) or not questions:
        return None
    if (state.get("task") == "rank_search_candidates" and state.get("profile") == "shopping"
            and state.get("relevance_criteria") == FORTY_CRITERIA
            and state.get("search_parameters", {}).get("query") == FORTY_QUERY):
        candidates = {row["candidate_id"]: row for row in state.get("candidates", [])}
        answers = {}
        for key in questions:
            row = candidates.get(key)
            if not isinstance(row, Mapping):
                return None
            value = 4.0 if row.get("data", {}).get("title") == "Synthetic candidate 39" else 3.0
            answers[key] = {"type": "score", "score": value, "legend": {"0": "conflict", "3": "plausible", "4": "fit"},
                            "confidence": 1.0, "probabilities": {key: float(key == str(int(value))) for key in ("0", "3", "4")}}
        return DecisionResponse(model=model, answers=answers)
    if not (_matches(state.get("messages")) or any(prompt in str(state.get("user_message") or "") for prompt in _PROMPTS)):
        return None
    answers = {}
    preferred = {"complexity": "simple", "task_area": "general", "topic_shift": "noticeable_shift",
                 "temperature": "balanced", "preview": "none", "language": "en", "icon": "shopping-cart",
                 "project_target": "none", "topic_area": "general_misc"}
    for question_id, question in questions.items():
        kind = question.get("type")
        if kind == "noul":
            instructions = question.get("instructions")
            candidate = instructions.get("candidate_id") if isinstance(instructions, Mapping) else None
            selected = (question_id.startswith("app_") and candidate == "shopping"
                        or question_id.startswith("skill_") and candidate == "shopping-search_products")
            answers[question_id] = {"type": kind, "noul": float(selected)}
        elif kind == "choice" and isinstance(criteria := question.get("criteria"), Mapping) and criteria:
            chosen = preferred.get(question_id)
            chosen = chosen if chosen in criteria else next(iter(criteria))
            answers[question_id] = {"type": kind, "choice": chosen, "confidence": 1.0,
                                    "probabilities": {str(key): float(key == chosen) for key in criteria}}
        elif kind == "score" and question_id == "harmful_response" and question.get("criteria"):
            legend = {str(index): str(label) for index, label in enumerate(question["criteria"])}
            answers[question_id] = {"type": kind, "score": 0.0, "legend": legend, "confidence": 1.0,
                                    "probabilities": {key: float(key == "0") for key in legend}}
        else:
            return None
    return DecisionResponse.model_validate({"provider": "shopping_gallery_fixture", "model": model,
                                           "answers": answers, "usage": {"input_tokens": 100, "output_tokens": len(answers)}})


def _call(name: str, arguments: dict[str, Any], model: str) -> dict[str, Any]:
    google = "gemini" in model
    return {"kind": "pydantic",
            "module": "backend.apps.ai.llm_providers.google_client" if google else "backend.apps.ai.llm_providers.openai_shared",
            "class": "ParsedGoogleToolCall" if google else "ParsedOpenAIToolCall",
            "value": {"tool_call_id": "shopping-gallery-fixture", "function_name": name,
                      "function_arguments_raw": json.dumps(arguments), "function_arguments_parsed": arguments,
                      "parsing_error": None}}


def _has_reference_failure_metadata(tail: list[dict[str, Any]]) -> bool:
    """Depend on the real server tool payload, never fabricate a skill outcome."""
    for message in tail:
        if not isinstance(message, dict) or message.get("role") != "tool":
            continue
        content = message.get("content")
        if not isinstance(content, str):
            continue
        try:
            payload = json.loads(content)
        except (ValueError, TypeError):
            try:
                payload = decode(content)
            except (ValueError, TypeError):
                continue
        if not isinstance(payload, dict) or not isinstance(payload.get("request_errors"), list):
            continue
        errors = payload["request_errors"]
        if len(errors) != 1 or payload.get("results") != [] or type(payload.get("count")) is not int or payload["count"] != 0:
            continue
        notice = payload.get("failure_notice")
        if not isinstance(notice, str) or "not evidence of no matching products" not in notice:
            continue
        error = errors[0]
        request_id = error.get("request_id") if isinstance(error, dict) else None
        # The real placeholder phase normalizes this one request to ID 1.
        matches_request = (type(request_id) is int and request_id == 1
                           or type(request_id) is str and request_id in {REFERENCE_ERROR_ID, "1"})
        if matches_request and error.get("message") == REFERENCE_ERROR_MESSAGE:
            return True
    return False


def _has_gallery_grounding_metadata(tail: list[dict[str, Any]]) -> bool:
    from backend.apps.ai.utils.app_skill_result_groups import SHOPPING_GROUNDING_NOTICE

    for message in tail:
        if not isinstance(message, dict) or message.get("role") != "tool":
            continue
        content = message.get("content")
        try:
            payload = json.loads(content)
        except (ValueError, TypeError):
            try:
                payload = decode(content)
            except (ValueError, TypeError):
                continue
        if not isinstance(payload, dict) or payload.get("grounding_notice") != SHOPPING_GROUNDING_NOTICE:
            continue
        products = payload.get("results")
        if (isinstance(products, list) and len(products) == 1 and isinstance(products[0], dict)
                and products[0].get("title") == "REWE Bio Joghurt mild 3,8% 500g"
                and not any(key in products[0] for key in ("composition", "ingredients", "material_composition"))
                and not payload.get("visual_evaluations")):
            return True
    return False


def _has_grounded_comparison_metadata(tail: list[dict[str, Any]]) -> bool:
    """Read real tool evidence before emitting the deterministic comparison answer."""
    from backend.apps.ai.utils.app_skill_result_groups import SHOPPING_GROUNDING_NOTICE

    for message in tail:
        if not isinstance(message, dict) or message.get("role") != "tool":
            continue
        content = message.get("content")
        try:
            payload = json.loads(content)
        except (ValueError, TypeError):
            try:
                payload = decode(content)
            except (ValueError, TypeError):
                continue
        if not isinstance(payload, dict) or payload.get("grounding_notice") != SHOPPING_GROUNDING_NOTICE:
            continue
        results, evaluations = payload.get("results"), payload.get("visual_evaluations")
        if not isinstance(results, list) or len(results) != 1 or not isinstance(evaluations, list) or len(evaluations) != 1:
            continue
        row = results[0]
        summary = evaluations[0].get("visual_evaluation") if isinstance(evaluations[0], dict) else None
        if not isinstance(row, dict) or not isinstance(summary, dict):
            continue
        match = row.get("visual_match")
        expected_summary = {"status": "evaluated", "reference_count": 1, "evaluated_count": 2,
                            "filtered_count": 1, "unavailable_count": 0, "minimum_score": 2,
                            "score_min": 0, "score_max": 4}
        if any(summary.get(key) != value or type(summary.get(key)) is not type(value)
               for key, value in expected_summary.items()):
            continue
        if (isinstance(match, dict) and match.get("status") == "evaluated" and match.get("score") == 3.24
                and match.get("score_min") == 0 and match.get("score_max") == 4
                and row.get("title") == "Cotton floral fabric" and "composition" not in row):
            return True
    return False


def _has_forty_results(tail: list[dict[str, Any]]) -> bool:
    for message in tail:
        if not isinstance(message, dict) or message.get("role") != "tool":
            continue
        try:
            payload = json.loads(message.get("content"))
        except (ValueError, TypeError):
            try:
                payload = decode(message.get("content"))
            except (ValueError, TypeError):
                continue
        rows = payload.get("results") if isinstance(payload, dict) else None
        if (isinstance(rows, list) and len(rows) == 3 and isinstance(rows[0], dict)
                and rows[0].get("title") == "Synthetic candidate 39"):
            return True
    return False


def llm_fixture(category: str, kwargs: dict[str, Any]) -> dict[str, Any] | None:
    if not active() or not _matches(kwargs.get("messages")):
        return None
    model = str(kwargs.get("model") or kwargs.get("model_id") or "")
    if not model or category.rsplit("/", 1)[-1] != model:
        return None
    names = {function["name"] for tool in kwargs.get("tools") or [] if isinstance(tool, dict)
             if isinstance(function := tool.get("function"), dict) and isinstance(function.get("name"), str)}
    if category.startswith("llm_non_stream/") and names == {"generate_suggestions_and_metadata"}:
        arguments = {"follow_up_app_skill_suggestions": ["Find another grocery product"],
                     "follow_up_general_suggestions": ["Explain the product details"],
                     "chat_summary": "Synthetic shopping gallery serialization check.", "chat_tags": ["shopping"],
                     "share_cta_text": "Explore shopping", "updated_chat_title": "Shopping Gallery",
                     "daily_inspiration_topic_suggestions": ["groceries"], "quick_tip_slug": ""}
        return {"response": {"type": "non_stream", "value": {"kind": "pydantic",
                "module": "backend.apps.ai.llm_providers.google_client", "class": "UnifiedGoogleResponse",
                "value": {"task_id": str(kwargs.get("task_id") or "shopping-gallery-postprocess"),
                          "model_id": model, "success": True,
                          "tool_calls_made": [_call("generate_suggestions_and_metadata", arguments, model)["value"]],
                          "usage": {"prompt_token_count": 100, "candidates_token_count": 40, "total_token_count": 140}}}}}
    if not category.startswith("llm/") or kwargs.get("stream") is False:
        return None
    messages = kwargs["messages"]
    last_user = max(index for index, message in enumerate(messages) if isinstance(message, dict) and message.get("role") == "user")
    tail = messages[last_user + 1:]
    reference_error = REFERENCE_ERROR_PROMPT in str(messages[last_user].get("content") or "")
    grounding = GROUNDING_PROMPT in str(messages[last_user].get("content") or "")
    forty = FORTY_PROMPT in str(messages[last_user].get("content") or "")
    if not tail and "shopping-search_products" in names:
        request = {"query": "bio joghurt", "provider": "REWE", "max_results": 1}
        if forty:
            request.update({"query": FORTY_QUERY, "max_results": 3, "relevance_criteria": FORTY_CRITERIA})
        if reference_error:
            request.update({"id": REFERENCE_ERROR_ID,
                            "reference_images": ["00000000-0000-4000-8000-000000000001"]})
        return {"response": {"type": "mixed_stream", "chunks": [
            _call("shopping-search_products", {"requests": [request]}, model)]}}
    if any(isinstance(message, dict) and message.get("role") == "tool" for message in tail):
        answer = GALLERY_RESPONSE if _has_gallery_grounding_metadata(tail) else MISSING_GALLERY_GROUNDING_RESPONSE
        if forty:
            answer = FORTY_RESPONSE if _has_forty_results(tail) else MISSING_FORTY_RESPONSE
        elif grounding:
            answer = GROUNDING_RESPONSE if _has_grounded_comparison_metadata(tail) else MISSING_GROUNDING_METADATA_RESPONSE
        elif reference_error:
            answer = REFERENCE_ERROR_RESPONSE if _has_reference_failure_metadata(tail) else MISSING_ERROR_METADATA_RESPONSE
        return {"response": {"type": "mixed_stream", "chunks": [
            {"kind": "text", "value": answer}]}}
    return None
