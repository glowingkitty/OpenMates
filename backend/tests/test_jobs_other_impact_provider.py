"""Hard Problems' published RSS contract and conservative country/filter handling."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from typing import Any
from xml.sax.saxutils import escape

import pytest
import httpx

from backend.shared.providers.jobs import hard_problems
from backend.shared.providers.jobs.common import ProviderError


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def no_live_detail_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    async def details(*args: Any) -> dict[str, str]:
        return {"detail_status": "complete"}
    monkeypatch.setattr(hard_problems, "fetch_role_details", details)


def _item(
    *,
    title: str = "Product Designer at Climate Lab",
    url: str = "https://www.hardproblems.com/jobs/role/climate-lab-product-designer",
    original: str = "https://climatelab.example/jobs/123",
    location: str = "Berlin, Germany · Remote",
    category: str = "Climate Tech",
    age_days: int = 0,
) -> str:
    published = format_datetime(datetime.now(timezone.utc) - timedelta(days=age_days))
    description = escape(f"<p>A useful role summary from the public feed.</p><p>{location}</p>")
    return (
        f"<item><title>{escape(title)}</title><link>{escape(url)}</link>"
        f"<guid>{escape(original)}</guid><pubDate>{published}</pubDate>"
        f"<category>{escape(category)}</category><description>{description}</description></item>"
    )


def _feed(*items: str) -> bytes:
    return ("<rss version='2.0'><channel><title>Hard Problems</title>" + "".join(items) + "</channel></rss>").encode()


# contract-test: supporting surface=rest_api assertions=app-skills.execution.registered-validated,app-skills.surface.semantic-parity
async def test_country_verified_normalization_and_description(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def fake_fetch(client: Any, country_name: str) -> bytes:
        calls.append(country_name)
        return _feed(_item(), _item(title="Out of country at Elsewhere", location="Paris, France"),
                     _item(title="Global at Anywhere", location="Global · Remote"))

    monkeypatch.setattr(hard_problems, "_fetch_feed", fake_fetch)
    jobs = await hard_problems.search_jobs(country="DE", query="designer", location="Berlin", remote=True, impact_area="climate")
    assert calls == ["Germany"]
    assert len(jobs) == 1
    job = jobs[0]
    assert job["id"] == "hard_problems:climate-lab-product-designer"
    assert job["title"] == "Product Designer"
    assert job["company"] == "Climate Lab"
    assert job["url"] == "https://www.hardproblems.com/jobs/role/climate-lab-product-designer"
    assert job["apply_url"] == "https://climatelab.example/jobs/123"
    assert job["country"] == "DE" and job["location"] == "Berlin, Germany"
    assert job["remote"] is True
    assert job["description"] == "A useful role summary from the public feed."
    assert job["salary_min"] is None
    assert job["employment_type"] is None and job["provider"] == "hard_problems"


# contract-test: supporting surface=rest_api assertions=app-skills.surface.semantic-parity
async def test_sweden_hybrid_unknown_and_stale_location_exclusions(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch(*args: Any) -> bytes:
        return _feed(
            _item(title="UX Researcher at Civic Health", location="Stockholm, Sweden · Hybrid", category="Health", age_days=2),
            _item(title="Designer at Old Lab", location="Stockholm, Sweden", age_days=30),
            _item(title="Designer at Wrong City", location="Gothenburg, Sweden"),
            _item(title="Designer at Global", location="Global · Remote"),
        )

    monkeypatch.setattr(hard_problems, "_fetch_feed", fake_fetch)
    jobs = await hard_problems.search_jobs(country="Sweden", location="Stockholm", max_days_old=7)
    assert [job["title"] for job in jobs] == ["UX Researcher"]
    assert jobs[0]["remote"] is None
    assert jobs[0]["country"] == "SE"
    assert await hard_problems.search_jobs(country="SE", location="Stockholm", remote=True) == []


# contract-test: supporting surface=rest_api assertions=app-skills.execution.registered-validated
async def test_unsupported_country_and_filters_make_no_request(monkeypatch: pytest.MonkeyPatch) -> None:
    async def forbidden_fetch(*args: Any) -> bytes:
        raise AssertionError("must not contact feed")

    monkeypatch.setattr(hard_problems, "_fetch_feed", forbidden_fetch)
    assert await hard_problems.search_jobs(country="FR") == []
    assert await hard_problems.search_jobs(country="") == []
    assert await hard_problems.search_jobs(country="DE", limit=0) == []
    assert await hard_problems.search_jobs(country="DE", limit=-1) == []
    for kwargs in ({"remote": False}, {"employment_type": "full_time"}, {"radius_km": 20}):
        with pytest.raises(ProviderError) as error:
            await hard_problems.search_jobs(country="DE", **kwargs)
        assert error.value.code == "unsupported_filter"


# contract-test: supporting surface=rest_api assertions=app-skills.execution.registered-validated
async def test_invalid_or_untrusted_rss_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    for content in (b"<rss>", b"<html/>", b"<!DOCTYPE rss><rss><channel/></rss>"):
        async def fake_fetch(*args: Any) -> bytes:
            return content

        monkeypatch.setattr(hard_problems, "_fetch_feed", fake_fetch)
        with pytest.raises(ProviderError) as error:
            await hard_problems.search_jobs(country="DE")
        assert error.value.code == "invalid_response"


# contract-test: supporting surface=rest_api assertions=app-skills.surface.semantic-parity
async def test_unsafe_links_omitted_and_result_limit_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    items = [
        _item(title=f"Designer {number} at Good Org", url=f"https://www.hardproblems.com/jobs/role/role-{number}", original="javascript:alert(1)")
        for number in range(30)
    ]

    async def fake_fetch(*args: Any) -> bytes:
        return _feed(*items)

    monkeypatch.setattr(hard_problems, "_fetch_feed", fake_fetch)
    jobs = await hard_problems.search_jobs(country="DE", limit=1000)
    assert len(jobs) == hard_problems.MAX_RESULTS
    assert all(job["apply_url"] is None for job in jobs)


# contract-test: supporting surface=rest_api assertions=app-skills.surface.semantic-parity
async def test_query_tail_after_160_characters_is_not_silently_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    long_term = "a" * 160

    async def fake_fetch(*args: Any) -> bytes:
        return _feed(_item(title=f"{long_term} at Climate Lab"))

    monkeypatch.setattr(hard_problems, "_fetch_feed", fake_fetch)
    assert len(await hard_problems.search_jobs(country="DE", query=long_term)) == 1
    assert await hard_problems.search_jobs(country="DE", query=f"{long_term} missing") == []


# contract-test: supporting surface=rest_api assertions=app-skills.execution.registered-validated
async def test_http_request_sends_only_country_and_rejects_oversize_feed() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=b"x" * (hard_problems.MAX_FEED_BYTES + 1))

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(ProviderError) as error:
            await hard_problems._fetch_feed(client, "Germany")
    assert error.value.code == "invalid_response"
    assert len(requests) == 1
    assert str(requests[0].url) == "https://www.hardproblems.com/jobs/feed.xml?country=Germany"
