# backend/tests/test_events_provider_routing.py
#
# Regression tests for events/search provider routing.
# Verifies explicit provider constraints survive request normalization and do
# not silently broaden to auto when a named provider fails.
# Architecture context: backend/apps/events/skills/search_skill.py

from typing import Any

import pytest

from backend.apps.events.skills.search_skill import SearchRequest, SearchSkill


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


@pytest.mark.asyncio
async def test_top_level_eventbrite_does_not_fallback_to_auto(monkeypatch: pytest.MonkeyPatch) -> None:
    """A user-requested Eventbrite search must not call Meetup/Luma after failure."""

    skill = _make_skill()
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


@pytest.mark.asyncio
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
