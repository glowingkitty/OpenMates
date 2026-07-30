# backend/tests/test_maps_geoapify_enrichment.py
#
# Backend contract tests for maps.search Geoapify OSM enrichment.
# They verify legacy Google behavior is preserved, enrichment can be disabled,
# source-labelled OSM details do not overwrite Google fields, strict amenity
# filters do not treat unknown values as matches, and best-effort failures are
# surfaced as warnings instead of breaking Google-only searches.
#
# Spec: docs/specs/maps-geoapify-osm-enrichment/spec.yml

import sys
from types import SimpleNamespace
from typing import Any

import pytest

sys.modules.setdefault("celery", SimpleNamespace(Celery=object))
sys.modules.setdefault(
    "backend.core.api.app.services.cache",
    SimpleNamespace(CacheService=object),
)

from backend.apps.maps.skills.search_skill import SearchSkill  # noqa: E402

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _FakeCacheService:
    async def get(self, key: str) -> Any:
        return None

    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        return True


def _make_skill() -> SearchSkill:
    return SearchSkill(
        app=None,
        app_id="maps",
        skill_id="search",
        skill_name="Search",
        skill_description="Search maps",
    )


async def _no_secrets(*args: Any, **kwargs: Any) -> tuple[object, None]:
    return object(), None


async def _identity_sanitize(payload: list[dict[str, Any]], **kwargs: Any) -> list[dict[str, Any]]:
    return payload


def _google_places() -> list[dict[str, Any]]:
    return [
        {
            "place_id": "google-1",
            "name": "Google Cafe",
            "formatted_address": "Google Address 1",
            "location": {"latitude": 52.52, "longitude": 13.405},
            "types": ["cafe"],
            "rating": 4.7,
            "user_rating_count": 100,
            "website_uri": "https://google.example/cafe",
            "phone_number": "+49 30 123",
            "price_level": "PRICE_LEVEL_MODERATE",
            "opening_hours": ["Monday: 09:00-18:00"],
            "open_now": True,
            "business_status": "OPERATIONAL",
            "description": "Google description",
            "photo_url": "https://google.example/photo.jpg",
        },
        {
            "place_id": "google-2",
            "name": "Unknown Cafe",
            "formatted_address": "Google Address 2",
            "location": {"latitude": 52.521, "longitude": 13.406},
            "types": ["cafe"],
            "rating": 4.3,
            "user_rating_count": 50,
            "business_status": "OPERATIONAL",
        },
    ]


