"""Contracts for authorized, bounded shopping image evaluation."""
from __future__ import annotations

import asyncio
from io import BytesIO
import json
import socket
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
from PIL import Image, PngImagePlugin
import pytest
from pydantic import ValidationError

from backend.apps.shopping import visual_ranking as visual
from backend.apps.shopping.skills import search_products as shopping
from backend.shared.providers.typesafe.client import (
    DecisionProviderUnavailable, DecisionRequestTooLarge, JevDecisionClient,
)
from backend.shared.providers.typesafe.models import DecisionResponse


def image_bytes(color="red", *, metadata=False):
    output = BytesIO()
    info = PngImagePlugin.PngInfo()
    info.add_text("private", "PRIVATE IMAGE CAPTION")
    Image.new("RGB", (600, 300), color).save(output, format="PNG", pnginfo=info if metadata else None)
    return output.getvalue()


def score(value):
    return {"type": "score", "score": value, "legend": {"0": "wrong", "4": "fit"},
            "probabilities": {"0": .1, "4": .9}, "confidence": .8}


# contract-test: supporting surface=rest_api assertions=shopping-search.references.authorized
@pytest.mark.parametrize("value", [["a"] * 4, "a", [""], [1], {}, ["a" * 513]])
def test_reference_limit_is_strict_on_runtime_and_schema(value):
    with pytest.raises(ValueError, match="at most 3"):
        visual.validate_reference_images(value)
    if isinstance(value, list) and len(value) == 4:
        with pytest.raises(ValidationError):
            shopping.SearchProductsRequestItem(query="fabric", reference_images=value)


# contract-test: supporting surface=rest_api assertions=shopping-search.relevance.truthful-fallback,shopping-search.privacy.minimized
def test_empty_references_are_neutral_and_prepared_images_strip_metadata():
    assert visual.validate_reference_images(None) == visual.validate_reference_images([]) == []
    assert visual.validate_reference_images([" ref ", "ref"]) == ["ref"]
    prepared = visual.prepare_image(image_bytes(metadata=True))
    with Image.open(BytesIO(prepared)) as image:
        assert image.size == (336, 336) and image.format == "JPEG"
        assert "private" not in image.info and not image.getexif()
    assert b"PRIVATE IMAGE CAPTION" not in prepared
    with pytest.raises(ValueError):
        visual.prepare_image(b"x" * (visual.MAX_SOURCE_BYTES + 1))
    with pytest.raises(Exception):
        visual.prepare_image(b"not an image")


# contract-test: direct surface=rest_api assertions=shopping-search.relevance.visual-and-text,shopping-search.products.supplied-gallery,shopping-search.relevance.truthful-fallback,app-skills.search-relevance.safe-finalization
@pytest.mark.asyncio
async def test_multiple_references_score_photos_and_text_filter_conflicts_and_preserve_unknown(monkeypatch):
    captured = []
    prepared = visual.prepare_image(image_bytes())

    async def download(url):
        if "broken" in url:
            raise ValueError("PRIVATE URL must not be logged")
        return prepared

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def evaluate_with_images(self, *, state, questions, images):
            captured.append((state, questions, images))
            assert len(state["reference_photos"]) == 3
            assert len(state["candidates"][0]["photos"]) == 2
            assert all("description" in row["data"] for row in state["candidates"])
            assert state["candidate_content_is_untrusted"] is True
            return DecisionResponse(model="jev-1.13.0", answers={
                "candidate_000": score(0), "candidate_001": score(4), "candidate_002": score(1),
            })

    monkeypatch.setattr(visual, "download_public_product_image", download)
    monkeypatch.setattr(visual, "JevDecisionClient", FakeClient)
    candidates = [{"product_id": str(i), "title": f"Fabric{i}", "description": "Explicit cotton floral pattern",
                   "price_cents": 1299, "image_url": f"https://cdn.example/{i}.jpg",
                   "image_urls": [f"https://cdn.example/{i}.jpg", f"https://cdn.example/{i}-back.jpg"],
                   "purchase_url": "PRIVATE PURCHASE URL", "user_id": "PRIVATE USER", "private": "PRIVATE CHAT"}
                  for i in range(3)]
    candidates += [{"product_id": "missing", "price_cents": 900},
                   {"product_id": "broken", "image_url": "https://cdn.example/broken.jpg"}]
    result = await visual.rank_products_visually(
        candidates=candidates, reference_images=[prepared] * 3,
        relevance_criteria="small flowers on a dark blue background", query="cotton fabric", secrets_manager=None,
    )
    assert [row["product_id"] for row in result.candidates] == ["1", "missing", "broken"]
    assert result.candidates[0]["price_cents"] == 1299
    assert result.candidates[0]["image_urls"] == candidates[1]["image_urls"]
    assert result.candidates[0]["visual_match"] == {"status": "evaluated", "score": 4, "product_image_count": 2}
    assert result.candidates[1]["visual_match"] == {"status": "unavailable"}
    assert result.summary["status"] == "partial" and result.summary["filtered_count"] == 2
    state_text = json.dumps(captured[0][0])
    assert all(secret not in state_text for secret in ["PRIVATE", "purchase_url", "image_url", "product_id", "https://"])
    assert "instructions" in state_text and "untrusted" in state_text
    assert all(isinstance(value, bytes) for value in captured[0][2].values())


