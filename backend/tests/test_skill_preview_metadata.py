"""
Tests for skill-owned preview metadata resolution.

Processing embed placeholders are created before a skill makes provider calls.
These tests keep provider routing metadata available during that processing
window so previews do not guess a default provider until final results arrive.
"""

import json
import sys
import types
from pathlib import Path

celery_stub = types.ModuleType("celery")
celery_stub.Celery = object
sys.modules.setdefault("celery", celery_stub)

toon_format_stub = types.ModuleType("toon_format")
toon_format_stub.encode = lambda value: str(value)
toon_format_stub.decode = lambda value: value
sys.modules.setdefault("toon_format", toon_format_stub)

cache_stub = types.ModuleType("backend.core.api.app.services.cache")
cache_stub.CacheService = object
sys.modules.setdefault("backend.core.api.app.services.cache", cache_stub)

directus_stub = types.ModuleType("backend.core.api.app.services.directus")
directus_stub.DirectusService = object
sys.modules.setdefault("backend.core.api.app.services.directus", directus_stub)

encryption_stub = types.ModuleType("backend.core.api.app.utils.encryption")
encryption_stub.EncryptionService = object
sys.modules.setdefault("backend.core.api.app.utils.encryption", encryption_stub)

youtube_metadata_stub = types.ModuleType("backend.shared.providers.youtube.youtube_metadata")
youtube_metadata_stub.extract_youtube_id_from_url = lambda _url: None
sys.modules.setdefault("backend.shared.providers.youtube.youtube_metadata", youtube_metadata_stub)

github_stub = types.ModuleType("backend.shared.providers.github")
github_stub.build_github_repo_embed = lambda *_args, **_kwargs: None
github_stub.is_github_repo_url = lambda _url: False
sys.modules.setdefault("backend.shared.providers.github", github_stub)

e2b_preview_stub = types.ModuleType("backend.shared.providers.e2b_application_preview")
e2b_preview_stub.ApplicationPreviewEntrypoint = object
e2b_preview_stub.ApplicationPreviewFile = object
e2b_preview_stub.ApplicationPreviewPlanningError = Exception
e2b_preview_stub.plan_application_preview_startup = lambda *_args, **_kwargs: None
sys.modules.setdefault("backend.shared.providers.e2b_application_preview", e2b_preview_stub)

airports_stub = types.ModuleType("airports")
airports_stub.airport_data = []
sys.modules.setdefault("airports", airports_stub)


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


def test_images_search_parent_preview_metadata_contains_lightweight_results() -> None:
    from backend.core.api.app.services.embed_service import EmbedService

    metadata = EmbedService._build_parent_preview_metadata(
        "images",
        "search",
        [
            {
                "title": "Sunset",
                "source_page_url": "https://example.com/page",
                "image_url": "https://example.com/image.jpg",
                "thumbnail_url": "https://example.com/thumb.jpg",
                "source": "example.com",
                "favicon_url": "https://example.com/favicon.ico",
                "description": "Large text that is only useful in fullscreen",
                "embed_ref": "image-result-abc123",
            }
        ],
    )

    preview_results = [
        {
            "title": "Sunset",
            "source_page_url": "https://example.com/page",
            "image_url": "https://example.com/image.jpg",
            "thumbnail_url": "https://example.com/thumb.jpg",
            "source": "example.com",
            "favicon_url": "https://example.com/favicon.ico",
        }
    ]
    assert metadata == {
        "preview_results": preview_results,
        "preview_results_json": json.dumps(preview_results, separators=(",", ":")),
    }


def test_images_search_parent_preview_metadata_filters_empty_and_caps_results() -> None:
    from backend.core.api.app.services.embed_service import EmbedService

    results = [
        {"title": "No URL"},
        *[
            {
                "title": f"Image {index}",
                "thumbnail_url": f"https://example.com/thumb-{index}.jpg",
            }
            for index in range(12)
        ],
    ]

    metadata = EmbedService._build_parent_preview_metadata("images", "search", results)

    assert len(metadata["preview_results"]) == 10
    assert metadata["preview_results"][0] == {
        "title": "Image 0",
        "thumbnail_url": "https://example.com/thumb-0.jpg",
    }
    assert metadata["preview_results"][-1] == {
        "title": "Image 9",
        "thumbnail_url": "https://example.com/thumb-9.jpg",
    }


def test_images_search_parent_preview_metadata_flattens_grouped_results() -> None:
    from backend.core.api.app.services.embed_service import EmbedService

    metadata = EmbedService._build_parent_preview_metadata(
        "images",
        "search",
        [
            {
                "id": 1,
                "results": [
                    {
                        "title": "Grouped image",
                        "image_url": "https://example.com/image.jpg",
                    }
                ],
            }
        ],
    )

    assert metadata["preview_results"] == [
        {
            "title": "Grouped image",
            "image_url": "https://example.com/image.jpg",
        }
    ]


