"""Deterministic home REST integration using the real generated route and skill.

Only external provider, enrichment, output scanning and billing transports are
replaced. API-key authorization, app.yml validation, SearchSkill execution and
REST response serialization remain production code.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Reuse the route suite's bounded import-time dependency shims. That module
# removes its temporary sys.modules entries after importing apps_api.
from backend.tests.test_apps_api import AppYAML, apps_api
from backend.apps.home.skills import search_skill


@pytest.fixture
def home_rest(monkeypatch):
    calls = {"providers": [], "dispatch": [], "safety": [], "priced": []}
    gallery = [f"https://img.kleinanzeigen.de/apartment-{index}.jpg" for index in range(18)]
    base = {
        "id": "ka_confirmed", "provider": "Kleinanzeigen", "listing_type": "rent",
        "title": "Apartment with balcony", "url": "https://www.kleinanzeigen.de/s-anzeige/apartment/123-203",
        "price": 1400, "price_type": "warm", "warm_rent_eur": 1400, "cold_rent_eur": 1100,
        "description": "Third floor apartment with advertised balcony and full supplied gallery.",
        "image_url": gallery[0], "image_urls": gallery, "gallery_status": "complete",
        "amenities": {"balcony": True}, "floor": 3, "rooms": 2, "size_sqm": 65,
        "latitude": 52.52, "longitude": 13.405, "location_precision": "district",
        "location_approximate": True, "location_source": "Kleinanzeigen",
    }
    unknown = {**deepcopy(base), "id": "ka_unknown", "url": "https://www.kleinanzeigen.de/s-anzeige/unknown/124-203",
               "price": 1200, "amenities": {"balcony": None}, "warm_rent_eur": None}
    conflict = {**deepcopy(base), "id": "ka_conflict", "url": "https://www.kleinanzeigen.de/s-anzeige/conflict/125-203",
                "price": 900, "amenities": {"balcony": False}}

    async def provider(**kwargs):
        calls["providers"].append(kwargs)
        return deepcopy([base, unknown, conflict])

    async def assess(listings, **kwargs):
        for listing in listings:
            advertised = listing["amenities"]["balcony"]
            listing["match_evidence"] = {"amenities": {"balcony": {
                "status": "confirmed" if advertised is True else "conflicting" if advertised is False else "unknown",
                "text_status": "present" if advertised is True else "absent" if advertised is False else "unknown",
                "visual_status": "unavailable", "source": "provider_advertisement",
            }}, "photo_coverage": {"supplied": 18, "assessed": 0, "status": "unavailable"}}
        return ["Fixture visual assessment unavailable; advertised evidence retained."]

    async def enrich(*args, **kwargs):
        return []

    skill = search_skill.SearchSkill(app=None, app_id="home", skill_id="search", skill_name="Home search", skill_description="Housing search")
    metadata_dict = yaml.safe_load((Path(__file__).resolve().parents[1] / "apps/home/app.yml").read_text())
    metadata_dict["icon_image"] = metadata_dict["icon_image"].strip()
    metadata = AppYAML.model_validate(metadata_dict)

    async def dispatch(app_id, skill_id, payload):
        calls["dispatch"].append(deepcopy(payload))
        assert (app_id, skill_id) == ("home", "search")
        result = await skill.execute(requests=payload["requests"])
        return result.model_dump(mode="json")

    async def output_safety(result, context):
        calls["safety"].append(context.surface)
        return result

    async def price(**kwargs):
        calls["priced"].append(kwargs["skill_id"])
        return 0

    user = {"user_id": "isolated-home-rest-user", "api_key_hash": "fixture-key-hash",
            "api_key_metadata": {"full_access": False, "scopes": {"apps": {"mode": "selected", "allowed_skills": ["home:search"]}}}}
    registry = SimpleNamespace(get_metadata=lambda app_id: metadata, dispatch_skill=dispatch)
    # The boundary is registry lookup, avoiding Celery/BaseApp startup. Scoped
    # monkeypatch restores the original module (or removes this shim) at teardown.
    module_name = "backend.core.api.app.services.skill_registry"
    registry_module = sys.modules.get(module_name)
    if registry_module is None:
        registry_module = ModuleType(module_name)
        monkeypatch.setitem(sys.modules, module_name, registry_module)
    monkeypatch.setattr(registry_module, "get_global_registry", lambda: registry, raising=False)
    monkeypatch.setattr(search_skill, "PROVIDER_MAP", {"Kleinanzeigen": provider})
    monkeypatch.setattr(search_skill, "assess_home_evidence", assess)
    monkeypatch.setattr(search_skill, "enrich_home_locations", enrich)
    monkeypatch.setattr(apps_api, "sanitize_app_skill_output", output_safety)
    monkeypatch.setattr(apps_api, "calculate_skill_credits", price)
    app = FastAPI()
    app.dependency_overrides[apps_api.get_session_or_api_key_info] = lambda: user
    app.dependency_overrides[apps_api.get_cache_service] = lambda: object()
    app.dependency_overrides[apps_api.get_directus_service] = lambda: object()
    apps_api.register_app_and_skill_routes(app, {"home": metadata})
    with TestClient(app) as client:
        yield client, user, calls, base


# contract-test: direct surface=rest_api assertions=home-search.listings.rich-provider-evidence,home-search.images.complete-gallery,home-search.filters.explicit-and-unknown,home-search.location.precision,home-search.vision.evidence-and-conflicts,home-search.output.safe-and-truthful
def test_home_rest_preserves_gallery_evidence_and_explicit_unknown_filters(home_rest):
    client, _, calls, base = home_rest
    request = {"query": "Berlin", "providers": ["Kleinanzeigen"], "required_amenities": ["balcony"],
               "max_warm_rent_eur": 1500, "include_unconfirmed": True, "visual_analysis": False, "max_results": 3}
    response = client.post("/v1/apps/home/skills/search", json={"requests": [request]})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True and body["error"] is None and body["credits_charged"] == 0
    listings = body["data"]["results"][0]["results"]
    assert {item["id"] for item in listings} == {"ka_confirmed", "ka_unknown"}
    confirmed = next(item for item in listings if item["id"] == "ka_confirmed")
    assert confirmed["image_urls"] == base["image_urls"] and len(confirmed["image_urls"]) == 18
    for key in ("image_url", "gallery_status", "description", "location_precision", "location_approximate", "location_source", "warm_rent_eur", "cold_rent_eur", "floor"):
        assert confirmed[key] == base[key]
    assert confirmed["match_evidence"]["amenities"]["balcony"]["status"] == "confirmed"
    assert confirmed["match_evidence"]["photo_coverage"]["assessed"] == 0
    unconfirmed = next(item for item in listings if item["id"] == "ka_unknown")
    assert unconfirmed["match_evidence"]["status"] == "unconfirmed"
    assert unconfirmed["warm_rent_eur"] is None and unconfirmed["amenities"]["balcony"] is None
    assert calls["providers"][0]["city"] == "Berlin"
    dispatched = calls["dispatch"][0]["requests"][0]
    assert dispatched["required_amenities"] == ["balcony"] and dispatched["max_warm_rent_eur"] == 1500
    assert dispatched["include_unconfirmed"] is True
    assert calls["safety"] and calls["priced"] == ["search"]
    request["include_unconfirmed"] = False
    confirmed_only = client.post("/v1/apps/home/skills/search", json={"requests": [request]})
    assert confirmed_only.status_code == 200
    assert [item["id"] for item in confirmed_only.json()["data"]["results"][0]["results"]] == ["ka_confirmed"]


@pytest.mark.parametrize("invalid", [
    {"required_amenities": "balcony"},
    {"max_warm_rent_eur": {"value": 1500}}, {"max_warm_rent_eur": -1},
    {"include_unconfirmed": {"enabled": True}},
])
# contract-test: direct surface=rest_api assertions=home-search.filters.explicit-and-unknown,home-search.output.safe-and-truthful
def test_home_rest_dynamic_schema_rejects_invalid_fields_before_dispatch(home_rest, invalid):
    client, _, calls, _ = home_rest
    response = client.post("/v1/apps/home/skills/search", json={"requests": [{"query": "Berlin", **invalid}]})
    assert response.status_code == 422, response.text
    assert calls["dispatch"] == [] and calls["providers"] == [] and calls["priced"] == []


# contract-test: direct surface=rest_api assertions=home-search.output.safe-and-truthful
def test_home_rest_missing_api_key_skill_scope_denied_before_provider(home_rest):
    client, user, calls, _ = home_rest
    user["api_key_metadata"]["scopes"]["apps"]["allowed_skills"] = ["maps:search"]
    response = client.post("/v1/apps/home/skills/search", json={"requests": [{"query": "Berlin"}]})
    assert response.status_code == 403, response.text
    assert response.json()["detail"] == {"error": "missing_scope", "missing_scope": "skill:home:search"}
    assert calls["dispatch"] == [] and calls["providers"] == [] and calls["safety"] == []


# contract-test: direct surface=rest_api assertions=home-search.filters.explicit-and-unknown,home-search.output.safe-and-truthful
def test_home_rest_unknown_amenity_returns_grouped_validation_error_before_provider(home_rest):
    client, _, calls, _ = home_rest
    response = client.post("/v1/apps/home/skills/search", json={"requests": [{"query": "Berlin", "required_amenities": ["swimming_pool"]}]})
    assert response.status_code == 200, response.text
    group = response.json()["data"]["results"][0]
    assert group["results"] == []
    assert "required_amenities" in group["error"] and "swimming_pool" in group["error"]
    assert calls["providers"] == [] and calls["priced"] == []


# contract-test: direct surface=rest_api assertions=home-search.location.precision,home-search.output.safe-and-truthful
def test_home_rest_city_fallback_cannot_retain_nested_provider_street_precision(home_rest):
    client, _, _, base = home_rest
    base.update(latitude=None, longitude=None, location_precision="street",
                location={"status": "candidate_limit", "precision": "street", "approximate": True,
                          "source": "Kleinanzeigen", "method": "unknown"})
    response = client.post("/v1/apps/home/skills/search", json={"requests": [{
        "query": "Berlin", "providers": ["Kleinanzeigen"], "required_amenities": ["balcony"],
        "max_results": 1, "visual_analysis": False,
    }]})
    assert response.status_code == 200, response.text
    listing = response.json()["data"]["results"][0]["results"][0]
    assert listing["id"] == "ka_confirmed"
    assert listing["location_precision"] == listing["location"]["precision"] == "city"
    assert listing["location_approximate"] is listing["location"]["approximate"] is True
    assert listing["location_source"] == listing["location"]["source"]
    assert listing["location_source"] != "Kleinanzeigen"
