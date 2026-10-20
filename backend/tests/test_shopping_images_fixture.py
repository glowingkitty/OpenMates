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
    fixture_path = fixture_root / "d3b67e02aea54956.json"
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


# contract-test: supporting surface=rest_api assertions=shopping-search.relevance.visual-and-text,shopping-search.relevance.truthful-fallback
@pytest.mark.asyncio
@pytest.mark.parametrize("encoding", [json.dumps, encode], ids=["json", "toon"])
async def test_grounded_answer_reads_actual_visual_helper_parent_and_provider_history(shopping_replay, monkeypatch, encoding):
    from backend.apps.shopping import visual_ranking as visual
    from backend.apps.shopping.skills.search_products import SearchProductsResponse
    from backend.apps.ai.processing.main_processor import _filter_skill_results_for_llm
    from backend.apps.ai.utils.app_skill_result_groups import shopping_result_parent_metadata, shopping_result_payload
    from backend.apps.ai.utils.llm_utils import _transform_message_history_for_llm
    from backend.apps.ai.testing.shopping_images_fixture import GROUNDING_PROMPT, GROUNDING_RESPONSE
    from backend.core.api.app.services.embed_service import _flatten_for_toon_tabular
    from backend.shared.providers.typesafe.models import DecisionResponse

    async def download(_url):
        return b"provider-free prepared image bytes"

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def evaluate_with_images(self, *, state, questions, images):
            assert len(state["reference_photos"]) == 1 and len(images) == 3
            assert all("composition" not in row["data"] for row in state["candidates"])
            return DecisionResponse(model="jev-1.13.0", answers={
                key: {"type": "score", "score": score,
                      "legend": {"0": "conflict", "4": "exceptional"},
                      "probabilities": {"0": .1, "4": .9}, "confidence": .8}
                for key, score in zip(questions, [3.24, 1.0])
            })

    monkeypatch.setattr(visual, "download_public_product_image", download)
    monkeypatch.setattr(visual, "JevDecisionClient", FakeClient)
    ranked = await visual.rank_products_visually(
        candidates=[{"title": "Cotton floral fabric", "image_url": "https://example.org/floral.png"},
                    {"title": "Striped fabric", "image_url": "https://example.org/stripes.png"}],
        reference_images=[b"provider-free prepared reference"], relevance_criteria="flowers",
        query="cotton fabric", secrets_manager=None,
    )
    assert callable(_filter_skill_results_for_llm)
    metadata = shopping_result_parent_metadata([{"id": 1, "results": ranked.candidates, "visual_evaluation": ranked.summary}])
    payload = shopping_result_payload(ranked.candidates, _flatten_for_toon_tabular(metadata))
    history = _transform_message_history_for_llm([
        {"role": "user", "content": GROUNDING_PROMPT},
        {"role": "tool", "name": "shopping-search_products", "tool_call_id": "shopping-gallery-fixture",
         "content": encoding(payload), "ignore_fields_for_inference": SearchProductsResponse().ignore_fields_for_inference},
    ])
    wire = decode(history[-1]["content"])
    summary = wire["visual_evaluations"][0]["visual_evaluation"]
    assert summary["evaluated_count"] == 2 and summary["unavailable_count"] == 0
    assert summary["filtered_count"] == 1 and summary["score_max"] == 4
    assert wire["results"][0]["visual_match"]["score"] == 3.24
    assert "image_url" not in wire["results"][0]
    assert "composition" not in wire["results"][0]
    response = llm_fixture("llm/gemini-3.8-flash", {
        "model": "gemini-3.8-flash", "stream": True, "messages": history,
    })
    assert response["response"]["chunks"][0]["value"] == GROUNDING_RESPONSE
    assert "missing images" not in GROUNDING_RESPONSE.lower()

    # Deleting any authoritative field must invalidate the answer instead of
    # inventing a denominator, percentages or an image-availability explanation.
    from copy import deepcopy
    from backend.apps.ai.testing.shopping_images_fixture import MISSING_GROUNDING_METADATA_RESPONSE
    for field in ["grounding_notice", "score_max", "evaluated_count", "unavailable_count"]:
        damaged = deepcopy(wire)
        if field == "grounding_notice":
            damaged.pop(field)
        else:
            damaged["visual_evaluations"][0]["visual_evaluation"].pop(field)
        damaged_history = [history[0], {**history[-1], "content": encoding(damaged)}]
        response = llm_fixture("llm/gemini-3.8-flash", {
            "model": "gemini-3.8-flash", "stream": True, "messages": damaged_history,
        })
        assert response["response"]["chunks"][0]["value"] == MISSING_GROUNDING_METADATA_RESPONSE


