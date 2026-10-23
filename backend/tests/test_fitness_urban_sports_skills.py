# backend/tests/test_fitness_urban_sports_skills.py
#
# Unit tests for the two Fitness Urban Sports skills. Provider I/O is replaced
# with a tiny fake client so the tests validate request normalization, grouped
# app-skill response shape, default all-plan behavior, and visible failures
# without network access.

from __future__ import annotations

import pytest

from backend.apps.fitness.skills.search_classes import SearchClassesSkill
from backend.apps.fitness.skills.search_locations import SearchLocationsSkill


class FakeUrbanSportsClient:
    async def search_locations(self, **kwargs):
        assert kwargs["radius_km"] == 1.0
        assert kwargs["plan"] is None
        return [
            {
                "id": "beat81-paul-lincke-ufer",
                "provider": "Urban Sports Club",
                "name": "BEAT81 - Paul-Lincke-Ufer",
                "url": "https://urbansportsclub.com/en/venues/beat81-paul-lincke-ufer",
                "distance_km": 0.714,
                "plans_required": ["Classic", "Premium", "Max"],
            }
        ]

    async def search_classes(self, **kwargs):
        assert kwargs["attendance_mode"] == "onsite"
        if kwargs.get("plan") == "essential":
            return [
                {
                    "id": "appt-yoga",
                    "provider": "Urban Sports Club",
                    "name": "Morning Yoga",
                    "venue_name": "Essential Yoga",
                    "date": "2026-07-07",
                    "time_range": "09:00 - 10:00",
                    "distance_km": 0.02,
                    "plans_required": ["Essential", "Classic"],
                    "spots_left": 3,
                }
            ]
        return [
            {
                "id": "appt-beat81",
                "provider": "Urban Sports Club",
                "name": "HIIT Strength",
                "venue_name": "BEAT81 - Paul-Lincke-Ufer",
                "date": "2026-07-07",
                "time_range": "18:00 - 18:45",
                "distance_km": 0.714,
                "plans_required": ["Classic", "Premium", "Max"],
                "spots_left": 8,
            }
        ]


class FailingUrbanSportsClient:
    async def search_locations(self, **kwargs):
        raise RuntimeError("provider unavailable")


# contract-test: supporting surface=cli assertions=app-skills.surface.semantic-parity,app-skills.execution.registered-validated
@pytest.mark.asyncio
async def test_search_locations_returns_grouped_radius_results() -> None:
    skill = SearchLocationsSkill(None, "fitness", "search_locations", "Search locations", "Search locations")
    skill.client = FakeUrbanSportsClient()

    response = await skill.execute(
        {"requests": [{"id": "nearby", "address": "Sorauer Str. 12", "city": "Berlin", "radius_km": 1}]}
    )

    group = response["results"][0]
    assert group["id"] == "nearby"
    assert group["provider"] == "Urban Sports Club"
    assert group["result_count"] == 1
    assert group["filters"]["plan"] == "all"
    assert group["results"][0]["name"] == "BEAT81 - Paul-Lincke-Ufer"


# contract-test: supporting surface=cli assertions=app-skills.surface.semantic-parity,app-skills.execution.registered-validated
@pytest.mark.asyncio
async def test_search_classes_defaults_to_all_plans_and_onsite_for_radius_search() -> None:
    skill = SearchClassesSkill(None, "fitness", "search_classes", "Search classes", "Search classes")
    skill.client = FakeUrbanSportsClient()

    response = await skill.execute(
        {"requests": [{"id": "classes", "address": "Sorauer Str. 12", "city": "Berlin", "radius_km": 1}]}
    )

    group = response["results"][0]
    assert group["filters"]["plan"] == "all"
    assert group["filters"]["attendance_mode"] == "onsite"
    assert group["results"][0]["name"] == "HIIT Strength"
    assert group["results"][0]["plans_required"] == ["Classic", "Premium", "Max"]


# contract-test: supporting surface=cli assertions=app-skills.surface.semantic-parity,app-skills.execution.registered-validated
@pytest.mark.asyncio
async def test_search_classes_accepts_flat_runtime_args() -> None:
    skill = SearchClassesSkill(None, "fitness", "search_classes", "Search classes", "Search classes")
    skill.client = FakeUrbanSportsClient()

    response = await skill.execute(address="Sorauer Str. 12", city="Berlin", radius_km=1)

    group = response["results"][0]
    assert group["filters"]["plan"] == "all"
    assert group["filters"]["attendance_mode"] == "onsite"
    assert group["results"][0]["name"] == "HIIT Strength"


