"""Usage-based billing of events.search: web search requests plus extraction tokens, never a flat fee.

Exercises the shared billing rule, the skill's per-group usage and the chat and
REST charge helpers without network, accounts or money effects.
"""
from __future__ import annotations

import ast
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException

from backend.apps.events.skills import search_skill
from backend.apps.events.skills.search_skill import SearchRequest, SearchSkill
from backend.shared.app_packages.provider_dispatch import InstalledProviderOutcome
from backend.shared.python_utils import web_source_billing as billing

ROOT = Path(__file__).resolve().parents[2]
MERCURY = {"tokens": {"input": {"per_credit_unit": 3335}, "output": {"per_credit_unit": 955}}}
PRICES = billing.WebSourcePrices(search_request_credits=10, model="inception/mercury-3", token_rules=MERCURY)
WEB_USAGE = {"web_search_requests": 1, "model": "inception/mercury-3", "input_tokens": 24868, "output_tokens": 6800}


def _helpers(relative_path: str, names: List[str]) -> SimpleNamespace:
    """Load exact helper bodies, excluding service startup and unrelated imports."""
    tree = ast.parse((ROOT / relative_path).read_text())
    nodes = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
             and node.name in names]
    assert {node.name for node in nodes} == set(names)
    namespace = dict(Any=Any, Dict=Dict, List=List, Optional=Optional, Tuple=Tuple, HTTPException=HTTPException,
                     _as_dict=lambda value: value if isinstance(value, dict) else {},
                     _dict_value=lambda value: value if isinstance(value, dict) else {},
                     logger=logging.getLogger(__name__))
    nodes = [node for node in tree.body if isinstance(node, ast.Assign) and any(
        isinstance(target, ast.Name) and target.id == "VARIABLE_RESULT_BILLING_SKILLS" for target in node.targets
    )] + nodes
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
                              *nodes], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), relative_path, "exec"), namespace)
    return SimpleNamespace(**namespace)


@pytest.fixture
def rest():
    return _helpers("backend/core/api/app/routes/apps_api.py", [
        "get_variable_result_charge_items", "get_variable_result_usage_details",
        "get_variable_preflight_reserved_credits", "_coerce_nonnegative_credits",
    ])


@pytest.fixture
def assistant():
    return _helpers("backend/apps/ai/processing/main_processor.py", [
        "_get_result_declared_charge_items", "_get_result_declared_usage_details",
        "_get_variable_preflight_reserved_credits", "_coerce_nonnegative_credits",
    ])


def _group(identity: str, *, credits: int, results: Optional[list] = None, error: Optional[str] = None,
           providers: Optional[list] = None) -> Dict[str, Any]:
    rows = [{"title": "FOSDEM 2027", "provider_id": "web"}] if results is None else results
    group: Dict[str, Any] = {"id": identity, "results": rows, "providers": providers or ["web"],
                             "usage": {"credits_charged": credits, **WEB_USAGE}}
    if error:
        group["error"] = error
    return group


# contract-test: direct surface=rest_api assertions=events-search.billing.usage
def test_successful_web_item_costs_search_request_plus_tokens_floored_once():
    usage = billing.group_usage(has_results=True, failed=False, web=WEB_USAGE, prices=PRICES)
    # 10 (search) + 24868/3335 (7.46) + 6800/955 (7.12) = 24.58 -> 24
    assert usage == {"credits_charged": 24, **WEB_USAGE}


# contract-test: direct surface=rest_api assertions=events-search.billing.usage
@pytest.mark.parametrize("has_results,failed,web,expected", [
    (False, False, WEB_USAGE, 0),   # nothing found: free, even though the web was searched
    (True, True, WEB_USAGE, 0),     # an error: free
    (True, False, {}, 1),           # official schedule only: platform minimum
    (True, False, {"web_search_requests": 0, "input_tokens": 0, "output_tokens": 0}, 1),
])
def test_failed_empty_and_schedule_only_items(has_results, failed, web, expected):
    assert billing.group_usage(has_results=has_results, failed=failed, web=web, prices=PRICES)["credits_charged"] \
        == expected


# contract-test: direct surface=rest_api assertions=events-search.billing.usage
def test_launch_price_halves_the_token_part():
    launch = billing.WebSourcePrices(10, "inception/mercury-3",
                                     {"tokens": {"input": {"per_credit_unit": 6670}, "output": {"per_credit_unit": 1905}}})
    # 10 + 3.73 + 3.57 = 17.3 -> 17
    assert billing.group_usage(has_results=True, failed=False, web=WEB_USAGE, prices=launch)["credits_charged"] == 17


# contract-test: direct surface=rest_api assertions=events-search.billing.usage
@pytest.mark.asyncio
async def test_prices_come_from_the_search_provider_and_the_model():
    prices = await billing.fetch_web_source_prices(
        "inception/mercury-3", provider_pricing=AsyncMock(return_value={"per_request_credits": 10}),
        model_pricing=AsyncMock(return_value=MERCURY))
    assert prices == PRICES


# contract-test: direct surface=rest_api assertions=events-search.billing.usage
@pytest.mark.asyncio
@pytest.mark.parametrize("search,model", [
    (None, MERCURY), ({"per_request_credits": 0}, MERCURY), ({"per_request_credits": 10}, None),
    ({"per_request_credits": 10}, {"per_unit": {"credits": 1}}),
])
async def test_missing_prices_are_an_error_never_free(search, model):
    with pytest.raises(billing.WebSourcePricingError):
        await billing.fetch_web_source_prices("inception/mercury-3", provider_pricing=AsyncMock(return_value=search),
                                              model_pricing=AsyncMock(return_value=model))
    with pytest.raises(billing.WebSourcePricingError):
        await billing.fetch_web_source_prices(
            "inception/mercury-3", provider_pricing=AsyncMock(side_effect=httpx.ConnectError("down")),
            model_pricing=AsyncMock(return_value=MERCURY))


