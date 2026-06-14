# backend/tests/test_weather_rain_radar_skill.py
#
# Unit tests for Weather rain radar V1.
# Covers Bright Sky radar normalization, radius validation, Germany-only routing,
# and LLM context minimization without live network calls.
#
# Architecture: docs/specs/weather-rain-radar/spec.yml

from __future__ import annotations

import base64
import asyncio
import json
import sys
import zlib
from types import ModuleType

import pytest

celery_stub = ModuleType("celery")
celery_stub.Celery = object
sys.modules.setdefault("celery", celery_stub)


class DummyApp:
    secrets_manager = None


def make_skill():
    from backend.apps.weather.skills.rain_radar_skill import RainRadarSkill

    return RainRadarSkill(
        app=DummyApp(),
        app_id="weather",
        skill_id="rain_radar",
        skill_name="Rain radar",
        skill_description="Get nearby rain radar.",
    )


def _compressed_grid(values: list[int]) -> str:
    raw = b"".join(int(value).to_bytes(2, "big", signed=False) for value in values)
    return base64.b64encode(zlib.compress(raw)).decode("ascii")


def sample_radar_payload() -> dict:
    return {
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [13.30, 52.60],
                [13.50, 52.60],
                [13.50, 52.45],
                [13.30, 52.45],
                [13.30, 52.60],
            ]],
        },
        "bbox": [510, 490, 513, 493],
        "latlon_position": {"x": 1, "y": 1},
        "radar": [
            {
                "timestamp": "2026-06-14T13:00:00+00:00",
                "source": "dwd:rv",
                "precipitation_5": _compressed_grid([0, 0, 0, 0, 2, 20, 0, 0, 1]),
            },
            {
                "timestamp": "2026-06-14T13:10:00+00:00",
                "source": "dwd:rv",
                "precipitation_5": _compressed_grid([0, 1, 3, 4, 8, 42, 2, 0, 0]),
            },
        ],
    }


def test_bright_sky_radar_normalization_produces_summary_and_blob() -> None:
    from backend.shared.providers.bright_sky.bright_sky import normalize_radar_frames

    result = normalize_radar_frames(
        sample_radar_payload(),
        location_name="Berlin",
        latitude=52.52,
        longitude=13.405,
        radius_km=5,
        now_timestamp="2026-06-14T13:00:00+00:00",
    )

    assert result["type"] == "rain_radar"
    assert result["summary"]["rain_expected"] is True
    assert result["summary"]["peak_intensity"] == "light"
    assert result["summary"]["preview_frame_id"] == "frame-1"
    assert len(result["timeline"]) == 2
    assert result["timeline"][1]["rain_at_location_mm_5min"] == 0.08
    assert result["timeline"][1]["max_intensity"] == "light"
    assert result["rendering"]["grid_resolution_km"] == 1
    assert result["radar_blob_b64"]
    blob = json.loads(zlib.decompress(base64.b64decode(result["radar_blob_b64"])).decode("utf-8"))
    assert blob["version"] == 1
    assert blob["grid"]["width"] == 3
    assert blob["frames"][1]["values"] == [0, 1, 3, 4, 8, 42, 2, 0, 0]


@pytest.mark.parametrize("radius_km", [1, 5, 100])
def test_rain_radar_skill_accepts_radius_range(monkeypatch, radius_km: int) -> None:
    from backend.apps.weather.skills import rain_radar_skill

    async def fake_geocode_location(location: str):
        return {
            "name": "Berlin",
            "country_code": "DE",
            "country": "Germany",
            "latitude": 52.52,
            "longitude": 13.405,
            "timezone": "Europe/Berlin",
        }

    async def fake_fetch_radar(**kwargs):
        assert kwargs["radius_km"] == radius_km
        return sample_radar_payload()

    monkeypatch.setattr(rain_radar_skill, "geocode_location", fake_geocode_location)
    monkeypatch.setattr(rain_radar_skill, "fetch_radar", fake_fetch_radar)

    response = asyncio.run(make_skill().execute(location="Berlin", radius_km=radius_km))

    assert response.coverage["status"] == "available"
    assert response.rendering["radius_km"] == radius_km
    assert response.summary["rain_expected"] is True


@pytest.mark.parametrize("radius_km", [0, 101])
def test_rain_radar_skill_rejects_invalid_radius(radius_km: int) -> None:
    response = asyncio.run(make_skill().execute(location="Berlin", radius_km=radius_km))

    assert response.coverage["status"] == "error"
    assert "radius_km" in (response.error or "")


