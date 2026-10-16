"""Boundaries for anonymous trademark reads and explicit regional coverage."""
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from backend.apps.business.skills.search_trademarks import SearchTrademarksSkill
from backend.shared.providers.trademarks import TrademarkProviderError, USPTOTrademarkClient


def skill():
    return SearchTrademarksSkill(app=None, app_id="business", skill_id="search_trademarks",
                                skill_name="Search trademarks", skill_description="Search names")


def response(records=None, total=None, **extra):
    records = records if records is not None else [{
        "id": "72318279", "wordmark": "ADIDAS", "alive": True, "registered": True,
        "ownerName": ["adidas AG"], "internationalClass": ["IC 018", "025."],
        "goodsAndServices": ["Tote bags"], "ownerAddress": "Excluded private field",
    }]
    return {"hits": {"totalValue": len(records) if total is None else total,
                     "totalRelation": "eq", "hits": [{"source": row} for row in records]},
            "timedOut": False, "shardsFailed": 0, **extra}


# contract-test: supporting surface=rest_api assertions=trademarks.request,trademarks.evidence
@pytest.mark.asyncio
async def test_normalized_records_and_structured_exact_filters():
    def handle(request):
        payload = json.loads(request.content)
        assert payload["query"]["bool"]["must"] == [{"term": {"wordmarkExact": {"value": "adidas"}}}]
        assert payload["query"]["bool"]["filter"] == [{"term": {"LD": "true"}}, {"terms": {"IC": ["018"]}}]
        assert "Authorization" not in request.headers
        return httpx.Response(200, json=response(total=20))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        data = await USPTOTrademarkClient(http_client=http).search(
            "Adidas", nice_classes=[18], status="active", match="exact", max_results=2)
    row = data["results"][0]
    assert row["status"] == "registered"
    assert row["name_match"] == "exact"
    assert row["nice_classes"] == [18, 25]
    assert row["source_url"].startswith("https://tsdr.uspto.gov/#caseNumber=72318279")
    assert "ownerAddress" not in row
    assert data["more_results"] is True
    assert data["partial"] is False


# contract-test: supporting surface=rest_api assertions=trademarks.provider,trademarks.coverage
@pytest.mark.asyncio
@pytest.mark.parametrize("code,body,error", [
    (429, {}, "rate_limited"), (403, {}, "access_restricted"),
    (202, {}, "access_restricted"), (500, {}, "provider_unavailable"),
    (200, {}, "invalid_response"), (200, response([{}], total=1), "invalid_response"),
])
async def test_failures_are_not_empty_successes(code, body, error):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(code, json=body))) as http:
        with pytest.raises(TrademarkProviderError) as caught:
            await USPTOTrademarkClient(http_client=http).search(
                "Private proposed name", nice_classes=[], status="active", match="similar", max_results=2)
    assert caught.value.code == error
    assert "Private proposed" not in str(caught.value)


# contract-test: supporting surface=rest_api assertions=trademarks.coverage
@pytest.mark.asyncio
@pytest.mark.parametrize("body,partial", [(response([], total=0), False), (response(timedOut=True), True), (response([{}, {"id": "72318279", "wordmark": "ADIDAS"}], total=2), True)])
async def test_genuine_zero_and_incomplete_response(body, partial):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))) as http:
        data = await USPTOTrademarkClient(http_client=http).search(
            "Adidas", nice_classes=[], status="all", match="similar", max_results=3)
    assert data["partial"] is partial
    assert len(data["results"]) == (0 if body["hits"]["totalValue"] == 0 else 1)


class FakeProvider:
    provider_name = "USPTO"
    def __init__(self, failure=False):
        self.calls = []
        self.failure = failure
    async def search(self, query, **kwargs):
        self.calls.append((query, kwargs))
        if self.failure:
            raise TrademarkProviderError("rate_limited", "Try later")
        return {"results": [], "total_matches": 0, "more_results": False,
                "partial": False, "checked_at": "2026-10-11T00:00:00Z"}