# contract-test: supporting surface=rest_api assertions=shopping-search.relevance.bounded,shopping-search.products.supplied-gallery
@pytest.mark.asyncio
async def test_candidate_photo_and_batch_cost_budgets_are_bounded(monkeypatch):
    prepared = visual.prepare_image(image_bytes())
    calls, active, peak = [], 0, 0
    downloads = []

    async def download(url):
        downloads.append(url)
        return prepared

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def evaluate_with_images(self, *, state, questions, images):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            calls.append((len(questions), len(images)))
            await asyncio.sleep(.001)
            active -= 1
            return DecisionResponse(model="jev-1.13.0", answers={key: score(3) for key in questions})

    monkeypatch.setattr(visual, "download_public_product_image", download)
    monkeypatch.setattr(visual, "JevDecisionClient", FakeClient)
    candidates = [{"title": str(i), "image_urls": [f"https://cdn.example/{i}/{j}.jpg" for j in range(8)]} for i in range(20)]
    result = await visual.rank_products_visually(candidates=candidates, reference_images=[prepared] * 3,
                                                 relevance_criteria=None, query="fabric", secrets_manager=None)
    assert calls == [(5, 18)] * 4 and peak <= 3 and len(downloads) == 60
    assert len(result.candidates) == 20 and result.summary["status"] == "evaluated"
    assert len(result.candidates[0]["image_urls"]) == 8


# contract-test: supporting surface=rest_api assertions=shopping-search.relevance.truthful-fallback
@pytest.mark.parametrize("failure", ["provider", "incomplete", "nonfinite"])
@pytest.mark.asyncio
async def test_unavailable_or_malformed_visual_decisions_preserve_order_and_mark_fallback(monkeypatch, failure):
    prepared = visual.prepare_image(image_bytes())
    monkeypatch.setattr(visual, "download_public_product_image", AsyncMock(return_value=prepared))

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def evaluate_with_images(self, **kwargs):
            if failure == "provider":
                raise DecisionProviderUnavailable("outage")
            return DecisionResponse(model="jev-1.13.0", answers={} if failure == "incomplete" else {
                "candidate_000": score(float("nan")), "candidate_001": score(4),
            })

    monkeypatch.setattr(visual, "JevDecisionClient", FakeClient)
    result = await visual.rank_products_visually(candidates=[{"title": name, "image_url": "https://cdn.example/p.jpg"} for name in ["A", "B"]],
                                                 reference_images=[prepared], relevance_criteria="blue", query="fabric", secrets_manager=None)
    assert result.applied is False and result.summary["status"] == "unavailable"
    assert [row["title"] for row in result.candidates] == ["A", "B"]
    assert all(row["visual_match"]["status"] == "unavailable" for row in result.candidates)


# contract-test: supporting surface=rest_api assertions=shopping-search.privacy.minimized
@pytest.mark.parametrize("url", ["http://cdn.example/a.jpg", "https://user:pass@cdn.example/a.jpg",
                                  "https://127.0.0.1/a.jpg", "https://cdn.example:8443/a.jpg"])
