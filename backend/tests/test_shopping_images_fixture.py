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
    DIRECT_REFERENCE_PROMPT, DIRECT_REFERENCE_QUERY, DIRECT_REFERENCE_IMAGE,
    DIRECT_REFERENCE_RESPONSE,
    DIRECT_SEARCH_PROMPT, LENS_FIXTURE_KEY, synthetic_http_response,
    _direct_image_references, _shopping_answer_policy,
)
from toon_format import decode, encode
from backend.shared.providers.typesafe import budget as jev_budget
from backend.shared.testing.api_response_cache import ApiResponseCache
from backend.shared.testing.mock_context import mock_group_var, mock_mode_var
from backend.apps.ai.utils.app_skill_result_groups import SHOPPING_GROUNDING_NOTICE


def _with_shopping_policy(messages):
    policy = _shopping_answer_policy()
    assert policy
    return [{"role": "system", "content": policy}, *messages]


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["initial", "post-tool", "recovery"])
@pytest.mark.parametrize("placement", ["system", "missing", "altered-system", "user-only"])
async def test_direct_shopping_provider_wire_requires_real_system_policy(shopping_replay, tmp_path, phase, placement):
    from backend.apps.ai.utils.app_skill_result_groups import shopping_result_parent_metadata, shopping_result_payload

    async def forbidden(**_kwargs):
        raise AssertionError("Signed fixture must not contact a model provider")

    policy = _shopping_answer_policy()
    user = f"{DIRECT_REFERENCE_PROMPT}\n[!](embed:sample.png)"
    messages = [{"role": "user", "content": user}]
    if placement == "system":
        messages.insert(0, {"role": "system", "content": policy})
    elif placement == "altered-system":
        messages.insert(0, {"role": "system", "content": policy.replace("brand", "seller", 1)})
    elif placement == "user-only":
        messages[0]["content"] += "\n" + policy
    if phase != "initial":
        row = {"title": "Synthetic direct reference product", "visual_match_status": "evaluated"}
        metadata = shopping_result_parent_metadata([{"id": 1, "results": [row], "visual_evaluation": {
            "status": "evaluated", "reference_count": 1, "evaluated_count": 1, "unavailable_count": 0}}])
        messages.append({"role": "tool", "content": encode(shopping_result_payload([row], metadata))})
        if phase == "recovery":
            messages.append({"role": "assistant", "content": "```toon\nstatus: finished\n```"})
    wrapped = wrap_provider_with_cache(forbidden, ApiResponseCache(root=tmp_path))
    stream = await wrapped(model="gemini-fixture", stream=True, messages=messages,
                           tools=[{"function": {"name": "shopping-search_products"}}])
    chunks = [chunk async for chunk in stream]
    if placement != "system":
        assert chunks == ["REGRESSION: Shopping answer policy is missing from the system message."]
    elif phase == "initial":
        assert len(chunks) == 1 and chunks[0].function_name == "shopping-search_products"
    else:
        assert chunks == [DIRECT_REFERENCE_RESPONSE]


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


@pytest.mark.parametrize("representation", ["markdown", "toon", "both", "duplicate-toon"])
def test_direct_reference_dispatch_preserves_exact_upload_without_view(shopping_replay, representation):
    reference = "sample-png-6e2a8e6e-85cf-4327-bcb1-47ca30b4d23b"
    markdown = f"[!](embed:{reference})"
    structured = "```toon\n" + encode({"type": "image", "app_id": "images",
        "skill_id": "upload", "embed_ref": reference, "filename": "sample.png"}) + "\n```"
    attachment = {"markdown": markdown, "toon": structured, "both": markdown + "\n" + structured,
                  "duplicate-toon": structured + "\n" + structured}[representation]
    result = llm_fixture("llm/synthetic-auto-model", {
        "model": "synthetic-auto-model", "stream": True,
        "messages": _with_shopping_policy([{"role": "user", "content": f"{DIRECT_REFERENCE_PROMPT}\n{attachment}"}]),
        "tools": [{"function": {"name": "shopping-search_products"}},
                  {"function": {"name": "images-view"}}],
    })
    chunks = result["response"]["chunks"]
    assert len(chunks) == 1
    assert chunks[0]["value"]["function_name"] == "shopping-search_products"
    request = chunks[0]["value"]["function_arguments_parsed"]["requests"][0]
    assert request["reference_images"] == [reference]
    assert request["query"] == DIRECT_REFERENCE_QUERY


