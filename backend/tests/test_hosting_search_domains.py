"""Focused, offline contract checks for grouped hosting domain discovery."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from backend.apps.hosting.skills import search_domains as skill_module
from backend.apps.hosting.skills.search_domains import SearchDomainsSkill
from backend.shared.providers.gandi import DomainPriceProduct, DomainPriceTier, DomainResult, DomainSearchResult
from backend.shared.python_utils.search_relevance import SearchRelevanceRankingResult


def domain(name: str, status: str, **kwargs: Any) -> DomainResult:
    return DomainResult(
        domain_ascii=name, domain_unicode=name, availability=status,
        currency=kwargs.pop("currency", "EUR"), country=kwargs.pop("country", "DE"), **kwargs,
    )


class Provider:
    def __init__(self, *, lookup: dict[str, DomainResult] | None = None,
                 suggestions: dict[str | None, list[DomainResult] | Exception] | None = None) -> None:
        self.lookups = lookup or {}
        self.suggestions = suggestions or {}
        self.calls: list[tuple[str, Any]] = []

    async def lookup(self, name: str, **kwargs: Any) -> DomainResult:
        self.calls.append(("lookup", name))
        return self.lookups[name]

    async def search(self, query: str, *, tld: str | None = None, **kwargs: Any) -> DomainSearchResult:
        self.calls.append(("search", tld))
        results = self.suggestions.get(tld, [])
        if isinstance(results, Exception):
            raise results
        return DomainSearchResult(query=query, results=results)


def skill() -> SearchDomainsSkill:
    return SearchDomainsSkill(None, "hosting", "search_domains", "Domain search", "Search domains")


# contract-test: supporting surface=rest_api assertions=hosting-domains.availability.selection,hosting-domains.results.partial-and-safe
@pytest.mark.asyncio
async def test_default_available_selection_tops_up_only_checked_unavailable() -> None:
    provider = Provider(suggestions={None: [
        domain("used.com", "unavailable"), domain("first.com", "available"),
        domain("uncertain.com", "unknown", error="availability_missing"),
        domain("second.com", "available"), domain("used2.com", "unavailable"),
    ]})
    response = await skill().execute(requests=[{"query": "ideas", "max_results": 3}], provider_client=provider)
    group = response.results[0]
    assert response.success
    assert group["country"] == "DE" and group["currency"] == "EUR"
    assert [item["domain_ascii"] for item in group["results"]] == ["first.com", "second.com", "used.com"]
    assert len(group["checked_results"]) == 5
    assert group["partial"]


# contract-test: supporting surface=rest_api assertions=hosting-domains.availability.selection
@pytest.mark.asyncio
async def test_available_only_and_all_keep_distinct_policies() -> None:
    children = [domain("used.com", "unavailable"), domain("open.com", "available")]
    provider = Provider(suggestions={None: children})
    response = await skill().execute(requests=[
        {"id": "only", "query": "names", "availability": "available_only"},
        {"id": 7, "query": "names", "availability": "all"},
    ], provider_client=provider)
    only, all_group = response.results
    assert only["id"] == "only" and [x["domain_ascii"] for x in only["results"]] == ["open.com"]
    assert all_group["id"] == 7
    assert [x["domain_ascii"] for x in all_group["results"]] == ["used.com", "open.com"]


# contract-test: supporting surface=rest_api assertions=hosting-domains.lookup.exact,hosting-domains.availability.selection
@pytest.mark.asyncio
async def test_exact_idn_lookup_and_unavailable_diagnostic() -> None:
    provider = Provider(lookup={"xn--bcher-kva.example": domain("xn--bcher-kva.example", "unavailable")})
    response = await skill().execute(requests=[{
        "query": "bücher.example", "availability": "available_only",
    }], provider_client=provider)
    group = response.results[0]
    assert provider.calls == [("lookup", "xn--bcher-kva.example")]
    assert group["results"] == [] and group["warnings"]
    assert group["checked_results"][0]["domain_unicode"] == "bücher.example"
    assert group["checked_results"][0]["url"].startswith("https://shop.gandi.net/")


# contract-test: supporting surface=rest_api assertions=hosting-domains.lookup.exact,hosting-domains.availability.selection
@pytest.mark.asyncio
async def test_short_name_tlds_check_exact_first_then_dedupe_suggestions() -> None:
    provider = Provider(
        lookup={
            "cedar.com": domain("cedar.com", "unavailable"),
            "cedar.net": domain("cedar.net", "available"),
        },
        suggestions={
            "com": [domain("cedar.com", "unavailable"), domain("cedars.com", "available")],
            "net": [domain("cedar.net", "available"), domain("cedars.net", "available")],
        },
    )
    response = await skill().execute(requests=[{
        "query": "cedar", "tlds": [".COM", "com", ".net"], "max_results": 3,
    }], provider_client=provider)
    group = response.results[0]
    assert provider.calls[:2] == [("lookup", "cedar.com"), ("lookup", "cedar.net")]
    assert provider.calls[2:] == [("search", "com"), ("search", "net")]
    assert [x["domain_ascii"] for x in group["checked_results"]] == [
        "cedar.com", "cedar.net", "cedars.com", "cedars.net",
    ]
    assert [x["domain_ascii"] for x in group["results"]] == ["cedar.net", "cedars.com", "cedars.net"]


# contract-test: supporting surface=rest_api assertions=hosting-domains.request.validated,hosting-domains.results.partial-and-safe
@pytest.mark.asyncio
async def test_failed_sibling_and_partial_provider_result_preserve_good_group() -> None:
    provider = Provider(suggestions={None: [domain("works.com", "available")]})
    response = await skill().execute(requests=[
        {"id": "bad", "query": "bad..domain"},
        {"id": "good", "query": "works"},
        {"id": "unsupported", "query": "works", "currency": "XYZ"},
    ], provider_client=provider)
    assert response.success
    assert [group["id"] for group in response.results] == ["bad", "good", "unsupported"]
    assert response.results[0]["error"] == "Invalid domain search request"
    assert response.results[1]["results"][0]["domain_ascii"] == "works.com"
    assert response.results[2]["error"] == "Invalid domain search request"
    assert provider.calls == [("search", None)]


# contract-test: supporting surface=rest_api assertions=hosting-domains.provider.bounded-fallback,hosting-domains.results.partial-and-safe
@pytest.mark.asyncio
async def test_provider_failure_is_error_not_clean_empty() -> None:
    provider = Provider(suggestions={None: RuntimeError("private diagnostic")})
    response = await skill().execute(requests=[{"query": "idea"}], provider_client=provider)
    group = response.results[0]
    assert not response.success and group["partial"]
    assert group["error"] == "Domain provider unavailable"
    assert "private diagnostic" not in str(response.model_dump())


# contract-test: supporting surface=rest_api assertions=hosting-domains.quotes.truthful,hosting-domains.results.partial-and-safe
@pytest.mark.asyncio
async def test_available_with_missing_price_is_partial_and_quote_terms_stay_separate() -> None:
    priced = domain(
        "priced.com", "available", premium=True, phase="golive",
        registration=[DomainPriceProduct(process="create", tiers=[DomainPriceTier(
            duration_unit="year", min_duration=1, max_duration=1,
            price_before_taxes=12.0, price_after_taxes=14.28,
            discount=True, normal_price_after_taxes=20.54,
        )])],
        renewal=[DomainPriceProduct(process="renew", tiers=[DomainPriceTier(
            duration_unit="year", min_duration=1, max_duration=1,
            price_after_taxes=47.60,
        )])],
        pricing_status="priced",
    )
    provider = Provider(suggestions={None: [priced, domain("unpriced.com", "available", pricing_status="missing")]})
    response = await skill().execute(requests=[{"query": "names"}], provider_client=provider)
    group = response.results[0]
    assert group["partial"] and "Some registration prices were unavailable" in group["warnings"]
    first = group["results"][0]
    assert first["premium"] and first["registration_phase"] == "golive"
    assert first["registration_tiers"][0]["price_including_tax"] == 14.28
    assert first["registration_tiers"][0]["normal_price"] == 20.54
    assert first["renewal_tiers"][0]["price_including_tax"] == 47.60
    from backend.shared.python_utils.search_relevance import _bounded_candidate_projection

    # Large provider details must not push renewal evidence out of Jev's input.
    expanded = {**first, "registration_tiers": first["registration_tiers"] * 4,
                "renewal_tiers": first["renewal_tiers"] * 4}
    projection = _bounded_candidate_projection(skill_module.SearchDomainsSkill._projection(expanded))
    assert not projection.get("projection_truncated")
    assert projection["registration_quote_1"]["normal_price"] == 20.54
    assert projection["renewal_quote_1"]["price_including_tax"] == 47.60
    assert projection["registration_quote_1"]["minimum_term"] == 1


# contract-test: supporting surface=rest_api assertions=hosting-domains.relevance.evidenced
@pytest.mark.asyncio
async def test_relevance_floor_and_failed_ranking_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = Provider(suggestions={None: [
        domain("one.com", "available"), domain("two.com", "available"),
    ]})
    calls: list[dict[str, Any]] = []

    async def ranked(**kwargs: Any) -> Any:
        calls.append(kwargs)
        return SearchRelevanceRankingResult(
            candidates=list(reversed(kwargs["candidates"])), applied=True, scores=[4, 0],
        )

    monkeypatch.setattr(skill_module, "rank_search_candidates", ranked)
    response = await skill().execute(requests=[{
        "query": "ideas", "relevance_criteria": "Low renewal cost", "availability": "available_only",
    }], provider_client=provider)
    assert len(calls) == 1 and calls[0]["profile"] == "hosting_domains"
    assert [x["domain_ascii"] for x in response.results[0]["results"]] == ["two.com"]
    assert [x["domain_ascii"] for x in response.results[0]["checked_results"]] == ["two.com"]

    async def failed(**kwargs: Any) -> Any:
        raise RuntimeError("ranking offline")

    monkeypatch.setattr(skill_module, "rank_search_candidates", failed)
    fallback = await skill().execute(requests=[{
        "query": "ideas", "relevance_criteria": "Low renewal cost",
    }], provider_client=provider)
    assert [x["domain_ascii"] for x in fallback.results[0]["results"]] == ["one.com", "two.com"]


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [
    {"query": ""}, {"query": "bad..name"}, {"query": "ok", "max_results": 21},
    {"query": "ok", "max_results": 0}, {"query": "ok", "max_results": True},
    {"query": "ok", "tlds": ["a", "b", "c", "d", "e", "f"]},
    {"query": "ok", "tlds": ["bad..tld"]},
    {"query": "ok", "relevance_criteria": "x" * 1001},
])
# contract-test: supporting surface=rest_api assertions=hosting-domains.request.validated
async def test_invalid_group_never_calls_provider(bad: dict[str, Any]) -> None:
    provider = Provider()
    response = await skill().execute(requests=[bad], provider_client=provider)
    assert response.results[0]["error"] == "Invalid domain search request"
    assert not provider.calls


# contract-test: supporting surface=rest_api assertions=hosting-domains.request.validated
@pytest.mark.asyncio
async def test_duplicate_request_ids_rejected_before_provider_calls() -> None:
    provider = Provider()
    response = await skill().execute(requests=[
        {"id": "same", "query": "first"}, {"id": "same", "query": "second"},
    ], provider_client=provider)
    assert response.error == "Duplicate request IDs"
    assert not provider.calls


# contract-test: supporting surface=rest_api assertions=hosting-domains.request.validated
@pytest.mark.asyncio
async def test_non_iso_country_and_mismatched_provider_currency_are_rejected() -> None:
    provider = Provider(lookup={"example.com": domain("example.com", "available", currency="USD")})
    invalid = await skill().execute(requests=[{"query": "example.com", "country": "ZZ"}], provider_client=provider)
    assert invalid.error == "Invalid domain search request"
    assert invalid.results[0]["error"] == "Invalid domain search request"
    assert not provider.calls
    wrong_quote = await skill().execute(requests=[{"query": "example.com"}], provider_client=provider)
    assert wrong_quote.results[0]["error"] == "Domain provider unavailable"
    assert wrong_quote.results[0]["partial"]


# contract-test: supporting surface=rest_api assertions=hosting-domains.results.partial-and-safe,hosting-domains.provider.bounded-fallback
@pytest.mark.asyncio
async def test_deadline_preserves_completed_sibling_check(monkeypatch: pytest.MonkeyPatch) -> None:
    class SlowProvider(Provider):
        async def lookup(self, name: str, **kwargs: Any) -> DomainResult:
            if name == "slow.net":
                await asyncio.sleep(1)
            return await super().lookup(name, **kwargs)

    monkeypatch.setattr(skill_module, "GROUP_DEADLINE_SECONDS", 0.1)
    provider = SlowProvider(lookup={"fast.com": domain("fast.com", "available")})
    response = await skill().execute(requests=[{
        "query": "fast", "tlds": ["com", "net"], "max_results": 1,
    }], provider_client=provider)
    group = response.results[0]
    assert group["partial"] and group["warnings"]
    assert [child["domain_ascii"] for child in group["checked_results"]] == ["fast.com"]
    assert [child["domain_ascii"] for child in group["results"]] == ["fast.com"]


# contract-test: supporting surface=rest_api assertions=hosting-domains.availability.selection,hosting-domains.relevance.evidenced
@pytest.mark.asyncio
async def test_five_tlds_never_exceed_forty_checked_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    tlds = ["com", "net", "org", "io", "ai"]
    provider = Provider(
        lookup={f"cedar.{suffix}": domain(f"cedar.{suffix}", "unavailable") for suffix in tlds},
        suggestions={suffix: [domain(f"cedar{i}.{suffix}", "available") for i in range(20)] for suffix in tlds},
    )
    counts: list[int] = []

    async def rank(**kwargs: Any) -> SearchRelevanceRankingResult[dict[str, Any]]:
        counts.append(len(kwargs["candidates"]))
        return SearchRelevanceRankingResult(candidates=list(kwargs["candidates"]), applied=False)

    monkeypatch.setattr(skill_module, "rank_search_candidates", rank)
    response = await skill().execute(requests=[{
        "query": "cedar", "tlds": tlds, "max_results": 20,
        "relevance_criteria": "low renewal cost",
    }], provider_client=provider)
    group = response.results[0]
    assert counts == [40]
    assert len(group["checked_results"]) == 40
    assert len(group["results"]) == 20


# contract-test: supporting surface=rest_api assertions=hosting-domains.request.validated,hosting-domains.results.partial-and-safe
@pytest.mark.asyncio
async def test_five_groups_start_together_with_two_shared_provider_slots() -> None:
    class ConcurrentSkill(SearchDomainsSkill):
        def __init__(self) -> None:
            super().__init__(None, "hosting", "search_domains", "Domain search", "Search domains")
            self.entered_groups = 0
            self.all_groups_entered = asyncio.Event()

        async def _run_group(self, group, item, client, semaphore, secrets_manager):
            self.entered_groups += 1
            if self.entered_groups == 5:
                self.all_groups_entered.set()
            await self.all_groups_entered.wait()
            return await super()._run_group(group, item, client, semaphore, secrets_manager)

    class GatedProvider(Provider):
        def __init__(self) -> None:
            super().__init__()
            self.active = 0
            self.max_active = 0
            self.pair_started = asyncio.Event()
            self.release = asyncio.Event()

        async def lookup(self, name: str, **kwargs: Any) -> DomainResult:
            self.calls.append(("lookup", name))
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            if self.active == 2:
                self.pair_started.set()
            try:
                await self.release.wait()
                return domain(name, "available")
            finally:
                self.active -= 1

    queries = ["one.com", "two.net", "three.org", "four.io", "five.ai"]
    identifiers = ["first", 2, "third", 4, "fifth"]
    provider = GatedProvider()
    search = ConcurrentSkill()
    work = asyncio.create_task(search.execute(
        requests=[{"id": identifier, "query": query, "max_results": 1}
                  for identifier, query in zip(identifiers, queries)],
        provider_client=provider,
    ))
    try:
        await asyncio.wait_for(provider.pair_started.wait(), timeout=2)
        assert search.entered_groups == 5
        # Both upstream slots stay occupied until the gate opens. Additional
        # groups may run, but cannot start a third provider operation.
        await asyncio.sleep(0)
        assert provider.active == 2
        assert len(provider.calls) == 2
    finally:
        provider.release.set()
    response = await asyncio.wait_for(work, timeout=2)

    assert provider.max_active == 2
    assert len(provider.calls) == 5
    assert [group["id"] for group in response.results] == identifiers
    assert [group["query"] for group in response.results] == queries
    assert [group["results"][0]["domain_ascii"] for group in response.results] == queries
