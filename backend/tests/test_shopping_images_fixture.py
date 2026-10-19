"""Signed synthetic gallery replay must stay scoped and call real skill code."""
# contract-test-file: infrastructure
import json
from pathlib import Path

import pytest

from backend.apps.ai.processing.jev_preprocessing import (
    decide_app_and_project_routing_with_jev, decide_preprocessing_with_jev,
)
from backend.apps.ai.testing.caching_llm_wrapper import wrap_provider_with_cache
from backend.apps.ai.testing.shopping_images_fixture import (
    GROUP, PROMPT, active, llm_fixture, REFERENCE_ERROR_PROMPT, REFERENCE_ERROR_ID,
    REFERENCE_ERROR_MESSAGE, REFERENCE_ERROR_RESPONSE, MISSING_ERROR_METADATA_RESPONSE,
)
from toon_format import decode, encode
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


def test_reference_failure_replay_dispatches_a_real_unowned_image_lookup(shopping_replay):
    response = llm_fixture("llm/gemini-3.5-flash-lite", {
        "model": "gemini-3.5-flash-lite", "stream": True,
        "messages": [{"role": "user", "content": REFERENCE_ERROR_PROMPT}],
        "tools": [{"function": {"name": "shopping-search_products"}}],
    })
    [call] = response["response"]["chunks"]
    assert call["value"]["function_name"] == "shopping-search_products"
    [request] = call["value"]["function_arguments_parsed"]["requests"]
    assert request["id"] == REFERENCE_ERROR_ID
    assert request["reference_images"] == ["00000000-0000-4000-8000-000000000001"]


@pytest.mark.parametrize("encoding", [json.dumps, encode], ids=["json", "toon"])
@pytest.mark.parametrize("invalid", [None, "missing-errors", "missing-notice", "wrong-request", "missing-reference-explanation", "boolean-request", "multiple-errors"])
def test_reference_failure_answer_depends_on_actual_server_error_metadata(shopping_replay, encoding, invalid):
    payload = {
        "results": [], "count": 0,
        "request_errors": [{"request_id": REFERENCE_ERROR_ID, "message": REFERENCE_ERROR_MESSAGE}],
        "failure_notice": "Failed requests are not evidence of no matching products. Do not invent a catalogue explanation.",
    }
    if invalid == "missing-errors":
        payload.pop("request_errors")
    elif invalid == "missing-notice":
        payload.pop("failure_notice")
    elif invalid == "wrong-request":
        payload["request_errors"][0]["request_id"] = "different-request"
    elif invalid == "missing-reference-explanation":
        payload["request_errors"][0]["message"] = "The shopping request could not be completed."
    elif invalid == "boolean-request":
        payload["request_errors"][0]["request_id"] = True
    elif invalid == "multiple-errors":
        payload["request_errors"].append({"request_id": "another", "message": REFERENCE_ERROR_MESSAGE})
    result = llm_fixture("llm/gemini-3.5-flash-lite", {
        "model": "gemini-3.5-flash-lite", "stream": True,
        "messages": [{"role": "user", "content": REFERENCE_ERROR_PROMPT},
                     {"role": "tool", "content": encoding(payload)}],
    })
    [chunk] = result["response"]["chunks"]
    assert chunk["value"] == (REFERENCE_ERROR_RESPONSE if invalid is None else MISSING_ERROR_METADATA_RESPONSE)


@pytest.mark.parametrize("request_id", [1, "1"])
def test_reference_failure_accepts_the_authoritative_single_request_placeholder_id(shopping_replay, request_id):
    payload = {"results": [], "count": 0,
               "request_errors": [{"request_id": request_id, "message": REFERENCE_ERROR_MESSAGE}],
               "failure_notice": "Failed requests are not evidence of no matching products."}
    response = llm_fixture("llm/gemini-3.5-flash-lite", {
        "model": "gemini-3.5-flash-lite", "stream": True,
        "messages": [{"role": "user", "content": REFERENCE_ERROR_PROMPT},
                     {"role": "tool", "content": encode(payload)}],
    })
    assert response["response"]["chunks"][0]["value"] == REFERENCE_ERROR_RESPONSE


@pytest.mark.parametrize("tool_name", ["shopping-search-products", "shopping-search_products", "shopping.search_products"])
@pytest.mark.parametrize("encoding", [encode, json.dumps], ids=["toon", "json"])
def test_reference_failure_survives_real_server_projection_and_provider_history_transform(
    shopping_replay, tool_name, encoding,
):
    # Require the real filter import so a lazy-import fallback cannot falsely
    # pass by skipping production history filtering altogether.
    from backend.apps.ai.processing.main_processor import _filter_skill_results_for_llm
    from backend.apps.ai.utils.app_skill_result_groups import shopping_result_parent_metadata, shopping_result_payload
    from backend.apps.ai.utils.llm_utils import _transform_message_history_for_llm
    from backend.apps.shopping.skills.search_products import SearchProductsResponse
    from backend.core.api.app.services.embed_service import _flatten_for_toon_tabular

    assert callable(_filter_skill_results_for_llm)
    metadata = shopping_result_parent_metadata([{
        "id": 1, "results": [], "error": "Reference image is unavailable to this caller",
    }])
    payload = shopping_result_payload([], _flatten_for_toon_tabular(metadata))
    history = [{"role": "user", "content": REFERENCE_ERROR_PROMPT}, {
        "role": "tool", "tool_call_id": "shopping-gallery-fixture", "name": tool_name,
        "content": encoding(payload),
        "ignore_fields_for_inference": SearchProductsResponse().ignore_fields_for_inference,
    }]

    transformed = _transform_message_history_for_llm(history)
    tool_payload = decode(transformed[-1]["content"])
    assert tool_payload["request_errors"] == payload["request_errors"]
    assert tool_payload["failure_notice"] == payload["failure_notice"]
    response = llm_fixture("llm/gemini-3.5-flash-lite", {
        "model": "gemini-3.5-flash-lite", "stream": True, "messages": transformed,
    })
    assert response["response"]["chunks"][0]["value"] == REFERENCE_ERROR_RESPONSE