@pytest.mark.parametrize("inline", [False, True])
@pytest.mark.parametrize("metadata", [
    {"type": "app_skill_use", "app_id": "images", "skill_id": "view", "embed_ref": "image.png"},
    {"type": "image", "app_id": "images", "skill_id": "upload", "embed_ref": 17},
    {"type": "image", "app_id": "images", "skill_id": "upload", "embed_ref": ["image.png"]},
    {"type": "image", "app_id": "images", "skill_id": "upload", "embed_ref": "https://example.invalid/image.png"},
    {"type": "image", "app_id": "images", "skill_id": "upload"},
    [{"type": "image", "embed_ref": "image.png"}],
])
def test_direct_reference_extraction_rejects_wrong_metadata_shapes(metadata, inline):
    content = "```toon\n" + encode(metadata) + "\n```"
    if inline:
        content = "Reference attachment: " + content + "Use this uploaded image."
    assert _direct_image_references(content) == []


@pytest.mark.parametrize("content", [
    "Please use image.png; embed_ref: image.png",
    "https://example.invalid/image.png",
    "[!](embed:https://example.invalid/image.png)",
    "```json\n[!](embed:image.png)\n```",
    "Reference attachment: ```json\n[!](embed:image.png)\n```Use this image.",
    "Reference attachment: ```toon\n[!](embed:image.png)",
    "```toon\ntype: image\napp_id: images\nskill_id: upload\nembed_ref[2]: first.png\n```",
    {"type": "image", "embed_ref": "image.png"},
])
def test_direct_reference_extraction_does_not_guess_references(content):
    assert _direct_image_references(content) == []


def test_direct_reference_extraction_preserves_canonical_filename_and_reference_order():
    metadata = {"type": "image", "app_id": "images", "skill_id": "upload", "embed_ref": "photo (2).png"}
    content = "```toon\n" + encode(metadata) + "\n```\n[!](embed:second.png)"
    assert _direct_image_references(content) == ["photo (2).png", "second.png"]


@pytest.mark.parametrize("prompt,tool", [(DIRECT_REFERENCE_PROMPT, "shopping-search_products"),
                                        (DIRECT_SEARCH_PROMPT, "images-search")])
@pytest.mark.parametrize("duplicate", [False, True])
def test_direct_dispatch_accepts_embed_service_inline_upload_metadata(shopping_replay, prompt, tool, duplicate):
    reference = "sample.png"
    metadata = {"type": "image", "app_id": "images", "skill_id": "upload", "status": "finished",
                "filename": "sample.png", "embed_ref": reference}
    # Match EmbedService's literal in-place replacement, without inventing
    # newlines between the caption/fence or the closing fence/user prompt.
    content = "Reference attachment: ```toon\n" + encode(metadata) + "\n```" + prompt
    if duplicate:
        content += f"\n[!](embed:{reference})"
    result = llm_fixture("llm/synthetic-auto-model", {
        "model": "synthetic-auto-model", "stream": True,
        "messages": _with_shopping_policy([{"role": "user", "content": content}]),
        "tools": [{"function": {"name": tool}}],
    })
    [chunk] = result["response"]["chunks"]
    assert chunk["value"]["function_name"] == tool
    [request] = chunk["value"]["function_arguments_parsed"]["requests"]
    assert (request.get("reference_images") if tool == "shopping-search_products"
            else [request.get("file_path")]) == [reference]


