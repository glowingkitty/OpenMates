"""Focused contracts for auto provider routing and deferred event work."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from backend.tests.runtime_import_stubs import install_code_route_import_stubs

install_code_route_import_stubs()

from backend.apps.events.skills import search_skill as search_module  # noqa: E402
from backend.apps.events.skills import provider_routing  # noqa: E402
from backend.apps.events.skills.provider_routing import deterministic_auto_providers  # noqa: E402
from backend.apps.events.skills.search_skill import SearchRequest, SearchSkill  # noqa: E402

pytestmark = pytest.mark.anyio


def _skill(providers: list[str]) -> SearchSkill:
    skill = SearchSkill(
        app=None,
        app_id="events",
        skill_id="search",
        skill_name="Search",
        skill_description="Search events",
    )
    skill._providers_meta = [{"id": pid, "scope": "global"} for pid in providers]
    return skill


async def _no_secrets(**_kwargs: Any) -> tuple[None, None]:
    return None, None


def _event(provider: str, index: int = 1) -> dict[str, Any]:
    return {
        "id": f"{provider}-{index}",
        "provider": provider,
        "title": f"AI Builder Gathering {index}",
        "url": f"https://example.invalid/{provider}/{index}",
        "date_start": f"2026-10-{index + 10:02d}T18:00:00+02:00",
        "event_type": "PHYSICAL",
    }


# contract-test: direct surface=rest_api assertions=events-search.providers.auto-relevance
def test_deterministic_specialists_do_not_run_for_ai_but_do_for_techno_and_classical() -> None:
    eligible = [
        "meetup", "luma", "eventbrite", "resident_advisor",
        "siegessaeule", "berlin_philharmonic",
    ]
    assert deterministic_auto_providers(query="AI meetup", eligible_ids=eligible) == (
        ["meetup", "luma", "eventbrite"], [],
    )
    assert deterministic_auto_providers(query="Techno night", eligible_ids=eligible) == (
        ["meetup", "luma", "eventbrite", "resident_advisor"], [],
    )
    assert deterministic_auto_providers(query="Piano concerts", eligible_ids=eligible) == (
        ["meetup", "luma", "eventbrite", "berlin_philharmonic"], [],
    )


# contract-test: direct surface=rest_api assertions=events-search.providers.auto-relevance,events-search.enrichment.deferred
async def test_auto_ai_skips_specialists_and_keeps_twenty_candidates_per_provider(monkeypatch) -> None:
    skill = _skill(["meetup", "luma", "eventbrite", "resident_advisor", "berlin_philharmonic"])
    monkeypatch.setattr(skill, "_get_or_create_secrets_manager", _no_secrets)
    calls: dict[str, int] = {}

    async def general(provider: str, **kwargs: Any) -> tuple[list[dict[str, Any]], int, None]:
        calls[provider] = kwargs["count"]
        return [_event(provider)], 1, None

    async def forbidden(**_kwargs: Any) -> tuple[list[dict[str, Any]], int, None]:
        raise AssertionError("Unrelated specialist was searched")

    async def no_enrichment(_results: list[dict[str, Any]], **_kwargs: Any) -> None:
        return None

    for pid in ("meetup", "luma", "eventbrite"):
        monkeypatch.setattr(skill, f"_search_{pid}", lambda provider=pid, **kw: general(provider, **kw))
    monkeypatch.setattr(skill, "_search_resident_advisor", forbidden)
    monkeypatch.setattr(skill, "_search_berlin_philharmonic", forbidden)
    monkeypatch.setattr(skill, "_enrich_finalists", no_enrichment)

    response = await skill.execute(SearchRequest(requests=[{
        "query": "AI meetup", "location": "Berlin", "count": 10,
    }]))

    assert response.error is None
    assert response.providers == ["meetup", "luma", "eventbrite"]
    assert calls == {"meetup": 20, "luma": 20, "eventbrite": 20}


# contract-test: direct surface=rest_api assertions=events-search.providers.auto-relevance,events-search.providers.explicit
async def test_ambiguous_jev_adds_only_eligible_specialists_and_explicit_bypasses_it(monkeypatch) -> None:
    skill = _skill(["meetup", "resident_advisor", "berlin_philharmonic"])
    monkeypatch.setattr(skill, "_get_or_create_secrets_manager", _no_secrets)
    decisions: list[list[str]] = []

    async def choose(**kwargs: Any) -> list[str]:
        decisions.append(list(kwargs["candidates"]))
        return ["resident_advisor", "not_a_provider"]

    async def empty(**_kwargs: Any) -> tuple[list[dict[str, Any]], int, None]:
        return [], 0, None

    async def ra(**_kwargs: Any) -> tuple[list[dict[str, Any]], int, None]:
        return [_event("resident_advisor")], 1, None

    monkeypatch.setattr(search_module, "select_ambiguous_specialists", choose)
    monkeypatch.setattr(skill, "_search_meetup", empty)
    monkeypatch.setattr(skill, "_search_resident_advisor", ra)
    monkeypatch.setattr(skill, "_search_berlin_philharmonic", empty)

    auto = await skill.execute(SearchRequest(requests=[{
        "query": "underground dance gathering", "location": "Berlin",
    }]))
    assert auto.providers == ["meetup", "resident_advisor"]
    assert decisions == [["resident_advisor", "berlin_philharmonic"]]

    explicit = await skill.execute(SearchRequest(requests=[{
        "query": "underground dance gathering", "location": "Berlin",
        "providers": ["meetup", "resident_advisor"],
    }]))
    assert explicit.providers == ["meetup", "resident_advisor"]
    assert len(decisions) == 1


# contract-test: direct surface=rest_api assertions=events-search.performance.bounded
async def test_slow_provider_returns_partial_results_without_retry(monkeypatch) -> None:
    skill = _skill(["meetup", "luma"])
    monkeypatch.setattr(skill, "_get_or_create_secrets_manager", _no_secrets)
    monkeypatch.setattr(search_module, "_PROVIDER_WORK_DEADLINE_SECONDS", 0.03)
    calls = {"meetup": 0, "luma": 0}

    async def meetup(**_kwargs: Any) -> tuple[list[dict[str, Any]], int, None]:
        calls["meetup"] += 1
        return [_event("meetup")], 1, None

    async def luma(**_kwargs: Any) -> tuple[list[dict[str, Any]], int, None]:
        calls["luma"] += 1
        await asyncio.sleep(1)
        return [_event("luma")], 1, None

    monkeypatch.setattr(skill, "_search_meetup", meetup)
    monkeypatch.setattr(skill, "_search_luma", luma)
    response = await skill.execute(SearchRequest(requests=[{
        "query": "AI", "location": "Berlin",
    }]))

    assert response.error is None
    assert [event["provider"] for event in response.results[0]["results"]] == ["meetup"]
    assert response.warnings == ["luma search unavailable"]
    assert calls == {"meetup": 1, "luma": 1}


# contract-test: direct surface=rest_api assertions=events-search.enrichment.deferred
async def test_only_finalists_receive_optional_enrichment(monkeypatch) -> None:
    skill = _skill(["luma"])
    monkeypatch.setattr(skill, "_get_or_create_secrets_manager", _no_secrets)
    enriched: list[str] = []

    async def luma(**kwargs: Any) -> tuple[list[dict[str, Any]], int, None]:
        assert kwargs["count"] == 4
        return [_event("luma", i) for i in range(1, 5)], 4, None

    async def enrich(events: list[dict[str, Any]], **_kwargs: Any) -> None:
        enriched.extend(event["id"] for event in events)
        for event in events:
            event["description"] = "Selected event details"

    monkeypatch.setattr(skill, "_search_luma", luma)
    monkeypatch.setattr(search_module.luma_provider, "enrich_events_async", enrich)
    response = await skill.execute(SearchRequest(requests=[{
        "query": "AI", "location": "Berlin", "count": 2,
    }]))

    assert enriched == ["luma-1", "luma-2"]
    assert [event["description"] for event in response.results[0]["results"]] == [
        "Selected event details", "Selected event details",
    ]


# contract-test: direct surface=rest_api assertions=events-search.providers.auto-relevance
async def test_jev_specialist_decision_is_bounded_and_falls_back(monkeypatch) -> None:
    from backend.shared.providers.typesafe.models import DecisionResponse

    seen: list[tuple[float, int, list[str]]] = []

    class FakeJev:
        def __init__(self, *, timeout_seconds: float, max_retries: int, **_kwargs: Any) -> None:
            seen.append((timeout_seconds, max_retries, []))

        async def evaluate(self, *, state: dict[str, Any], questions: dict[str, Any]) -> DecisionResponse:
            seen[-1][2].extend(questions)
            assert state["eligible_specialists"] == ["resident_advisor", "berlin_philharmonic"]
            return DecisionResponse.model_validate({
                "model": "typesafe/jev-1.13",
                "answers": {
                    "resident_advisor": {"type": "noul", "noul": 0.91},
                    "berlin_philharmonic": {"type": "noul", "noul": 0.08},
                },
            })

    monkeypatch.setattr(provider_routing, "JevDecisionClient", FakeJev)
    kwargs = {
        "query": "underground dance gathering",
        "location": "Berlin",
        "event_type": "PHYSICAL",
        "candidates": ["resident_advisor", "berlin_philharmonic"],
        "provider_metadata": [],
        "secrets_manager": None,
    }
    assert await provider_routing.select_ambiguous_specialists(**kwargs) == ["resident_advisor"]
    assert seen == [(0.9, 0, ["resident_advisor", "berlin_philharmonic"])]

    class FailedJev(FakeJev):
        async def evaluate(self, **_kwargs: Any) -> DecisionResponse:
            raise TimeoutError("routing model unavailable")

    monkeypatch.setattr(provider_routing, "JevDecisionClient", FailedJev)
    assert await provider_routing.select_ambiguous_specialists(**kwargs) == []


# contract-test: direct surface=rest_api assertions=events-search.enrichment.deferred
async def test_provider_searches_request_lightweight_candidates(monkeypatch) -> None:
    skill = _skill(["luma", "eventbrite"])
    flags: list[tuple[str, bool, bool | None]] = []

    async def fake_luma(**kwargs: Any) -> tuple[list[dict[str, Any]], int]:
        flags.append(("luma", kwargs["fetch_descriptions"], kwargs["geocode_venues"]))
        return [], 0

    async def fake_eventbrite(**kwargs: Any) -> tuple[list[dict[str, Any]], int]:
        flags.append(("eventbrite", kwargs["fetch_descriptions"], None))
        return [], 0

    monkeypatch.setattr(search_module.luma_provider, "search_events_async", fake_luma)
    monkeypatch.setattr(search_module.eventbrite_provider, "search_events_async", fake_eventbrite)
    await skill._search_luma(query="AI", location_str="Berlin", count=20)
    await skill._search_eventbrite(query="AI", location_str="Berlin", event_type="PHYSICAL", count=20)
    assert flags == [("luma", False, False), ("eventbrite", False, None)]


# contract-test: direct surface=rest_api assertions=events-search.enrichment.deferred,events-search.performance.bounded
async def test_uncached_meetup_geocoder_does_not_block_text_provider(monkeypatch) -> None:
    skill = _skill(["meetup", "eventbrite"])
    monkeypatch.setattr(skill, "_get_or_create_secrets_manager", _no_secrets)
    order: list[str] = []

    def resolve_unknown(_location: str) -> tuple[float, float, str, str]:
        time.sleep(0.05)
        order.append("geocoder")
        return 35.68, 139.69, "Tokyo", "JP"

    async def meetup(**_kwargs: Any) -> tuple[list[dict[str, Any]], int, None]:
        order.append("meetup")
        return [_event("meetup")], 1, None

    async def eventbrite(**_kwargs: Any) -> tuple[list[dict[str, Any]], int, None]:
        order.append("eventbrite")
        return [_event("eventbrite")], 1, None

    async def no_enrichment(_results: list[dict[str, Any]], **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(search_module.meetup_provider, "resolve_location", resolve_unknown)
    monkeypatch.setattr(skill, "_search_meetup", meetup)
    monkeypatch.setattr(skill, "_search_eventbrite", eventbrite)
    monkeypatch.setattr(skill, "_enrich_finalists", no_enrichment)

    response = await skill.execute(SearchRequest(requests=[{
        "query": "AI", "location": "An Unknown City",
    }]))
    assert response.error is None
    assert order == ["eventbrite", "geocoder", "meetup"]