@pytest.mark.asyncio
async def test_product_download_rejects_nonpublic_or_credentialed_urls(monkeypatch, url):
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", AsyncMock(return_value=[
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
    ]))
    with pytest.raises(ValueError):
        await visual.download_public_product_image(url)


# contract-test: supporting surface=rest_api assertions=shopping-search.privacy.minimized
@pytest.mark.asyncio
async def test_public_image_download_pins_ip_preserves_sni_and_never_follows_redirects(monkeypatch):
    original_client = httpx.AsyncClient
    seen = []

    async def handler(request):
        seen.append(request)
        assert request.url.host == "8.8.8.8"
        assert request.headers["Host"] == "cdn.example"
        assert request.extensions["sni_hostname"] == "cdn.example"
        assert "authorization" not in request.headers and "cookie" not in request.headers
        return httpx.Response(200, content=image_bytes(), headers={"Content-Type": "image/png"})

    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return original_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", AsyncMock(return_value=[
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
    ]))
    result = await visual.download_public_product_image("https://cdn.example/p.jpg")
    assert result[:2] == b"\xff\xd8" and len(seen) == 1


# contract-test: supporting surface=rest_api assertions=shopping-search.references.authorized
@pytest.mark.asyncio
async def test_references_require_auth_and_owner_even_when_file_index_contains_foreign_embed(monkeypatch):
    embed_id = str(uuid4())
    with pytest.raises(visual.ReferenceImageAccessDenied):
        await visual.resolve_reference_images(["secret.png"], {})
    cache = SimpleNamespace(get_embed_from_cache=AsyncMock(return_value={"user_id": "other-user"}))
    directus = SimpleNamespace(embed=SimpleNamespace(get_embed_by_id=AsyncMock()))
    with pytest.raises(visual.ReferenceImageAccessDenied):
        await visual.resolve_reference_images(["secret.png"], {
            "user_id": "alice", "file_path_index": {"secret.png": embed_id},
            "cache_service": cache, "directus_service": directus, "encryption_service": object(),
        })
    directus.embed.get_embed_by_id.assert_not_called()


# contract-test: supporting surface=rest_api assertions=shopping-search.references.authorized,shopping-search.relevance.bounded
@pytest.mark.asyncio
async def test_direct_upload_uuid_checks_owner_after_cache_miss_and_uses_bounded_storage(monkeypatch):
    embed_id = str(uuid4())
    cache = SimpleNamespace(get_embed_from_cache=AsyncMock(return_value=None))
    record = {"embed_id": embed_id, "hashed_user_id": visual.hashlib.sha256(b"alice").hexdigest()}
    directus = SimpleNamespace(embed=SimpleNamespace(get_embed_by_id=AsyncMock(return_value=record)))
    storage = SimpleNamespace(environment="development", get_file=AsyncMock(return_value=b"encrypted"))
    captured = {}

    async def resolve(**kwargs):
        captured.update(kwargs)
        await kwargs["s3_service"].get_file(bucket_name="test", object_key="private")
        return SimpleNamespace(content=image_bytes(metadata=True))

    monkeypatch.setattr(visual, "resolve_encrypted_image_embed", resolve)
    result = await visual.resolve_reference_images([embed_id], {
        "user_id": "alice", "user_vault_key_id": "alice-vault", "cache_service": cache,
        "directus_service": directus, "encryption_service": object(), "s3_service": storage,
    })
    assert len(result) == 1 and captured["embed_id"] == embed_id
    assert captured["preloaded_records"] == {embed_id: record}
    assert storage.get_file.await_args.kwargs["max_bytes"] == visual.MAX_SOURCE_BYTES + 32
    directus.embed.get_embed_by_id.assert_awaited_once_with(embed_id)