@pytest.mark.parametrize("prompt,tool", [(DIRECT_REFERENCE_PROMPT, "shopping-search_products"),
                                        (DIRECT_SEARCH_PROMPT, "images-search")])
def test_direct_reference_dispatch_still_requires_one_distinct_image(shopping_replay, prompt, tool):
    result = llm_fixture("llm/synthetic-auto-model", {
        "model": "synthetic-auto-model", "stream": True,
        "messages": _with_shopping_policy([{"role": "user", "content": f"{prompt}\n[!](embed:first.png)\n[!](embed:second.png)"}]),
        "tools": [{"function": {"name": tool}}],
    })
    [chunk] = result["response"]["chunks"]
    assert chunk == {"kind": "text", "value": "REGRESSION: expected one uploaded image reference."}


@pytest.mark.parametrize("valid", [True, False])
@pytest.mark.parametrize("flattened", [False, True])
def test_direct_reference_answer_depends_on_actual_comparison_metadata(shopping_replay, valid, flattened):
    payload = {"grounding_notice": SHOPPING_GROUNDING_NOTICE,
               "results": [{"title": "Synthetic direct reference product",
                            "visual_match": {"status": "evaluated"}}],
               "visual_evaluations": [{"visual_evaluation": {
                   "status": "evaluated", "reference_count": 1, "evaluated_count": 1, "unavailable_count": 0}}]}
    if not valid:
        payload["visual_evaluations"][0]["visual_evaluation"]["unavailable_count"] = 1
    if flattened:
        from backend.core.api.app.services.embed_service import _flatten_for_toon_tabular
        payload = _flatten_for_toon_tabular(payload)
    result = llm_fixture("llm/synthetic-auto-model", {
        "model": "synthetic-auto-model", "stream": True,
        "messages": _with_shopping_policy([{"role": "user", "content": DIRECT_REFERENCE_PROMPT},
                     {"role": "tool", "content": json.dumps(payload)}]), "tools": [],
    })
    answer = result["response"]["chunks"][0]["value"]
    assert (answer == DIRECT_REFERENCE_RESPONSE) is valid


@pytest.mark.parametrize("match", [
    {"visual_match_status": "unavailable"},
    {"visual_match": "evaluated", "visual_match_status": "evaluated"},
    {"visual_match": {"status": "unavailable"}, "visual_match_status": "evaluated"},
    {"visual_match": {"status": "evaluated"}, "visual_match_status": "unavailable"},
])
def test_direct_reference_answer_rejects_unavailable_or_conflicting_match_metadata(shopping_replay, match):
    payload = {"grounding_notice": SHOPPING_GROUNDING_NOTICE,
               "results": [{"title": "Synthetic direct reference product", **match}],
               "visual_evaluations": [{"visual_evaluation": {
                   "status": "evaluated", "reference_count": 1, "evaluated_count": 1, "unavailable_count": 0}}]}
    result = llm_fixture("llm/synthetic-auto-model", {
        "model": "synthetic-auto-model", "stream": True,
        "messages": _with_shopping_policy([{"role": "user", "content": DIRECT_REFERENCE_PROMPT},
                     {"role": "tool", "content": encode(payload)}]), "tools": [],
    })
    assert result["response"]["chunks"][0]["value"].startswith("REGRESSION:")


@pytest.mark.parametrize("extra", [None, {"visual_evaluation": {"status": "invalid"}}])
def test_direct_reference_answer_rejects_extra_malformed_evaluations(shopping_replay, extra):
    payload = {"grounding_notice": SHOPPING_GROUNDING_NOTICE,
               "results": [{"title": "Synthetic direct reference product", "visual_match_status": "evaluated"}],
               "visual_evaluations": [{"visual_evaluation": {
                   "status": "evaluated", "reference_count": 1, "evaluated_count": 1, "unavailable_count": 0}}, extra]}
    result = llm_fixture("llm/synthetic-auto-model", {
        "model": "synthetic-auto-model", "stream": True,
        "messages": _with_shopping_policy([{"role": "user", "content": DIRECT_REFERENCE_PROMPT},
                     {"role": "tool", "content": encode(payload)}]), "tools": [],
    })
    assert result["response"]["chunks"][0]["value"].startswith("REGRESSION:")


