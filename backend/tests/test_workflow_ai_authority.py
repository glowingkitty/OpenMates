"""Workflow-to-AskSkill dispatch with real owner-bound signing and no provider IO.

Only broker publication and answer transport are substituted. The adapter,
OpenAI request conversion, lazy stream authority and internal dispatch are real.
"""

from __future__ import annotations

import hashlib
import asyncio
import contextvars
import json
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from backend.apps.ai.skills import ask_skill
from backend.core.api.app.services.workflow_app_skill_adapter import WorkflowAppSkillAdapter
from backend.shared.python_utils.volatile_embed_authority import (
    MAIN_HEADER,
    AuthenticatedVolatileAI,
    active_authenticated_volatile_ai,
    verify_main_header,
)


@pytest.fixture
def dispatch_boundary(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "workflow-regression-signing-key")
    broker = Mock()
    task = SimpleNamespace(apply_async=broker)
    monkeypatch.setitem(sys.modules, "backend.apps.ai.tasks.ask_skill_task",
                        SimpleNamespace(process_ai_skill_ask_task=task))
    monkeypatch.setitem(sys.modules, "backend.apps.ai.tasks.stage_one_task", SimpleNamespace(
        eligible_for_routing_lane=lambda _request: False, process_ai_stage_one_task=task,
    ))
    monkeypatch.setattr(ask_skill, "notify_chat_failure", AsyncMock())
    skill = object.__new__(ask_skill.AskSkill)
    skill.parsed_default_config = None
    skill.celery_producer = object()

    async def sync_answer(request, _openai_request):
        await skill._handle_internal_request(request)
        return {"choices": [{"message": {"content": "Workflow answer"}}]}

    async def stream_answer(request, _openai_request):
        await skill._handle_internal_request(request)
        yield "data: " + json.dumps({
            "choices": [{"delta": {}, "finish_reason": "stop"}],
            "full_content": "Workflow answer", "usage": {"total_credits": 2},
        }) + "\n\n"

    monkeypatch.setattr(skill, "_handle_openai_sync_response", sync_answer)
    monkeypatch.setattr(skill, "_stream_openai_response", stream_answer)

    class Registry:
        async def dispatch_skill(self, app_id, skill_id, request):
            assert (app_id, skill_id) == ("ai", "ask")
            return await skill._handle_openai_request(ask_skill.OpenAICompletionRequest.model_validate(request))

    return WorkflowAppSkillAdapter(registry=Registry()), broker


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
# contract-test: direct surface=rest_api assertions=workflows.ai-ask.execution,workflows.actions.skill-contract
async def test_workflow_ai_dispatch_signs_resolved_owner_even_for_lazy_stream(dispatch_boundary, stream):
    adapter, broker = dispatch_boundary
    request = {"prompt": "Private workflow input", "_user_id": "forged-owner",
               "_external_request": False, "user_id": "forged-owner"}
    if stream:
        result = await adapter.stream_ask(request, user_id="workflow-owner", billing_context={
            "workflow_id": "workflow-1", "run_id": "run-1", "node_id": "ask", "source": "workflow_test",
        }, on_snapshot=AsyncMock())
    else:
        result = await adapter.execute("ai", "ask", request, user_id="workflow-owner")
    assert result["answer"] == "Workflow answer"
    broker.assert_called_once()
    call = broker.call_args.kwargs
    payload = call["kwargs"]["request_data_dict"]
    verified = verify_main_header(call["headers"][MAIN_HEADER], owner_id="workflow-owner",
        owner_hash=hashlib.sha256(b"workflow-owner").hexdigest(), chat_id=payload["chat_id"],
        message_id=payload["message_id"], main_task_id=call["task_id"], hashed_team_id=None)
    assert verified.mode == "external"
    assert payload["user_preferences"]["workflow_ai"] is True
    assert payload["user_preferences"]["apps_enabled"] is False
    assert "Private workflow input" not in json.dumps(call["headers"])
    assert active_authenticated_volatile_ai.get() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("ambient_owner,ambient_team", [("other-owner", None), ("workflow-owner", "a" * 64)])
