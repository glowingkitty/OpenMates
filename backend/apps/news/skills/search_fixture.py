# backend/apps/news/skills/search_fixture.py
#
# Dependency-light fixture helpers for news/search E2E tests.
# Kept separate from search_skill.py so host-side pytest gates can validate the
# deterministic fixture contract without importing the full backend runtime
# dependencies used by the live skill implementation.

import os
from typing import Any, Dict, List


DEFAULT_E2E_NEWS_FIXTURE_RESULT_COUNT = 6
E2E_NEWS_FIXTURE_QUERY_TOKEN = "openmates_e2e_news_fixture_ai"
E2E_NEWS_FIXTURE_RESULTS = [
    {
        "type": "search_result",
        "title": "OpenMates E2E AI News Fixture",
        "url": "https://app.dev.openmates.org/news/fixtures/ai-progress",
        "description": "A deterministic AI news fixture used by the OpenMates E2E news search flow.",
        "page_age": "2026-07-25T00:00:00Z",
        "profile": {"name": "OpenMates E2E News"},
        "meta_url": {"favicon": "https://app.dev.openmates.org/favicon.png"},
        "thumbnail": {"src": "https://app.dev.openmates.org/store-examples/news-fixture.webp"},
        "extra_snippets": ["Fixture result for provider-independent news search rendering."],
        "hash": "openmates-e2e-news-fixture-ai",
    },
    {
        "type": "search_result",
        "title": "AI Research Fixture Update",
        "url": "https://app.dev.openmates.org/news/fixtures/ai-research",
        "description": "A second deterministic article card for testing grouped news search results.",
        "page_age": "2026-07-24T00:00:00Z",
        "profile": {"name": "OpenMates E2E News"},
        "meta_url": {"favicon": "https://app.dev.openmates.org/favicon.png"},
        "thumbnail": {"src": "https://app.dev.openmates.org/store-examples/news-fixture-2.webp"},
        "extra_snippets": ["Second fixture result for stable grid assertions."],
        "hash": "openmates-e2e-news-fixture-research",
    },
]


def is_e2e_news_fixture_query(query: str) -> bool:
    """Return True for the explicit non-production E2E news search fixture token."""
    return (
        os.getenv("SERVER_ENVIRONMENT", "production") != "production"
        and E2E_NEWS_FIXTURE_QUERY_TOKEN in query.lower()
    )


def build_e2e_news_fixture_results(requested_count: int | None) -> List[Dict[str, Any]]:
    result_count = max(
        1,
        min(
            int(requested_count or DEFAULT_E2E_NEWS_FIXTURE_RESULT_COUNT),
            len(E2E_NEWS_FIXTURE_RESULTS),
        ),
    )
    return [dict(result) for result in E2E_NEWS_FIXTURE_RESULTS[:result_count]]