@pytest.mark.asyncio
@pytest.mark.parametrize("transform_history", [False, True], ids=["current-tool-message", "restored-history"])
@pytest.mark.parametrize("notice", ["actual", "missing", "altered"])
async def test_direct_reference_answer_reads_real_flattened_visual_result(shopping_replay, transform_history, notice):
    from backend.apps.shopping.visual_ranking import download_public_product_image, rank_products_visually
    from backend.apps.shopping.providers.rewe_provider import _parse_product
    from backend.apps.shopping.skills.search_products import SearchProductsResponse
    from backend.apps.ai.utils.app_skill_result_groups import shopping_result_parent_metadata, shopping_result_payload
    from backend.apps.ai.utils.llm_utils import _transform_message_history_for_llm
    from backend.core.api.app.services.embed_service import _flatten_for_toon_tabular

    fixture_path = Path(__file__).parents[1] / "apps/ai/testing/api_cache" / GROUP / "rewe/4f3f2917b9cf25e8.json"
    raw = json.loads(fixture_path.read_text())["response"]["body"]["_embedded"]["products"][0]
    product = _parse_product(raw, 1).to_result_dict()
    reference = await download_public_product_image(DIRECT_REFERENCE_IMAGE)
    ranked = await rank_products_visually(
        candidates=[product], reference_images=[reference], relevance_criteria=None,
        query=DIRECT_REFERENCE_QUERY, secrets_manager=None,
    )
    assert ranked.summary["evaluated_count"] == 1
    metadata = shopping_result_parent_metadata([{
        "id": 1, "results": ranked.candidates, "visual_evaluation": ranked.summary}])
    # Match main_processor's current tool-message boundary: product rows as
    # well as the parent metadata are flattened before TOON encoding.
    payload = shopping_result_payload(
        [_flatten_for_toon_tabular(row) for row in ranked.candidates],
        _flatten_for_toon_tabular(metadata),
    )
    assert payload["results"][0]["visual_match_status"] == "evaluated"
    history = _with_shopping_policy([{"role": "user", "content": DIRECT_REFERENCE_PROMPT}, {
        "role": "tool", "name": "shopping-search_products", "tool_call_id": "shopping-gallery-fixture",
        "content": encode(payload), "ignore_fields_for_inference": SearchProductsResponse().ignore_fields_for_inference,
    }])
    if transform_history:
        history = _transform_message_history_for_llm(history)
    actual_dispatch_payload = decode(history[-1]["content"])
    assert actual_dispatch_payload["grounding_notice"] == SHOPPING_GROUNDING_NOTICE
    # Mutate the actual model-dispatch payload after history normalization:
    # normalization is allowed to restore server-authored grounding metadata.
    if notice == "missing":
        actual_dispatch_payload.pop("grounding_notice")
    elif notice == "altered":
        actual_dispatch_payload["grounding_notice"] = "Incomplete grounding guidance."
    history[-1]["content"] = encode(actual_dispatch_payload)
    result = llm_fixture("llm/synthetic-auto-model", {
        "model": "synthetic-auto-model", "stream": True, "messages": history,
    })
    answer = result["response"]["chunks"][0]["value"]
    assert (answer == DIRECT_REFERENCE_RESPONSE) is (notice == "actual")


