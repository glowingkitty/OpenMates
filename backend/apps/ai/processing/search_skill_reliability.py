# backend/apps/ai/processing/search_skill_reliability.py
#
# Pure helpers for search app-skill routing and malformed request recovery.
# These functions are kept dependency-free so regressions in preselected tool
# availability and query placeholder metadata can be tested without importing the
# full streaming main processor runtime.

from __future__ import annotations

from typing import Any


# Search surfaces are intentionally offered together so the main model can pick
# the best source instead of having a preprocessor-only routing decision suppress
# current news results.
COMPANION_SKILLS: dict[str, list[str]] = {
    "web-search": ["news-search", "images-search"],
    "news-search": ["images-search"],
}


def expand_companion_skills(preselected_skills: set[str]) -> set[str]:
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
