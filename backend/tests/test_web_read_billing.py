"""Exercise production billing helpers without network, accounts, or money effects."""
from __future__ import annotations

import ast
import logging
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[2]


def _helpers(relative_path, names):
    """Load exact helper bodies, excluding service startup and unrelated imports."""
    tree = ast.parse((ROOT / relative_path).read_text())
    nodes = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
    assert {node.name for node in nodes} == set(names)
    namespace = dict(Any=Any, Dict=Dict, List=List, Optional=Optional, Tuple=Tuple,
                     HTTPException=HTTPException,
                     _as_dict=lambda value: value if isinstance(value, dict) else {},
                     _dict_value=lambda value: value if isinstance(value, dict) else {},
                     logger=logging.getLogger(__name__))
    nodes = [node for node in tree.body if isinstance(node, ast.Assign) and any(
        isinstance(target, ast.Name) and target.id == "VARIABLE_RESULT_BILLING_SKILLS"
        for target in node.targets
    )] + nodes
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), *nodes], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), relative_path, "exec"), namespace)
    return SimpleNamespace(**namespace)


@pytest.fixture(autouse=True)
def request_schema_without_reader_startup(monkeypatch):
    # Exercise the real Pydantic request declarations without importing the
    # HTML parser or transport, which billing itself never invokes.
    path = ROOT / "backend/apps/web/skills/read_skill.py"
    tree = ast.parse(path.read_text())
    nodes = [node for node in tree.body if (
        isinstance(node, ast.ClassDef) and node.name in {"WebReadRequestItem", "ReadRequest"}
    ) or (
        isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id in {
            "MAX_READ_REQUESTS", "MAX_READ_TIMEOUT_MS"
        } for target in node.targets)
    )]
    namespace = dict(BaseModel=BaseModel, Field=Field, Optional=Optional, Any=Any, List=List, Literal=Literal)
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(path), "exec"), namespace)
    namespace["WebReadRequestItem"].model_rebuild(_types_namespace=namespace)
    namespace["ReadRequest"].model_rebuild(_types_namespace=namespace)
    schema_module = types.ModuleType("backend.apps.web.skills.read_skill")
    schema_module.ReadRequest = namespace["ReadRequest"]
    monkeypatch.setitem(sys.modules, schema_module.__name__, schema_module)


@pytest.fixture
def rest():
    return _helpers("backend/core/api/app/routes/apps_api.py", [
        "get_variable_result_charge_items", "get_variable_result_credits",
        "get_variable_result_usage_details", "get_variable_preflight_reserved_credits",
        "calculate_skill_credits", "_coerce_nonnegative_credits",
    ])


@pytest.fixture
def assistant():
    return _helpers("backend/apps/ai/processing/main_processor.py", [
        "_get_result_declared_charge_items", "_get_result_declared_usage_details",
        "_get_variable_preflight_reserved_credits", "_coerce_nonnegative_credits", "_charge_skill_credits",
    ])


def _success(credits=20):
    return {"id": "ok", "results": [{"markdown": "Full extracted page", "url": "https://example.com"}],
            "usage": {"credits_charged": credits}}


# contract-test: supporting surface=rest_api assertions=web-read.billing
@pytest.mark.parametrize("groups,expected", [
    ([_success()], [(0, 20)]),
    ([{"id": "blocked", "error": "robots_disallowed", "results": [], "usage": {"credits_charged": 0}}, _success()], [(1, 20)]),
    ([{"error": "blocked", **_success()}], []),
    ([{"results": [], "usage": {"credits_charged": 20}}], []),
    ([_success(1), _success(999), {"results": [{"markdown": " "}], "usage": {"credits_charged": 20}}], []),
    ([{"results": [{"markdown": "text", "error": "failed"}], "usage": {"credits_charged": 20}}], []),
    ([_success()] * 6, [(i, 20) for i in range(5)]),
])
# contract-test: supporting surface=rest_api assertions=web-read.billing
def test_server_success_groups_are_the_only_charge_authority(rest, assistant, groups, expected):
    assert rest.get_variable_result_charge_items("web", "read", {"results": groups}) == expected
    assert [(i, credits) for i, credits, _ in assistant._get_result_declared_charge_items("web", "read", groups)] == expected