@pytest.mark.asyncio
async def test_signed_direct_reference_images_and_visual_decisions_never_call_providers(shopping_replay, monkeypatch):
    from backend.apps.shopping.visual_ranking import download_public_product_image, rank_products_visually
    from backend.shared.providers.typesafe.client import JevDecisionClient
    import httpx

    def forbidden(*args, **kwargs):
        raise AssertionError("Signed replay must not initialize external HTTP")

    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    monkeypatch.setattr(JevDecisionClient, "_evaluate_provider", forbidden)
    reference = await download_public_product_image(DIRECT_REFERENCE_IMAGE)
    result = await rank_products_visually(
        candidates=[{"title": "Synthetic direct reference product", "image_url": DIRECT_REFERENCE_IMAGE}],
        reference_images=[reference], relevance_criteria=None, query=DIRECT_REFERENCE_QUERY,
        secrets_manager=None,
    )
    assert result.summary["evaluated_count"] == 1
    assert result.candidates[0]["visual_match"]["score"] == 3.0
    with pytest.raises(ValueError, match="no product image fixture"):
        await download_public_product_image("https://unlisted.invalid/image.jpg")


LENS_TEMP_URL = "http://storage.ci.test:9000/dev-openmates-temp-images/reverse_search/0123456789abcdef_0123456789abcdef.png?X-Amz-Signature=synthetic"


@pytest.fixture
def uploaded_search_replay(shopping_replay, monkeypatch):
    from backend.shared.testing.mock_context import activate_mock_mode, deactivate_mock_mode
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("OPENMATES_CI_AI_FIXTURES", "1")
    monkeypatch.setenv("S3_ENDPOINT_URL", "http://storage.ci.test:9000")
    monkeypatch.setenv("VAULT_URL", "http://vault:8200")
    monkeypatch.setenv("CMS_URL", "http://cms:8055")
    monkeypatch.setenv("OPENMATES_CI_ISOLATED", "1")
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("OPENMATES_STORAGE_CAPACITY_FIXTURES", raising=False)
    activate_mock_mode("mock", GROUP, task_id="signed-direct-image-reference-fixture")
    try:
        yield
    finally:
        deactivate_mock_mode()


@pytest.mark.parametrize("variant", ["valid", "unsigned", "wrong-engine", "unexpected-query", "wrong-host", "public-image", "wrong-storage-endpoint"])
def test_lens_http_replay_is_strictly_scoped(uploaded_search_replay, variant, monkeypatch):
    import httpx
    params = {"engine": "google_lens", "url": LENS_TEMP_URL, "num": "3", "api_key": LENS_FIXTURE_KEY}
    host = "serpapi.com"
    if variant == "wrong-engine":
        params["engine"] = "google"
    elif variant == "unexpected-query":
        params["q"] = "another query"
    elif variant == "wrong-host":
        host = "elsewhere.invalid"
    elif variant == "public-image":
        params["url"] = "https://example.invalid/image.jpg"
    elif variant == "wrong-storage-endpoint":
        monkeypatch.setenv("S3_ENDPOINT_URL", "http://another-storage.invalid:9000")
    token = mock_group_var.set("unsigned") if variant == "unsigned" else None
    try:
        response = synthetic_http_response(httpx.Request("GET", f"https://{host}/search", params=params))
        assert (response is not None) is (variant == "valid")
    finally:
        if token is not None:
            mock_group_var.reset(token)


@pytest.mark.asyncio
async def test_real_lens_parser_consumes_signed_transport_replay_without_secrets(uploaded_search_replay):
    from backend.shared.providers.serpapi import google_lens_reverse_search
    from backend.shared.testing.mock_context import _install_httpx_transport_guard
    _install_httpx_transport_guard()
    result = await google_lens_reverse_search(LENS_TEMP_URL, secrets_manager=None, max_results=3)
    assert result["error"] is None
    assert result["results"][0]["title"] == "Synthetic direct uploaded reference match"
    assert result["results"][0]["source_page_url"] == "https://example.invalid/direct-reference-match"