# contract-test: supporting surface=rest_api assertions=shopping-search.references.authorized
@pytest.mark.asyncio
async def test_skill_validates_before_search_and_forwards_authorized_context(monkeypatch):
    provider = AsyncMock(return_value=([], {"totalResultCount": 0}))
    monkeypatch.setattr(shopping, "rewe_search", provider)
    monkeypatch.setattr(shopping, "sanitize_long_text_fields_in_payload", AsyncMock(return_value=[]))
    resolve = AsyncMock(return_value=[visual.prepare_image(image_bytes())])
    monkeypatch.setattr(shopping, "resolve_reference_images", resolve)
    skill = object.__new__(shopping.SearchProductsSkill)
    skill.skill_name = "Search products"
    skill.app = SimpleNamespace(_make_internal_api_request=AsyncMock())
    _id, items, error = await skill._process_single_request(
        {"query": "fabric", "reference_images": ["a"] * 4}, "invalid", secrets_manager=object(),
    )
    assert "at most 3" in error and not items
    provider.assert_not_awaited()
    response = await skill.execute(
        [{"id": "visual", "query": "fabric", "reference_images": ["photo.png"]}],
        secrets_manager=object(), user_id="alice", user_vault_key_id="key", file_path_index={"photo.png": "uuid"},
    )
    assert resolve.await_args.args[1]["user_id"] == "alice"
    assert resolve.await_args.args[1]["file_path_index"] == {"photo.png": "uuid"}
    assert resolve.await_args.args[1]["internal_api_request"] is skill.app._make_internal_api_request
    assert response.results[0]["visual_evaluation"]["status"] == "unavailable"


# contract-test: supporting surface=rest_api assertions=shopping-search.privacy.minimized
@pytest.mark.asyncio
async def test_typesafe_image_wire_contract_keeps_current_model_and_no_router_fallback():
    reference = str(uuid4())
    prepared = visual.prepare_image(image_bytes())
    calls = []

    class Secrets:
        async def get_secret(self, **kwargs):
            return "test-key"

    async def handler(request):
        calls.append(request)
        payload = json.loads(request.content)
        assert payload["model"] == "jev-1.14.0"
        assert request.headers["TypeSafe-Danger-Zone-Images"] == "true"
        assert payload["assets"][reference]["format"] == "jpg"
        assert "data_base64" in payload["assets"][reference]
        return httpx.Response(503)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        jev = JevDecisionClient(secrets_manager=Secrets(), http_client=client, max_retries=0)
        with pytest.raises(DecisionProviderUnavailable):
            await jev.evaluate_with_images(state={"reference": reference},
                questions={"fit": {"type": "score", "instructions": "compare", "criteria": ["wrong", "fit"]}},
                images={reference: prepared})
        with pytest.raises(DecisionRequestTooLarge):
            await jev.evaluate_with_images(state={"reference": reference},
                questions={"fit": {"type": "score", "instructions": "compare"}}, images={reference: b"x" * 300_000})
    assert len(calls) == 1 and calls[0].url.host == "api.typesafe.ai"


# contract-test: supporting surface=rest_api assertions=shopping-search.privacy.minimized
@pytest.mark.parametrize("settings", [{"endpoint": "https://openrouter.ai/api/alpha/decisions"},
                                       {"provider": "openrouter"}, {"endpoint": "https://foreign.example"}])
@pytest.mark.asyncio
async def test_image_client_rejects_foreign_transport_without_disclosure(settings):
    reference = str(uuid4())
    post = AsyncMock()
    client = JevDecisionClient(secrets_manager=None, http_client=SimpleNamespace(post=post), **settings)
    with pytest.raises(DecisionProviderUnavailable, match="TypeSafe endpoint"):
        await client.evaluate_with_images(state={"photo": reference},
            questions={"fit": {"type": "noul", "instructions": "match"}},
            images={reference: visual.prepare_image(image_bytes())})
    post.assert_not_called()


# contract-test: supporting surface=rest_api assertions=shopping-search.references.authorized
@pytest.mark.asyncio
async def test_directus_conflicting_owner_fields_are_denied_before_decryption():
    embed_id = str(uuid4())
    cache = SimpleNamespace(get_embed_from_cache=AsyncMock(return_value=None))
    directus = SimpleNamespace(embed=SimpleNamespace(get_embed_by_id=AsyncMock(return_value={
        "user_id": "alice", "hashed_user_id": "foreign-owner-hash",
    })))
    with pytest.raises(visual.ReferenceImageAccessDenied):
        await visual.resolve_reference_images([embed_id], {
            "user_id": "alice", "cache_service": cache, "directus_service": directus,
            "encryption_service": object(),
        })


