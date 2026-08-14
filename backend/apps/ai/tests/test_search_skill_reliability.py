"""Regression tests for search skill routing and embed request normalization.

The main processor must offer companion search surfaces and preserve malformed
LLM query arguments before app-skill placeholders are emitted. These helpers are
tested directly so the coverage is deterministic and does not require streaming
LLM/tool orchestration.
"""

from __future__ import annotations

from backend.apps.ai.processing.search_skill_reliability import (
    expand_companion_skills,
    normalize_string_query_request_items,
)


# contract-test: supporting surface=gui.web assertions=web-search.surface-parity
def test_web_search_preselection_includes_news_and_images_companions() -> None:
    expanded = expand_companion_skills({"web-search"})

    assert expanded == {"web-search", "news-search", "images-search"}


# contract-test: supporting surface=gui.web assertions=web-search.request.validated,web-search.surface-parity
def test_search_request_string_items_normalize_to_query_objects() -> None:
    normalized, count = normalize_string_query_request_items(
        arguments={
            "requests": ["  OpenMates admin query  ", "OpenMates news"],
            "_placeholder_embed_ids": ["embed-1"],
        },
        item_required_fields=["query"],
    )

    assert count == 2
    assert normalized == {
        "requests": [
            {"query": "OpenMates admin query"},
            {"query": "OpenMates news"},
        ],
        "_placeholder_embed_ids": ["embed-1"],
    }