# contract-test: supporting surface=cli assertions=app-skills.surface.semantic-parity,app-skills.execution.registered-validated
@pytest.mark.asyncio
async def test_search_classes_explicit_plan_filter_is_visible_in_summary() -> None:
    skill = SearchClassesSkill(None, "fitness", "search_classes", "Search classes", "Search classes")
    skill.client = FakeUrbanSportsClient()

    response = await skill.execute(
        {"requests": [{"id": "essential", "address": "Sorauer Str. 12", "city": "Berlin", "radius_km": 1, "plan": "essential"}]}
    )

    group = response["results"][0]
    assert group["filters"]["plan"] == "essential"
    assert "Filtered to Essential" in group["summary"]
    assert group["results"][0]["name"] == "Morning Yoga"


# contract-test: supporting surface=cli assertions=app-skills.surface.semantic-parity,app-skills.execution.registered-validated
@pytest.mark.asyncio
async def test_search_classes_preserves_batch_when_dispatched_as_kwargs() -> None:
    skill = SearchClassesSkill(None, "fitness", "search_classes", "Search classes", "Search classes")
    skill.client = FakeUrbanSportsClient()
    response = await skill.execute(requests=[
        {"id": "all-plans", "address": "Sorauer Str. 12", "radius_km": 1},
        {"id": "essential", "address": "Sorauer Str. 12", "radius_km": 1, "plan": "essential"},
    ])
    assert [group["id"] for group in response["results"]] == ["all-plans", "essential"]
    assert [group["results"][0]["name"] for group in response["results"]] == ["HIIT Strength", "Morning Yoga"]


# contract-test: supporting surface=cli assertions=app-skills.surface.semantic-parity,app-skills.execution.registered-validated
@pytest.mark.asyncio
async def test_provider_failures_are_visible_errors() -> None:
    skill = SearchLocationsSkill(None, "fitness", "search_locations", "Search locations", "Search locations")
    skill.client = FailingUrbanSportsClient()

    response = await skill.execute({"requests": [{"id": "bad", "city": "Berlin"}]})

    group = response["results"][0]
    assert group["result_count"] == 0
    assert group["error"] == "Urban Sports Club search failed: provider unavailable"


# contract-test: supporting surface=cli assertions=app-skills.assistant.bounded-private-failure
@pytest.mark.asyncio
async def test_class_groups_overlap_preserve_order_and_isolate_failure(monkeypatch):
    import asyncio

    skill = SearchClassesSkill(None, 'fitness', 'search_classes', 'Search classes', 'Search classes')
    from unittest.mock import Mock
    from backend.apps.fitness.skills import search_classes
    failure_log = Mock()
    monkeypatch.setattr(search_classes.logger, "exception", failure_log)
    all_started = asyncio.Event()
    active = 0
    peak = 0
    completed = []

    class Client:
        async def search_classes(self, **kwargs):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            if active == 3:
                all_started.set()
            try:
                await all_started.wait()
                assert kwargs['days'] == 3
                if kwargs['query'] == 'bad':
                    raise RuntimeError('provider unavailable')
                completed.append(kwargs['query'])
                return [{'id': kwargs['query']}]
            finally:
                active -= 1

    skill.client = Client()
    result = await asyncio.wait_for(skill.execute(requests=[
        {'id': value, 'query': value, 'days': 3} for value in ['first', 'bad', 'last', 'fourth']
    ]), timeout=2)
    assert peak == 3
    assert [group['id'] for group in result['results']] == ['first', 'bad', 'last', 'fourth']
    assert result['results'][1]['result_count'] == 0
    assert 'provider unavailable' in result['results'][1]['error']
    assert [group['results'][0]['id'] for group in result['results'] if not group.get('error')] == ['first', 'last', 'fourth']
    assert sorted(completed) == ['first', 'fourth', 'last']
    failure_log.assert_called_once_with('Urban Sports Club class search failed for group index %s', 1)
    assert active == 0


