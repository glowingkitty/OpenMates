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


def test_embed_metadata_merge_strips_raw_finance_request_payloads() -> None:
    from backend.core.api.app.services.embed_service import EmbedService

    metadata = EmbedService._merge_request_metadata(
        {
            "app_id": "finance",
            "skill_id": "check_accounts",
            "status": "processing",
            "csv_statements": [
                {"filename": "cash.csv", "content": "2026-01-01,Grocery Mart,-50.00"}
            ],
            "csv_count": 1,
        },
        {
            "csv_statements": [
                {"filename": "cash.csv", "content": "2026-01-01,Acme Payroll,1000.00"}
            ],
            "csv_statements[1]{content,filename}": "2026-01-01,Coffee Shop,-4.50,cash.csv",
            "connected_account_requests": [{"access_token_handle": "ath_1"}],
            "connected_account_access_tokens": {"ath_1": "secret-token"},
            "user_id": "user-secret",
            "user_vault_key_id": "vault-secret",
            "vault_key_id": "vault-secret",
            "external_request": True,
            "placeholder_embed_ids": ["embed-secret"],
            "embed_id": "embed-secret",
            "period": "monthly",
            "csv_count": 1,
        },
    )

    serialized = json.dumps(metadata)
    assert metadata == {"csv_count": 1, "period": "monthly"}
    assert "csv_statements" not in metadata
    assert "csv_statements[1]{content,filename}" not in metadata
    assert "connected_account_requests" not in metadata
    assert "connected_account_access_tokens" not in metadata
    assert "user_id" not in metadata
    assert "user_vault_key_id" not in metadata
    assert "vault_key_id" not in metadata
    assert "external_request" not in metadata
    assert "placeholder_embed_ids" not in metadata
    assert "embed_id" not in metadata
    assert "Grocery Mart" not in serialized
    assert "Acme Payroll" not in serialized
    assert "Coffee Shop" not in serialized
    assert "secret-token" not in serialized


def test_embed_metadata_sanitizer_strips_nested_raw_finance_request_payloads() -> None:
    from backend.core.api.app.services.embed_service import EmbedService

    metadata = EmbedService._sanitize_request_metadata({
        "requests": [
            {
                "period": "monthly",
                "csv_statements": [
                    {"filename": "cash.csv", "content": "2026-01-01,Coffee Shop,-4.50"}
                ],
                "connected_account_requests": [{"access_token_handle": "ath_1"}],
                "_connected_account_access_tokens": {"ath_1": "secret-token"},
                "user_id": "user-secret",
            }
        ],
        "projection_horizon": "monthly",
    })

    serialized = json.dumps(metadata)
    assert metadata == {
        "requests": [{"period": "monthly"}],
        "projection_horizon": "monthly",
    }
    assert "csv_statements" not in serialized
    assert "Coffee Shop" not in serialized
    assert "connected_account_requests" not in serialized
    assert "secret-token" not in serialized
    assert "user-secret" not in serialized


def test_finance_final_embed_content_sanitizer_strips_raw_request_and_internal_fields() -> None:
    from backend.core.api.app.services.embed_service import EmbedService

    content = EmbedService._sanitize_final_app_skill_content(
        "finance",
        "check_accounts",
        {
            "app_id": "finance",
            "skill_id": "check_accounts",
            "status": "finished",
            "result_count": 1,
            "embed_ref": "check_accounts-abc",
            "embed_id": "embed-secret",
            "vault_key_id": "vault-secret",
            "user_id": "user-secret",
            "csv_statements[1]{filename,content}": "cash.csv,2026-01-01,Coffee Shop,-4.50",
            "results": [
                {
                    "success": True,
                    "overview": {"summaries": {"net_total": 42}},
                    "connected_account_requests": [{"access_token_handle": "ath_1"}],
                }
            ],
        },
    )

    serialized = json.dumps(content)
    assert content["app_id"] == "finance"
    assert content["skill_id"] == "check_accounts"
    assert content["results"] == [{"success": True, "overview": {"summaries": {"net_total": 42}}}]
    assert "embed-secret" not in serialized
    assert "vault-secret" not in serialized
    assert "user-secret" not in serialized
    assert "csv_statements" not in serialized
    assert "Coffee Shop" not in serialized
    assert "connected_account_requests" not in serialized


