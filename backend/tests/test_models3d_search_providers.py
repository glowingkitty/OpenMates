"""3D model search provider normalization tests.

These tests keep catalog adapters preview-only: providers may expose file names,
download URLs, or raw blobs, but OpenMates V1 stores only public display
metadata and source links in result embeds.
"""

from __future__ import annotations

import pytest

from backend.shared.providers.models3d_catalogs import (
    Model3DProviderError,
    Model3DProviderResult,
    collect_provider_search_results,
    normalize_myminifactory_object,
    normalize_printables_print,
    normalize_thingiverse_thing,
)


FORBIDDEN_RESULT_KEYS = {
    "file_url",
    "file_urls",
    "download_url",
    "download_urls",
    "files",
    "fileUploads",
    "javascript",
    "script",
    "api_key",
    "access_token",
}


def assert_preview_only(result: Model3DProviderResult) -> None:
    payload = result.model_dump(exclude_none=True)
    assert payload["title"]
    assert payload["source_page_url"].startswith("https://")
    assert payload["provider"]
    assert payload["preview_image_url"].startswith("https://")
    assert FORBIDDEN_RESULT_KEYS.isdisjoint(payload)
    assert FORBIDDEN_RESULT_KEYS.isdisjoint(payload.get("normalized_provider_metadata", {}))


def test_printables_normalization_is_preview_only() -> None:
    result = normalize_printables_print(
        {
            "id": "3161",
            "name": "3DBenchy",
            "slug": "3dbenchy",
            "summary": "A calibration boat.",
            "created": "2019-05-23T11:23:58+00:00",
            "datePublished": "2025-02-14T09:26:10+00:00",
            "modified": "2025-02-14T09:26:45+00:00",
            "user": {"publicUsername": "CreativeTools"},
            "image": {"filePath": "/media/prints/3161/images/123.jpg"},
            "license": "Creative Commons - Attribution",
            "tags": [{"name": "benchy"}, {"name": "test"}],
            "category": {"name": "Test models"},
            "likesCount": 42,
            "downloadCount": 1234,
            "filesCount": 3,
            "price": 0,
            "fileUploads": [{"downloadUrl": "https://example.com/model.stl"}],
        }
    )

    assert_preview_only(result)
    assert result.provider == "Printables"
    assert result.provider_kind == "reverse_engineered_browser_api"
    assert result.provider_item_id == "3161"
    assert result.is_free is True
    assert result.files_count == 3
    assert result.creator_name == "CreativeTools"
    assert result.description == "A calibration boat."
    assert result.created_at == "2019-05-23T11:23:58+00:00"
    assert result.published_at == "2025-02-14T09:26:10+00:00"
    assert result.updated_at == "2025-02-14T09:26:45+00:00"
    assert result.source_page_url == "https://www.printables.com/model/3161-3dbenchy"


def test_myminifactory_normalization_is_preview_only() -> None:
    result = normalize_myminifactory_object(
        {
            "id": 123,
            "name": "Phone Stand",
            "url": "https://www.myminifactory.com/object/3d-print-phone-stand-123",
            "thumbnailUrl": "https://cdn.myminifactory.com/object-assets/thumb.jpg",
            "designer": {"username": "maker"},
            "license": "CC BY",
            "tags": ["phone", "stand"],
            "price": "0.00",
            "files": [{"url": "https://example.com/file.stl"}],
        }
    )

    assert_preview_only(result)
    assert result.provider == "MyMiniFactory"
    assert result.provider_kind == "official_api"
    assert result.provider_item_id == "123"
    assert result.is_free is True


def test_thingiverse_normalization_is_preview_only() -> None:
    result = normalize_thingiverse_thing(
        {
            "id": 456,
            "name": "Cable Clip",
            "public_url": "https://www.thingiverse.com/thing:456",
            "thumbnail": "https://cdn.thingiverse.com/thumb.jpg",
            "creator": {"name": "designer"},
            "license": "cc-sa",
            "tags": [{"name": "cable"}],
            "like_count": 12,
            "download_count": 34,
            "files_url": "https://api.thingiverse.com/things/456/files",
        }
    )

    assert_preview_only(result)
    assert result.provider == "Thingiverse"
    assert result.provider_kind == "official_api"
    assert result.provider_item_id == "456"


@pytest.mark.asyncio
async def test_collect_provider_search_results_returns_partial_warnings() -> None:
    class SuccessfulProvider:
        provider_name = "Printables"

        async def search(self, query: str, *, count: int) -> list[Model3DProviderResult]:
            assert query == "benchy"
            assert count == 2
            return [
                Model3DProviderResult(
                    title="Bench Boat",
                    provider="Printables",
                    provider_kind="reverse_engineered_browser_api",
                    provider_item_id="3161",
                    source_page_url="https://www.printables.com/model/3161-bench-boat",
                    preview_image_url="https://media.printables.com/bench.jpg",
                )
            ]

    class FailingProvider:
        provider_name = "MyMiniFactory"

        async def search(self, query: str, *, count: int) -> list[Model3DProviderResult]:
            raise Model3DProviderError("MyMiniFactory", "missing_api_key", "Missing MyMiniFactory API key")

    results, warnings = await collect_provider_search_results(
        query="benchy",
        count=2,
        providers=[SuccessfulProvider(), FailingProvider()],
    )

    assert [result.provider for result in results] == ["Printables"]
    assert warnings == [
        {
            "provider": "MyMiniFactory",
            "code": "missing_api_key",
            "message": "Missing MyMiniFactory API key",
        }
    ]


@pytest.mark.asyncio
async def test_collect_provider_search_results_raises_when_all_providers_fail() -> None:
    class FailingProvider:
        provider_name = "MyMiniFactory"

        async def search(self, query: str, *, count: int) -> list[Model3DProviderResult]:
            raise Model3DProviderError("MyMiniFactory", "missing_api_key", "Missing MyMiniFactory API key")

    with pytest.raises(Model3DProviderError) as exc_info:
        await collect_provider_search_results(
            query="benchy",
            count=2,
            providers=[FailingProvider()],
        )

    assert exc_info.value.code == "all_providers_failed"
