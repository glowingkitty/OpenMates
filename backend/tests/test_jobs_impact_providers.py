"""Contract checks for curated impact job-board adapters."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any

import httpx
import pytest

from backend.shared.providers.jobs import eighty_thousand_hours as hours
from backend.shared.providers.jobs.common import ProviderError

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _hit(
    source_id: str = "21234", *, country: str = "Germany", city: str = "Berlin, Germany",
    role: str = "Full-time", url: str = "https://example.org/apply",
) -> dict[str, Any]:
    return {
        "objectID": source_id, "title": "AI safety researcher", "company_name": "Example Institute",
        "url_external": url, "tags_country": [country, "Europe (ex UK)"],
        "tags_city": [city], "tags_role_type": [role],
        "posted_at": datetime.now(timezone.utc).timestamp(),
        "description_short": "A board-owned description that must not be copied.",
        "salary": "Competitive",
    }


# contract-test: supporting surface=rest_api assertions=app-skills.execution.registered-validated
async def test_80k_unsupported_country_and_filters_fail_before_http(monkeypatch: pytest.MonkeyPatch) -> None:
    async def forbidden_config(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("No upstream request expected")

    monkeypatch.setattr(hours, "_browser_config", forbidden_config)
    assert await hours.search_jobs(country="FR") == []
    for kwargs in ({"radius_km": 20}, {"remote": True}, {"impact_area": "climate"},
                   {"employment_type": "apprenticeship"}):
        with pytest.raises(ProviderError) as error:
            await hours.search_jobs(country="DE", **kwargs)
        assert error.value.code == "unsupported_filter"


# contract-test: supporting surface=rest_api assertions=app-skills.surface.semantic-parity
async def test_80k_strict_country_city_and_minimal_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    async def fake_config(client: Any) -> tuple[str, str, str]:
        return "PUBLICAPP", "browser-search-key", "jobs_prod"

    async def fake_search(client: Any, app: str, key: str, index: str, **kwargs: Any) -> list[dict[str, Any]]:
        calls.append(kwargs)
        return [
            _hit("berlin"), _hit("munich", city="Munich, Germany"),
            _hit("france", country="France", city="Berlin, Germany"),
            _hit("unsafe", url="javascript:alert(1)"),
        ]

    monkeypatch.setattr(hours, "_browser_config", fake_config)
    monkeypatch.setattr(hours, "_search_index", fake_search)
    jobs = await hours.search_jobs(query="researcher", location="Berlin", country="DE", limit=5)
    assert calls == [{"query": "researcher", "country_name": "Germany", "limit": 5}]
    assert [job["id"] for job in jobs] == ["eighty_thousand_hours:berlin"]
    assert jobs[0]["provider"] == "eighty_thousand_hours"
    assert jobs[0]["country"] == "DE"
    assert jobs[0]["employment_type"] == "full_time"
    assert jobs[0]["remote"] is None
    assert jobs[0]["url"] == "https://example.org/apply"
    assert jobs[0]["description"] is None
    assert jobs[0]["salary_min"] is None
    assert await hours.search_jobs(location="Sweden", country="DE") == []


# contract-test: supporting surface=rest_api assertions=app-skills.surface.semantic-parity
async def test_80k_sweden_and_role_date_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_config(client: Any) -> tuple[str, str, str]:
        return "PUBLICAPP", "browser-search-key", "jobs_prod"

    async def fake_search(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        old = _hit("old", country="Sweden", city="Stockholm, Sweden", role="Internship")
        old["posted_at"] = 1_641_859_200
        current = _hit("current", country="Sweden", city="Stockholm, Sweden", role="Internship")
        current["tags_city"] = ["San Francisco Bay Area", "Stockholm, Sweden", "New York, NY"]
        return [old, current]

    monkeypatch.setattr(hours, "_browser_config", fake_config)
    monkeypatch.setattr(hours, "_search_index", fake_search)
    jobs = await hours.search_jobs(country="SE", location="Stockholm", employment_type="internship", max_days_old=30)
    assert [job["id"] for job in jobs] == ["eighty_thousand_hours:current"]
    assert jobs[0]["country"] == "SE"
    assert jobs[0]["location"] == "Stockholm, Sweden"


# contract-test: supporting surface=rest_api assertions=app-skills.execution.registered-validated
async def test_80k_browser_config_and_algolia_request_are_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hours, "_CONFIG_CACHE", None)
    seen: list[httpx.Request] = []
    public_config = (
        '<script>window.__NUXT__.config={public:{algoliaApplicationId:"PUBLICAPP",'
        'algoliaApiKey:"browsersearchkey123",algoliaJobsIndex:"jobs_prod"}}</script>'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "jobs.80000hours.org":
            return httpx.Response(200, text=public_config)
        assert request.url.host == "publicapp-dsn.algolia.net"
        return httpx.Response(200, json={"hits": [_hit()]})

    real_client = httpx.AsyncClient

    def mock_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        return real_client(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(hours.httpx, "AsyncClient", mock_client)
    jobs = await hours.search_jobs(country="DE", query="researcher" * 100, limit=1000)
    assert len(jobs) == 1
    assert len(seen) == 2
    assert seen[1].method == "POST"
    assert seen[1].url.path == "/1/indexes/jobs_prod/query"
    assert seen[1].headers["x-algolia-api-key"] == "browsersearchkey123"
    body = json.loads(seen[1].content)
    assert body["facetFilters"] == ["tags_country:Germany"]
    assert body["hitsPerPage"] <= hours.MAX_FETCH
    assert len(body["query"]) == hours.MAX_QUERY_CHARS
    assert body["attributesToRetrieve"] == [
        "objectID", "title", "company_name", "url_external", "tags_country",
        "tags_city", "tags_role_type", "posted_at",
    ]
    async with real_client(transport=httpx.MockTransport(handler)) as cached_client:
        assert await hours._browser_config(cached_client) == (
            "PUBLICAPP", "browsersearchkey123", "jobs_prod",
        )
    assert len(seen) == 2  # cached board config avoids another GET


# contract-test: supporting surface=rest_api assertions=app-skills.execution.registered-validated
async def test_80k_changed_config_and_rate_limit_are_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hours, "_CONFIG_CACHE", None)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, text="changed"))) as client:
        with pytest.raises(ProviderError) as error:
            await hours._browser_config(client)
        assert error.value.code == "invalid_response"

    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(429))) as client:
        with pytest.raises(ProviderError) as error:
            await hours._search_index(client, "PUBLICAPP", "browser-search-key", "jobs_prod",
                                      query="", country_name="Germany", limit=10)
        assert error.value.code == "rate_limited"
