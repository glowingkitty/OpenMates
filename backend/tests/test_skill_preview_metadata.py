"""
Tests for skill-owned preview metadata resolution.

Processing embed placeholders are created before a skill makes provider calls.
These tests keep provider routing metadata available during that processing
window so previews do not guess a default provider until final results arrive.
"""

import sys
import types

celery_stub = types.ModuleType("celery")
celery_stub.Celery = object
sys.modules.setdefault("celery", celery_stub)


def test_shopping_preview_metadata_routes_fabric_to_stoffe() -> None:
    from backend.apps.shopping.skills.search_products import SearchProductsSkill

    metadata = SearchProductsSkill.resolve_preview_metadata({
        "query": "lyocell stoff meterware",
        "category": "fabrics",
    })

    assert metadata == {
        "provider": "Stoffe.de",
        "providers": ["Stoffe.de"],
    }


def test_shopping_preview_metadata_routes_country_to_amazon() -> None:
    from backend.apps.shopping.skills.search_products import SearchProductsSkill

    metadata = SearchProductsSkill.resolve_preview_metadata({
        "query": "coffee grinder",
        "country": "US",
    })

    assert metadata == {
        "provider": "Amazon",
        "providers": ["Amazon"],
    }


def test_events_preview_metadata_expands_auto_to_provider_slugs() -> None:
    from backend.apps.events.skills.search_skill import SearchSkill as EventsSearchSkill

    metadata = EventsSearchSkill.resolve_preview_metadata({"query": "AI", "provider": "auto"})

    assert metadata["provider"] == "auto"
    assert "meetup" in metadata["providers"]
    assert "luma" in metadata["providers"]


def test_home_preview_metadata_defaults_to_all_providers() -> None:
    from backend.apps.home.skills.search_skill import SearchSkill as HomeSearchSkill

    metadata = HomeSearchSkill.resolve_preview_metadata({"query": "Berlin"})

    assert metadata == {
        "provider": "Multi",
        "providers": ["ImmoScout24", "Kleinanzeigen", "WG-Gesucht"],
    }


def test_travel_preview_metadata_resolves_train_provider_icons() -> None:
    from backend.apps.travel.skills.search_connections import SearchConnectionsSkill

    metadata = SearchConnectionsSkill.resolve_preview_metadata({
        "legs": [{"origin": "Berlin", "destination": "Dresden", "date": "2026-04-01"}],
        "transport_methods": ["train"],
    })

    assert metadata["provider"] == ""
    assert [provider["id"] for provider in metadata["providers"]] == ["deutsche_bahn", "flix"]
    assert metadata["query"] == "Berlin → Dresden, 2026-04-01"


def test_embed_metadata_merge_preserves_preview_providers_and_final_filters() -> None:
    from backend.core.api.app.services.embed_service import EmbedService

    metadata = EmbedService._merge_request_metadata(
        {
            "app_id": "travel",
            "skill_id": "search_connections",
            "status": "processing",
            "query": "Berlin → Dresden, 2026-04-01",
            "providers": [{"id": "deutsche_bahn", "name": "Deutsche Bahn"}],
        },
        {
            "request_id": 1,
            "legs": [{"origin": "Berlin", "destination": "Dresden", "date": "2026-04-01"}],
            "transport_methods": ["train"],
            "max_results": 10,
        },
    )

    assert metadata["query"] == "Berlin → Dresden, 2026-04-01"
    assert metadata["providers"] == [{"id": "deutsche_bahn", "name": "Deutsche Bahn"}]
    assert metadata["legs"] == [{"origin": "Berlin", "destination": "Dresden", "date": "2026-04-01"}]
    assert metadata["transport_methods"] == ["train"]
    assert metadata["max_results"] == 10
    assert "status" not in metadata
    assert "request_id" not in metadata
