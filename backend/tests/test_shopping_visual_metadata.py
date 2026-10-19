"""Shopping comparison evidence survives tool projection and real embed construction."""
from types import SimpleNamespace

import pytest
from toon_format import decode, encode

from backend.apps.ai.utils.app_skill_result_groups import shopping_result_parent_metadata, shopping_result_payload
from backend.core.api.app.services.embed_service import EmbedService, _flatten_for_toon_tabular


def summary(status="evaluated", count=1):
    return {"status": status, "reference_count": 3, "evaluated_count": count,
            "filtered_count": count, "notice": "Similarity is an estimate."}


# contract-test: supporting surface=rest_api assertions=shopping-search.relevance.truthful-fallback
@pytest.mark.parametrize("results", [[], [{"title": "Fabric"}], [{"title": "A"}, {"title": "B"}]])
def test_no_reference_calls_keep_legacy_tool_payload_shape(results):
    assert shopping_result_parent_metadata([{"id": 1, "results": results}]) == {}
    payload = shopping_result_payload(results, {})
    assert payload == (results[0] if len(results) == 1 else {"results": results, "count": len(results)})


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
               "visual_match": {"status": "evaluated", "score": 4, "product_image_count": 2}}
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
    if product_count:
        child = decode(sent[0]["content_toon"])
        assert child["visual_match_status"] == "evaluated" and child["visual_match_score"] == 4
        assert child["price_cents"] == 1299
    else:
        assert len(sent) == 1
