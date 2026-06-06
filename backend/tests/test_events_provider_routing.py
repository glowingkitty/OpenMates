# backend/tests/test_events_provider_routing.py
#
# Regression tests for events/search provider routing.
# Verifies explicit provider constraints survive request normalization and do
# not silently broaden to auto when a named provider fails.
# Architecture context: backend/apps/events/skills/search_skill.py

from typing import Any

import pytest

from backend.apps.events.skills.search_skill import SearchRequest, SearchSkill

pytestmark = pytest.mark.anyio


def _make_skill() -> SearchSkill:
    return SearchSkill(
        app=None,
        app_id="events",
        skill_id="search",
        skill_name="Search",
        skill_description="Search events",
    )


async def _no_secrets(*args: Any, **kwargs: Any) -> tuple[None, None]:
    return None, None


async def test_top_level_eventbrite_does_not_fallback_to_auto(monkeypatch: pytest.MonkeyPatch) -> None:
    """A user-requested Eventbrite search must not call Meetup/Luma after failure."""

    skill = _make_skill()
    skill._providers_meta = [
        {"id": "meetup", "scope": "global"},
        {"id": "luma", "scope": "global"},
    ]
    monkeypatch.setattr(skill, "_get_or_create_secrets_manager", _no_secrets)

    called: list[str] = []

    async def eventbrite_failure(*args: Any, **kwargs: Any) -> tuple[list[dict[str, Any]], int, str]:
        called.append("eventbrite")
        return [], 0, "Eventbrite unavailable"

    async def forbidden_provider(*args: Any, **kwargs: Any) -> tuple[list[dict[str, Any]], int, None]:
        called.append("fallback")
        return [], 0, None

    monkeypatch.setattr(skill, "_search_eventbrite", eventbrite_failure)
    monkeypatch.setattr(skill, "_search_meetup", forbidden_provider)
    monkeypatch.setattr(skill, "_search_luma", forbidden_provider)

    response = await skill.execute(
        SearchRequest(
            provider="Eventbrite",
            requests=[{"query": "AI", "lat": 52.52, "lon": 13.405, "location": "Berlin"}],
        )
    )

    assert called == ["eventbrite"]
    assert response.provider == "eventbrite"
    assert response.results[0]["error"] == "Eventbrite search failed: Eventbrite unavailable"