# contract-test: supporting surface=rest_api assertions=shopping-search.products.supplied-gallery,shopping-search.relevance.truthful-fallback
@pytest.mark.parametrize("encoding", [json.dumps, encode], ids=["json", "toon"])
def test_gallery_answer_requires_real_parser_facts_and_server_grounding_notice(shopping_replay, encoding):
    from backend.apps.shopping.providers.rewe_provider import _parse_product
    from backend.apps.shopping.skills.search_products import SearchProductsResponse
    from backend.apps.ai.utils.app_skill_result_groups import shopping_result_parent_metadata, shopping_result_payload
    from backend.apps.ai.utils.llm_utils import _transform_message_history_for_llm
    from backend.apps.ai.testing.shopping_images_fixture import GALLERY_RESPONSE, MISSING_GALLERY_GROUNDING_RESPONSE
    from backend.core.api.app.services.embed_service import _flatten_for_toon_tabular

    fixture_root = Path(__file__).parents[1] / "apps/ai/testing/api_cache" / GROUP / "rewe"
    fixture_path = fixture_root / "d3b67e02aea54956.json"
    raw = json.loads(fixture_path.read_text())["response"]["body"]["_embedded"]["products"][0]
    product = _parse_product(raw, 1).to_result_dict()
    metadata = shopping_result_parent_metadata([{"id": 1, "results": [product]}])
    payload = shopping_result_payload([product], _flatten_for_toon_tabular(metadata))
    history = _transform_message_history_for_llm([
        {"role": "user", "content": PROMPT},
        {"role": "tool", "name": "shopping-search_products", "tool_call_id": "shopping-gallery-fixture",
         "content": encoding(payload), "ignore_fields_for_inference": SearchProductsResponse().ignore_fields_for_inference},
    ])
    arguments = {"model": "gemini-3.8-flash", "stream": True, "messages": history}
    result = llm_fixture("llm/gemini-3.8-flash", arguments)
    assert result["response"]["chunks"][0]["value"] == GALLERY_RESPONSE
    decoded = decode(history[-1]["content"])
    decoded.pop("grounding_notice")
    arguments["messages"] = [history[0], {**history[-1], "content": encoding(decoded)}]
    result = llm_fixture("llm/gemini-3.8-flash", arguments)
    assert result["response"]["chunks"][0]["value"] == MISSING_GALLERY_GROUNDING_RESPONSE


# contract-test: supporting surface=rest_api assertions=shopping-search.relevance.bounded,app-skills.search-relevance.safe-finalization
@pytest.mark.asyncio
async def test_forty_replay_runs_real_provider_ranking_and_final_limit(shopping_replay):
    from backend.apps.ai.testing.shopping_images_fixture import FORTY_PROMPT, FORTY_RESPONSE
    from backend.apps.shopping.skills.search_products import SearchProductsSkill
    from backend.apps.ai.utils.app_skill_result_groups import shopping_result_parent_metadata, shopping_result_payload
    response = llm_fixture("llm/gemini-fixture", {
        "model": "gemini-fixture", "stream": True,
        "messages": [{"role": "user", "content": FORTY_PROMPT}],
        "tools": [{"function": {"name": "shopping-search_products"}}],
    })
    [request] = response["response"]["chunks"][0]["value"]["function_arguments_parsed"]["requests"]
    # The signed replay's cached HTTP transport returns forty raw products and
    # the real Jev ranking fixture scores the late candidate through real batching.
    _, rows, error = await object.__new__(SearchProductsSkill)._process_single_request(
        request, "forty", secrets_manager=None)
    assert error is None and len(rows) == 3
    assert rows[0]["product_id"] == "forty-039"
    payload = shopping_result_payload(rows, shopping_result_parent_metadata([{"id": 1, "results": rows}]))
    answer = llm_fixture("llm/gemini-fixture", {
        "model": "gemini-fixture", "stream": True,
        "messages": [{"role": "user", "content": FORTY_PROMPT}, {"role": "tool", "content": encode(payload)}],
    })
    assert answer["response"]["chunks"][0]["value"] == FORTY_RESPONSE
