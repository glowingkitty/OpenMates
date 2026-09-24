# backend/apps/ai/processing/search_skill_reliability.py
#
# Pure helpers for search app-skill routing and malformed request recovery.
# These functions are kept dependency-free so regressions in preselected tool
# availability and query placeholder metadata can be tested without importing the
# full streaming main processor runtime.

from __future__ import annotations

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
        "high",
        "mature",
        "quality",
        "reliable",
        "secure",
        "well",
    },
}
_GENERIC_REPOSITORY_RANKING_WORDS = frozenset().union(
    *_GENERIC_REPOSITORY_RANKING_CONCEPTS.values()
)
_REPOSITORY_SUBJECT_WORDS = {
    "code",
    "editor",
    "editors",
    "framework",
    "frameworks",
    "library",
    "libraries",
    "option",
    "options",
    "project",
    "projects",
    "repository",
    "repositories",
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


def _word_tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.casefold()))


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
        if not generic_only or criteria_concepts & user_concepts:
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
