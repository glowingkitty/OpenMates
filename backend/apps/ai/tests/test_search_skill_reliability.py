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
    omit_unstated_generic_repository_criteria,
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


# contract-test: supporting surface=gui.web assertions=app-skills.search-relevance.optional-and-inferred
def test_neutral_repository_search_drops_invented_generic_ranking_defaults() -> None:
    normalized, removed = omit_unstated_generic_repository_criteria(
        {
            "requests": [
                {
                    "query": "typescript markdown editor",
                    "count": 10,
                    "relevance_criteria": "Popular and well-maintained TypeScript Markdown editor libraries",
                }
            ]
        },
        "Find TypeScript Markdown editor libraries on GitHub.",
    )

    assert removed == 1
    assert normalized == {
        "requests": [{"query": "typescript markdown editor", "count": 10}]
    }

    quoted_variant, quoted_removed = omit_unstated_generic_repository_criteria(
        {
            "requests": [
                {
                    "query": "markdown editor language:TypeScript",
                    "relevance_criteria": '"Popular, active, or well-known TypeScript Markdown editor libraries and components"',
                }
            ]
        },
        "Find TypeScript Markdown editor libraries on GitHub.",
    )
    assert quoted_removed == 1
    assert quoted_variant == {
        "requests": [{"query": "markdown editor language:TypeScript"}]
    }

    specific_repo_variant, specific_repo_removed = omit_unstated_generic_repository_criteria(
        {
            "requests": [
                {
                    "query": "mdx-editor/editor",
                    "relevance_criteria": "MDX editor library in TypeScript",
                }
            ]
        },
        "Find TypeScript Markdown editor libraries on GitHub.",
    )
    assert specific_repo_removed == 1
    assert specific_repo_variant == {
        "requests": [{"query": "mdx-editor/editor"}]
    }


# contract-test: supporting surface=gui.web assertions=app-skills.search-relevance.optional-and-inferred
def test_repository_search_keeps_explicit_or_goal_specific_ranking() -> None:
    explicit_generic = {
        "requests": [
            {
                "query": "typescript markdown editor",
                "relevance_criteria": "Popular and well-maintained TypeScript Markdown editor libraries",
            }
        ]
    }
    purpose_specific = {
        "requests": [
            {
                "query": "typescript markdown editor",
                "relevance_criteria": "Permissive license and collaborative editing for a small SaaS team",
            }
        ]
    }

    assert omit_unstated_generic_repository_criteria(
        explicit_generic,
        "Find popular, well-maintained TypeScript Markdown editor libraries.",
    ) == (explicit_generic, 0)
    assert omit_unstated_generic_repository_criteria(
        purpose_specific,
        "Find a permissively licensed editor for collaborative SaaS editing.",
    ) == (purpose_specific, 0)
