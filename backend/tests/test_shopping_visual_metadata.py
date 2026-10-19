"""Shopping comparison evidence survives tool projection and real embed construction."""
from types import SimpleNamespace

import pytest
from toon_format import decode, encode

from backend.apps.ai.utils.app_skill_result_groups import (
    SHOPPING_GROUNDING_NOTICE, shopping_result_parent_metadata, shopping_result_payload,
)
from backend.core.api.app.services.embed_service import EmbedService, _flatten_for_toon_tabular


def summary(status="evaluated", count=1):
    return {"status": status, "reference_count": 3, "evaluated_count": count,
            "filtered_count": count, "unavailable_count": 0, "score_min": 0, "score_max": 4, "notice": "Similarity is an estimate."}


# contract-test: supporting surface=rest_api assertions=shopping-search.relevance.truthful-fallback
@pytest.mark.parametrize("results", [[], [{"title": "Fabric"}], [{"title": "A"}, {"title": "B"}]])
def test_no_reference_calls_keep_product_facts_with_grounding_and_no_visual_claims(results):
    metadata = shopping_result_parent_metadata([{"id": 1, "results": results}])
    assert metadata == {"grounding_notice": SHOPPING_GROUNDING_NOTICE}
    payload = shopping_result_payload(results, metadata)
    assert payload == {"results": results, "count": len(results), **metadata}
    assert "visual_evaluations" not in payload


# contract-test: supporting surface=rest_api assertions=shopping-search.relevance.truthful-fallback,shopping-search.privacy.minimized
def test_group_summaries_keep_request_identity_and_exclude_unrelated_metadata():
    first = {**summary(), "user_id": "PRIVATE OWNER", "image_url": "PRIVATE IMAGE URL"}
    groups = [{"id": "first", "results": [], "visual_evaluation": first},
              {"id": "second", "results": [], "visual_evaluation": summary("unavailable", 0)},
              {"id": "neutral", "results": []}]
    metadata = shopping_result_parent_metadata(groups)
    assert [row["request_id"] for row in metadata["visual_evaluations"]] == ["first", "second"]
    assert "PRIVATE" not in str(metadata)
    metadata["visual_evaluations"][0]["visual_evaluation"]["status"] = "changed"
    assert first["status"] == "evaluated"
    # Each parent gets only its own comparison evidence.
    assert len(shopping_result_parent_metadata(groups[:1])["visual_evaluations"]) == 1


# contract-test: supporting surface=rest_api assertions=shopping-search.relevance.truthful-fallback
def test_empty_comparison_tool_and_preview_wrappers_preserve_evidence_without_product_rows():
    metadata = shopping_result_parent_metadata([{"id": "all-filtered", "results": [], "visual_evaluation": summary()}])
    payload = shopping_result_payload([], _flatten_for_toon_tabular(metadata))
    decoded = decode(encode(payload))
    assert decoded["results"] == [] and decoded["count"] == 0
    assert decoded["visual_evaluations"][0]["request_id"] == "all-filtered"
    assert decoded["visual_evaluations"][0]["visual_evaluation_status"] == "evaluated"
    # Re-updating a cached TOON parent must retain the same comparison evidence.
    merged = EmbedService._merge_request_metadata(decoded, None)
    assert merged["visual_evaluations"] == metadata["visual_evaluations"]


# contract-test: supporting surface=rest_api assertions=shopping-search.relevance.truthful-fallback,shopping-search.privacy.minimized
@pytest.mark.parametrize("error", ["Reference image is unavailable to this caller", "PRIVATE provider URL and credentials", {"private": "diagnostics"}])
def test_failed_search_tool_payload_retains_safe_error_instead_of_claiming_no_matches(error):
    metadata = shopping_result_parent_metadata([{"id": "failed", "results": [], "error": error}])
    payload = decode(encode(shopping_result_payload([], _flatten_for_toon_tabular(metadata))))
    assert payload["count"] == 0 and payload["results"] == []
    assert payload["request_errors"][0]["request_id"] == "failed"
    assert "not evidence of no matching products" in payload["failure_notice"]
    assert "PRIVATE" not in str(payload) and "diagnostics" not in str(payload)
    if isinstance(error, str) and error.startswith("Reference image"):
        assert "reference image could not be accessed" in payload["request_errors"][0]["message"]
    assert "visual_evaluations" not in payload


