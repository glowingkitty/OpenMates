"""3D model search skill contract tests.

The skill is a read-only, preview-only catalog search. It returns child embed
payloads that can be grouped under an app_skill_use parent without downloading
or rendering provider model files.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from backend.apps.models3d.skills.search_skill import SearchSkill
from backend.shared.providers.models3d_catalogs import Model3DProviderError, Model3DProviderResult

REPO_ROOT = Path(__file__).resolve().parents[2]


def _skill() -> SearchSkill:
    return SearchSkill(
        app=None,
        app_id="models3d",
        skill_id="search",
        skill_name="Search 3D models",
        skill_description="Find existing 3D models.",
    )


class FakeProvider:
    def __init__(self, provider_name: str = "Printables") -> None:
        self.provider_name = provider_name
        self.calls: list[dict[str, Any]] = []

    async def search(self, query: str, *, count: int) -> list[Model3DProviderResult]:
        self.calls.append({"query": query, "count": count})
        return [
            Model3DProviderResult(
                title="Bench Boat",
                creator_name="CreativeTools",
                provider=self.provider_name,
                provider_kind="official_api" if self.provider_name != "Printables" else "reverse_engineered_browser_api",
                provider_item_id=f"{self.provider_name.lower()}-3161",
                source_page_url=f"https://example.com/{self.provider_name.lower()}/bench-boat",
                description="A calibration boat for testing 3D printers.",
                preview_image_url=f"https://example.com/{self.provider_name.lower()}/bench.jpg",
                thumbnail_url=f"https://example.com/{self.provider_name.lower()}/bench-thumb.jpg",
                license="CC BY",
                published_at="2025-02-14T09:26:10+00:00",
                created_at="2019-05-23T11:23:58+00:00",
                updated_at="2025-02-14T09:26:45+00:00",
                tags=["benchy", "calibration"],
                category="Test models",
                likes_count=42,
                download_count=1234,
                files_count=3,
                is_free=True,
            )
        ]


@pytest.mark.asyncio
async def test_models3d_search_returns_preview_only_child_results() -> None:
    provider = FakeProvider()

    response = await _skill().execute(
        requests=[{"id": "r1", "query": "benchy", "count": 5, "providers": ["Printables"]}],
        provider_clients={"printables": provider},
    )
    payload = response.model_dump()

    assert payload["success"] is True
    assert payload["app_id"] == "models3d"
    assert payload["skill_id"] == "search"
    assert payload["status"] == "finished"
    assert payload["result_count"] == 1
    assert provider.calls == [{"query": "benchy", "count": 5}]
    assert payload["results"][0]["id"] == "r1"
    child = payload["results"][0]["results"][0]
    assert child["type"] == "model_result"
    assert child["parent_app_skill_type"] == "app_skill_use"
    assert child["title"] == "Bench Boat"
    assert child["description"] == "A calibration boat for testing 3D printers."
    assert child["creator_name"] == "CreativeTools"
    assert child["published_at"] == "2025-02-14T09:26:10+00:00"
    assert child["created_at"] == "2019-05-23T11:23:58+00:00"
    assert child["updated_at"] == "2025-02-14T09:26:45+00:00"
    assert child["source_page_url"] == "https://example.com/printables/bench-boat"
    assert child["preview_image_url"] == "https://example.com/printables/bench.jpg"
    forbidden = {
        "file_url",
        "download_url",
        "file_urls",
        "download_urls",
        "javascript",
        "script",
        "api_key",
        "access_token",
        "open_cta_label",
    }
    assert forbidden.isdisjoint(child)


@pytest.mark.asyncio
async def test_models3d_search_defaults_to_all_providers_ten_results_and_trims_total() -> None:
    providers = {
        "printables": FakeProvider("Printables"),
        "myminifactory": FakeProvider("MyMiniFactory"),
        "thingiverse": FakeProvider("Thingiverse"),
    }

    response = await _skill().execute(requests=[{"query": "benchy"}], provider_clients=providers)
    payload = response.model_dump()

    assert payload["success"] is True
    assert payload["provider"] == "MyMiniFactory, Printables, Thingiverse"
    assert payload["result_count"] == 3
    assert [provider.calls for provider in providers.values()] == [
        [{"query": "benchy", "count": 10}],
        [{"query": "benchy", "count": 10}],
        [{"query": "benchy", "count": 10}],
    ]


@pytest.mark.asyncio
async def test_models3d_search_applies_sort_free_filter_and_total_count() -> None:
    class RankedProvider:
        provider_name = "Printables"

        async def search(self, query: str, *, count: int) -> list[Model3DProviderResult]:
            assert query == "stand"
            assert count == 2
            return [
                Model3DProviderResult(
                    title="Paid popular stand",
                    provider="Printables",
                    provider_kind="reverse_engineered_browser_api",
                    provider_item_id="paid",
                    source_page_url="https://example.com/paid",
                    preview_image_url="https://example.com/paid.jpg",
                    likes_count=100,
                    download_count=20,
                    is_free=False,
                ),
                Model3DProviderResult(
                    title="Free downloaded stand",
                    provider="Printables",
                    provider_kind="reverse_engineered_browser_api",
                    provider_item_id="free-downloaded",
                    source_page_url="https://example.com/free-downloaded",
                    preview_image_url="https://example.com/free-downloaded.jpg",
                    likes_count=20,
                    download_count=200,
                    is_free=True,
                ),
                Model3DProviderResult(
                    title="Free low-rank stand",
                    provider="Printables",
                    provider_kind="reverse_engineered_browser_api",
                    provider_item_id="free-low",
                    source_page_url="https://example.com/free-low",
                    preview_image_url="https://example.com/free-low.jpg",
                    likes_count=1,
                    download_count=1,
                    is_free=True,
                ),
            ]

    response = await _skill().execute(
        requests=[{"query": "stand", "providers": ["Printables"], "count": 2, "sort": "downloads", "free_only": True}],
        provider_clients={"printables": RankedProvider()},
    )
    payload = response.model_dump()

    assert payload["success"] is True
    children = payload["results"][0]["results"]
    assert [child["title"] for child in children] == ["Free downloaded stand", "Free low-rank stand"]


@pytest.mark.asyncio
async def test_models3d_search_surfaces_partial_provider_warnings() -> None:
    class FailingProvider:
        provider_name = "MyMiniFactory"

        async def search(self, query: str, *, count: int) -> list[Model3DProviderResult]:
            raise Model3DProviderError("MyMiniFactory", "missing_api_key", "Missing MyMiniFactory API key")

    response = await _skill().execute(
        requests=[{"query": "benchy", "providers": ["Printables", "MyMiniFactory"]}],
        provider_clients={"printables": FakeProvider(), "myminifactory": FailingProvider()},
    )
    payload = response.model_dump()

    assert payload["success"] is True
    assert payload["warnings"] == [
        {"provider": "MyMiniFactory", "code": "missing_api_key", "message": "Missing MyMiniFactory API key"}
    ]
    assert payload["result_count"] == 1


@pytest.mark.asyncio
async def test_models3d_search_returns_typed_error_when_all_providers_fail() -> None:
    class FailingProvider:
        provider_name = "MyMiniFactory"

        async def search(self, query: str, *, count: int) -> list[Model3DProviderResult]:
            raise Model3DProviderError("MyMiniFactory", "missing_api_key", "Missing MyMiniFactory API key")

    response = await _skill().execute(
        requests=[{"query": "benchy", "providers": ["MyMiniFactory"]}],
        provider_clients={"myminifactory": FailingProvider()},
    )
    payload = response.model_dump()

    assert payload["success"] is False
    assert payload["error"] == "No 3D model search providers returned results"
    assert payload["error_code"] == "all_providers_failed"


def test_models3d_app_metadata_declares_parent_child_search_embeds() -> None:
    app_yml = yaml.safe_load((REPO_ROOT / "backend/apps/models3d/app.yml").read_text())
    search_embed = next(embed for embed in app_yml["embed_types"] if embed["id"] == "search")
    child_embed = next(embed for embed in app_yml["embed_types"] if embed["id"] == "model_result")

    assert search_embed["category"] == "app-skill-use"
    assert search_embed["skill_id"] == "search"
    assert search_embed["has_children"] is True
    assert search_embed["child_type"] == "model_result"
    assert child_embed["category"] == "direct"
    assert child_embed["frontend_type"] == "models3d-model-result"