# contract-test: supporting surface=rest_api assertions=shopping-search.relevance.truthful-fallback
@pytest.mark.asyncio
async def test_concurrent_execute_calls_do_not_share_visual_summary_by_request_id(monkeypatch):
    skill = object.__new__(shopping.SearchProductsSkill)
    skill.skill_name = "Search products"
    # Force interleaving: first call starts, second call finishes, first resumes.
    started, resume = asyncio.Event(), asyncio.Event()

    async def process(*, req, request_id, visual_evaluation_summaries, **kwargs):
        if req["query"] == "first":
            visual_evaluation_summaries[request_id] = {"status": "partial"}
            started.set()
            await resume.wait()
        else:
            await started.wait()
            visual_evaluation_summaries[request_id] = {"status": "unavailable"}
            resume.set()
        return request_id, [], None

    monkeypatch.setattr(skill, "_process_single_request", process)
    first, second = await asyncio.gather(
        skill.execute([{"id": "same-id", "query": "first"}], secrets_manager=object()),
        skill.execute([{"id": "same-id", "query": "second"}], secrets_manager=object()),
    )
    assert first.results[0]["visual_evaluation"] == {"status": "partial"}
    assert second.results[0]["visual_evaluation"] == {"status": "unavailable"}


# contract-test: supporting surface=rest_api assertions=shopping-search.relevance.bounded,shopping-search.relevance.truthful-fallback
@pytest.mark.asyncio
async def test_slow_search_preserves_results_when_optional_visual_deadline_is_spent(monkeypatch):
    skill = object.__new__(shopping.SearchProductsSkill)
    product = {"product_id": "fabric", "title": "Blue fabric", "price_cents": 1299,
               "image_url": "https://cdn.example/fabric.jpg"}
    provider = AsyncMock(return_value=([SimpleNamespace(to_result_dict=lambda: dict(product))], {}))
    monkeypatch.setattr(shopping, "rewe_search", provider)
    monkeypatch.setattr(shopping, "sanitize_long_text_fields_in_payload", AsyncMock(return_value=[product]))
    monkeypatch.setattr(shopping, "resolve_reference_images", AsyncMock(return_value=[b"prepared"]))
    visual_call, text_call = AsyncMock(), AsyncMock()
    monkeypatch.setattr(shopping, "rank_products_visually", visual_call)
    monkeypatch.setattr(shopping, "rank_search_candidates", text_call)
    ticks = iter([0, 18, 18])
    monkeypatch.setattr(shopping, "time", SimpleNamespace(monotonic=lambda: next(ticks)))
    summaries = {}
    _id, items, error = await skill._process_single_request(
        {"query": "fabric", "reference_images": ["photo.png"], "relevance_criteria": "blue floral"},
        "slow", secrets_manager=object(), visual_evaluation_summaries=summaries,
    )
    assert error is None and items[0]["price_cents"] == 1299
    assert items[0]["visual_match"]["status"] == summaries["slow"]["status"] == "unavailable"
    visual_call.assert_not_awaited()
    text_call.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=shopping-search.relevance.bounded,shopping-search.relevance.truthful-fallback
@pytest.mark.asyncio
async def test_visual_timeout_cancels_provider_work_before_truthful_fallback(monkeypatch):
    prepared = visual.prepare_image(image_bytes())
    cancelled = asyncio.Event()
    monkeypatch.setattr(visual, "download_public_product_image", AsyncMock(return_value=prepared))
    monkeypatch.setattr(visual, "VISUAL_EVALUATION_SECONDS", .01)

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def evaluate_with_images(self, **kwargs):
            try:
                await asyncio.sleep(30)
            finally:
                cancelled.set()

    monkeypatch.setattr(visual, "JevDecisionClient", FakeClient)
    result = await visual.rank_products_visually(
        candidates=[{"title": "Fabric", "image_url": "https://cdn.example/fabric.jpg"}],
        reference_images=[prepared], relevance_criteria="blue", query="fabric", secrets_manager=None,
    )
    assert cancelled.is_set() and result.summary["status"] == "unavailable"
    assert result.candidates[0]["visual_match"]["status"] == "unavailable"