# contract-test: supporting surface=rest_api assertions=shopping-search.relevance.truthful-fallback
def test_partial_request_failure_keeps_successful_products_and_its_own_request_identity():
    groups = [{"id": "failed", "results": [], "error": "Reference image is no longer available"},
              {"id": "matched", "results": [{"title": "Fabric"}], "visual_evaluation": summary()}]
    metadata = shopping_result_parent_metadata(groups)
    payload = shopping_result_payload(groups[1]["results"], metadata)
    assert payload["results"] == [{"title": "Fabric"}] and payload["count"] == 1
    assert payload["request_errors"][0]["request_id"] == "failed"
    assert payload["visual_evaluations"][0]["request_id"] == "matched"
    assert shopping_result_parent_metadata([{"id": "empty-success", "results": []}]) == {
        "grounding_notice": SHOPPING_GROUNDING_NOTICE,
    }


# contract-test: supporting surface=rest_api assertions=shopping-search.relevance.truthful-fallback,shopping-search.privacy.minimized
@pytest.mark.parametrize("product_count", [0, 1, 2])
@pytest.mark.parametrize("wire_format", ["toon", "json"])
def test_real_history_conversion_retains_comparison_evidence_and_still_excludes_image_urls(product_count, wire_format):
    import json
    from backend.apps.ai.utils.llm_utils import _transform_message_history_for_llm

    products = [{"title": "Fabric", "image_urls": ["PRIVATE PHOTO URL"], "price_cents": 1299}
                for _ in range(product_count)]
    evidence = shopping_result_parent_metadata([{"id": "compared", "results": products,
                                                "visual_evaluation": summary("partial", 2)}])
    payload = {"results": products, "count": product_count, **evidence,
               "private_wrapper_key": "PRIVATE WRAPPER VALUE"}
    content = encode(_flatten_for_toon_tabular(payload)) if wire_format == "toon" else json.dumps(payload)
    transformed = _transform_message_history_for_llm([{
        "role": "tool", "name": "shopping-search_products", "tool_call_id": "visual",
        "content": content, "ignore_fields_for_inference": ["image_urls"],
    }])
    decoded = decode(transformed[0]["content"])
    assert decoded["visual_evaluations"][0]["request_id"] == "compared"
    assert decoded["visual_evaluations"][0]["visual_evaluation"]["status"] == "partial"
    assert decoded["count"] == product_count
    assert decoded["grounding_notice"] == SHOPPING_GROUNDING_NOTICE
    evaluation = decoded["visual_evaluations"][0]["visual_evaluation"]
    assert (evaluation["score_min"], evaluation["score_max"], evaluation["unavailable_count"]) == (0, 4, 0)
    assert "PRIVATE" not in str(decoded)
    if product_count:
        assert decoded["results"][0]["price_cents"] == 1299


# contract-test: supporting surface=rest_api assertions=shopping-search.privacy.minimized,shopping-search.relevance.truthful-fallback
def test_history_retention_uses_only_safe_shopping_metadata():
    from backend.apps.ai.utils.app_skill_result_groups import shopping_inference_metadata

    raw = {"request_errors": [{"request_id": 1, "message": "PRIVATE error"},
                               {"request_id": 2, "message": "The shopping request could not be completed.", "secret": "PRIVATE"}],
           "failure_notice": "PRIVATE notice", "image_url": "PRIVATE photo"}
    retained = shopping_inference_metadata(raw)
    assert retained["request_errors"] == [{"request_id": 2, "message": "The shopping request could not be completed."}]
    assert "not evidence of no matching products" in retained["failure_notice"]
    assert "PRIVATE" not in str(retained)


