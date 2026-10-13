"""Deterministic contract tests for Sweden's public JobTech JobSearch adapter."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from backend.shared.providers.jobs import jobtech
from backend.shared.providers.jobs.common import ProviderError


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _ad(
    source_id: str = "31562679",
    *,
    country_code: str = "199",
    hours: str = "Heltid",
    workplace_model: str | None = None,
) -> dict[str, Any]:
    return {
        "id": source_id,
        "headline": "iOS Developer",
        "employer": {"name": "Vend Marketplaces AB"},
        "webpage_url": f"https://arbetsformedlingen.se/platsbanken/annonser/{source_id}",
        "application_details": {"url": "javascript:alert(1)"},
        "workplace_address": {
            "city": "Stockholm",
            "municipality": "Stockholm",
            "region": "Stockholms län",
            "country_code": country_code,
            "country_concept_id": jobtech.SWEDEN_CONCEPT_ID if country_code == "199" else "other",
        },
        "publication_date": datetime.now(timezone.utc).isoformat(),
        "description": {"text": "<p>Build safe mobile apps.</p>"},
        "working_hours_type": {"label": hours},
        "workplace_model": {"label": workplace_model},
        "salary_description": "Competitive salary",
    }


# contract-test: supporting surface=rest_api assertions=app-skills.execution.registered-validated
async def test_non_sweden_country_is_rejected_before_http(monkeypatch: pytest.MonkeyPatch) -> None:
    async def forbidden_fetch(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("No request should be made")

    monkeypatch.setattr(jobtech, "fetch_json", forbidden_fetch)
    assert await jobtech.search_jobs(query="developer", country="DE") == []
    assert await jobtech.search_jobs(query="developer", country="") == []


# contract-test: supporting surface=rest_api assertions=app-skills.surface.semantic-parity
async def test_search_maps_filters_and_normalizes_only_swedish_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    async def fake_fetch(client: Any, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        assert url == jobtech.JOBTECH_SEARCH_URL
        calls.append(params)
        return {"hits": [_ad(), _ad("abroad", country_code="123")]}

    monkeypatch.setattr(jobtech, "fetch_json", fake_fetch)
    jobs = await jobtech.search_jobs(
        query="developer", location="Stockholm", country="SE", remote=True,
        employment_type="full_time", max_days_old=3, limit=10,
    )

    assert len(calls) == 1
    assert calls[0]["country"] == jobtech.SWEDEN_CONCEPT_ID
    assert calls[0]["q"] == "developer Stockholm"
    assert calls[0]["remote"] is True
    assert calls[0]["published-after"] == 4320
    assert len(jobs) == 1
    assert jobs[0]["id"] == "jobtech:31562679"
    assert jobs[0]["provider"] == "jobtech"
    assert jobs[0]["company"] == "Vend Marketplaces AB"
    assert jobs[0]["location"] == "Stockholm, Stockholms län"
    assert jobs[0]["country"] == "SE"
    assert jobs[0]["remote"] is None  # phrase search is not a verified job attribute
    assert jobs[0]["employment_type"] == "full_time"
    assert jobs[0]["apply_url"] == jobs[0]["url"]  # unsafe application URL is discarded
    assert jobs[0]["description"] == "Build safe mobile apps."
    assert jobs[0]["salary_min"] is None
    assert jobs[0]["salary_max"] is None
    assert jobs[0]["salary_currency"] is None


# contract-test: supporting surface=rest_api assertions=app-skills.surface.semantic-parity
async def test_requested_city_must_match_workplace_not_description(monkeypatch: pytest.MonkeyPatch) -> None:
    wrong_city = _ad("wrong-city")
    wrong_city["workplace_address"].update({
        "city": "Uppsala", "municipality": "Uppsala", "region": "Uppsala län",
    })
    wrong_city["description"]["text"] = "Work with our Stockholm office from Uppsala."

    async def fake_fetch(*args: Any, **kwargs: Any) -> dict[str, Any]:
        assert kwargs["params"]["q"] == "developer Stockholm"
        return {"hits": [wrong_city]}

    monkeypatch.setattr(jobtech, "fetch_json", fake_fetch)
    assert await jobtech.search_jobs(query="developer", location="Stockholm", country="SE") == []


# contract-test: supporting surface=rest_api assertions=app-skills.execution.registered-validated
async def test_unverifiable_workplace_surfaces_location_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    unknown_city = _ad("unknown-city")
    unknown_city["workplace_address"].update({"city": None, "municipality": None, "region": "Stockholms län"})

    async def fake_fetch(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"hits": [unknown_city]}

    monkeypatch.setattr(jobtech, "fetch_json", fake_fetch)
    with pytest.raises(ProviderError) as error:
        await jobtech.search_jobs(location="Stockholm", country="SE")
    assert error.value.code == "unsupported_filter"
    assert "could not verify" in error.value.message


# contract-test: supporting surface=rest_api assertions=app-skills.execution.registered-validated,app-skills.surface.semantic-parity
async def test_employment_type_filter_uses_explicit_worktime(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"hits": [_ad("full"), _ad("part", hours="Deltid")]}

    monkeypatch.setattr(jobtech, "fetch_json", fake_fetch)
    jobs = await jobtech.search_jobs(country="Sweden", employment_type="part_time")
    assert [job["id"] for job in jobs] == ["jobtech:part"]
    assert jobs[0]["employment_type"] == "part_time"


# contract-test: supporting surface=rest_api assertions=app-skills.surface.semantic-parity
async def test_structured_remote_model_can_be_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"hits": [_ad(workplace_model="Remote")]}

    monkeypatch.setattr(jobtech, "fetch_json", fake_fetch)
    jobs = await jobtech.search_jobs(country="SE")
    assert jobs[0]["remote"] is True


# contract-test: supporting surface=rest_api assertions=app-skills.surface.semantic-parity
async def test_hybrid_and_partial_distance_models_remain_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"hits": [
            _ad("hybrid", workplace_model="Hybrid / remote"),
            _ad("partial", workplace_model="Delvis distansarbete"),
            _ad("possible", workplace_model="Möjlighet till distansarbete"),
        ]}

    monkeypatch.setattr(jobtech, "fetch_json", fake_fetch)
    jobs = await jobtech.search_jobs(country="SE")
    assert [job["remote"] for job in jobs] == [None, None, None]


# contract-test: supporting surface=rest_api assertions=app-skills.surface.semantic-parity
async def test_remote_phrase_candidate_can_be_explicitly_onsite(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"hits": [_ad(workplace_model="Arbete på plats")]}

    monkeypatch.setattr(jobtech, "fetch_json", fake_fetch)
    jobs = await jobtech.search_jobs(country="SE", remote=True)
    assert jobs[0]["remote"] is False


# contract-test: supporting surface=rest_api assertions=app-skills.execution.registered-validated
async def test_radius_and_impact_filters_fail_explicitly() -> None:
    with pytest.raises(ProviderError) as radius:
        await jobtech.search_jobs(country="SE", radius_km=20)
    assert radius.value.code == "unsupported_filter"

    with pytest.raises(ProviderError) as impact:
        await jobtech.search_jobs(country="SE", impact_area="climate")
    assert impact.value.code == "unsupported_filter"


# contract-test: supporting surface=rest_api assertions=app-skills.execution.registered-validated
async def test_invalid_payload_and_provider_failures_propagate(monkeypatch: pytest.MonkeyPatch) -> None:
    async def malformed(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"hits": "wrong type"}

    monkeypatch.setattr(jobtech, "fetch_json", malformed)
    with pytest.raises(ProviderError) as invalid:
        await jobtech.search_jobs(country="SE")
    assert invalid.value.code == "invalid_response"

    async def unavailable(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise ProviderError("unavailable", "Job source is temporarily unavailable.")

    monkeypatch.setattr(jobtech, "fetch_json", unavailable)
    with pytest.raises(ProviderError) as error:
        await jobtech.search_jobs(country="SE")
    assert error.value.code == "unavailable"


# contract-test: supporting surface=rest_api assertions=app-skills.execution.registered-validated,app-skills.surface.semantic-parity
async def test_result_and_request_limits_are_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    params_seen: list[dict[str, Any]] = []

    async def fake_fetch(client: Any, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        params_seen.append(params)
        return {"hits": [_ad(str(i)) for i in range(40)]}

    monkeypatch.setattr(jobtech, "fetch_json", fake_fetch)
    jobs = await jobtech.search_jobs(country="SE", limit=10_000)
    assert params_seen[0]["limit"] <= jobtech.MAX_FETCH
    assert len(jobs) == jobtech.MAX_RESULTS