def test_rain_radar_skill_returns_unavailable_outside_germany(monkeypatch) -> None:
    from backend.apps.weather.skills import rain_radar_skill

    async def fake_geocode_location(location: str):
        return {
            "name": "Tokyo",
            "country_code": "JP",
            "country": "Japan",
            "latitude": 35.6764,
            "longitude": 139.65,
            "timezone": "Asia/Tokyo",
        }

    monkeypatch.setattr(rain_radar_skill, "geocode_location", fake_geocode_location)

    response = asyncio.run(make_skill().execute(location="Tokyo"))

    assert response.provider == "Deutscher Wetterdienst (DWD) via Bright Sky"
    assert response.coverage["status"] == "unavailable"
    assert response.location["country_code"] == "JP"
    assert "Germany" in response.summary["next_2_hours"]


def test_rain_radar_llm_filter_strips_heavy_storage_fields() -> None:
    from backend.core.api.app.services.embed_service import EmbedService
    from toon_format import decode, encode

    content = {
        "type": "rain_radar",
        "app_id": "weather",
        "skill_id": "rain_radar",
        "summary": {"rain_expected": True, "in_10_min": "Light rain nearby."},
        "timeline": [{"frame_id": "frame-1", "max_intensity": "light"}],
        "files": {"preview": {"s3_key": "secret-preview.webp"}},
        "s3_base_url": "https://bucket.example",
        "aes_key": "secret-key",
        "aes_nonce": "secret-nonce",
        "vault_wrapped_aes_key": "vault-secret",
        "radar_blob_b64": "too-large-for-llm",
    }

    filtered_toon, embed_ref = EmbedService.__new__(EmbedService)._filter_toon_for_llm(
        encode(content),
        "embed-radar-123456",
        seen_embed_refs={},
    )
    filtered = decode(filtered_toon)

    assert embed_ref is None
    assert filtered["summary"]["rain_expected"] is True
    assert "timeline" in filtered
    assert "files" not in filtered
    assert "s3_base_url" not in filtered
    assert "aes_key" not in filtered
    assert "aes_nonce" not in filtered
    assert "vault_wrapped_aes_key" not in filtered
    assert "radar_blob_b64" not in filtered


def test_rain_radar_asset_storage_uses_nonce_prefixed_objects(monkeypatch) -> None:
    from backend.core.api.app.services import cache as cache_module
    from backend.core.api.app.services.s3 import config as s3_config_module
    from backend.core.api.app.services.s3 import service as s3_service_module
    from backend.core.api.app.utils import secrets_manager as secrets_module
    from backend.shared.providers.bright_sky.bright_sky import normalize_radar_frames

    uploads: list[tuple[str, bytes]] = []
    cache_sets: list[tuple[str, str, int | None]] = []

    class FakeSecretsManager:
        async def initialize(self) -> None:
            return None

    class FakeS3UploadService:
        base_domain = "storage.example"

        def __init__(self, secrets_manager=None) -> None:
            self.secrets_manager = secrets_manager

        async def initialize(self) -> None:
            return None

        async def upload_file(self, *, bucket_key: str, file_key: str, content: bytes, content_type: str) -> None:
            assert bucket_key == "chatfiles"
            assert content_type == "application/octet-stream"
            uploads.append((file_key, content))

    class FakeRedis:
        async def set(self, key: str, value: str, ex: int | None = None) -> None:
            cache_sets.append((key, value, ex))

    class FakeCacheService:
        @property
        async def client(self):
            return FakeRedis()

    monkeypatch.setattr(secrets_module, "SecretsManager", FakeSecretsManager)
    monkeypatch.setattr(s3_service_module, "S3UploadService", FakeS3UploadService)
    monkeypatch.setattr(s3_config_module, "get_bucket_name", lambda bucket_key: f"{bucket_key}-bucket")
    monkeypatch.setattr(cache_module, "CacheService", FakeCacheService)

    radar_result = normalize_radar_frames(
        sample_radar_payload(),
        location_name="Berlin",
        latitude=52.52,
        longitude=13.405,
        radius_km=5,
        now_timestamp="2026-06-14T13:00:00+00:00",
    )

    metadata = asyncio.run(make_skill()._store_radar_assets_if_possible(
        radar_result=radar_result,
        user_id="user-1",
        placeholder_embed_ids=["embed-radar-1"],
    ))

    assert metadata is not None
    assert metadata["aes_key"]
    assert metadata["aes_nonce"] == ""
    assert metadata["s3_base_url"] == "https://chatfiles-bucket.storage.example"
    assert metadata["files"]["radar_blob"]["s3_key"].endswith("_blob.zlib")
    assert len(uploads) == 2
    preview_nonce = uploads[0][1][:12]
    blob_nonce = uploads[1][1][:12]
    assert len(preview_nonce) == 12
    assert len(blob_nonce) == 12
    assert preview_nonce != blob_nonce
    assert cache_sets and cache_sets[0][0] == "embed:embed-radar-1:s3_file_keys"