# contract-test: supporting surface=rest_api assertions=shopping-search.relevance.truthful-fallback,shopping-search.relevance.visual-and-text
@pytest.mark.parametrize("operation", ["create", "update"])
@pytest.mark.parametrize("product_count", [0, 1])
@pytest.mark.asyncio
async def test_actual_parent_and_child_construction_preserves_visual_evidence(operation, product_count):
    sent = []

    async def encrypt(value, _key):
        return "encrypted:" + value, None

    async def send(**kwargs):
        sent.append(kwargs)
        return True

    async def existing(*args):
        return {}

    async def cache(*args):
        return None

    class MetadataCache:
        async def get_discovered_apps_metadata(self):
            return None

    service = EmbedService.__new__(EmbedService)
    service.cache_service = MetadataCache()
    service.encryption_service = SimpleNamespace(encrypt_with_user_key=encrypt)
    service.send_embed_data_to_client = send
    service._get_cached_embed = existing
    service._cache_embed = cache
    service._schedule_embed_persistence_fallback = lambda embed_id: None
    product = {"title": "Blue fabric", "price_cents": 1299,
               "visual_match": {"status": "evaluated", "score": 3.24, "score_min": 0, "score_max": 4, "product_image_count": 2}}
    results = [product] if product_count else []
    metadata = shopping_result_parent_metadata([{"id": "request-A", "results": results,
                                                 "visual_evaluation": summary()}])
    kwargs = dict(app_id="shopping", skill_id="search_products", results=results,
                  chat_id="chat", message_id="message", user_id="alice", user_id_hash="hash",
                  user_vault_key_id="vault", request_metadata={"query": "blue fabric", **metadata})
    if operation == "update":
        result = await service.update_embed_with_results(embed_id="parent", **kwargs)
    else:
        result = await service.create_embeds_from_skill_results(**kwargs)
    assert result is not None
    parent = decode(sent[-1]["content_toon"])
    assert parent["result_count"] == product_count and parent["status"] == "finished"
    assert parent["visual_evaluations"][0]["request_id"] == "request-A"
    assert parent["visual_evaluations"][0]["visual_evaluation_status"] == "evaluated"
    assert parent["grounding_notice"] == SHOPPING_GROUNDING_NOTICE
    assert parent["visual_evaluations"][0]["visual_evaluation_score_min"] == 0
    assert parent["visual_evaluations"][0]["visual_evaluation_score_max"] == 4
    if product_count:
        child = decode(sent[0]["content_toon"])
        assert child["visual_match_status"] == "evaluated" and child["visual_match_score"] == 3.24
        assert (child["visual_match_score_min"], child["visual_match_score_max"]) == (0, 4)
        assert child["price_cents"] == 1299
    else:
        assert len(sent) == 1


# contract-test: supporting surface=rest_api assertions=shopping-search.relevance.truthful-fallback,shopping-search.relevance.visual-and-text
@pytest.mark.parametrize("composition", [None, "100% Baumwolle", "80% cotton, 20% polyester"])
@pytest.mark.parametrize("wire_format", ["toon", "json"])
@pytest.mark.parametrize("legacy_single", [False, True])
def test_history_preserves_only_explicit_material_evidence_and_canonical_grounding(composition, wire_format, legacy_single):
    import json
    from backend.apps.ai.utils.llm_utils import _transform_message_history_for_llm

    product = {"title": "Baumwoll-Popeline Kleine Blumen dunkelblau", "attributes": {"weight": "120 g/m²", "width": "145 cm"},
               "image_urls": ["PRIVATE PHOTO"], "visual_match": {"status": "evaluated", "score": 3.24,
                                                                    "score_min": 0, "score_max": 4}}
    if composition is not None:
        product["attributes"]["composition"] = composition
    payload = product if legacy_single else {"results": [product], "count": 1, "grounding_notice": "UNTRUSTED notice"}
    content = encode(payload) if wire_format == "toon" else json.dumps(payload)
    transformed = _transform_message_history_for_llm([{
        "role": "tool", "name": "shopping-search_products", "tool_call_id": "grounding",
        "content": content, "ignore_fields_for_inference": ["image_urls"],
    }])
    decoded = decode(transformed[0]["content"])
    retained = decoded["results"][0]
    assert retained["attributes"] == product["attributes"]
    assert retained["attributes"]["weight"] == "120 g/m²"
    assert retained["attributes"]["width"] == "145 cm"
    assert retained["visual_match"] == product["visual_match"]
    assert decoded["grounding_notice"] == SHOPPING_GROUNDING_NOTICE
    assert "UNTRUSTED" not in str(decoded) and "PRIVATE" not in str(decoded)
    if composition is None:
        assert "100%" not in str(retained) and "composition" not in retained["attributes"]
    assert "Visual appearance cannot establish composition" in decoded["grounding_notice"]
    assert "only when explicitly supplied" in decoded["grounding_notice"]


# contract-test: supporting surface=rest_api assertions=shopping-search.relevance.truthful-fallback
@pytest.mark.parametrize("wire_format", ["toon", "json"])
def test_legacy_product_list_history_receives_grounding_without_visual_status(wire_format):
    import json
    from backend.apps.ai.utils.llm_utils import _transform_message_history_for_llm

    products = [{"title": "Cotton poplin", "price_cents": 1200, "image_url": "PRIVATE PHOTO"}]
    content = encode(products) if wire_format == "toon" else json.dumps(products)
    transformed = _transform_message_history_for_llm([{
        "role": "tool", "name": "shopping-search_products", "tool_call_id": "legacy-list",
        "content": content, "ignore_fields_for_inference": ["image_url"],
    }])
    payload = decode(transformed[0]["content"])
    assert payload == {"results": [{"title": "Cotton poplin", "price_cents": 1200}], "count": 1,
                       "grounding_notice": SHOPPING_GROUNDING_NOTICE}
