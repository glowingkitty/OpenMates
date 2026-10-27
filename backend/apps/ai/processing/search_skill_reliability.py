# backend/apps/ai/processing/search_skill_reliability.py
#
# Pure helpers for search app-skill routing and malformed request recovery.
# These functions are kept dependency-free so regressions in preselected tool
# availability and query placeholder metadata can be tested without importing the
# full streaming main processor runtime.

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


# Search surfaces are intentionally offered together so the main model can pick
# the best source instead of having a preprocessor-only routing decision suppress
# current news results.
COMPANION_SKILLS: dict[str, list[str]] = {
    "web-search": ["news-search", "images-search"],
    "news-search": ["images-search"],
}

_GENERIC_REPOSITORY_RANKING_CONCEPTS: dict[str, set[str]] = {
    "popularity": {"best", "popular", "popularity", "top"},
    "maintenance": {"active", "actively", "maintained", "maintenance"},
    "recency": {"latest", "modern", "new", "recent", "recently"},
    "quality": {
        "compatible",
        "documented",
        "established",
        "high",
        "known",
        "mature",
        "notable",
        "prominent",
        "quality",
        "reliable",
        "secure",
        "trusted",
        "used",
        "well",
        "widely",
    },
}
_GENERIC_REPOSITORY_RANKING_WORDS = frozenset().union(
    *_GENERIC_REPOSITORY_RANKING_CONCEPTS.values()
)
_REPOSITORY_SUBJECT_WORDS = {
    "code",
    "component",
    "components",
    "editor",
    "editors",
    "framework",
    "frameworks",
    "library",
    "libraries",
    "option",
    "options",
    "package",
    "packages",
    "project",
    "projects",
    "repository",
    "repositories",
    "solution",
    "solutions",
    "software",
    "tool",
    "tools",
}
_CRITERIA_GLUE_WORDS = {
    "a",
    "an",
    "and",
    "for",
    "of",
    "or",
    "the",
    "to",
    "with",
}
_REPOSITORY_DISCOVERY_VERBS = {"find", "list", "search", "show"}
_REPOSITORY_PREFERENCE_CUES = _GENERIC_REPOSITORY_RANKING_WORDS | {
    "advanced",
    "beginner",
    "collaborative",
    "compatible",
    "fast",
    "for",
    "license",
    "licensed",
    "lightweight",
    "need",
    "needs",
    "permissive",
    "prefer",
    "privacy",
    "production",
    "secure",
    "self",
    "small",
    "suitable",
    "team",
    "that",
    "to",
    "want",
    "where",
    "which",
    "with",
}


def _word_tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.casefold()))


def _is_plain_github_repository_discovery(value: str | None) -> bool:
    ordered_tokens = re.findall(r"[a-z0-9]+", (value or "").casefold())
    if not ordered_tokens or ordered_tokens[0] not in _REPOSITORY_DISCOVERY_VERBS:
        return False
    tokens = set(ordered_tokens)
    return "github" in tokens and not (tokens & _REPOSITORY_PREFERENCE_CUES)


def omit_unstated_generic_repository_criteria(
    arguments: dict[str, Any],
    user_request_text: str | None,
) -> tuple[dict[str, Any], int]:
    """Drop generic ranking defaults that the user did not ask for.

    The app prompt remains the primary contract. This guard catches the narrow
    failure mode where a model turns neutral repository discovery into a Jev
    request using only defaults such as popularity or maintenance. Explicitly
    requested generic preferences remain intact.
    """

    requests = arguments.get("requests")
    if not isinstance(requests, list):
        return arguments, 0

    user_tokens = _word_tokens(user_request_text or "")
    plain_discovery = _is_plain_github_repository_discovery(user_request_text)
    user_concepts = {
        concept
        for concept, words in _GENERIC_REPOSITORY_RANKING_CONCEPTS.items()
        if user_tokens & words
    }
    normalized_requests: list[Any] = []
    removed = 0

    for item in requests:
        if not isinstance(item, dict):
            normalized_requests.append(item)
            continue

        criteria = item.get("relevance_criteria")
        query = item.get("query")
        if not isinstance(criteria, str) or not criteria.strip():
            normalized_requests.append(item)
            continue

        criteria_tokens = _word_tokens(criteria)
        query_tokens = _word_tokens(query) if isinstance(query, str) else set()
        distinguishing_tokens = criteria_tokens - query_tokens - _REPOSITORY_SUBJECT_WORDS - _CRITERIA_GLUE_WORDS
        criteria_concepts = {
            concept
            for concept, words in _GENERIC_REPOSITORY_RANKING_CONCEPTS.items()
            if distinguishing_tokens & words
        }
        generic_only = bool(distinguishing_tokens) and (
            distinguishing_tokens <= _GENERIC_REPOSITORY_RANKING_WORDS
        )
        if not plain_discovery and (
            not generic_only or criteria_concepts & user_concepts
        ):
            normalized_requests.append(item)
            continue

        cleaned_item = item.copy()
        cleaned_item.pop("relevance_criteria", None)
        normalized_requests.append(cleaned_item)
        removed += 1

    if not removed:
        return arguments, 0

    normalized = arguments.copy()
    normalized["requests"] = normalized_requests
    return normalized, removed


