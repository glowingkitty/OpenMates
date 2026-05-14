# backend/tests/test_embed_service_composite.py
#
# Unit tests for composite app-skill embed detection in EmbedService.
# Composite skills create a parent app_skill_use embed plus child embeds.
# This must be driven by app.yml child_type metadata, not a hardcoded skill
# allowlist, so new search-style skills get working child embed links.

import asyncio

import pytest

try:
    from backend.core.api.app.services.embed_service import EmbedService
except ImportError as _exc:
    pytestmark = pytest.mark.skip(reason=f"Backend dependencies not installed: {_exc}")


class _EmptyMetadataCache:
    async def get_discovered_apps_metadata(self):
        return None


def _run(coro):
    return asyncio.run(coro)


def test_composite_child_type_returns_repo_for_code_search_repos(monkeypatch):
    async def fake_child_type(*args, **kwargs):
        return "repo"

    monkeypatch.setattr(EmbedService, "get_child_embed_type", fake_child_type)

    child_type = _run(EmbedService.get_composite_child_embed_type("code", "search_repos"))

    assert child_type == "repo"


def test_composite_child_type_returns_none_for_non_composite(monkeypatch):
    async def fake_child_type(*args, **kwargs):
        raise ValueError("not composite")

    monkeypatch.setattr(EmbedService, "get_child_embed_type", fake_child_type)

    child_type = _run(EmbedService.get_composite_child_embed_type("code", "get_docs"))

    assert child_type is None


def test_code_search_repos_has_cold_start_child_type_fallback():
    assert EmbedService._CHILD_EMBED_TYPE_FALLBACK[("code", "search_repos")] == "repo"


def test_get_child_embed_type_uses_code_search_repos_fallback_when_cache_empty():
    child_type = _run(EmbedService.get_child_embed_type(
        "code",
        "search_repos",
        cache_service=_EmptyMetadataCache(),
    ))

    assert child_type == "repo"


def test_web_search_github_repo_result_uses_repo_child_type():
    child_type = EmbedService._get_per_result_child_type(
        "website",
        {"url": "https://github.com/openmates/example"},
        "web",
        "search",
    )

    assert child_type == "repo"


def test_non_repo_github_url_stays_website_child_type():
    child_type = EmbedService._get_per_result_child_type(
        "website",
        {"url": "https://github.com/openmates/example/issues"},
        "web",
        "search",
    )

    assert child_type == "website"


def test_repo_enrichment_preserves_web_search_snippets(monkeypatch):
    async def fake_build_github_repo_embed(url):
        assert url == "https://github.com/openmates/example"
        return {
            "url": "https://github.com/openmates/example",
            "full_name": "openmates/example",
            "name": "example",
            "description": "Repository API description",
            "license_spdx_id": "MIT",
            "stars": 42,
        }

    monkeypatch.setattr(
        "backend.core.api.app.services.embed_service.build_github_repo_embed",
        fake_build_github_repo_embed,
    )

    child_type, enriched = _run(EmbedService._enrich_repo_result_if_needed(
        "repo",
        {
            "url": "https://github.com/openmates/example",
            "title": "OpenMates example on GitHub",
            "description": "Web search snippet description",
            "extra_snippets": ["First snippet", "Second snippet"],
            "page_age": "2 weeks ago",
        },
    ))

    assert child_type == "repo"
    assert enriched["full_name"] == "openmates/example"
    assert enriched["description"] == "Repository API description"
    assert enriched["web_search_title"] == "OpenMates example on GitHub"
    assert enriched["web_search_description"] == "Web search snippet description"
    assert enriched["web_search_extra_snippets"] == ["First snippet", "Second snippet"]
    assert enriched["web_search_page_age"] == "2 weeks ago"


def test_repo_enrichment_falls_back_to_website_when_github_metadata_missing(monkeypatch):
    async def fake_build_github_repo_embed(_url):
        return None

    monkeypatch.setattr(
        "backend.core.api.app.services.embed_service.build_github_repo_embed",
        fake_build_github_repo_embed,
    )

    child_type, enriched = _run(EmbedService._enrich_repo_result_if_needed(
        "repo",
        {"url": "https://github.com/openmates/example", "description": "Search snippet"},
    ))

    assert child_type == "website"
    assert enriched == {"url": "https://github.com/openmates/example", "description": "Search snippet"}