def test_finance_outbound_toon_sanitizer_strips_raw_request_and_internal_fields() -> None:
    from backend.core.api.app.services.embed_service import EmbedService

    toon = "\n".join([
        "app_id: finance",
        "skill_id: check_accounts",
        "results[1]:",
        "  - success: true",
        "result_count: 1",
        "embed_ref: check_accounts-abc",
        "embed_id: embed-secret",
        "vault_key_id: vault-secret",
        "user_id: user-secret",
        "csv_statements[1]{filename,content}:",
        "  cash.csv,2026-01-01,Coffee Shop,-4.50",
        "period: monthly",
    ])

    sanitized = EmbedService._sanitize_finance_check_accounts_toon(toon)

    assert "app_id: finance" in sanitized
    assert "skill_id: check_accounts" in sanitized
    assert "results[1]:" in sanitized
    assert "period: monthly" in sanitized
    assert "embed-secret" not in sanitized
    assert "vault-secret" not in sanitized
    assert "user-secret" not in sanitized
    assert "csv_statements" not in sanitized
    assert "Coffee Shop" not in sanitized


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


def test_news_search_parent_preview_metadata_contains_favicon_capable_results() -> None:
    from backend.core.api.app.services.embed_service import EmbedService

    metadata = EmbedService._build_parent_preview_metadata(
        "news",
        "search",
        [
            {
                "title": "OpenMates raises privacy bar",
                "url": "https://news.example/openmates",
                "description": "Long article text that should stay child-only",
                "favicon": "https://news.example/favicon.ico",
                "published_date": "2026-06-21",
                "raw_provider_payload": {"large": "blob"},
            }
        ],
    )

    assert metadata == {
        "preview_results": [
            {
                "title": "OpenMates raises privacy bar",
                "url": "https://news.example/openmates",
                "favicon": "https://news.example/favicon.ico",
                "published_date": "2026-06-21",
            }
        ]
    }


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


def test_weather_forecast_parent_preview_metadata_contains_day_summaries() -> None:
    from backend.core.api.app.services.embed_service import EmbedService

    metadata = EmbedService._build_parent_preview_metadata(
        "weather",
        "forecast",
        [
            {
                "type": "weather_day",
                "date": "2026-06-19",
                "location_name": "Berlin",
                "provider": "Deutscher Wetterdienst (DWD)",
                "condition": "partly cloudy",
                "icon": "partly-cloudy-day",
                "temperature_min_c": 18,
                "temperature_max_c": 32,
                "precipitation_total_mm": 0,
                "precipitation_probability_max_pct": 4,
                "rain_hours": 0,
                "hourly": [{"large": "child-only hourly details"}],
            }
        ],
    )

    assert metadata == {
        "preview_results": [
            {
                "date": "2026-06-19",
                "location_name": "Berlin",
                "provider": "Deutscher Wetterdienst (DWD)",
                "condition": "partly cloudy",
                "icon": "partly-cloudy-day",
                "temperature_min_c": 18,
                "temperature_max_c": 32,
                "precipitation_total_mm": 0,
                "precipitation_probability_max_pct": 4,
                "rain_hours": 0,
            }
        ]
    }


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


def test_weather_forecast_preview_component_consumes_parent_preview_results() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    component_path = repo_root / "frontend/packages/ui/src/components/embeds/weather/WeatherForecastEmbedPreview.svelte"
    component_source = component_path.read_text(encoding="utf-8")

    assert "preview_results" in component_source


def test_weather_forecast_inline_renderers_pass_parent_preview_results() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    app_skill_renderer = (
        repo_root / "frontend/packages/ui/src/components/enter_message/extensions/embed_renderers/AppSkillUseRenderer.ts"
    ).read_text(encoding="utf-8")
    group_renderer = (
        repo_root / "frontend/packages/ui/src/components/enter_message/extensions/embed_renderers/GroupRenderer.ts"
    ).read_text(encoding="utf-8")

    weather_function = app_skill_renderer.split("private renderWeatherForecastComponent", 1)[1]
    weather_function = weather_function.split("private renderWeatherRainRadarComponent", 1)[0]
    weather_branch = group_renderer.split('if (appId === "weather" && skillId === "forecast")', 1)[1]
    weather_branch = weather_branch.split('if (appId === "weather" && skillId === "rain_radar")', 1)[0]

    for renderer_source in (weather_function, weather_branch):
        assert "preview_results" in renderer_source
        assert "previewResults" in renderer_source
        assert "WeatherForecastEmbedPreview" in renderer_source