# contract-test: supporting surface=cli assertions=app-skills.assistant.bounded-private-failure
@pytest.mark.asyncio
async def test_class_group_cancellation_drains_running_and_queued_groups():
    import asyncio

    skill = SearchClassesSkill(None, 'fitness', 'search_classes', 'Search classes', 'Search classes')
    started = asyncio.Event()
    active = 0
    calls = 0

    class Client:
        async def search_classes(self, **kwargs):
            nonlocal active, calls
            active += 1
            calls += 1
            if active == 3:
                started.set()
            try:
                await asyncio.Event().wait()
            finally:
                active -= 1

    skill.client = Client()
    work = asyncio.create_task(skill.execute(requests=[{'query': str(i)} for i in range(5)]))
    await asyncio.wait_for(started.wait(), 2)
    work.cancel()
    with pytest.raises(asyncio.CancelledError):
        await work
    assert active == 0
    assert calls == 3


# contract-test: supporting surface=cli assertions=app-skills.execution.registered-validated
@pytest.mark.asyncio
@pytest.mark.parametrize("grouped", [False, True])
@pytest.mark.parametrize("explicit_null", [False, True])
async def test_class_optional_nulls_use_defaults_without_mutating_input(grouped, explicit_null):
    from copy import deepcopy
    from unittest.mock import AsyncMock

    skill = SearchClassesSkill(None, "fitness", "search_classes", "Search classes", "Search classes")
    skill.client.search_classes = AsyncMock(return_value=[])
    item = {"query": "Yoga"}
    if explicit_null:
        item.update({key: None for key in ("min_spots", "limit", "days", "city", "language")})
    before = deepcopy(item)
    response = await skill.execute(requests=[item]) if grouped else await skill.execute(**item)
    sent = skill.client.search_classes.call_args.kwargs
    assert {key: sent[key] for key in ("min_spots", "limit", "days", "city", "language")} == {
        "min_spots": 1, "limit": 10, "days": 1, "city": "Berlin", "language": "en",
    }
    assert response["results"][0]["filters"]["min_spots"] == 1
    assert item == before


# contract-test: supporting surface=cli assertions=app-skills.execution.registered-validated
@pytest.mark.asyncio
@pytest.mark.parametrize("min_spots", [0, 3])
async def test_class_spot_filter_preserves_explicit_zero_and_positive_values(min_spots):
    from unittest.mock import AsyncMock

    skill = SearchClassesSkill(None, "fitness", "search_classes", "Search classes", "Search classes")
    skill.client.search_classes = AsyncMock(return_value=[])
    response = await skill.execute(requests=[{"min_spots": min_spots}])
    assert skill.client.search_classes.call_args.kwargs["min_spots"] == min_spots
    assert response["results"][0]["filters"]["min_spots"] == min_spots


# contract-test: supporting surface=cli assertions=app-skills.execution.registered-validated
@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [{"min_spots": -1}, {"min_spots": "bad"}, {"limit": 0}, {"days": 15}])
async def test_class_optional_default_normalization_keeps_validation_bounds(invalid):
    from unittest.mock import AsyncMock
    from pydantic import ValidationError

    skill = SearchClassesSkill(None, "fitness", "search_classes", "Search classes", "Search classes")
    skill.client.search_classes = AsyncMock()
    with pytest.raises(ValidationError):
        await skill.execute(requests=[invalid])
    skill.client.search_classes.assert_not_called()


# contract-test: supporting surface=cli assertions=app-skills.surface.semantic-parity
@pytest.mark.asyncio
@pytest.mark.parametrize("skill_type,method", [(SearchClassesSkill, "search_classes"), (SearchLocationsSkill, "search_locations")])
async def test_grouped_fitness_skill_preserves_provider_image_for_rendering(skill_type, method):
    from unittest.mock import AsyncMock

    skill = skill_type(None, "fitness", method, "Search", "Search")
    supplied = {"id": "provider-result", "image_url": "https://images.example.test/provider-photo.jpg"}
    setattr(skill.client, method, AsyncMock(return_value=[supplied]))
    response = await skill.execute({"requests": [{"id": "photos"}]})
    assert response["results"][0]["results"][0] == supplied
    assert "image_url" in response["ignore_fields_for_inference"]
