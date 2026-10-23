"""Closing-time regressions exercise the real maps skill and structured hours."""

from datetime import datetime, timezone
from types import SimpleNamespace
import sys

import pytest

sys.modules.setdefault("celery", SimpleNamespace(Celery=object))
sys.modules.setdefault("backend.core.api.app.services.cache", SimpleNamespace(CacheService=object))

from backend.apps.maps.opening_hours import ClosingTimeConstraint, matches_closing_time  # noqa: E402
from backend.apps.maps.skills.search_skill import MapSearchRequestItem, SearchSkill  # noqa: E402

NOW = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)
CONSTRAINT = ClosingTimeConstraint.from_request({"openUntil": "21:00", "openOn": "2026-10-23"})


def point(day, hour, minute=0, **extra):
    return {"day": day, "hour": hour, "minute": minute, **extra}


def place(name="Cafe", close_day=5, close_hour=22, **raw):
    return {"name": name, "place_id": name, "types": ["cafe"], "_raw": {
        "utcOffsetMinutes": 120,
        "regularOpeningHours": {"periods": [{"open": point(5, 8), "close": point(close_day, close_hour)}]},
        **raw,
    }}


@pytest.mark.parametrize("candidate,expected", [
    (place(close_hour=17), False),
    (place(close_hour=21), True),
    (place(close_day=6, close_hour=2), True),
    (place(regularOpeningHours={"periods": []}), False),
    (place(regularOpeningHours={"periods": [{"open": point(0, 0)}]}), True),
    (place(regularOpeningHours={"periods": [{"open": point(5, 8)}]}), None),
    ({"opening_hours": ["Friday: 08:00–23:00"], "_raw": {}}, None),
    (place(currentOpeningHours={"periods": [{"open": point(5, 8), "close": point(5, 17)}]}), False),
    (place(currentOpeningHours={"periods": []}), False),
    (place(currentOpeningHours={"openNow": True}), True),
    (place(regularOpeningHours={"periods": [{"open": point(5, 22), "close": point(6, 2)}]}), False),
])
# contract-test: supporting surface=rest_api assertions=maps-search.compatibility.regular-search
def test_structured_hours_decide_the_threshold(candidate, expected):
    assert matches_closing_time(candidate, CONSTRAINT, now=NOW) is expected


# contract-test: supporting surface=rest_api assertions=maps-search.compatibility.regular-search
def test_current_dated_periods_and_local_today_override_server_date():
    friday = {"year": 2026, "month": 10, "day": 23}
    candidate = place(currentOpeningHours={"periods": [{
        "open": point(5, 8, date=friday), "close": point(5, 17, date=friday),
    }]})
    # UTC is still Thursday; the place is already on Friday.
    now = datetime(2026, 10, 22, 23, tzinfo=timezone.utc)
    assert matches_closing_time(candidate, ClosingTimeConstraint.from_request({"openUntil": "21:00"}), now=now) is False
    candidate["_raw"]["currentOpeningHours"]["periods"][0]["close"]["hour"] = 22
    assert matches_closing_time(candidate, CONSTRAINT, now=NOW) is True
    candidate["business_status"] = "CLOSED_TEMPORARILY"
    assert matches_closing_time(candidate, CONSTRAINT, now=NOW) is False


# contract-test: supporting surface=rest_api assertions=maps-search.compatibility.regular-search
def test_week_boundary_and_dates_outside_current_coverage():
    candidate = place(regularOpeningHours={"periods": [{"open": point(0, 22), "close": point(1, 2)}]})
    monday = ClosingTimeConstraint.from_request({"openUntil": "01:00", "openOn": "2026-10-26"})
    assert matches_closing_time(candidate, monday, now=NOW) is True
    candidate = place(currentOpeningHours={"periods": []})
    future = ClosingTimeConstraint.from_request({"openUntil": "21:00", "openOn": "2026-10-30"})
    assert matches_closing_time(candidate, future, now=NOW) is True


@pytest.mark.parametrize("input_data", [
    {"openUntil": "25:00"}, {"openUntil": "9pm"}, {"openUntil": "21:60"},
    {"openUntil": "21:00", "openOn": "2026-02-30"}, {"openOn": "2026-10-23"},
])
# contract-test: supporting surface=rest_api assertions=maps-search.compatibility.regular-search
def test_invalid_constraints_are_rejected(input_data):
    with pytest.raises(ValueError):
        ClosingTimeConstraint.from_request(input_data)


# contract-test: supporting surface=rest_api assertions=maps-search.compatibility.regular-search
def test_typed_schema_keeps_the_filter_optional_and_validates_the_clock():
    assert MapSearchRequestItem(query="cafes").openUntil is None
    with pytest.raises(ValueError):
        MapSearchRequestItem(query="cafes", openUntil="25:00")


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("rank", [False, True])
# contract-test: supporting surface=rest_api assertions=maps-search.compatibility.regular-search
async def test_skill_excludes_early_and_unknown_places_before_ranking_and_page_limit(monkeypatch, rank, anyio_backend):
    skill = SearchSkill(app=None, app_id="maps", skill_id="search", skill_name="Search", skill_description="Maps")

    async def secrets(**kwargs):
        return object(), None

    async def search(**kwargs):
        assert kwargs["page_size"] == 20  # Filter before limiting to the requested one result.
        return {"results": [place("Early Cafe", close_hour=17), {"place_id": "unknown"}, place("Evening Cafe")]}

    async def sanitize(payload, **kwargs):
        return payload

    async def allowed(**kwargs):
        return True, None

    async def ranking(**kwargs):
        assert [item["name"] for item in kwargs["candidates"]] == ["Evening Cafe"]
        return SimpleNamespace(candidates=kwargs["candidates"])

    module = "backend.apps.maps.skills.search_skill."
    monkeypatch.setattr(skill, "_get_or_create_secrets_manager", secrets)
    monkeypatch.setattr(module + "CacheService", object)
    monkeypatch.setattr(module + "search_places", search)
    monkeypatch.setattr(module + "check_rate_limit", allowed)
    monkeypatch.setattr(module + "sanitize_long_text_fields_in_payload", sanitize)
    monkeypatch.setattr(module + "rank_search_candidates", ranking)
    monkeypatch.setattr(module + "matches_closing_time", lambda candidate, constraint: matches_closing_time(candidate, constraint, now=NOW))
    response = await skill.execute([{
        "query": "cafes", "pageSize": 1, "openUntil": "21:00", "openOn": "2026-10-23",
        "osmEnrichment": "disabled", "relevance_criteria": "quiet" if rank else None,
    }])
    group = response.results[0]
    assert response.error is None
    assert [item["name"] for item in group["results"]] == ["Evening Cafe"]
    assert "unknown opening hours" in group["warnings"][0]


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
# contract-test: supporting surface=rest_api assertions=maps-search.compatibility.regular-search
async def test_raw_invalid_filter_never_calls_provider(monkeypatch, anyio_backend):
    skill = SearchSkill(app=None, app_id="maps", skill_id="search", skill_name="Search", skill_description="Maps")

    async def forbidden(**kwargs):
        raise AssertionError("Provider must not be called for an invalid filter")

    monkeypatch.setattr("backend.apps.maps.skills.search_skill.search_places", forbidden)
    result = await skill._process_single_search_request({"query": "cafes", "openUntil": "25:00"}, "invalid", object(), object())
    assert result[1] == []
    assert "HH:MM" in result[2]
    assert result[3]["status"] == "invalid_request"
