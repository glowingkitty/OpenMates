"""Instance app packages: events.search dispatch to installed providers, availability and REST billing units.

Runs with the backend dependencies (api image). The runner is faked at the
client boundary; runner isolation itself is covered by
test_app_packages_runner.py.
Architecture: docs/architecture/apps/instance-app-packages.md
"""
from __future__ import annotations

import asyncio
import sys
from types import ModuleType, SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import AsyncMock

import pytest
import yaml
from fastapi import HTTPException
from starlette.requests import Request

from backend.apps.events.skills import search_skill
from backend.core.api.app.routes import apps, apps_api
from backend.apps.events.skills.search_skill import SearchRequest, SearchSkill
from backend.shared.app_packages import billing, loader, provider_dispatch
from backend.shared.app_packages.overlay import apply_app_package_overlay
from backend.shared.app_packages.runner_client import RunnerResult
from backend.shared.python_utils.billing_utils import calculate_total_credits
from backend.shared.python_utils.search_relevance import SearchRelevanceRankingResult
from backend.shared.python_schemas.app_metadata_schemas import AppSkillDefinition
from backend.tests.app_packages_test_support import (
    PROVIDER_ID, PROVIDER_NAME, FakeSecretsManager, configured_secrets, enable, install_example,
)

BUILTIN = search_skill._BUILTIN_PROVIDER
FUTURE = "2031-06-01T18:00:00Z"


@pytest.fixture(autouse=True)
def _installed(monkeypatch, tmp_path):
    install_example(tmp_path)
    enable(monkeypatch, tmp_path)
    monkeypatch.delenv("SECRET__EXAMPLE_SITE_EVENTS__API_KEY", raising=False)
    # Topic ranking needs an LLM; keep candidate order and record the parameters.
    ranking_calls: List[Dict[str, Any]] = []

    async def passthrough_ranking(**kwargs):
        ranking_calls.append(kwargs["search_parameters"])
        return SearchRelevanceRankingResult(candidates=list(kwargs["candidates"]), applied=False)

    monkeypatch.setattr(search_skill, "rank_search_candidates", passthrough_ranking)
    yield ranking_calls
    loader.reset_installed_packages_cache()


def _fake_runner(monkeypatch, outcome: RunnerResult) -> List[Dict[str, Any]]:
    calls: List[Dict[str, Any]] = []

    async def fake_run_provider(provider, input_item, secrets, **kwargs):
        calls.append({"provider": provider.provider_id, "input": input_item, "secrets": secrets})
        return outcome

    monkeypatch.setattr(provider_dispatch, "run_provider", fake_run_provider)
    return calls


def _skill(monkeypatch, builtin_events=None, builtin_error=None) -> tuple[SearchSkill, AsyncMock]:
    skill = object.__new__(SearchSkill)
    source = AsyncMock(return_value=(builtin_events or [], len(builtin_events or []), builtin_error))
    monkeypatch.setattr(skill, "_search_pretalx", source)
    return skill, source


def _site_event(title: str = "Open day") -> Dict[str, Any]:
    return {"title": title, "url": f"https://events.example.org/{title.replace(' ', '-').lower()}",
            "date_start": FUTURE, "provider_id": "spoofed", "free": True}


# contract-test: direct surface=rest_api assertions=events-search.providers.explicit
@pytest.mark.anyio
async def test_explicit_installed_provider_returns_attributed_results(monkeypatch, _installed):
    calls = _fake_runner(monkeypatch, RunnerResult(ok=True, results=[_site_event(), {"title": "invalid"}]))
    skill, builtin = _skill(monkeypatch)
    response = await skill.execute(SearchRequest(requests=[{"id": "site", "query": "open day", "provider": PROVIDER_ID}]),
                                   secrets_manager=configured_secrets())
    assert response.error is None
    assert response.providers == [PROVIDER_ID] and response.provider == PROVIDER_ID
    group = response.results[0]
    assert group["providers"] == [PROVIDER_ID]
    (event,) = group["results"]
    assert event["provider_id"] == PROVIDER_ID and event["provider"] == PROVIDER_NAME
    assert event["type"] == "event_result" and "free" not in event
    assert calls[0]["secrets"] == {"api_key": "placeholder-value"}
    assert calls[0]["input"]["query"] == "open day" and "provider" not in calls[0]["input"]
    assert _installed[0]["providers"] == [PROVIDER_ID]
    builtin.assert_not_awaited()


# contract-test: direct surface=rest_api assertions=instance-app-packages.operator-secrets
@pytest.mark.anyio
async def test_missing_secret_never_calls_runner(monkeypatch):
    calls = _fake_runner(monkeypatch, RunnerResult(ok=True, results=[_site_event()]))
    skill, _ = _skill(monkeypatch)
    response = await skill.execute(SearchRequest(requests=[{"id": "site", "query": "open day", "provider": PROVIDER_ID}]),
                                   secrets_manager=FakeSecretsManager())
    assert calls == []
    assert response.results[0]["results"] == []
    assert response.error == f"{PROVIDER_NAME} is not configured on this server."