@pytest.mark.parametrize("representation", ["markdown", "toon"])
def test_direct_reverse_search_dispatch_uses_exact_reference_without_query_or_view(uploaded_search_replay, representation):
    reference = "uploaded-reference-01234567"
    attachment = f"[!](embed:{reference})" if representation == "markdown" else "```toon\n" + encode({
        "type": "image", "app_id": "images", "skill_id": "upload", "embed_ref": reference}) + "\n```"
    result = llm_fixture("llm/synthetic-auto-model", {
        "model": "synthetic-auto-model", "stream": True,
        "messages": [{"role": "user", "content": f"{DIRECT_SEARCH_PROMPT}\n{attachment}"}],
        "tools": [{"function": {"name": "images-search"}}, {"function": {"name": "images-view"}}],
    })
    [call] = result["response"]["chunks"]
    assert call["value"]["function_name"] == "images-search"
    assert call["value"]["function_arguments_parsed"] == {"requests": [{"file_path": reference, "count": 3}]}


@pytest.mark.asyncio
async def test_direct_reverse_search_routes_only_search_not_view(uploaded_search_replay):
    history = [{"role": "user", "content": DIRECT_SEARCH_PROMPT}]
    routing = await decide_app_and_project_routing_with_jev(
        model_id="typesafe/jev-1.13", secrets_manager=None, message_history=history,
        available_apps=["shopping", "images"], available_skills=[], available_focus_modes=[],
        topic_areas=["general_misc"], is_first_message=True,
    )
    assert routing["selected_app_ids"] == ["images"]
    result = await decide_preprocessing_with_jev(
        model_id="typesafe/jev-1.13", secrets_manager=None, message_history=history,
        topic_areas=["general_misc"], available_skills=["images-search", "images-view"],
        available_focus_modes=[], available_settings_and_memories={}, recent_skill_activity=[],
        conversation_summary=None, previous_category=None, is_first_message=True,
        available_apps=["shopping", "images"], selected_app_ids=routing["selected_app_ids"],
        early_decisions=routing["early_decisions"],
    )
    assert result["relevant_app_skills"] == ["images-search"]


def test_reverse_search_internal_upload_permission_is_signed_and_path_bounded(uploaded_search_replay, monkeypatch):
    from backend.shared.testing.mock_context import _allow_isolated_capacity_internal as allowed
    assert allowed("http://api:8000/internal/s3/upload-temp-image", "POST")
    assert allowed("http://api:8000/internal/s3/temp-image?s3_key=reverse_search/0123456789abcdef_0123456789abcdef.png", "DELETE")
    assert not allowed("http://api:8000/internal/s3/upload-temp-image", "GET")
    assert not allowed("http://api:8000/internal/s3/temp-image?s3_key=another/path.png", "DELETE")
    assert not allowed("http://elsewhere:8000/internal/s3/upload-temp-image", "POST")
    token = mock_group_var.set("unsigned")
    try:
        assert not allowed("http://api:8000/internal/s3/upload-temp-image", "POST")
    finally:
        mock_group_var.reset(token)
    monkeypatch.setenv("S3_ENDPOINT_URL", "http://another-storage.invalid:9000")
    assert not allowed("http://api:8000/internal/s3/upload-temp-image", "POST")
    monkeypatch.delenv("S3_ENDPOINT_URL")
    assert not allowed("http://api:8000/internal/s3/upload-temp-image", "POST")


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
    assert request["max_results"] == 5
    # The signed replay's cached HTTP transport returns forty raw products and
    # the real Jev ranking fixture scores the late candidate through real batching.
    _, rows, error = await object.__new__(SearchProductsSkill)._process_single_request(
        request, "forty", secrets_manager=None)
    assert error is None and len(rows) == 5
    assert rows[0]["product_id"] == "forty-039"
    payload = shopping_result_payload(rows, shopping_result_parent_metadata([{"id": 1, "results": rows}]))
    answer = llm_fixture("llm/gemini-fixture", {
        "model": "gemini-fixture", "stream": True,
        "messages": [{"role": "user", "content": FORTY_PROMPT}, {"role": "tool", "content": encode(payload)}],
    })
    assert answer["response"]["chunks"][0]["value"] == FORTY_RESPONSE
