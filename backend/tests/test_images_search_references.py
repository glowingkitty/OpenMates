"""Unsupported reverse-image input never resolves, decrypts or uploads user media."""

# contract-test-file: infrastructure
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.apps.images.skills import search_skill


@pytest.mark.asyncio
@pytest.mark.parametrize("file_path", ["photo.png", "", "generated.png", "https://images.example/photo.jpg"])
@pytest.mark.parametrize("query", [None, "similar pictures"])
async def test_reverse_input_is_rejected_before_any_image_or_text_operation(monkeypatch, file_path, query):
    skill = object.__new__(search_skill.SearchSkill)
    forbidden = AsyncMock(side_effect=AssertionError("No reverse-input operations are permitted"))
    monkeypatch.setattr(skill, "_text_search", forbidden)
    monkeypatch.setattr(skill, "_get_or_create_secrets_manager", forbidden)
    monkeypatch.setattr(search_skill, "sanitize_long_text_fields_in_payload", forbidden)
    result = await skill.execute(
        search_skill.SearchRequest(requests=[search_skill.ImageSearchRequestItem(
            file_path=file_path, query=query,
        )]),
        cache_service=SimpleNamespace(get_embed_from_cache=forbidden),
        encryption_service=SimpleNamespace(decrypt_with_user_key=forbidden),
        s3_service=SimpleNamespace(get_file=forbidden),
        internal_api_request=forbidden,
    )
    assert result.results == [{"id": 1, "results": []}]
    assert "Reverse image search is unavailable" in result.error
    forbidden.assert_not_called()
    assert not hasattr(skill, "_resolve_image_input")
    assert not hasattr(skill, "_upload_temp_image")
    assert not hasattr(skill, "_reverse_image_search")


@pytest.mark.asyncio
async def test_text_search_preserves_results_hashes_and_sanitization(monkeypatch):
    skill = object.__new__(search_skill.SearchSkill)
    row = {"type": "image_result", "title": "Public image", "image_url": "https://images.example/public.jpg"}
    text_search = AsyncMock(return_value=([row], "Brave Search"))
    sanitizer = AsyncMock(side_effect=lambda **kwargs: kwargs["payload"])
    monkeypatch.setattr(skill, "_text_search", text_search)
    monkeypatch.setattr(search_skill, "sanitize_long_text_fields_in_payload", sanitizer)
    result = await skill._process_single_request(
        req={"query": "public image", "count": 3, "country": "de", "search_lang": "de"},
        request_id="text", secrets_manager=object(),
    )
    assert result[0] == "text" and result[2:] == ("Brave Search", None)
    assert result[1][0]["image_url"] == row["image_url"]
    assert result[1][0]["hash"]
    text_search.assert_awaited_once()
    assert text_search.await_args.kwargs["country"] == "de"
    assert text_search.await_args.kwargs["count"] == 3
    sanitizer.assert_awaited_once()
