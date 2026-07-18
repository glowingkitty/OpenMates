# backend/tests/test_design_search_icons_skill.py
#
# Contract tests for the Design app icon search skill.
# The skill is read-only and returns metadata-only parent/child embed payloads;
# SVG markup is fetched later through the OpenMates API route. Provider calls are
# faked here so failures remain deterministic and cheap.

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from backend.apps.design.skills.search_icons_skill import SearchIconsSkill
from backend.shared.providers.iconify.client import IconifyIconResult, IconifyProviderError

REPO_ROOT = Path(__file__).resolve().parents[2]


def _skill() -> SearchIconsSkill:
    return SearchIconsSkill(
        app=None,
        app_id="design",
        skill_id="search_icons",
        skill_name="Search icons",
        skill_description="Find free SVG icons for product design.",
    )


class FakeIconifyProvider:
    provider_name = "Iconify"

    def __init__(self, results: list[IconifyIconResult] | None = None) -> None:
        self.results = results if results is not None else [_icon()]
        self.calls: list[dict[str, Any]] = []

    async def search_icons(
        self,
        query: str,
        *,
        count: int,
        license_policy: str,
        include_prefixes: list[str] | None = None,
        exclude_prefixes: list[str] | None = None,
    ) -> list[IconifyIconResult]:
        self.calls.append(
            {
                "query": query,
                "count": count,
                "license_policy": license_policy,
                "include_prefixes": include_prefixes,
                "exclude_prefixes": exclude_prefixes,
            }
        )
        return self.results


def _icon(**overrides: Any) -> IconifyIconResult:
    data = {
        "icon_id": "lucide:home",
        "prefix": "lucide",
        "name": "home",
        "display_name": "Home",
        "collection_name": "Lucide",
        "collection_category": "general",
        "license_title": "ISC",
        "license_spdx": "ISC",
        "license_url": "https://lucide.dev/license",
        "author_name": "Lucide Contributors",
        "author_url": "https://lucide.dev",
        "width": 24,
        "height": 24,
        "palette": False,
        "svg_path": "/v1/apps/design/icons/iconify/lucide/home.svg",
        "tags": ["house", "navigation"],
    }
    data.update(overrides)
    return IconifyIconResult(**data)


@pytest.mark.asyncio
async def test_design_search_icons_returns_metadata_only_child_results() -> None:
    provider = FakeIconifyProvider()

    response = await _skill().execute(
        requests=[{"id": "r1", "query": "home", "count": 12}],
        provider_client=provider,
    )
    payload = response.model_dump()

    assert payload["success"] is True
    assert payload["app_id"] == "design"
    assert payload["skill_id"] == "search_icons"
    assert payload["provider"] == "Iconify"
    assert payload["result_count"] == 1
    assert provider.calls == [
        {
            "query": "home",
            "count": 12,
            "license_policy": "permissive",
            "include_prefixes": None,
            "exclude_prefixes": None,
        }
    ]
    group = payload["results"][0]
    assert group["id"] == "r1"
    assert group["query"] == "home"
    assert group["license_policy"] == "permissive"
    child = group["results"][0]
    assert child["type"] == "icon_result"
    assert child["parent_app_skill_type"] == "app_skill_use"
    assert child["icon_id"] == "lucide:home"
    assert child["svg_path"] == "/v1/apps/design/icons/iconify/lucide/home.svg"
    assert "svg" not in child
    assert "svg_markup" not in child
    assert "png" not in child
    assert "preview_server_url" not in child


@pytest.mark.asyncio
async def test_design_search_icons_rejects_invalid_requests() -> None:
    blank_response = await _skill().execute(requests=[{"query": "   "}], provider_client=FakeIconifyProvider())
    bad_license_response = await _skill().execute(
        requests=[{"query": "home", "license_policy": "copyleft"}],
        provider_client=FakeIconifyProvider(),
    )
    bad_prefix_response = await _skill().execute(
        requests=[{"query": "home", "include_prefixes": ["bad/prefix"]}],
        provider_client=FakeIconifyProvider(),
    )

    assert blank_response.success is False
    assert blank_response.error_code == "invalid_request"
    assert bad_license_response.success is False
    assert bad_license_response.error_code == "invalid_request"
    assert bad_prefix_response.success is False
    assert bad_prefix_response.error_code == "invalid_request"


@pytest.mark.asyncio
async def test_design_search_icons_distinguishes_no_results_from_provider_failure() -> None:
    empty_response = await _skill().execute(
        requests=[{"query": "zzzz-no-icons", "count": 5}],
        provider_client=FakeIconifyProvider(results=[]),
    )

    class FailingProvider(FakeIconifyProvider):
        async def search_icons(self, *args: Any, **kwargs: Any) -> list[IconifyIconResult]:
            raise IconifyProviderError("Iconify", "provider_unavailable", "Iconify unavailable")

    failure_response = await _skill().execute(
        requests=[{"query": "home", "count": 5}],
        provider_client=FailingProvider(),
    )

    assert empty_response.success is True
    assert empty_response.result_count == 0
    assert empty_response.results[0]["empty_reason"] == "no_results"
    assert failure_response.success is False
    assert failure_response.error_code == "provider_unavailable"
    assert "Iconify unavailable" in (failure_response.error or "")


def test_design_app_metadata_declares_search_icons_and_child_embed_contract() -> None:
    app_yml = yaml.safe_load((REPO_ROOT / "backend/apps/design/app.yml").read_text())
    search_embed = next(embed for embed in app_yml["embed_types"] if embed["id"] == "search_icons")
    child_embed = next(embed for embed in app_yml["embed_types"] if embed["id"] == "icon_result")
    search_skill = next(skill for skill in app_yml["skills"] if skill["id"] == "search_icons")

    assert app_yml["expose_in_api"] is True
    assert search_embed["category"] == "app-skill-use"
    assert search_embed["skill_id"] == "search_icons"
    assert search_embed["has_children"] is True
    assert search_embed["child_type"] == "icon_result"
    assert child_embed["category"] == "direct"
    assert child_embed["frontend_type"] == "design-icon-result"
    assert search_skill["providers"] == [{"name": "Iconify", "no_api_key": True}]
    request_schema = search_skill["tool_schema"]["properties"]["requests"]["items"]["properties"]
    assert request_schema["license_policy"]["enum"] == ["permissive", "all"]


def test_design_app_metadata_forbids_svg_payload_fields() -> None:
    app_yml = yaml.safe_load((REPO_ROOT / "backend/apps/design/app.yml").read_text())
    child_embed = next(embed for embed in app_yml["embed_types"] if embed["id"] == "icon_result")
    field_names = {field["name"] for field in child_embed["content_fields"]}

    assert "svg_path" in field_names
    assert "icon_id" in field_names
    assert "svg" not in field_names
    assert "svg_markup" not in field_names
    assert "png" not in field_names
    assert "preview_server_url" not in field_names
