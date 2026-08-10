# backend/tests/test_geoapify_places_provider.py
#
# Contract tests for the Geoapify Places provider adapter.
# These tests encode the OSM enrichment boundary used by maps.search: source
# labelled detail fields, explicit unknowns for absent OSM tags, safe cache
# keys, and typed provider statuses without live Geoapify calls.
#
# Spec: docs/specs/maps-geoapify-osm-enrichment/spec.yml

from typing import Any

import httpx
import pytest

from backend.shared.providers.geoapify.places import (
    GEOAPIFY_API_KEY_ENV_VAR,
    GEOAPIFY_SECRET_PATH,
    GeoapifyPlacesProvider,
    normalize_place_details,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _FakeSecretsManager:
    def __init__(self, values: dict[tuple[str, str], str | None]) -> None:
        self.values = values

    async def get_secret(self, secret_path: str, secret_key: str) -> str | None:
        return self.values.get((secret_path, secret_key))


class _MemoryCache:
    def __init__(self) -> None:
        self.values: dict[str, Any] = {}
        self.set_calls: list[tuple[str, Any, int | None]] = []

    async def get(self, key: str) -> Any:
        return self.values.get(key)

    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        self.values[key] = value
        self.set_calls.append((key, value, ttl))
        return True


def _response(status_code: int, json_body: dict[str, Any]) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=json_body,
        request=httpx.Request("GET", "https://api.geoapify.com/v2/place-details"),
    )


async def test_api_key_uses_vault_before_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(GEOAPIFY_API_KEY_ENV_VAR, "env-key")
    provider = GeoapifyPlacesProvider(
        secrets_manager=_FakeSecretsManager({(GEOAPIFY_SECRET_PATH, "api_key"): " vault-key "})
    )

    assert await provider.get_api_key() == "vault-key"


async def test_api_key_falls_back_to_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(GEOAPIFY_API_KEY_ENV_VAR, " env-key ")
    provider = GeoapifyPlacesProvider(secrets_manager=_FakeSecretsManager({}))

    assert await provider.get_api_key() == "env-key"


def test_place_details_normalization_source_labels_and_unknowns() -> None:
    normalized = normalize_place_details(
        {
            "properties": {
                "place_id": "osm-node-1",
                "datasource": {"sourcename": "openstreetmap"},
                "facilities": {
                    "air_conditioning": True,
                    "internet_access": "free",
                    "wheelchair": "limited",
                    "toilets": True,
                    "smoking": "outside",
                    "outdoor_seating": True,
                },
                "catering": {"diet:vegetarian": True},
                "payment_options": {"cash": True, "cards": False},
            }
        }
    )

    assert normalized["provider"] == "Geoapify"
    assert normalized["data_source"] == "OpenStreetMap via Geoapify"
    assert normalized["status"] == "matched"
    assert normalized["match"]["geoapify_place_id"] == "osm-node-1"
    assert normalized["fields"]["air_conditioning"] == {
        "value": "yes",
        "source": "OpenStreetMap via Geoapify",
        "raw_value": True,
    }
    assert normalized["fields"]["internet_access"]["value"] == "free"
    assert normalized["fields"]["wheelchair"]["value"] == "limited"
    assert normalized["fields"]["outdoor_seating"]["value"] == "yes"
    assert normalized["fields"]["diet"]["value"] == {"vegetarian": "yes"}
    assert normalized["fields"]["payment"]["value"] == {"cash": "yes", "cards": "no"}
    assert normalized["fields"]["dogs"]["value"] == "unknown"


async def test_supported_conditions_are_forwarded_and_unsupported_are_not() -> None:
    captured_params: list[dict[str, Any]] = []

    async def fake_get(url: str, params: dict[str, Any], timeout: float) -> httpx.Response:
        captured_params.append(params)
        return _response(200, {"features": []})

    provider = GeoapifyPlacesProvider(
        secrets_manager=_FakeSecretsManager({(GEOAPIFY_SECRET_PATH, "api_key"): "geo-key"}),
        http_get=fake_get,
    )

    result = await provider.search_places(
        query="restaurants in Berlin",
        limit=20,
        conditions=["internet_access.free", "wheelchair", "air_conditioning"],
    )

    assert result.status == "ok"
    assert captured_params[0]["conditions"] == "internet_access.free,wheelchair"
    assert "air_conditioning" in result.unsupported_conditions


async def test_details_cache_key_excludes_private_context_and_sets_positive_ttl() -> None:
    cache = _MemoryCache()

    async def fake_get(url: str, params: dict[str, Any], timeout: float) -> httpx.Response:
        return _response(
            200,
            {
                "features": [
                    {
                        "properties": {
                            "place_id": "osm-node-2",
                            "facilities": {"air_conditioning": True},
                        }
                    }
                ]
            },
        )

    provider = GeoapifyPlacesProvider(
        secrets_manager=_FakeSecretsManager({(GEOAPIFY_SECRET_PATH, "api_key"): "geo-key"}),
        cache_service=cache,
        http_get=fake_get,
    )

    result = await provider.get_place_details(
        place_id="osm-node-2",
        context={"user_id": "user-1", "chat_id": "chat-1", "api_key": "secret"},
    )

    assert result.status == "matched"
    cache_key, cached_value, ttl = cache.set_calls[0]
    assert cache_key.startswith("geoapify:place_details:v1:")
    assert "user-1" not in cache_key
    assert "chat-1" not in cache_key
    assert "secret" not in cache_key
    assert "_raw" not in cached_value
    assert ttl == 30 * 24 * 60 * 60


async def test_provider_errors_return_typed_statuses() -> None:
    async def rate_limited_get(url: str, params: dict[str, Any], timeout: float) -> httpx.Response:
        return _response(429, {"message": "quota exceeded"})

    provider = GeoapifyPlacesProvider(
        secrets_manager=_FakeSecretsManager({(GEOAPIFY_SECRET_PATH, "api_key"): "geo-key"}),
        http_get=rate_limited_get,
    )

    result = await provider.search_places(query="cafes in Berlin")

    assert result.status == "rate_limited"
    assert result.error


async def test_missing_api_key_returns_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(GEOAPIFY_API_KEY_ENV_VAR, raising=False)
    provider = GeoapifyPlacesProvider(secrets_manager=_FakeSecretsManager({}))

    result = await provider.search_places(query="cafes in Berlin")

    assert result.status == "not_configured"
    assert result.places == []