# contract-test: supporting surface=rest_api assertions=web-read.billing
@pytest.mark.parametrize("result", [None, {}, {"results": None}, {"results": []}])
@pytest.mark.asyncio
async def test_missing_server_usage_never_falls_back_to_one_credit(rest, result):
    assert await rest.calculate_skill_credits(SimpleNamespace(id="web"), "read", {
        "requests": [{"url": "https://example.com", "usage": {"credits_charged": 999}}],
        "usage": {"credits_charged": 999},
    }, result, "web") == 0


# contract-test: supporting surface=rest_api assertions=web-read.billing
@pytest.mark.parametrize("count", [1, 5])
def test_preflight_reserves_twenty_per_validated_page(rest, assistant, count):
    body = {"requests": [{"url": "https://example.com"}] * count}
    assert rest.get_variable_preflight_reserved_credits("web", "read", body) == 20 * count
    assert assistant._get_variable_preflight_reserved_credits("web", "read", body) == [20] * count


# contract-test: supporting surface=rest_api assertions=web-read.billing
@pytest.mark.parametrize("body", [{}, {"requests": []}, {"requests": [{}]}, {"requests": [{"url": "https://example.com"}] * 6}])
def test_invalid_batches_rejected_before_reservation(rest, assistant, body):
    with pytest.raises(HTTPException) as error:
        rest.get_variable_preflight_reserved_credits("web", "read", body)
    assert error.value.status_code == 422
    with pytest.raises(ValueError):
        assistant._get_variable_preflight_reserved_credits("web", "read", body)


# contract-test: supporting surface=rest_api assertions=web-read.billing
def test_usage_details_are_web_specific(rest, assistant):
    expected = {"web_read_credits_charged": 20}
    assert rest.get_variable_result_usage_details("web", "read", {"results": [_success()]}, 0) == expected
    assert assistant._get_result_declared_usage_details("web", "read", _success()) == expected


# contract-test: supporting surface=rest_api assertions=web-read.billing
@pytest.mark.asyncio
async def test_assistant_charge_uses_group_index_and_never_charges_blocked_page(assistant, monkeypatch):
    from backend.core.api.app.services.creators import paid_web_read_income
    payout = AsyncMock(return_value=True)
    monkeypatch.setattr(paid_web_read_income, "record_paid_web_read_income", payout)
    fn = assistant._charge_skill_credits
    env = fn.__globals__
    calls = []

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def post(self, url, **kwargs):
            calls.append(kwargs["json"])
            return httpx.Response(200, json={"status": "success", "state": "committed", "charge_id": "paid", "charged_credits": 20}, request=httpx.Request("POST", url))

    env.update(httpx=SimpleNamespace(AsyncClient=Client, HTTPStatusError=httpx.HTTPStatusError),
               ASYNC_SKILLS=set(), MINIMUM_CREDITS_CHARGED=1,
               _resolve_skill_billing_config=AsyncMock(return_value=(SimpleNamespace(full_model_reference=None), {"fixed": 1})),
               resolve_skill_usage_provider_id=lambda *_: None,
               _apply_benchmark_usage_details=lambda *_: None,
               _skill_operation_id=lambda *args: f"operation-{args[-1]}",
               INTERNAL_API_SHARED_TOKEN="", INTERNAL_API_BASE_URL="https://billing.invalid")
    request = SimpleNamespace(user_id="test", user_id_hash="hashed", chat_id="chat", root_chat_id=None,
                              root_turn_id=None, orchestration_id=None, sub_chat_depth=0, message_id="message")
    blocked = {"id": "blocked", "results": [], "error": "robots_disallowed", "usage": {"credits_charged": 0}}
    await fn("task", "execution", request, "web", "read", {}, [_success()["results"][0]],
             {"requests": [{"url": "https://example.com"}] * 2}, "test", grouped_results=[blocked, _success()])
    assert [(call["credits"], call["idempotency_key"]) for call in calls] == [(20, "operation-1")]
    assert calls[0]["usage_details"]["web_read_credits_charged"] == 20
    payout.assert_awaited_once_with(_success(), {
        "status": "success", "state": "committed", "charge_id": "paid", "charged_credits": 20,
    })
    calls.clear()
    await fn("task", "execution", request, "web", "read", {}, [{"error": "blocked"}],
             {"requests": [{"url": "https://example.com"}]}, "test", grouped_results=[blocked])
    assert calls == []
    assert payout.await_count == 1
