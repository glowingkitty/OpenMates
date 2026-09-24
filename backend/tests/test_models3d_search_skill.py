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

from backend.apps.models3d.skills import search_skill as models3d_search
from backend.apps.models3d.skills.search_skill import SearchSkill
from backend.shared.python_utils.search_relevance import SearchRelevanceRankingResult
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


# contract-test: supporting surface=rest_api assertions=app-skills.surface.semantic-parity
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


# contract-test: direct surface=rest_api assertions=app-skills.search-relevance.bounded-and-conditional,app-skills.search-relevance.safe-finalization
@pytest.mark.asyncio
async def test_models3d_search_defaults_to_printables_only_ten_results() -> None:
    providers = {"printables": FakeProvider("Printables")}

    response = await _skill().execute(requests=[{"query": "benchy"}], provider_clients=providers)
    payload = response.model_dump()

    assert payload["success"] is True
    assert payload["provider"] == "Printables"
    assert payload["result_count"] == 1
    assert [provider.calls for provider in providers.values()] == [
        [{"query": "benchy", "count": 10}],
    ]


# contract-test: direct surface=rest_api assertions=app-skills.search-relevance.safe-finalization
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


# contract-test: direct surface=rest_api assertions=app-skills.search-relevance.optional-and-inferred,app-skills.search-relevance.bounded-and-conditional,app-skills.search-relevance.safe-finalization
@pytest.mark.asyncio
async def test_models3d_search_relevance_ranks_filtered_deduplicated_candidate_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class CandidateProvider:
        provider_name = "Printables"

        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        async def search(self, query: str, *, count: int) -> list[Model3DProviderResult]:
            self.calls.append({"query": query, "count": count})
            return [
                Model3DProviderResult(
                    title="Paid enclosure",
                    provider="Printables",
                    provider_kind="reverse_engineered_browser_api",
                    provider_item_id="paid",
                    source_page_url="https://example.com/paid",
                    download_count=500,
                    is_free=False,
                ),
                Model3DProviderResult(
                    title="Compact enclosure",
                    description="A vented compact enclosure for a Raspberry Pi 5.",
                    creator_name="Maker One",
                    provider="Printables",
                    provider_kind="reverse_engineered_browser_api",
                    provider_item_id="compact",
                    source_page_url="https://example.com/compact",
                    tags=["raspberry pi", "vented"],
                    category="Cases",
                    license="CC BY",
                    download_count=200,
                    likes_count=20,
                    rating=4.7,
                    files_count=2,
                    is_free=True,
                ),
                Model3DProviderResult(
                    title="Duplicate compact enclosure",
                    provider="Printables",
                    provider_kind="reverse_engineered_browser_api",
                    provider_item_id="compact",
                    source_page_url="https://example.com/compact-copy",
                    download_count=150,
                    is_free=True,
                ),
                Model3DProviderResult(
                    title="Large enclosure",
                    description="A large enclosure with explicit wall-mount holes.",
                    provider="Printables",
                    provider_kind="reverse_engineered_browser_api",
                    provider_item_id="large",
                    source_page_url="https://example.com/large",
                    download_count=100,
                    is_free=True,
                ),
            ]

    provider = CandidateProvider()
    secret = object()
    rank_calls: list[dict[str, Any]] = []

    async def fake_rank(**kwargs: Any) -> SearchRelevanceRankingResult[Model3DProviderResult]:
        rank_calls.append(kwargs)
        return SearchRelevanceRankingResult(
            candidates=list(reversed(kwargs["candidates"])),
            applied=True,
        )

    monkeypatch.setattr(models3d_search, "rank_search_candidates", fake_rank)
    response = await _skill().execute(
        requests=[
            {
                "query": "raspberry pi enclosure",
                "count": 1,
                "sort": "downloads",
                "free_only": True,
                "relevance_criteria": "Compact and well ventilated based on explicit listing facts",
            }
        ],
        provider_clients={"printables": provider},
        secrets_manager=secret,
    )

    assert provider.calls == [{"query": "raspberry pi enclosure", "count": 40}]
    assert len(rank_calls) == 1
    rank_call = rank_calls[0]
    assert [candidate.provider_item_id for candidate in rank_call["candidates"]] == ["compact", "large"]
    assert rank_call["candidate_projections"] == [
        {
            "title": "Compact enclosure",
            "description": "A vented compact enclosure for a Raspberry Pi 5.",
            "creator_name": "Maker One",
            "tags": ["raspberry pi", "vented"],
            "category": "Cases",
            "license": "CC BY",
            "rating": 4.7,
            "likes_count": 20,
            "download_count": 200,
            "files_count": 2,
            "is_free": True,
        },
        {
            "title": "Large enclosure",
            "description": "A large enclosure with explicit wall-mount holes.",
            "download_count": 100,
            "is_free": True,
        },
    ]
    assert rank_call["relevance_criteria"] == "Compact and well ventilated based on explicit listing facts"
    assert rank_call["search_parameters"] == {
        "query": "raspberry pi enclosure",
        "providers": ["Printables"],
        "sort": "downloads",
        "free_only": True,
    }
    assert rank_call["profile"] == "models3d"
    assert rank_call["secrets_manager"] is secret
    assert [item["provider_item_id"] for item in response.results[0]["results"]] == ["large"]


