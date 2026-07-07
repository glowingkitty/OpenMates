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


@pytest.mark.asyncio
async def test_provider_failures_are_visible_errors() -> None:
    skill = SearchLocationsSkill(None, "fitness", "search_locations", "Search locations", "Search locations")
    skill.client = FailingUrbanSportsClient()

    response = await skill.execute({"requests": [{"id": "bad", "city": "Berlin"}]})

    group = response["results"][0]
    assert group["result_count"] == 0
    assert group["error"] == "Urban Sports Club search failed: provider unavailable"