# contract-test: supporting surface=rest_api assertions=shopping-search.references.authorized
@pytest.mark.asyncio
async def test_owned_fresh_upload_recovers_after_cache_and_chat_embed_miss_without_renewing_expiry(monkeypatch):
    embed_id = str(uuid4())
    now = int(visual.time.time())
    record = {"embed_id": embed_id, "user_id": "alice", "created_at": now - 100,
              "expires_at": now - 100 + 86400, "content_type": "image/png",
              "files": {"original": {"s3_key": "encrypted-file"}}, "vault_wrapped_aes_key": "vault:v1:ciphertext"}
    request_internal = AsyncMock(return_value={"status": "success", "content": record})
    cache = SimpleNamespace(get_embed_from_cache=AsyncMock(return_value=None), set=AsyncMock(return_value=True))
    directus = SimpleNamespace(embed=SimpleNamespace(get_embed_by_id=AsyncMock(return_value=None)))
    decrypt = AsyncMock(return_value=SimpleNamespace(content=image_bytes()))
    monkeypatch.setattr(visual, "resolve_encrypted_image_embed", decrypt)
    images = await visual.resolve_reference_images([embed_id], {
        "user_id": "alice", "user_vault_key_id": "alice-key", "cache_service": cache,
        "encryption_service": object(), "directus_service": directus,
        "s3_service": SimpleNamespace(environment="development"), "internal_api_request": request_internal,
    })
    assert len(images) == 1
    request_internal.assert_awaited_once_with(
        "POST", "internal/uploads/resolve-image", payload={"embed_id": embed_id, "user_id": "alice"},
    )
    assert decrypt.await_args.kwargs["preloaded_records"] == {embed_id: record}
    assert cache.set.await_args.args == (f"embed:{embed_id}", record)
    assert 86298 <= cache.set.await_args.kwargs["ttl"] <= 86300
    assert record["expires_at"] == now - 100 + 86400


# contract-test: supporting surface=rest_api assertions=shopping-search.references.authorized
@pytest.mark.parametrize("fault", ["foreign", "expired", "future", "wrong-id", "renewed-expiry", "missing-metadata", "not-found"])
@pytest.mark.asyncio
async def test_fresh_upload_recovery_rejects_foreign_expired_or_invalid_records_before_decryption(monkeypatch, fault):
    from fastapi import HTTPException

    embed_id = str(uuid4())
    now = int(visual.time.time())
    record = {"embed_id": embed_id, "user_id": "alice", "created_at": now - 100,
              "expires_at": now - 100 + 86400, "content_type": "image/png",
              "files": {"original": {"s3_key": "encrypted-file"}}, "vault_wrapped_aes_key": "vault:v1:ciphertext"}
    if fault == "foreign":
        record["user_id"] = "other-user"
    elif fault == "expired":
        record.update(created_at=now - 86400, expires_at=now)
    elif fault == "future":
        record.update(created_at=now + 10, expires_at=now + 86410)
    elif fault == "wrong-id":
        record["embed_id"] = str(uuid4())
    elif fault == "renewed-expiry":
        record["expires_at"] += 100
    elif fault == "missing-metadata":
        record["files"] = {}
    request_internal = AsyncMock(return_value={"status": "success", "content": record})
    if fault == "not-found":
        request_internal.side_effect = HTTPException(status_code=404, detail="not found")
    cache = SimpleNamespace(get_embed_from_cache=AsyncMock(return_value=None), set=AsyncMock())
    directus = SimpleNamespace(embed=SimpleNamespace(get_embed_by_id=AsyncMock(return_value=None)))
    decrypt = AsyncMock()
    monkeypatch.setattr(visual, "resolve_encrypted_image_embed", decrypt)
    with pytest.raises(visual.ReferenceImageAccessDenied):
        await visual.resolve_reference_images([embed_id], {
            "user_id": "alice", "user_vault_key_id": "alice-key", "cache_service": cache,
            "encryption_service": object(), "directus_service": directus,
            "s3_service": SimpleNamespace(environment="development"), "internal_api_request": request_internal,
        })
    decrypt.assert_not_awaited()
    cache.set.assert_not_awaited()