# contract-test: direct surface=rest_api assertions=app-skills.search-relevance.optional-and-inferred,app-skills.search-relevance.bounded-and-conditional
@pytest.mark.asyncio
async def test_models3d_search_blank_relevance_preserves_plain_path_and_skips_ranking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = FakeProvider()

    async def unexpected_rank(**_kwargs: Any) -> SearchRelevanceRankingResult[Model3DProviderResult]:
        raise AssertionError("blank relevance criteria must not invoke ranking")

    monkeypatch.setattr(models3d_search, "rank_search_candidates", unexpected_rank)
    response = await _skill().execute(
        requests=[{"query": "benchy", "count": 2, "relevance_criteria": "  \n  "}],
        provider_clients={"printables": provider},
    )

    assert response.success is True
    assert provider.calls == [{"query": "benchy", "count": 2}]


# contract-test: direct surface=rest_api assertions=app-skills.search-relevance.safe-finalization
@pytest.mark.asyncio
async def test_models3d_search_ranking_failure_keeps_valid_provider_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class OrderedProvider:
        provider_name = "Printables"

        async def search(self, query: str, *, count: int) -> list[Model3DProviderResult]:
            assert count == 40
            return [
                Model3DProviderResult(
                    title=f"Result {index}",
                    provider="Printables",
                    provider_kind="reverse_engineered_browser_api",
                    provider_item_id=str(index),
                    source_page_url=f"https://example.com/{index}",
                    is_free=True,
                )
                for index in range(4)
            ]

    async def failed_rank(**_kwargs: Any) -> SearchRelevanceRankingResult[Model3DProviderResult]:
        raise RuntimeError("Jev unavailable")

    monkeypatch.setattr(models3d_search, "rank_search_candidates", failed_rank)
    response = await _skill().execute(
        requests=[{"query": "case", "count": 2, "relevance_criteria": "Best fit for my project"}],
        provider_clients={"printables": OrderedProvider()},
    )

    assert [item["provider_item_id"] for item in response.results[0]["results"]] == ["0", "1"]


# contract-test: direct surface=rest_api assertions=app-skills.search-relevance.optional-and-inferred
@pytest.mark.asyncio
async def test_models3d_search_rejects_overlong_relevance_criteria() -> None:
    response = await _skill().execute(
        requests=[{"query": "case", "relevance_criteria": "x" * 1001}],
        provider_clients={"printables": FakeProvider()},
    )

    assert response.success is False
    assert response.error_code == "invalid_request"
    assert response.error == "relevance_criteria must be at most 1000 characters"


# contract-test: direct surface=rest_api assertions=app-skills.execution.registered-validated
@pytest.mark.asyncio
async def test_models3d_search_rejects_removed_provider_names() -> None:
    response = await _skill().execute(
        requests=[{"query": "benchy", "providers": ["Thingiverse"]}],
        provider_clients={"printables": FakeProvider()},
    )
    payload = response.model_dump()

    assert payload["success"] is False
    assert payload["error_code"] == "invalid_request"
    assert payload["error"] == "Unsupported 3D model search provider: Thingiverse"


# contract-test: supporting surface=rest_api assertions=app-skills.execution.registered-validated,app-skills.surface.semantic-parity
@pytest.mark.asyncio
async def test_models3d_search_returns_typed_error_when_all_providers_fail() -> None:
    class FailingProvider:
        provider_name = "Printables"

        async def search(self, query: str, *, count: int) -> list[Model3DProviderResult]:
            raise Model3DProviderError("Printables", "provider_unavailable", "Printables unavailable")

    response = await _skill().execute(
        requests=[{"query": "benchy", "providers": ["Printables"]}],
        provider_clients={"printables": FailingProvider()},
    )
    payload = response.model_dump()

    assert payload["success"] is False
    assert payload["error"] == "No 3D model search providers returned results"
    assert payload["error_code"] == "all_providers_failed"


# contract-test: direct surface=rest_api assertions=app-skills.execution.registered-validated,app-skills.search-relevance.optional-and-inferred,app-skills.surface.semantic-parity
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
    search_skill = next(skill for skill in app_yml["skills"] if skill["id"] == "search")
    providers = search_skill["tool_schema"]["properties"]["requests"]["items"]["properties"]["providers"]["items"]["enum"]
    assert search_skill["providers"] == [{"name": "Printables", "no_api_key": True}]
    assert providers == ["Printables"]
    request_properties = search_skill["tool_schema"]["properties"]["requests"]["items"]["properties"]
    assert request_properties["count"]["default"] == 10
    assert request_properties["count"]["maximum"] == 20
    assert request_properties["relevance_criteria"]["maxLength"] == 1000
    guidance = " ".join(
        (
            search_skill["preprocessor_hint"],
            request_properties["relevance_criteria"]["description"],
        )
    )
    assert "material" in guidance
    assert "never invent" in guidance
