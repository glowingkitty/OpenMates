# backend/apps/web/skills/search_fixture.py
#
# Dependency-light fixture helpers for web/search E2E tests.
# Direct app-skill calls bypass chat live-mock markers, so tests use an explicit
# non-production query token to exercise result rendering without spending Brave
# Search quota.

import os
from typing import Any, Dict, List


DEFAULT_E2E_WEB_FIXTURE_RESULT_COUNT = 6
E2E_WEB_FIXTURE_QUERY_TOKEN = "openmates_e2e_web_fixture_ai"
E2E_WEB_FIXTURE_RESULTS = [
    {
        "type": "search_result",
        "title": "OpenMates E2E Web Fixture",
        "url": "https://app.dev.openmates.org/web/fixtures/ai-assistant",
        "description": "A deterministic web result used by the OpenMates E2E web search flow.",
        "age": "2026-07-25T00:00:00Z",
        "page_age": "2026-07-25T00:00:00Z",
        "language": "en",
        "family_friendly": True,
        "profile": {"name": "OpenMates E2E Web"},
        "meta_url": {"favicon": "https://app.dev.openmates.org/favicon.png"},
        "thumbnail": {"src": "https://app.dev.openmates.org/store-examples/news-fixture.webp"},
        "extra_snippets": ["Fixture result for provider-independent web search rendering."],
        "hash": "openmates-e2e-web-fixture-ai",
    },
    {
        "type": "search_result",
        "title": "OpenMates Search Fixture Result",
        "url": "https://app.dev.openmates.org/web/fixtures/search-result",
        "description": "A second deterministic result card for testing grouped web search results.",
        "age": "2026-07-24T00:00:00Z",
        "page_age": "2026-07-24T00:00:00Z",
        "language": "en",
        "family_friendly": True,
        "profile": {"name": "OpenMates E2E Web"},
        "meta_url": {"favicon": "https://app.dev.openmates.org/favicon.png"},
        "thumbnail": {"src": "https://app.dev.openmates.org/store-examples/news-fixture-2.webp"},
        "extra_snippets": ["Second fixture result for stable grid assertions."],
        "hash": "openmates-e2e-web-fixture-search",
    },
]


def is_e2e_web_fixture_query(query: str) -> bool:
    """Return True for the explicit non-production E2E web search fixture token."""
    return (
        os.getenv("SERVER_ENVIRONMENT", "production") != "production"
        and E2E_WEB_FIXTURE_QUERY_TOKEN in query.lower()
    )


def build_e2e_web_fixture_results(requested_count: int | None) -> List[Dict[str, Any]]:
    result_count = max(
        1,
        min(
            int(requested_count or DEFAULT_E2E_WEB_FIXTURE_RESULT_COUNT),
            len(E2E_WEB_FIXTURE_RESULTS),
        ),
    )
    return [dict(result) for result in E2E_WEB_FIXTURE_RESULTS[:result_count]]