def expand_companion_skills(
    preselected_skills: set[str],
    *,
    exact_request: bool = False,
) -> set[str]:
    if exact_request:
        return preselected_skills

    companions_to_add: set[str] = set()
    for trigger, companions in COMPANION_SKILLS.items():
        if trigger in preselected_skills:
            for companion in companions:
                if companion not in preselected_skills:
                    companions_to_add.add(companion)

    return preselected_skills | companions_to_add


def normalize_json_request_array(arguments: dict[str, Any]) -> dict[str, Any]:
    """Recover a JSON-encoded request list without changing invalid payloads."""
    value = arguments.get("requests")
    if not isinstance(value, str):
        return arguments
    try:
        decoded = json.loads(value)
    except (ValueError, TypeError):
        return arguments
    if not isinstance(decoded, list) or not all(isinstance(item, dict) for item in decoded):
        return arguments
    return {**arguments, "requests": decoded}


def normalize_string_query_request_items(
    arguments: dict[str, Any],
    item_required_fields: list[str],
) -> tuple[dict[str, Any], int]:
    requests_list = arguments.get("requests")
    if not isinstance(requests_list, list) or "query" not in item_required_fields:
        return arguments, 0

    normalized_requests: list[Any] = []
    normalized_string_items = 0
    for item in requests_list:
        if isinstance(item, str):
            normalized_requests.append({"query": item.strip()})
            normalized_string_items += 1
        else:
            normalized_requests.append(item)

    if not normalized_string_items:
        return arguments, 0

    normalized = arguments.copy()
    normalized["requests"] = normalized_requests
    return normalized, normalized_string_items


def web_search_request_key(arguments: dict, request: Any) -> str | None:
    """Identify equivalent read-only requests without correlation/internal fields.

    Keys remain private turn state and must never be included in diagnostics.
    Preserve every search option, including unknown future options.
    """
    if not isinstance(request, dict) or not isinstance(request.get("query"), str):
        return None
    item = {k: v for k, v in request.items() if k != "id" and not k.startswith("_") and v is not None}
    item["query"] = item["query"].strip()
    item.setdefault("count", 10)
    for field, default in (("provider", "brave"), ("country", "us"), ("search_lang", "en"), ("safesearch", "moderate")):
        value = item.get(field, default)
        item[field] = value.strip().lower() if isinstance(value, str) else value
    if isinstance(item.get("relevance_criteria", ""), str) and not item.get("relevance_criteria", "").strip():
        item.pop("relevance_criteria", None)
    options = {k: v for k, v in arguments.items() if k not in {"requests", "id"} and not k.startswith("_")}
    encoded = json.dumps([options, item], sort_keys=True, ensure_ascii=False)
    return "web-search-request:" + hashlib.sha256(encoded.encode()).hexdigest()


def search_request_key(app_id: str, arguments: dict, request: Any) -> str | None:
    """Identify a read-only search member while preserving search constraints.

    Event dates, counts, providers and selection criteria remain part of the key:
    a narrower date window can retrieve new events after a capped first search.
    Correlation IDs and internal transport metadata do not change the search.
    """
    if app_id == "web":
        return web_search_request_key(arguments, request)
    if app_id != "events" or not isinstance(request, dict):
        return None
    if not any(isinstance(request.get(field), str) and request[field].strip()
               for field in ("query", "conference")):
        return None
    item = {key: value for key, value in request.items()
            if key != "id" and not key.startswith("_") and value is not None}
    if isinstance(item.get("query"), str):
        item["query"] = item["query"].strip()
    item.setdefault("count", 10)
    item.setdefault("radius_miles", 25)
    item.setdefault("past_events", False)
    options = {key: value for key, value in arguments.items()
               if key not in {"requests", "id"} and not key.startswith("_")}
    encoded = json.dumps([options, item], sort_keys=True, ensure_ascii=False)
    return "events-search-request:" + hashlib.sha256(encoded.encode()).hexdigest()


def reuse_completed_search_requests(app_id: str, arguments: dict, completed: dict) -> tuple[dict, list[dict]]:
    """Partition completed web/event requests before any new work is admitted."""
    requests = arguments.get("requests")
    if not isinstance(requests, list) or not requests:
        return arguments, []
    fresh, reused = [], []
    for request in requests:
        key = search_request_key(app_id, arguments, request)
        if key is not None and key in completed:
            reused.append(completed[key])
        else:
            fresh.append(request)
    return ({**arguments, "requests": fresh}, reused) if reused else (arguments, [])
