"""Shopping price comparison across installed providers and the provider result cache.

Covers the exact-product filter, the condition filter, shipping-inclusive totals,
cheapest-first ordering for ``sort: price_asc`` through the generic delegate of
``shopping.search_products`` (runner faked at the client boundary, web source off),
and the short-lived result cache in provider dispatch. Synthetic shops and products only.
Architecture: docs/architecture/apps/instance-app-packages.md ("Price comparison", "Result cache").
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest
import yaml

from backend.shared.app_packages import delegate_skill, loader, provider_dispatch, result_cache
from backend.shared.app_packages.delegate_skill import InstalledProviderSkill
from backend.shared.app_packages.generic_contract import SKILL_REQUESTS_V1
from backend.shared.app_packages.price_comparison import (
    PROVIDER_SECONDS, compare_offers, matches_product, order_by_total_price,
)
from backend.shared.app_packages.runner_client import RunnerResult
from backend.tests.app_packages_test_support import enable, manifest, write_package, write_registry

APP, SKILL = "shopping", "search_products"
PACKAGE = "my.shops"
SHOP_A, SHOP_B = "my_provider", "my_other_provider"


def _offer(title: str, price: float, shipping: Any = None, **extra: Any) -> Dict[str, Any]:
    offer: Dict[str, Any] = {"title": title, "price_amount": price, "currency": "EUR",
                             "purchase_url": f"https://example.org/{title.replace(' ', '-')}", **extra}
    if shipping is not None:
        offer["shipping_amount"] = shipping
    return offer


# --------------------------------------------------------------------------- pure comparison

# contract-test: supporting surface=rest_api assertions=shopping-search.compare.exact-product
def test_exact_product_keeps_brand_and_digit_model_tokens_only():
    assert matches_product({"title": "Example Audio X100 dynamic microphone"}, "Example Audio", "X100")
    assert not matches_product({"title": "Example Audio X10 dynamic microphone"}, "Example Audio", "X100")
    assert not matches_product({"title": "Example Audio X100S dynamic microphone"}, "Example Audio", "X100")
    assert not matches_product({"title": "Other Brand X100 stand"}, "Example Audio", "X100")
    # A model without digits does not filter; the brand still does.
    assert matches_product({"title": "Example Audio wrist rest"}, "Example Audio", "Wrist Rest Pad")


# contract-test: supporting surface=rest_api assertions=shopping-search.compare.total-price
def test_totals_include_shipping_and_order_cheapest_first():
    offers = [
        _offer("Example Audio X100", 52.0, shipping=6.0),       # total 58
        _offer("Example Audio X100", 55.0, shipping=0.0),       # total 55
        _offer("Example Audio X100", 54.0),                     # shipping unknown -> 54
        {"title": "Example Audio X100 no price", "purchase_url": "https://example.org/x"},
    ]
    kept, summary = compare_offers(offers, {"sort": "price_asc", "brand": "Example Audio", "model": "X100"})
    assert [offer.get("total_amount", offer.get("price_amount")) for offer in kept] == [54.0, 55.0, 58.0, None]
    assert kept[0]["shipping_known"] is False and kept[1]["shipping_known"] is True
    assert summary == {"offers_considered": 4, "offers_kept": 4, "exact_product": "Example Audio X100",
                       "exact_product_found": True, "order": "total_price_incl_shipping"}


# contract-test: supporting surface=rest_api assertions=shopping-search.compare.exact-product,shopping-search.compare.condition
def test_other_models_accessories_and_wrong_condition_are_dropped():
    offers = [
        _offer("Example Audio X100 microphone", 50.0, shipping=0.0, condition="new"),
        _offer("Example Audio X100 microphone", 30.0, condition="used"),
        _offer("Example Audio X10 microphone", 20.0, condition="new"),
        _offer("Boom arm for microphones", 15.0, condition="new"),
    ]
    used, _ = compare_offers(offers, {"sort": "price_asc", "brand": "Example Audio", "model": "X100",
                                      "condition": "used"})
    assert [offer["price_amount"] for offer in used] == [30.0]
    anything, _ = compare_offers(offers, {"sort": "price_asc", "brand": "Example Audio", "model": "X100"})
    assert [offer["price_amount"] for offer in anything] == [30.0, 50.0]


# contract-test: supporting surface=rest_api assertions=shopping-search.compare.exact-product
def test_no_exact_match_keeps_similar_offers_flagged():
    offers = [_offer("Example Audio X10 microphone", 20.0)]
    kept, summary = compare_offers(offers, {"brand": "Example Audio", "model": "X100"})
    assert len(kept) == 1 and summary["exact_product_found"] is False


# contract-test: supporting surface=rest_api assertions=shopping-search.compare.total-price
def test_other_currency_and_unpriced_offers_follow_in_their_order():
    offers = [_offer("A", 10.0, currency="USD"), _offer("B", 30.0), _offer("C", 20.0), _offer("D", 40.0)]
    assert [offer["title"] for offer in order_by_total_price(offers)] == ["C", "B", "D", "A"]


# --------------------------------------------------------------------------- delegate integration

def _entry(provider_id: str, name: str) -> Dict[str, Any]:
    return {"app": APP, "skill": SKILL, "contract": SKILL_REQUESTS_V1, "id": provider_id, "name": name,
            "runtime": "executable", "entrypoint": "bin/provider"}


@pytest.fixture
def shops(monkeypatch, tmp_path: Path):
    sha = write_package(tmp_path, manifest(package_id=PACKAGE, providers=[
        _entry(SHOP_A, "Example Shop"), _entry(SHOP_B, "Example Market")]), package_id=PACKAGE)
    write_registry(tmp_path, {PACKAGE: {"version": "1.0.0", "sha256": sha}})
    enable(monkeypatch, tmp_path)
    loader.reset_installed_packages_cache()
    delegate_skill.resolve_original_skill_models.cache_clear()
    # The web source is a separate source with its own tests; keep this run offline.
    monkeypatch.setattr(delegate_skill, "delegate_web_kind", lambda *_args: None)
    yield tmp_path
    loader.reset_installed_packages_cache()


def _fake_runner(monkeypatch, results: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    calls: List[Dict[str, Any]] = []

    async def fake_run_provider(provider, input_item, secrets, **_kwargs):
        calls.append({"provider": provider.provider_id, "input": input_item})
        return RunnerResult(ok=True, results=results[provider.provider_id])

    monkeypatch.setattr(provider_dispatch, "run_provider", fake_run_provider)
    return calls


def _delegate() -> InstalledProviderSkill:
    raw = yaml.safe_load((loader.BUILTIN_APPS_DIR / APP / "app.yml").read_text(encoding="utf-8"))
    original = str(next(s for s in raw["skills"] if s["id"] == SKILL)["class_path"]).strip()
    skill = object.__new__(InstalledProviderSkill)
    skill.app_id, skill.skill_id = APP, SKILL
    skill.app = SimpleNamespace(get_skill_by_id=lambda _sid: SimpleNamespace(delegated_class_path=original))
    return skill


# contract-test: supporting surface=rest_api assertions=shopping-search.compare.total-price,shopping-search.compare.exact-product
def test_price_asc_merges_providers_cheapest_total_first(shops, monkeypatch):
    calls = _fake_runner(monkeypatch, {
        SHOP_A: [_offer("Example Audio X100 microphone", 52.0, shipping=6.0, condition="new"),
                 _offer("Example Audio X100 boom arm bundle", 80.0, shipping=0.0, condition="new"),
                 _offer("Example Audio X10 microphone", 25.0, shipping=0.0, condition="new")],
        SHOP_B: [_offer("Example Audio X100 microphone", 55.0, shipping=0.0, condition="new"),
                 _offer("Example Audio X100 microphone", 31.0, shipping=5.5, condition="used")],
    })
    response = asyncio.run(_delegate().execute(requests=[{
        "query": "Example Audio X100 microphone", "brand": "Example Audio", "model": "X100",
        "sort": "price_asc", "max_results": 3,
    }]))
    group = response["results"][0]
    assert [offer["total_amount"] for offer in group["results"]] == [36.5, 55.0, 58.0]
    assert [offer["condition"] for offer in group["results"]] == ["used", "new", "new"]
    assert group["price_comparison"]["order"] == "total_price_incl_shipping"
    # Providers are asked for a wider pool than the final list.
    assert {call["input"]["max_results"] for call in calls} == {20}
    assert {call["input"]["condition"] for call in calls} == {"any"}


# contract-test: supporting surface=rest_api assertions=shopping-search.compare.condition
def test_used_nearby_request_reaches_providers_with_location(shops, monkeypatch):
    calls = _fake_runner(monkeypatch, {SHOP_A: [], SHOP_B: [_offer("Example Audio X100", 30.0, condition="used")]})
    response = asyncio.run(_delegate().execute(requests=[{
        "query": "Example Audio X100", "condition": "used", "location": "10115", "radius_km": 20,
    }]))
    assert {(call["input"]["location"], call["input"]["radius_km"]) for call in calls} == {("10115", 20)}
    assert response["results"][0]["results"][0]["condition"] == "used"


# contract-test: supporting surface=rest_api assertions=shopping-search.providers.slow-provider-alone
def test_slow_provider_fails_alone_and_the_other_offers_stay(shops, monkeypatch):
    timeouts: Dict[str, Any] = {}

    async def fake_run_provider(provider, input_item, secrets, **kwargs):
        timeouts[provider.provider_id] = kwargs.get("timeout_seconds")
        if provider.provider_id == SHOP_B:
            return RunnerResult(ok=False, error_code="TIMEOUT")
        return RunnerResult(ok=True, results=[_offer("Example Audio X100", 40.0, shipping=0.0)])

    monkeypatch.setattr(provider_dispatch, "run_provider", fake_run_provider)
    response = asyncio.run(_delegate().execute(requests=[{
        "query": "Example Audio X100", "brand": "Example Audio", "model": "X100", "sort": "price_asc",
    }]))
    group = response["results"][0]
    # Every provider of a compared search runs within the skill envelope.
    assert timeouts == {SHOP_A: PROVIDER_SECONDS, SHOP_B: PROVIDER_SECONDS} and PROVIDER_SECONDS < 20
    assert [offer["total_amount"] for offer in group["results"]] == [40.0]
    assert not group.get("error")


# contract-test: supporting surface=rest_api assertions=shopping-search.providers.slow-provider-alone
def test_dispatch_without_a_limit_keeps_the_runner_default(shops, monkeypatch):
    seen: List[Dict[str, Any]] = []

    async def fake_run_provider(provider, input_item, secrets, **kwargs):
        seen.append(kwargs)
        return RunnerResult(ok=True, results=[])

    monkeypatch.setattr(provider_dispatch, "run_provider", fake_run_provider)
    asyncio.run(provider_dispatch.run_installed_providers(APP, SKILL, [SHOP_A], {"query": "x"}, None))
    assert seen == [{}]


# --------------------------------------------------------------------------- result cache

# contract-test: supporting surface=rest_api assertions=shopping-search.providers.repeat-cached
def test_same_search_is_answered_from_the_result_cache(shops, monkeypatch):
    store: Dict[str, Any] = {}

    async def fake_cached(key):
        return store.get(key)

    async def fake_store(key, results):
        store[key] = [dict(result) for result in results]

    monkeypatch.setattr(provider_dispatch, "cached_results", fake_cached)
    monkeypatch.setattr(provider_dispatch, "store_results", fake_store)
    calls = _fake_runner(monkeypatch, {SHOP_A: [_offer("Example Audio X100", 50.0)], SHOP_B: []})
    item = {"query": "Example Audio X100", "max_results": 5}
    first = asyncio.run(provider_dispatch.run_installed_providers(APP, SKILL, [SHOP_A], item, None))
    second = asyncio.run(provider_dispatch.run_installed_providers(APP, SKILL, [SHOP_A], item, None))
    assert len(calls) == 1
    assert [o.results[0]["title"] for o in first] == [o.results[0]["title"] for o in second]


# contract-test: supporting surface=rest_api assertions=shopping-search.providers.repeat-cached
def test_result_cache_key_ignores_secrets_and_changes_with_input_and_version(shops):
    provider = loader.get_installed_provider(APP, SKILL, SHOP_A)
    key = result_cache.result_cache_key(provider, {"query": "a"})
    assert key == result_cache.result_cache_key(provider, {"query": "a"})
    assert key != result_cache.result_cache_key(provider, {"query": "b"})
    assert key != result_cache.result_cache_key(replace(provider, package_version="1.0.1"), {"query": "a"})
    assert key.startswith(result_cache.RESULT_CACHE_PREFIX) and "query" not in key


# contract-test: supporting surface=rest_api assertions=shopping-search.providers.repeat-cached
def test_result_cache_lifetime_is_configurable(monkeypatch):
    monkeypatch.setenv(result_cache.RESULT_CACHE_ENV, "60")
    assert result_cache.result_cache_seconds() == 60
    monkeypatch.setenv(result_cache.RESULT_CACHE_ENV, "0")
    assert result_cache.result_cache_seconds() == 0
    monkeypatch.delenv(result_cache.RESULT_CACHE_ENV)
    assert result_cache.result_cache_seconds() == result_cache.DEFAULT_RESULT_CACHE_SECONDS
