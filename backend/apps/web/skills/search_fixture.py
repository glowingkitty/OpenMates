# backend/apps/web/skills/search_fixture.py
#
# Dependency-light fixture helpers for web/search E2E tests.
# Direct app-skill calls bypass chat live-mock markers, so tests use an explicit
# non-production query token to exercise result rendering without spending Brave
# Search quota.

import asyncio
import os
from typing import Any, Dict, List


DEFAULT_E2E_WEB_FIXTURE_RESULT_COUNT = 6
E2E_WEB_FIXTURE_QUERY_TOKEN = "openmates_e2e_web_fixture_ai"
E2E_CAMERA_SEARCH_QUERY = E2E_WEB_FIXTURE_QUERY_TOKEN + " camera-current-frame"
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


async def wait_camera_search_provider_fixture(query: str) -> None:
    """Expose real processing UI with latency only in the exact isolated call fixture."""
    if query != E2E_CAMERA_SEARCH_QUERY:
        return
    from backend.shared.testing.voice_call_fixture import isolated_voice_fixture_enabled
    if isolated_voice_fixture_enabled():
        await asyncio.sleep(1)


async def wait_throttled_search_provider_fixture(query: str, cache_service: Any) -> None:
    """Exercise real provider retries/Redis against an isolated synthetic 1-RPS API."""
    from backend.apps.ai.testing.mercury_routing_fixture import active

    marker = f"{E2E_WEB_FIXTURE_QUERY_TOKEN} throttle "
    if not active() or not query.startswith(marker):
        return
    from uuid import UUID
    import httpx
    from backend.shared.providers.brave.brave_search import _request_with_429_retry

    batch_id = str(UUID(query[len(marker):].split()[0]))
    cache = await cache_service.client
    if cache is None:
        raise RuntimeError("Isolated Brave throttle fixture requires its real Redis cache")

    class Provider:
        async def get(self, url: str, params: dict, headers: dict) -> httpx.Response:
            admitted = await cache.set(f"brave:fixture:{batch_id}:slot", "1", nx=True, px=1000)
            return httpx.Response(
                200 if admitted else 429,
                headers={"X-RateLimit-Limit": "1, 2000", "X-RateLimit-Reset": "1, 1200"},
                json={} if admitted else {"error": {
                    "code": "RATE_LIMITED", "meta": {"rate_limit": 1, "quota_limit": 2000, "quota_current": 10},
                }},
                request=httpx.Request("GET", url),
            )

    # Only the HTTP boundary is synthetic: bounded retries and separate cache
    # connections use the same provider path as normal web/news/image/video calls.
    await _request_with_429_retry(
        client=Provider(),
        url="https://fixture.invalid/brave/search",
        params={},
        headers={"X-Subscription-Token": f"ci-brave-placeholder-{batch_id}"},
        query="isolated concurrent search",
        search_type="web",
    )