# contract-test: direct surface=rest_api assertions=instance-app-packages.provider-contract
@pytest.mark.anyio
async def test_auto_merges_builtin_and_installed_results(monkeypatch):
    _fake_runner(monkeypatch, RunnerResult(ok=True, results=[_site_event("Site workshop")]))
    builtin_event = {"title": "Opening", "url": "https://conference.example.org/talk", "date_start": FUTURE,
                     "provider": "39c3"}
    skill, builtin = _skill(monkeypatch, builtin_events=[builtin_event])
    response = await skill.execute(SearchRequest(requests=[{"id": "all", "conference": "39C3"}]),
                                   secrets_manager=configured_secrets())
    assert response.error is None
    assert response.provider == "auto" and set(response.providers) == {BUILTIN, PROVIDER_ID}
    group = response.results[0]
    assert set(group["providers"]) == {BUILTIN, PROVIDER_ID}
    assert {event["title"] for event in group["results"]} == {"Opening", "Site workshop"}
    builtin.assert_awaited_once()


# contract-test: direct surface=rest_api assertions=instance-app-packages.provider-contract
@pytest.mark.anyio
async def test_installed_provider_failure_is_isolated(monkeypatch):
    _fake_runner(monkeypatch, RunnerResult(ok=False, error_code="TIMEOUT", message="internal detail"))
    builtin_event = {"title": "Opening", "url": "https://conference.example.org/talk", "date_start": FUTURE}
    skill, _ = _skill(monkeypatch, builtin_events=[builtin_event])
    response = await skill.execute(SearchRequest(requests=[{"id": "all", "conference": "39C3"}]),
                                   secrets_manager=configured_secrets())
    assert response.error is None
    group = response.results[0]
    assert [event["title"] for event in group["results"]] == ["Opening"]
    assert group["providers"] == [BUILTIN]
    assert group["warnings"] == [f"{PROVIDER_NAME} did not respond in time."]
    assert "internal detail" not in str(response.model_dump())


# contract-test: direct surface=rest_api assertions=instance-app-packages.provider-contract
@pytest.mark.anyio
async def test_only_failing_installed_provider_yields_safe_error(monkeypatch):
    _fake_runner(monkeypatch, RunnerResult(ok=False, error_code="EXECUTION_FAILED"))
    skill, _ = _skill(monkeypatch)
    response = await skill.execute(SearchRequest(requests=[{"id": "site", "query": "open day", "provider": PROVIDER_ID}]),
                                   secrets_manager=configured_secrets())
    assert response.error == f"{PROVIDER_NAME} failed."
    assert response.results[0]["results"] == []


# contract-test: direct surface=rest_api assertions=instance-app-packages.instance-availability
@pytest.mark.anyio
async def test_flag_off_rejects_installed_provider_id(monkeypatch):
    monkeypatch.delenv(loader.ENABLED_ENV)
    loader.reset_installed_packages_cache()
    calls = _fake_runner(monkeypatch, RunnerResult(ok=True, results=[_site_event()]))
    skill, _ = _skill(monkeypatch)
    response = await skill.execute(SearchRequest(requests=[{"id": "site", "query": "open day", "provider": PROVIDER_ID}]),
                                   secrets_manager=configured_secrets())
    assert "unavailable" in response.error.lower()
    assert calls == []


# --------------------------------------------------------------------------- availability

def _overlaid_search_skill() -> AppSkillDefinition:
    raw = yaml.safe_load((loader.BUILTIN_APPS_DIR / "events" / "app.yml").read_text(encoding="utf-8"))
    overlaid = apply_app_package_overlay("events", raw)
    skill = next(s for s in overlaid["skills"] if s["id"] == "search")
    # Only the installed provider, so availability depends on its secrets alone.
    skill["providers"] = [p for p in skill["providers"] if p.get("installed")]
    return AppSkillDefinition(**skill)


# contract-test: direct surface=rest_api assertions=instance-app-packages.instance-availability,instance-app-packages.operator-secrets
@pytest.mark.anyio
async def test_installed_provider_availability_requires_declared_secrets():
    skill = _overlaid_search_skill()
    assert skill.providers[0].installed is True and skill.provider_contract == "events.search@1"
    assert await apps.is_skill_available(skill, "events", FakeSecretsManager()) is False
    assert await apps.is_skill_available(skill, "events", configured_secrets()) is True
    assert await apps_api.is_skill_available(skill, "events", FakeSecretsManager()) is False
    assert await apps_api.is_skill_available(skill, "events", configured_secrets()) is True


# --------------------------------------------------------------------------- REST billing units