# contract-test: direct surface=rest_api assertions=workflows.ai-ask.execution,workflows.actions.skill-contract
async def test_workflow_ai_rejects_conflicting_ambient_authority(dispatch_boundary, ambient_owner, ambient_team):
    adapter, broker = dispatch_boundary
    principal = AuthenticatedVolatileAI(owner_id=ambient_owner,
        owner_hash=hashlib.sha256(ambient_owner.encode()).hexdigest(), mode="external", hashed_team_id=ambient_team)
    token = active_authenticated_volatile_ai.set(principal)
    try:
        with pytest.raises(PermissionError, match="does not match"):
            await adapter.execute("ai", "ask", {"prompt": "Private input"}, user_id="workflow-owner")
        broker.assert_not_called()
        assert active_authenticated_volatile_ai.get() is principal
    finally:
        active_authenticated_volatile_ai.reset(token)


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=workflows.ai-ask.execution
async def test_workflow_ai_without_resolved_owner_cannot_dispatch(dispatch_boundary):
    adapter, broker = dispatch_boundary
    with pytest.raises(PermissionError, match="owner is unavailable"):
        await adapter.execute("ai", "ask", {"prompt": "Private input", "_user_id": "forged-owner"})
    broker.assert_not_called()


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=workflows.ai-ask.execution
async def test_workflow_ai_signing_failure_does_not_leak_authority(dispatch_boundary, monkeypatch):
    adapter, broker = dispatch_boundary
    monkeypatch.delenv("INTERNAL_API_SHARED_TOKEN")
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        await adapter.execute("ai", "ask", {"prompt": "Private input"}, user_id="workflow-owner")
    broker.assert_not_called()
    assert active_authenticated_volatile_ai.get() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("authenticated", [False, True])
@pytest.mark.parametrize("finish", ["complete", "cross_context_complete", "cross_context_close", "close_error", "error"])
# contract-test: supporting surface=rest_api assertions=workflows.ai-ask.execution,operational-monitoring.chat-failures.safe-delivery
async def test_lazy_stream_authority_is_scoped_to_iteration_and_cleanup(monkeypatch, authenticated, finish):
    principal = AuthenticatedVolatileAI(owner_id="owner", owner_hash="a" * 64, mode="external") if authenticated else None
    ambient = AuthenticatedVolatileAI(owner_id="caller", owner_hash="b" * 64, mode="external")
    observed = []

    async def inner(_request, _openai_request):
        observed.append(active_authenticated_volatile_ai.get())
        try:
            yield "first chunk"
            observed.append(active_authenticated_volatile_ai.get())
            if finish == "error":
                raise RuntimeError("stream failed")
        finally:
            observed.append(active_authenticated_volatile_ai.get())
            if finish == "close_error":
                raise RuntimeError("cleanup failed")

    skill = object.__new__(ask_skill.AskSkill)
    monkeypatch.setattr(skill, "_stream_openai_response", inner)
    iterator = skill._stream_openai_response_with_authority(None, None, principal)
    token = active_authenticated_volatile_ai.set(ambient)
    try:
        assert await anext(iterator) == "first chunk"
        assert active_authenticated_volatile_ai.get() is ambient
        if finish == "cross_context_close":
            await asyncio.create_task(iterator.aclose(), context=contextvars.Context())
        elif finish == "cross_context_complete":
            with pytest.raises(StopAsyncIteration):
                await asyncio.create_task(anext(iterator), context=contextvars.Context())
        elif finish == "close_error":
            with pytest.raises(RuntimeError, match="cleanup failed"):
                await iterator.aclose()
        elif finish == "error":
            with pytest.raises(RuntimeError, match="stream failed"):
                await anext(iterator)
        else:
            with pytest.raises(StopAsyncIteration):
                await anext(iterator)
        assert observed and all(value is principal for value in observed)
        assert active_authenticated_volatile_ai.get() is ambient
    finally:
        await iterator.aclose()
        active_authenticated_volatile_ai.reset(token)


@pytest.mark.asyncio
@pytest.mark.parametrize("authenticated", [False, True])
# contract-test: supporting surface=rest_api assertions=workflows.ai-ask.execution,operational-monitoring.chat-failures.safe-delivery
async def test_cancelled_lazy_iteration_restores_authority_in_consumer_task(monkeypatch, authenticated):
    principal = AuthenticatedVolatileAI(owner_id="owner", owner_hash="a" * 64, mode="external") if authenticated else None
    ambient = AuthenticatedVolatileAI(owner_id="caller", owner_hash="b" * 64, mode="external")
    entered = asyncio.Event()
    never = asyncio.Event()
    observed = []
    restored = []

    async def inner(_request, _openai_request):
        try:
            entered.set()
            await never.wait()
            yield "unreachable"
        finally:
            observed.append(active_authenticated_volatile_ai.get())

    skill = object.__new__(ask_skill.AskSkill)
    monkeypatch.setattr(skill, "_stream_openai_response", inner)
    iterator = skill._stream_openai_response_with_authority(None, None, principal)

    async def consume():
        token = active_authenticated_volatile_ai.set(ambient)
        try:
            await anext(iterator)
        except asyncio.CancelledError:
            restored.append(active_authenticated_volatile_ai.get())
            raise
        finally:
            active_authenticated_volatile_ai.reset(token)

    consumer = asyncio.create_task(consume())
    await asyncio.wait_for(entered.wait(), timeout=1)
    consumer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await consumer
    assert observed == [principal]
    assert restored == [ambient]
    assert active_authenticated_volatile_ai.get() is None