async def test_unknown_explicit_provider_is_visible_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Invalid explicit providers should fail visibly instead of becoming auto."""

    skill = _make_skill()
    monkeypatch.setattr(skill, "_get_or_create_secrets_manager", _no_secrets)

    called: list[str] = []

    async def forbidden_provider(*args: Any, **kwargs: Any) -> tuple[list[dict[str, Any]], int, None]:
        called.append("fallback")
        return [], 0, None

    monkeypatch.setattr(skill, "_search_meetup", forbidden_provider)
    monkeypatch.setattr(skill, "_search_luma", forbidden_provider)
    monkeypatch.setattr(skill, "_search_eventbrite", forbidden_provider)

    response = await skill.execute(
        SearchRequest(
            provider="Luna",
            requests=[{"query": "AI", "lat": 52.52, "lon": 13.405, "location": "Berlin"}],
        )
    )

    assert called == []
    assert response.results[0]["error"] == "Unknown events provider: luna"


async def test_event_schedule_provider_allows_conference_without_location(monkeypatch: pytest.MonkeyPatch) -> None:
    """Conference searches should not require a city location when conference is set."""

    skill = _make_skill()
    monkeypatch.setattr(skill, "_get_or_create_secrets_manager", _no_secrets)

    async def fake_sanitize(payload: list[dict[str, Any]], **kwargs: Any) -> list[dict[str, Any]]:
        return payload

    async def fake_pretalx(*args: Any, **kwargs: Any) -> tuple[list[dict[str, Any]], int, None]:
        return [
            {
                "id": "talk-1",
                "provider": "gpn24",
                "title": "Evaluating machine learning models",
                "url": "https://cfp.gulas.ch/gpn24/talk/WMNWXJ/",
                "date_start": "2026-06-04T18:45:00+02:00",
            }
        ], 1, None

    monkeypatch.setattr(
        "backend.apps.events.skills.search_skill.sanitize_long_text_fields_in_payload",
        fake_sanitize,
    )
    monkeypatch.setattr(skill, "_search_pretalx", fake_pretalx)

    response = await skill.execute(
        SearchRequest(
            provider="GPN24",
            requests=[{"query": "machine learning", "conference": "GPN24"}],
        )
    )

    assert response.error is None
    assert response.results[0]["results"][0]["provider"] == "gpn24"
    assert response.results[0]["results"][0]["title"] == "Evaluating machine learning models"


async def test_event_schedule_provider_allows_conference_without_query(monkeypatch: pytest.MonkeyPatch) -> None:
    """Conference-only searches should not fail validation when query is omitted."""

    skill = _make_skill()
    monkeypatch.setattr(skill, "_get_or_create_secrets_manager", _no_secrets)

    async def fake_sanitize(payload: list[dict[str, Any]], **kwargs: Any) -> list[dict[str, Any]]:
        return payload

    async def fake_pretalx(*args: Any, **kwargs: Any) -> tuple[list[dict[str, Any]], int, None]:
        return [
            {
                "id": "talk-gpn24",
                "provider": "gpn24",
                "title": "GPN24 schedule overview",
                "url": "https://cfp.gulas.ch/gpn24/talk/example/",
                "date_start": "2026-06-04T10:00:00+02:00",
            }
        ], 1, None

    monkeypatch.setattr(
        "backend.apps.events.skills.search_skill.sanitize_long_text_fields_in_payload",
        fake_sanitize,
    )
    monkeypatch.setattr(skill, "_search_pretalx", fake_pretalx)

    response = await skill.execute(
        SearchRequest(
            provider="GPN24",
            requests=[{"conference": "GPN24"}],
        )
    )

    assert response.error is None
    assert response.results[0]["results"][0]["provider"] == "gpn24"
    assert response.results[0]["results"][0]["title"] == "GPN24 schedule overview"


async def test_gpn24_conference_search_supports_ai_query(monkeypatch: pytest.MonkeyPatch) -> None:
    """Users should be able to search for a topic at the GPN24 conference."""

    skill = _make_skill()
    monkeypatch.setattr(skill, "_get_or_create_secrets_manager", _no_secrets)

    async def fake_sanitize(payload: list[dict[str, Any]], **kwargs: Any) -> list[dict[str, Any]]:
        return payload

    async def fake_pretalx(*args: Any, **kwargs: Any) -> tuple[list[dict[str, Any]], int, None]:
        assert kwargs["query"] == "AI"
        assert kwargs["conference"] == "GPN24"
        return [
            {
                "id": "talk-ai-gpn24",
                "provider": "gpn24",
                "title": "AI at GPN24",
                "url": "https://cfp.gulas.ch/gpn24/talk/AI123/",
                "date_start": "2026-06-04T18:45:00+02:00",
            }
        ], 1, None

    monkeypatch.setattr(
        "backend.apps.events.skills.search_skill.sanitize_long_text_fields_in_payload",
        fake_sanitize,
    )
    monkeypatch.setattr(skill, "_search_pretalx", fake_pretalx)

    response = await skill.execute(
        SearchRequest(
            provider="GPN24",
            requests=[{"query": "AI", "conference": "GPN24"}],
        )
    )

    assert response.error is None
    assert response.results[0]["results"][0]["provider"] == "gpn24"
    assert response.results[0]["results"][0]["title"] == "AI at GPN24"


async def test_malformed_event_batch_item_does_not_block_valid_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    """One missing-query LLM batch item should not turn the whole embed group into an error."""

    skill = _make_skill()
    monkeypatch.setattr(skill, "_get_or_create_secrets_manager", _no_secrets)

    async def fake_process_requests_in_parallel(
        requests: list[dict[str, Any]],
        *args: Any,
        **kwargs: Any,
    ) -> list[tuple[Any, list[dict[str, Any]], None, int]]:
        return [
            (req["id"], [{"id": f"event-{req['id']}", "title": req["query"]}], None, 1)
            for req in requests
        ]

    monkeypatch.setattr(skill, "_process_requests_in_parallel", fake_process_requests_in_parallel)

    response = await skill.execute(
        SearchRequest(
            requests=[
                {"id": "good-1", "query": "AI meetup", "location": "Berlin"},
                {"id": "bad-1", "location": "Berlin"},
                {"id": "good-2", "query": "developer events", "location": "Berlin"},
            ],
        )
    )

    assert response.error is None
    assert [result["id"] for result in response.results] == ["good-1", "bad-1", "good-2"]
    assert response.results[0]["results"][0]["title"] == "AI meetup"
    assert response.results[1]["error"] == "Request 2 (id: bad-1) is missing required 'query' field"
    assert response.results[2]["results"][0]["title"] == "developer events"


async def test_multi_provider_response_lists_queried_providers_without_results(monkeypatch: pytest.MonkeyPatch) -> None:
    """Embed previews should show all providers searched, not only result contributors."""

    skill = _make_skill()
    monkeypatch.setattr(skill, "_get_or_create_secrets_manager", _no_secrets)

    async def fake_sanitize(payload: list[dict[str, Any]], **kwargs: Any) -> list[dict[str, Any]]:
        return payload

    async def empty_meetup(*args: Any, **kwargs: Any) -> tuple[list[dict[str, Any]], int, None]:
        return [], 0, None

    async def luma_result(*args: Any, **kwargs: Any) -> tuple[list[dict[str, Any]], int, None]:
        return [
            {
                "id": "luma-1",
                "provider": "luma",
                "title": "AI Night",
                "url": "https://lu.ma/ai-night",
            }
        ], 1, None

    monkeypatch.setattr(
        "backend.apps.events.skills.search_skill.sanitize_long_text_fields_in_payload",
        fake_sanitize,
    )
    monkeypatch.setattr(skill, "_search_meetup", empty_meetup)
    monkeypatch.setattr(skill, "_search_luma", luma_result)

    response = await skill.execute(
        SearchRequest(
            requests=[{
                "query": "AI events",
                "location": "Berlin, Germany",
                "providers": ["meetup", "luma"],
                "lat": 52.52,
                "lon": 13.405,
            }],
        )
    )

    assert response.error is None
    assert response.providers == ["meetup", "luma"]
    assert response.results[0]["results"][0]["provider"] == "luma"


async def test_auto_mode_adds_conference_schedule_for_known_conference(monkeypatch: pytest.MonkeyPatch) -> None:
    """Auto mode should include pretalx only when the query names a known conference."""

    skill = _make_skill()
    monkeypatch.setattr(skill, "_get_or_create_secrets_manager", _no_secrets)

    async def fake_sanitize(payload: list[dict[str, Any]], **kwargs: Any) -> list[dict[str, Any]]:
        return payload

    async def empty_provider(*args: Any, **kwargs: Any) -> tuple[list[dict[str, Any]], int, None]:
        return [], 0, None

    async def fake_pretalx(*args: Any, **kwargs: Any) -> tuple[list[dict[str, Any]], int, None]:
        return [
            {
                "id": "talk-39c3",
                "provider": "39c3",
                "title": "AI Agent, AI Spy",
                "url": "https://cfp.cccv.de/39c3/talk/example/",
                "date_start": "2025-12-27T12:00:00+01:00",
            }
        ], 1, None

    monkeypatch.setattr(
        "backend.apps.events.skills.search_skill.sanitize_long_text_fields_in_payload",
        fake_sanitize,
    )
    monkeypatch.setattr(skill, "_search_meetup", empty_provider)
    monkeypatch.setattr(skill, "_search_luma", empty_provider)
    monkeypatch.setattr(skill, "_search_eventbrite", empty_provider)
    monkeypatch.setattr(skill, "_search_google_events", empty_provider)
    monkeypatch.setattr(skill, "_search_resident_advisor", empty_provider)
    monkeypatch.setattr(skill, "_search_berlin_philharmonic", empty_provider)
    monkeypatch.setattr(skill, "_search_pretalx", fake_pretalx)

    response = await skill.execute(
        SearchRequest(
            requests=[{"query": "AI at 39C3", "location": "Hamburg, Germany"}],
        )
    )

    assert response.error is None
    assert response.results[0]["results"][0]["provider"] == "39c3"