# contract-test: direct surface=rest_api assertions=instance-app-packages.no-installed-provider-charges
def test_rest_chargeable_units():
    request = {"requests": [{"id": 1}, {"id": 2}]}
    site = {"id": 1, "results": [{"provider_id": PROVIDER_ID}], "providers": [PROVIDER_ID]}
    conference = {"id": 2, "results": [{"provider_id": BUILTIN}], "providers": [BUILTIN]}
    spoofed = {"id": 2, "results": [{"provider_id": "x", "free": True}], "providers": ["x"], "free": True}
    assert apps_api.chargeable_skill_units("events", "search", request, None) == 2
    assert apps_api.chargeable_skill_units("events", "search", request, {"results": [site, conference]}) == 1
    assert apps_api.chargeable_skill_units("events", "search", request, {"data": {"results": [site, spoofed]}}) == 1
    assert apps_api.chargeable_skill_units("events", "search", {"requests": [{"id": 1}]}, {"results": [site]}) == 0
    assert apps_api.chargeable_skill_units("web", "search", {"requests": [{"id": 1}]}, {"results": [site]}) == 1


# --------------------------------------------------------------------------- credit calculation and usage rows

_SITE_GROUP = {"id": 1, "results": [{"provider_id": PROVIDER_ID}], "providers": [PROVIDER_ID]}
_CONFERENCE_GROUP = {"id": 2, "results": [{"provider_id": BUILTIN}], "providers": [BUILTIN]}


def _events_metadata(pricing):
    skill = SimpleNamespace(
        id="search", full_model_reference=None, providers=[],
        pricing=None if pricing is None else SimpleNamespace(model_dump=lambda **_kwargs: dict(pricing)),
    )
    return SimpleNamespace(id="events", skills=[skill])


def _builtin_formula(pricing, input_data) -> int:
    """The pre-app-packages REST credit formula (one unit per request, minimum 1 without pricing)."""
    requests = input_data.get("requests")
    units = len(requests) if isinstance(requests, list) else 1
    return calculate_total_credits(pricing_config=dict(pricing), units_processed=units) if pricing else 1


# contract-test: direct surface=rest_api assertions=instance-app-packages.no-installed-provider-charges
@pytest.mark.anyio
@pytest.mark.parametrize("flag_on", [False, True])
@pytest.mark.parametrize("pricing", [None, {"fixed": 7}, {"per_unit": {"credits": 3}}])
@pytest.mark.parametrize("input_data", [{"requests": []}, {"requests": [{"id": 1}, {"id": 2}]}, {"query": "x"}])
async def test_builtin_credit_formula_is_unchanged_without_installed_groups(monkeypatch, flag_on, pricing, input_data):
    if not flag_on:
        monkeypatch.delenv(loader.ENABLED_ENV, raising=False)
        loader.reset_installed_packages_cache()
    result = {"results": [_CONFERENCE_GROUP, _CONFERENCE_GROUP]} if flag_on else {"results": [_SITE_GROUP, _SITE_GROUP]}
    credits = await apps_api.calculate_skill_credits(_events_metadata(pricing), "search", input_data, result, "events")
    assert credits == _builtin_formula(pricing, input_data)


# contract-test: direct surface=rest_api assertions=instance-app-packages.no-installed-provider-charges
@pytest.mark.anyio
async def test_installed_only_groups_reduce_credits_and_all_installed_is_free():
    metadata = _events_metadata({"per_unit": {"credits": 3}})
    two = {"requests": [{"id": 1}, {"id": 2}]}
    mixed = {"results": [_SITE_GROUP, _CONFERENCE_GROUP]}
    assert await apps_api.calculate_skill_credits(metadata, "search", two, mixed, "events") == 3
    assert await apps_api.calculate_skill_credits(
        metadata, "search", two, {"results": [_SITE_GROUP, _SITE_GROUP]}, "events") == 0
    # More groups than requests cannot be matched to requests: nothing is exempt.
    assert await apps_api.calculate_skill_credits(
        metadata, "search", {"requests": [{"id": 1}]}, mixed, "events") == 3


# contract-test: direct surface=rest_api assertions=instance-app-packages.no-installed-provider-charges
def test_usage_rows_reference_charged_request_indices(monkeypatch):
    two = {"requests": [{"id": 1}, {"id": 2}]}
    split = billing.even_request_charge_items
    assert split("events", "search", two, {"results": [_SITE_GROUP, _CONFERENCE_GROUP]}, 10) == [(1, 10)]
    assert split("events", "search", two, {"results": [_CONFERENCE_GROUP, _SITE_GROUP]}, 10) == [(0, 10)]
    assert split("events", "search", two, {"results": [_CONFERENCE_GROUP, _CONFERENCE_GROUP]}, 11) == [(0, 5), (1, 6)]
    monkeypatch.delenv(loader.ENABLED_ENV, raising=False)
    loader.reset_installed_packages_cache()
    assert split("events", "search", two, {"results": [_SITE_GROUP, _CONFERENCE_GROUP]}, 11) == [(0, 5), (1, 6)]
    assert split("events", "search", {"requests": []}, {"results": []}, 4) == []


