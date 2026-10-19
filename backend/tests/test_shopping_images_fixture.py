"""Signed synthetic gallery replay must stay scoped and call real skill code."""
# contract-test-file: infrastructure
import json
from pathlib import Path

import pytest

from backend.apps.ai.processing.jev_preprocessing import (
    decide_app_and_project_routing_with_jev, decide_preprocessing_with_jev,
)
from backend.apps.ai.testing.caching_llm_wrapper import wrap_provider_with_cache
from backend.apps.ai.testing.shopping_images_fixture import GROUP, PROMPT, active, llm_fixture
from backend.shared.providers.typesafe import budget as jev_budget
from backend.shared.testing.api_response_cache import ApiResponseCache
from backend.shared.testing.mock_context import mock_group_var, mock_mode_var


@pytest.fixture
def shopping_replay(monkeypatch):
    jev_budget._encodings()
    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
    monkeypatch.setenv("MOCK_EXTERNAL_APIS", "true")
    mode = mock_mode_var.set("mock")
    group = mock_group_var.set(GROUP)
    try:
        yield
    finally:
        mock_group_var.reset(group)
        mock_mode_var.reset(mode)


@pytest.mark.asyncio
async def test_gallery_replay_selects_only_shopping_through_real_jev_questions(shopping_replay):
    history = [{"role": "user", "content": PROMPT}]
    routing = await decide_app_and_project_routing_with_jev(
        model_id="typesafe/jev-1.13", secrets_manager=None, message_history=history,
        available_apps=["shopping", "web"], available_skills=[], available_focus_modes=[],
        topic_areas=["general_misc"], is_first_message=True,
    )
    assert routing["selected_app_ids"] == ["shopping"]
    result = await decide_preprocessing_with_jev(
        model_id="typesafe/jev-1.13", secrets_manager=None, message_history=history,
        topic_areas=["general_misc"], available_skills=["shopping-search_products"],
        available_focus_modes=[], available_settings_and_memories={}, recent_skill_activity=[],
        conversation_summary=None, previous_category=None, is_first_message=True,
        available_apps=["shopping", "web"], selected_app_ids=routing["selected_app_ids"],
        early_decisions=routing["early_decisions"],
    )
    assert result["relevant_app_skills"] == ["shopping-search_products"]


@pytest.mark.asyncio
async def test_gallery_replay_emits_a_tool_call_without_replacing_its_result(shopping_replay, tmp_path):
    async def forbidden(**kwargs):
        raise AssertionError("Synthetic replay must not contact a provider")

    wrapped = wrap_provider_with_cache(forbidden, ApiResponseCache(root=tmp_path))
    stream = await wrapped(model="gemini-3.5-flash-lite", stream=True,
                           messages=[{"role": "user", "content": PROMPT}],
                           tools=[{"function": {"name": "shopping-search_products"}}])
    calls = [chunk async for chunk in stream]
    assert len(calls) == 1
    assert calls[0].function_name == "shopping-search_products"
    assert calls[0].function_arguments_parsed == {
        "requests": [{"query": "bio joghurt", "provider": "REWE", "max_results": 1}]}
    fixture_root = Path(__file__).parents[1] / "apps/ai/testing/api_cache" / GROUP / "rewe"
    [fixture_path] = fixture_root.glob("*.json")
    fixture = json.loads(fixture_path.read_text())
    assert fixture["fingerprint"] == ApiResponseCache().fingerprint_http_request("GET", fixture["request"]["url"])
    raw = fixture["response"]["body"]["_embedded"]["products"][0]
    photos = [item["_links"]["self"]["href"] for item in raw["media"]["images"]]
    assert len(photos) == 5 and len(set(photos)) == 3
    assert "image_urls" not in raw  # The real provider parser must create it.


@pytest.mark.parametrize("environment,mode,group", [
    ("production", "mock", GROUP), ("development", "real", GROUP),
    ("development", "record", GROUP), ("development", "mock", "unrelated"),
])
def test_gallery_fixture_rejects_other_contexts(monkeypatch, environment, mode, group):
    monkeypatch.setenv("MOCK_EXTERNAL_APIS", "true")
    monkeypatch.setenv("SERVER_ENVIRONMENT", environment)
    mode_token, group_token = mock_mode_var.set(mode), mock_group_var.set(group)
    try:
        assert not active()
        assert llm_fixture("llm/gemini-3.5-flash-lite", {"messages": [{"role": "user", "content": PROMPT}]}) is None
    finally:
        mock_group_var.reset(group_token)
        mock_mode_var.reset(mode_token)


def test_gallery_replay_rejects_unrecognized_prompt(shopping_replay):
    assert llm_fixture("llm/gemini-3.5-flash-lite", {
        "model": "gemini-3.5-flash-lite", "messages": [{"role": "user", "content": "Another request"}],
    }) is None