# contract-test: direct surface=rest_api assertions=events-search.billing.usage
def test_chat_and_rest_charge_only_successful_groups(rest, assistant, monkeypatch):
    from backend.shared.app_packages import billing as package_billing
    monkeypatch.setattr(package_billing, "is_installed_only_group",
                        lambda app, skill, group: group.get("providers") == ["my_provider"])
    groups = [
        _group("ok", credits=24),
        _group("failed", credits=24, error="Web search is unavailable."),
        _group("empty", credits=24, results=[]),
        _group("installed", credits=24, providers=["my_provider"],
               results=[{"title": "Community evening", "provider_id": "my_provider"}]),
        _group("schedule", credits=1, providers=["pretalx"]),
    ]
    assert rest.get_variable_result_charge_items("events", "search", {"results": groups}) == [(0, 24), (4, 1)]
    assert [(i, credits) for i, credits, _ in assistant._get_result_declared_charge_items(
        "events", "search", groups)] == [(0, 24), (4, 1)]


# contract-test: direct surface=rest_api assertions=events-search.billing.usage
def test_usage_details_and_reservation(rest, assistant):
    expected = {"model_used": "inception/mercury-3", "input_tokens": 24868, "output_tokens": 6800,
                "web_search_requests": 1}
    group = _group("ok", credits=24)
    assert assistant._get_result_declared_usage_details("events", "search", group) == expected
    assert rest.get_variable_result_usage_details("events", "search", {"results": [group]}, 0) == expected
    body = {"requests": [{"query": "open source conferences"}, {"query": "tech events"}]}
    assert rest.get_variable_preflight_reserved_credits("events", "search", body) == 100
    assert assistant._get_variable_preflight_reserved_credits("events", "search", body) == [50, 50]


# contract-test: direct surface=rest_api assertions=events-search.billing.usage,events-search.discovery.web-pages
@pytest.mark.anyio
async def test_skill_declares_web_usage_per_group(monkeypatch):
    skill = object.__new__(SearchSkill)
    monkeypatch.setattr(search_skill, "_installed_provider_labels", lambda: {})
    monkeypatch.setattr(search_skill, "fetch_web_source_prices", AsyncMock(return_value=PRICES))
    row = {"title": "FOSDEM 2027", "date_start": "2099-01-30", "url": "https://example.org/fosdem",
           "provider": "example.org", "provider_id": "web", "source_page_url": "https://example.org/list",
           "source_page_title": "Open source conferences"}
    monkeypatch.setattr(search_skill, "run_web_source", AsyncMock(side_effect=[
        InstalledProviderOutcome("web", results=[row], usage=WEB_USAGE),
        InstalledProviderOutcome("web", error="Web search is unavailable.", usage={**WEB_USAGE, "input_tokens": 0}),
    ]))
    response = await skill.execute(SearchRequest(requests=[
        {"id": "eu", "query": "open source conferences"}, {"id": "none", "query": "tech events"}]),
        secrets_manager=object())
    found, failed = response.results
    assert found["usage"] == {"credits_charged": 24, **WEB_USAGE}
    assert failed["usage"]["credits_charged"] == 0
    search_skill.fetch_web_source_prices.assert_awaited_once()  # loaded once per call


# contract-test: direct surface=rest_api assertions=events-search.billing.usage
@pytest.mark.anyio
async def test_web_is_not_searched_without_prices(monkeypatch):
    skill = object.__new__(SearchSkill)
    monkeypatch.setattr(search_skill, "_installed_provider_labels", lambda: {})
    monkeypatch.setattr(search_skill, "fetch_web_source_prices",
                        AsyncMock(side_effect=billing.WebSourcePricingError("no per-request price for web search")))
    web = AsyncMock(side_effect=AssertionError("must not search the web without prices"))
    monkeypatch.setattr(search_skill, "run_web_source", web)
    response = await skill.execute(SearchRequest(requests=[{"id": "eu", "query": "open source conferences"}]),
                                   secrets_manager=object())
    group = response.results[0]
    assert group["results"] == [] and "unavailable" in group["error"].lower()
    assert group["usage"]["credits_charged"] == 0
    web.assert_not_awaited()


# contract-test: direct surface=rest_api assertions=events-search.billing.usage
def test_settings_metadata_shows_web_search_price_and_mercury_token_price():
    """/v1/apps/metadata (which admits default-off events.search) carries the prices the settings page shows."""
    import yaml
    from backend.shared.python_schemas.app_metadata_schemas import AppSkillDefinition

    raw = yaml.safe_load((ROOT / "backend/apps/events/app.yml").read_text())
    skill = AppSkillDefinition.model_validate(next(s for s in raw["skills"] if s["id"] == "search"))
    pricing = _helpers("backend/core/api/app/routes/apps.py", ["_skill_pricing"])._skill_pricing(
        skill=skill, app_id="events", provider_configs={})
    # Mirrored by frontend/packages/ui/src/components/settings/SkillDetails.preview.ts.
    assert pricing == {
        "per_unit": {"credits": 10, "unit_name": "web search"},
        "tokens": {"input": {"per_credit_unit": 3335}, "output": {"per_credit_unit": 955}},
        "tokens_model": "inception/mercury-3",
    }