# contract-test: supporting surface=rest_api assertions=trademarks.coverage
@pytest.mark.asyncio
async def test_regions_do_not_silently_fall_back_to_us():
    provider = FakeProvider()
    data = await skill().execute(queries=["Name"], regions=["EU", "DE", "WORLDWIDE"], provider_client=provider)
    assert not provider.calls
    assert data.success is False
    assert data.partial is True
    assert all(row["status"] == "unsupported" for row in data.coverage)
    assert data.error_code == "search_unavailable"


# contract-test: supporting surface=rest_api assertions=trademarks.coverage,trademarks.evidence
@pytest.mark.asyncio
async def test_mixed_coverage_and_no_results_remain_distinct():
    provider = FakeProvider()
    data = await skill().execute(queries=[" Name ", "Name"], regions=["US", "DE", "US"], provider_client=provider)
    assert len(provider.calls) == 1
    assert data.success is True and data.partial is True
    assert [row["status"] for row in data.coverage] == ["searched", "unsupported"]
    assert data.coverage[0]["total_matches"] == 0
    assert "legal availability" in data.limitation
    failed = await skill().execute(queries=["Name"], regions=["US"], provider_client=FakeProvider(True))
    assert not failed.success
    assert failed.coverage[0]["error_code"] == "rate_limited"


# contract-test: supporting surface=gui.web assertions=trademarks.coverage,trademarks.parity
@pytest.mark.asyncio
async def test_saved_embed_retains_zero_matches_and_regional_coverage():
    from backend.core.api.app.services.embed_service import _flatten_for_toon_tabular
    from toon_format import decode, encode

    data = await skill().execute(queries=["Name"], regions=["US", "DE"], provider_client=FakeProvider())
    payload = data.model_dump()
    # Non-result-list responses retain the full response through the shared embed path.
    assert "results" not in payload
    saved = decode(encode(_flatten_for_toon_tabular({"results": [payload]})))
    restored = saved["results"][0]
    assert restored["matches"] == []
    assert restored["regions"] == "US|DE"
    assert restored["coverage"][0]["total_matches"] == 0
    assert restored["coverage"][1]["status"] == "unsupported"
    assert restored["partial"] is True
    assert "legal availability" in restored["limitation"]
    assert restored["status_filter"] == "active"
    assert restored["match"] == "similar"


# contract-test: supporting surface=rest_api assertions=trademarks.request
@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [
    {}, {"queries": []}, {"queries": [" "]}, {"queries": ["a\nb"]},
    {"queries": ["a"] * 4}, {"regions": []}, {"regions": ["GB"]},
    {"nice_classes": [0]}, {"nice_classes": [46]}, {"nice_classes": [True]},
    {"max_results": 21}, {"max_results": True}, {"nice_classes": False},
])
async def test_invalid_requests_never_call_provider(invalid):
    provider = FakeProvider()
    args = {"queries": ["Name"], "regions": ["US"], **invalid}
    if not invalid:
        args.pop("regions")
    data = await skill().execute(**args, provider_client=provider)
    assert not provider.calls
    assert data.error_code == "invalid_request"


# contract-test: supporting surface=cli assertions=trademarks.request,trademarks.coverage,trademarks.parity,brand-naming.flow
@pytest.mark.asyncio
async def test_ai_execution_preserves_native_name_region_and_class_arrays(monkeypatch):
    from backend.apps.ai.processing import skill_executor
    execute = AsyncMock(return_value={"success": True, "matches": [], "coverage": []})
    monkeypatch.setattr(skill_executor, "execute_skill", execute)
    args = {"queries": ["Tidely", "Stillsum"], "regions": ["US", "DE"], "nice_classes": [9, 42], "max_results": 5}
    result = await skill_executor.execute_skill_with_multiple_requests("business", "search_trademarks", args)
    execute.assert_awaited_once()
    assert execute.await_args.args[:3] == ("business", "search_trademarks", args)
    assert result == [{"success": True, "matches": [], "coverage": []}]