async def _fake_google_search(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return {"query": kwargs["text_query"], "results": _google_places(), "error": None}


async def _prepare_skill(monkeypatch: pytest.MonkeyPatch) -> SearchSkill:
    skill = _make_skill()
    monkeypatch.setattr(skill, "_get_or_create_secrets_manager", _no_secrets)
    monkeypatch.setattr("backend.apps.maps.skills.search_skill.search_places", _fake_google_search)
    monkeypatch.setattr("backend.apps.maps.skills.search_skill.CacheService", _FakeCacheService)
    monkeypatch.setattr(
        "backend.apps.maps.skills.search_skill.sanitize_long_text_fields_in_payload",
        _identity_sanitize,
    )
    return skill


async def test_legacy_request_shape_still_returns_google_results(monkeypatch: pytest.MonkeyPatch) -> None:
    skill = await _prepare_skill(monkeypatch)

    response = await skill.execute([{"id": "legacy", "query": "cafes in Berlin"}])

    assert response.error is None
    assert response.provider == "Google Maps + Geoapify"
    assert response.results[0]["id"] == "legacy"
    assert response.results[0]["results"][0]["name"] == "Google Cafe"
    assert response.results[0]["results"][0]["formatted_address"] == "Google Address 1"


async def test_osm_enrichment_disabled_avoids_geoapify_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    skill = await _prepare_skill(monkeypatch)

    async def forbidden_enrichment(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        raise AssertionError("Geoapify should not be called when enrichment is disabled")

    monkeypatch.setattr(skill, "_enrich_with_geoapify", forbidden_enrichment)

    response = await skill.execute(
        [{"id": "disabled", "query": "cafes in Berlin", "osmEnrichment": "disabled"}]
    )

    assert response.error is None
    assert response.provider == "Google Maps"
    assert "osm_enrichment" not in response.results[0]["results"][0]


async def test_best_effort_enrichment_preserves_google_fields_and_order(monkeypatch: pytest.MonkeyPatch) -> None:
    skill = await _prepare_skill(monkeypatch)

    async def fake_enrichment(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return [
            {
                "status": "matched",
                "match": {"geoapify_place_id": "osm-1", "cache_hit": False},
                "fields": {
                    "air_conditioning": {
                        "value": "yes",
                        "source": "OpenStreetMap via Geoapify",
                        "raw_value": True,
                    }
                },
            },
            {"status": "no_match", "fields": {"air_conditioning": {"value": "unknown", "source": "OpenStreetMap via Geoapify"}}},
        ]

    monkeypatch.setattr(skill, "_enrich_with_geoapify", fake_enrichment)

    response = await skill.execute([{"id": "auto", "query": "cafes in Berlin", "osmEnrichment": "auto"}])

    places = response.results[0]["results"]
    assert [place["place_id"] for place in places] == ["google-1", "google-2"]
    assert places[0]["name"] == "Google Cafe"
    assert places[0]["formatted_address"] == "Google Address 1"
    enrichment = places[0]["osm_enrichment"]
    assert enrichment["provider"] == "Geoapify"
    assert enrichment["data_source"] == "OpenStreetMap via Geoapify"
    assert enrichment["fields"]["air_conditioning"]["value"] == "yes"


async def test_strict_filters_keep_only_verified_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    skill = await _prepare_skill(monkeypatch)

    async def fake_enrichment(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return [
            {"status": "matched", "fields": {"air_conditioning": {"value": "yes", "source": "OpenStreetMap via Geoapify"}}},
            {"status": "matched", "fields": {"air_conditioning": {"value": "unknown", "source": "OpenStreetMap via Geoapify"}}},
        ]

    monkeypatch.setattr(skill, "_enrich_with_geoapify", fake_enrichment)

    response = await skill.execute(
        [
            {
                "id": "strict",
                "query": "cafes in Berlin with air conditioning",
                "osmEnrichment": "required",
                "amenityFilters": {"airConditioning": "required"},
            }
        ]
    )

    group = response.results[0]
    assert [place["place_id"] for place in group["results"]] == ["google-1"]
    assert group["filter_summary"]["required"] == ["air_conditioning"]
    assert group["filter_summary"]["verified_count"] == 1


async def test_strict_filters_explain_no_verified_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    skill = await _prepare_skill(monkeypatch)

    async def fake_enrichment(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return [
            {"status": "matched", "fields": {"air_conditioning": {"value": "unknown", "source": "OpenStreetMap via Geoapify"}}},
            {"status": "no_match", "fields": {"air_conditioning": {"value": "unknown", "source": "OpenStreetMap via Geoapify"}}},
        ]

    monkeypatch.setattr(skill, "_enrich_with_geoapify", fake_enrichment)

    response = await skill.execute(
        [
            {
                "id": "none",
                "query": "cafes in Berlin with air conditioning",
                "osmEnrichment": "required",
                "amenityFilters": {"airConditioning": "required"},
            }
        ]
    )

    group = response.results[0]
    assert group["results"] == []
    assert group["filter_summary"]["status"] == "no_verified_results"
    assert "No Geoapify/OSM-verified matches" in group["warnings"][0]


async def test_geoapify_failure_keeps_google_results_with_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    skill = await _prepare_skill(monkeypatch)

    async def failing_enrichment(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return [{"status": "timed_out", "fields": {}}, {"status": "timed_out", "fields": {}}]

    monkeypatch.setattr(skill, "_enrich_with_geoapify", failing_enrichment)

    response = await skill.execute([{"id": "timeout", "query": "cafes in Berlin"}])

    group = response.results[0]
    assert [place["place_id"] for place in group["results"]] == ["google-1", "google-2"]
    assert group["warnings"] == ["Geoapify OSM enrichment timed out; showing Google Places results."]
    assert group["results"][0]["osm_enrichment"]["status"] == "timed_out"
