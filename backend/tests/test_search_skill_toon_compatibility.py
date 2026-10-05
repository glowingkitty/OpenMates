"""Exercise search sanitization with the real pinned TOON codec, without providers."""

import importlib
from unittest.mock import AsyncMock

import pytest
import toon_format

from backend.tests.runtime_import_stubs import install_code_route_import_stubs

install_code_route_import_stubs()


@pytest.mark.asyncio
@pytest.mark.parametrize("app_id", ["news", "videos"])
@pytest.mark.parametrize("lenient", [False, True])
# contract-test: supporting surface=rest_api assertions=web-search.response.sanitized,app-skills.search-relevance.safe-finalization
async def test_search_decodes_sanitized_toon_with_real_codec(monkeypatch, app_id, lenient):
    assert getattr(toon_format, "__file__", None), "This regression requires the real TOON package"
    module = importlib.import_module(f"backend.apps.{app_id}.skills.search_skill")
    url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ" if app_id == "videos" else "https://news.example/story"
    provider = AsyncMock(return_value={"results": [{
        "title": "Original title", "description": "Original description", "url": url,
        "extra_snippets": ["Original snippet"],
    }], "sanitize_output": True})
    monkeypatch.setattr(module, f"search_{app_id}", provider)
    monkeypatch.setattr(module, "check_rate_limit", AsyncMock(return_value=(True, None)))
    if app_id == "videos":
        monkeypatch.setattr(module, "get_video_metadata_batched", AsyncMock(return_value={}))

    async def sanitize(*, content, **_kwargs):
        sanitized = content.replace("Original title", "Sanitized title")
        # A mismatched row count exercises the existing strict-to-lenient path.
        return sanitized.replace("[1]", "[2]", 1) if lenient else sanitized

    monkeypatch.setattr(module, "sanitize_external_content", sanitize)
    skill = module.SearchSkill(app=None, app_id=app_id, skill_id="search",
                               skill_name="Search", skill_description="Test search")
    request_id, results, error = await skill._process_single_search_request(
        {"query": "codec compatibility", "count": 1, "filter_tabloids": False},
        "codec-test", None, None,
    )
    assert request_id == "codec-test"
    assert error is None
    assert len(results) == 1
    assert results[0]["title"] == "Sanitized title"
    assert results[0]["description"] == "Original description"
    assert results[0]["url"] == url
    provider.assert_awaited_once()
