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