# --------------------------------------------------------------------------- anonymous REST billing

class _FakeAnonymousMeter:
    """Anonymous usage meter stand-in that records settlement of the one reservation."""

    def __init__(self) -> None:
        self.finalized: List[int] = []
        self.released: List[str] = []

    def request_identity(self, _anonymous_id, _ip_address) -> str:
        return "identity-1"

    async def consume_local_rate_limit(self, _key: str, *, max_requests: int) -> bool:
        return True

    async def open_request(self, **_kwargs):
        return SimpleNamespace(accepted=True, reason=None)

    async def reserve_operation(self, **_kwargs):
        return SimpleNamespace(accepted=True, reason=None)

    async def finalize_charge(self, _operation_id: str, *, actual_credits: int) -> None:
        self.finalized.append(actual_credits)

    async def release_reservation(self, _operation_id: str, *, reason: str) -> None:
        self.released.append(reason)


async def _anonymous_events_call(monkeypatch, body, groups):
    from backend.core.api.app.routes import anonymous as anonymous_routes
    from backend.shared.python_utils import app_skill_output_safety

    meter = _FakeAnonymousMeter()
    monkeypatch.setattr(anonymous_routes, "_anonymous_usage_service", lambda *_args: meter)
    skill = SimpleNamespace(
        id="search", internal=False, anonymous_access="inline", api_config=None,
        pricing=SimpleNamespace(model_dump=lambda **_kwargs: {"per_unit": {"credits": 6}}),
        providers=[], full_model_reference=None,
        model_dump=lambda: {"id": "search", "anonymous_access": "inline", "internal": False},
    )
    dispatched: List[Dict[str, Any]] = []

    class FakeRegistry:
        def get_metadata(self, app_id: str):
            return SimpleNamespace(skills=[skill])

        def is_skill_available(self, app_id: str, skill_id: str) -> bool:
            return (app_id, skill_id) == ("events", "search")

        async def dispatch_skill(self, app_id: str, skill_id: str, payload: dict) -> dict:
            dispatched.append(payload)
            return {"success": True, "data": {"results": groups}}

    registry_module = ModuleType("backend.core.api.app.services.skill_registry")
    registry_module.get_global_registry = lambda: FakeRegistry()
    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.skill_registry", registry_module)
    monkeypatch.setattr(anonymous_routes, "validate_request_domain",
                        lambda _request: ("api.dev.openmates.org", False, "development"))
    monkeypatch.setattr(app_skill_output_safety, "sanitize_app_skill_output",
                        lambda result, _context: asyncio.sleep(0, result=result))
    request = Request({
        "type": "http", "method": "POST", "path": "/v1/anonymous/apps/events/skills/search",
        "headers": [(b"host", b"api.dev.openmates.org")], "client": ("198.51.100.7", 443),
        "app": SimpleNamespace(state=SimpleNamespace(secrets_manager=None)),
    })
    response = await anonymous_routes.anonymous_app_skill(request, "events", "search", body, None, None)
    return response, meter, dispatched


# contract-test: direct surface=rest_api assertions=instance-app-packages.no-installed-provider-charges
@pytest.mark.anyio
async def test_anonymous_rest_mixed_result_is_charged(monkeypatch):
    one = {"requests": [{"query": "open day"}]}
    response, meter, _ = await _anonymous_events_call(monkeypatch, one, [_SITE_GROUP, _CONFERENCE_GROUP])
    assert (response["credits_charged"], meter.finalized, meter.released) == (6, [6], [])


# contract-test: direct surface=rest_api assertions=instance-app-packages.no-installed-provider-charges
@pytest.mark.anyio
async def test_anonymous_rest_installed_only_result_is_released(monkeypatch):
    one = {"requests": [{"query": "open day"}]}
    response, meter, dispatched = await _anonymous_events_call(monkeypatch, one, [_SITE_GROUP])
    assert len(dispatched) == 1
    assert (response["credits_charged"], meter.finalized, meter.released) == (0, [], ["installed_provider"])


# contract-test: direct surface=rest_api assertions=instance-app-packages.no-installed-provider-charges
@pytest.mark.anyio
async def test_anonymous_rest_multi_request_body_never_runs_free(monkeypatch):
    two = {"requests": [{"query": "open day"}, {"query": "talks", "conference": "39c3"}]}
    with pytest.raises(HTTPException) as exc_info:
        await _anonymous_events_call(monkeypatch, two, [_SITE_GROUP, _CONFERENCE_GROUP])
    assert exc_info.value.status_code == 422
