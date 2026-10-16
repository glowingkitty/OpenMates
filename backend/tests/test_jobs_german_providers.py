"""Deterministic contracts for the two German job search adapters."""

from datetime import datetime, timezone

import httpx
import pytest

from backend.shared.providers.jobs import arbeitnow, arbeitsagentur
from backend.shared.providers.jobs.common import ProviderError, fetch_json

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def clear_feed_cache() -> None:
    arbeitnow._PAGE_CACHE.clear()


# contract-test: supporting surface=rest_api assertions=app-skills.surface.semantic-parity
async def test_arbeitnow_scans_later_pages_and_preserves_explicit_remote(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = {
        1: ([{"slug": "not-target", "title": "Designer", "company_name": "Acme",
              "url": "https://www.arbeitnow.com/view/not-target", "location": "Berlin, Germany",
              "remote": False, "created_at": 1791849600}], True),
        2: ([{"slug": "engineer-2", "title": "Engineer", "company_name": "Acme",
              "description": "<p>Clean <strong>energy</strong> work</p>",
              "url": "https://www.arbeitnow.com/view/engineer-2#tracking",
              "location": "Berlin, Germany", "remote": True,
              "job_types": ["full_time"], "created_at": 1791849600}], False),
    }
    calls: list[int] = []

    async def page(_client: httpx.AsyncClient, number: int) -> tuple[list[dict], bool]:
        calls.append(number)
        return pages[number]

    monkeypatch.setattr(arbeitnow, "_page", page)
    jobs = await arbeitnow.search_jobs(query="energy", location="Berlin", remote=True,
                                        employment_type="full_time")
    assert calls == [1, 2]
    assert len(jobs) == 1
    assert jobs[0]["id"] == "arbeitnow:engineer-2"
    assert jobs[0]["description"] == "Clean energy work"
    assert jobs[0]["url"] == "https://www.arbeitnow.com/view/engineer-2"
    assert jobs[0]["remote"] is True
    assert jobs[0]["salary_min"] is None


@pytest.mark.parametrize(
    ("location", "is_german"),
    [
        ("Aachen, Germany", True),
        ("Berlin, Berlin, Deutschland", True),
        ("Germany | Berlin, remote/hybrid", True),
        ("Darmstadt, DE", True),
        ("Berlin", False),
        ("Leverkusen", False),
        ("Remote", False),
        ("Homeoffice", False),
        ("Lisbon", False),
        ("London, UK", False),
        ("Paris, France", False),
        ("", False),
        (None, False),
    ],
)
# contract-test: supporting surface=rest_api assertions=app-skills.surface.semantic-parity
def test_arbeitnow_needs_affirmative_german_location(location: str | None, is_german: bool) -> None:
    raw = {"slug": "role-1", "title": "Engineer", "location": location, "remote": True}
    job = arbeitnow._normalize(raw)
    assert (job is not None) is is_german
    if job:
        assert job["country"] == "DE"
        assert job["location"] == location


# contract-test: supporting surface=rest_api assertions=app-skills.execution.registered-validated
async def test_arbeitnow_unsupported_country_and_radius(monkeypatch: pytest.MonkeyPatch) -> None:
    async def should_not_fetch(*_args: object) -> None:
        raise AssertionError("unsupported country must not touch provider")

    monkeypatch.setattr(arbeitnow, "_page", should_not_fetch)
    assert await arbeitnow.search_jobs(country="SE") == []
    with pytest.raises(ProviderError, match="radius") as exc:
        await arbeitnow.search_jobs(radius_km=20)
    assert exc.value.code == "unsupported_filter"


# contract-test: supporting surface=rest_api assertions=app-skills.surface.semantic-parity
async def test_ba_v6_filters_and_v4_detail_with_radius(monkeypatch: pytest.MonkeyPatch) -> None:
    search_params: list[dict] = []
    records = [
        {"referenznummer": "10001-123-S", "stellenangebotsTitel": "Engineer",
         "firma": "Example GmbH", "arbeitszeitVollzeit": True,
         "homeofficemoeglich": True, "homeofficetyp": "NACH_VEREINBARUNG",
         "stellenlokationen": [{"adresse": {"ort": "Berlin", "region": "BERLIN"}}],
         "datumErsteVeroeffentlichung": datetime.now(timezone.utc).date().isoformat()},
        {"referenznummer": "10001-124-S", "stellenangebotsTitel": "Remote Engineer",
         "firma": "Example GmbH", "arbeitszeitVollzeit": True,
         "homeofficemoeglich": False,
         "datumErsteVeroeffentlichung": datetime.now(timezone.utc).date().isoformat()},
    ]

    async def fake_fetch(_client: httpx.AsyncClient, url: str, *, params: dict | None = None,
                         headers: dict | None = None) -> dict:
        assert headers == arbeitsagentur.PUBLIC_HEADER
        if url == arbeitsagentur.SEARCH_URL:
            search_params.append(dict(params or {}))
            return {"ergebnisliste": records}
        assert url.startswith(arbeitsagentur.DETAIL_ROOT)
        return {"stellenangebotsBeschreibung": "<p>Build climate software.</p>"}

    monkeypatch.setattr(arbeitsagentur, "fetch_json", fake_fetch)
    jobs = await arbeitsagentur.search_jobs(query="Engineer", location="Berlin", radius_km=20,
                                             employment_type="full_time", limit=2)
    assert search_params[0]["umkreis"] == 20
    assert search_params[0]["wo"] == "Berlin"
    assert search_params[0]["angebotsart"] == 1
    assert [job["id"] for job in jobs] == ["arbeitsagentur:10001-123-S", "arbeitsagentur:10001-124-S"]
    assert jobs[0]["remote"] is None
    assert jobs[1]["remote"] is False
    assert jobs[0]["description"] == "Build climate software."
    assert jobs[0]["url"] == "https://www.arbeitsagentur.de/jobsuche/jobdetail/10001-123-S"
    assert await arbeitsagentur.search_jobs(query="Engineer", remote=True) == []


# contract-test: supporting surface=rest_api assertions=app-skills.execution.registered-validated
async def test_ba_unsupported_country_and_radius_before_http() -> None:
    assert await arbeitsagentur.search_jobs(country="SE") == []
    with pytest.raises(ProviderError) as exc:
        await arbeitsagentur.search_jobs(radius_km=20)
    assert exc.value.code == "unsupported_filter"


# contract-test: supporting surface=rest_api assertions=app-skills.execution.registered-validated
async def test_shared_retry_and_safe_error() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"data": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await fetch_json(client, "https://example.test/jobs") == {"data": []}
    assert calls == 2

    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _request: httpx.Response(429))) as client:
        with pytest.raises(ProviderError) as exc:
            await fetch_json(client, "https://example.test/jobs")
    assert exc.value.code == "rate_limited"