def test_web_search_parent_preview_metadata_contains_lightweight_results() -> None:
    from backend.core.api.app.services.embed_service import EmbedService

    metadata = EmbedService._build_parent_preview_metadata(
        "web",
        "search",
        [
            {
                "title": "OpenMates",
                "url": "https://openmates.org",
                "description": "Private AI assistants",
                "favicon": "https://openmates.org/favicon.svg",
                "meta_url": {"favicon": "https://openmates.org/favicon.svg"},
                "extra_snippets": ["Large text not needed in parent preview"],
            }
        ],
    )

    assert metadata == {
        "preview_results": [
            {
                "title": "OpenMates",
                "url": "https://openmates.org",
                "favicon": "https://openmates.org/favicon.svg",
                "meta_url": {"favicon": "https://openmates.org/favicon.svg"},
                "description": "Private AI assistants",
            }
        ]
    }


def test_web_search_parent_preview_metadata_filters_empty_and_caps_results() -> None:
    from backend.core.api.app.services.embed_service import EmbedService

    results = [
        {"title": "No URL"},
        *[
            {
                "title": f"Result {index}",
                "url": f"https://example.com/{index}",
                "favicon_url": f"https://example.com/favicon-{index}.ico",
            }
            for index in range(8)
        ],
    ]

    metadata = EmbedService._build_parent_preview_metadata("web", "search", results)

    assert len(metadata["preview_results"]) == 6
    assert metadata["preview_results"][0] == {
        "title": "Result 0",
        "url": "https://example.com/0",
        "favicon_url": "https://example.com/favicon-0.ico",
    }
    assert metadata["preview_results"][-1] == {
        "title": "Result 5",
        "url": "https://example.com/5",
        "favicon_url": "https://example.com/favicon-5.ico",
    }


def test_web_search_parent_preview_metadata_flattens_grouped_results() -> None:
    from backend.core.api.app.services.embed_service import EmbedService

    metadata = EmbedService._build_parent_preview_metadata(
        "web",
        "search",
        [
            {
                "id": 1,
                "results": [
                    {
                        "title": "Grouped result",
                        "url": "https://example.com/grouped",
                    }
                ],
            }
        ],
    )

    assert metadata["preview_results"] == [
        {
            "title": "Grouped result",
            "url": "https://example.com/grouped",
        }
    ]


def test_generic_result_list_parent_preview_metadata_contains_shallow_fields() -> None:
    from backend.core.api.app.services.embed_service import EmbedService

    metadata = EmbedService._build_parent_preview_metadata(
        "events",
        "search",
        [
            {
                "title": "Berlin AI Meetup",
                "url": "https://example.com/events/berlin-ai",
                "start_date": "2026-06-20",
                "end_date": "2026-06-21",
                "location": "Berlin",
                "description": "Long child-only details should not be copied into the generic parent preview.",
                "raw_provider_payload": {"large": "blob"},
            }
        ],
    )

    assert metadata == {
        "preview_results": [
            {
                "title": "Berlin AI Meetup",
                "url": "https://example.com/events/berlin-ai",
                "start_date": "2026-06-20",
                "end_date": "2026-06-21",
                "location": "Berlin",
            }
        ]
    }


def test_generic_result_list_parent_preview_metadata_caps_results() -> None:
    from backend.core.api.app.services.embed_service import EmbedService

    results = [
        {
            "title": f"Recipe {index}",
            "url": f"https://example.com/recipes/{index}",
            "thumbnail_url": f"https://example.com/thumb-{index}.jpg",
        }
        for index in range(8)
    ]

    metadata = EmbedService._build_parent_preview_metadata("nutrition", "search_recipes", results)

    assert len(metadata["preview_results"]) == 6
    assert metadata["preview_results"][0]["title"] == "Recipe 0"
    assert metadata["preview_results"][-1]["title"] == "Recipe 5"


def test_non_search_parent_preview_metadata_is_empty() -> None:
    from backend.core.api.app.services.embed_service import EmbedService

    metadata = EmbedService._build_parent_preview_metadata(
        "web",
        "read",
        [{"large_text": "No shallow preview fields"}],
    )

    assert metadata == {}


def test_images_search_preview_component_stays_parent_metadata_only() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    component_path = repo_root / "frontend/packages/ui/src/components/embeds/images/ImagesSearchEmbedPreview.svelte"
    component_source = component_path.read_text(encoding="utf-8")

    forbidden_child_hydration_tokens = [
        "embedResolver",
        "loadEmbedsWithRetry",
        "decodeToonContent",
        "loadChildEmbedsForPreview",
    ]

    for token in forbidden_child_hydration_tokens:
        assert token not in component_source


def test_web_search_preview_component_stays_parent_metadata_only() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    component_path = repo_root / "frontend/packages/ui/src/components/embeds/web/WebSearchEmbedPreview.svelte"
    component_source = component_path.read_text(encoding="utf-8")

    forbidden_child_hydration_tokens = [
        "embedResolver",
        "loadEmbedsWithRetry",
        "decodeToonContent",
        "loadChildEmbedsForPreview",
    ]

    for token in forbidden_child_hydration_tokens:
        assert token not in component_source
