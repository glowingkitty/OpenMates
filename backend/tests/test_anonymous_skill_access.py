"""
backend/tests/test_anonymous_skill_access.py

Contract tests for anonymous execution gating. Anonymous callers may use skills
classified as not requiring connected accounts, but file/upload payloads and
connected-account skills must be rejected before inference or provider work.
"""

from __future__ import annotations

import sys
import json
import asyncio
from types import ModuleType

import pytest
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from starlette.requests import Request

import backend.core.api.app.routes.anonymous as anonymous_routes
from backend.core.api.app.routes.anonymous import (
    AnonymousChatStreamRequest,
    anonymous_chat_stream,
    reject_anonymous_file_payloads,
    validate_anonymous_skill_allowed,
)
from backend.core.api.app.services.anonymous_free_usage_service import AnonymousFreeUsageService, AnonymousReservationResult
from backend.tests.test_anonymous_free_usage_budget import FakeCache, FakeDirectus


@pytest.fixture(autouse=True)
def use_in_process_anonymous_meter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        anonymous_routes,
        "_anonymous_usage_service",
        lambda directus_service, cache_service: AnonymousFreeUsageService(
            directus_service=directus_service,
            cache_service=cache_service,
            hmac_secret="test-secret",
        ),
    )


# contract-test: direct surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering
def test_skill_without_connected_account_requirement_is_allowed() -> None:
    skill = {
        "id": "search",
        "connected_account_required": False,
    }

    validate_anonymous_skill_allowed("web", skill)


# contract-test: direct surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering
def test_connected_account_skill_is_rejected_for_anonymous_callers() -> None:
    skill = {
        "id": "get-events",
        "connected_account_required": True,
    }

    with pytest.raises(HTTPException) as exc_info:
        validate_anonymous_skill_allowed("calendar", skill)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "signup_required"


# contract-test: direct surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering
def test_missing_connected_account_classification_fails_closed() -> None:
    skill = {"id": "unknown"}

    with pytest.raises(HTTPException) as exc_info:
        validate_anonymous_skill_allowed("unknown", skill)

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail["code"] == "skill_metadata_missing"


# contract-test: direct surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering
def test_anonymous_chat_rejects_file_upload_payloads_before_inference() -> None:
    request = AnonymousChatStreamRequest(
        anonymous_id="anon-1",
        client_chat_id="chat-1",
        client_message_id="message-1",
        plaintext_message="Please read this file",
        message_history=[],
        files=[{"name": "paper.pdf", "size": 1234}],
    )

    with pytest.raises(HTTPException) as exc_info:
        reject_anonymous_file_payloads(request)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "signup_required"


# contract-test: direct surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering
def test_anonymous_chat_rejects_embed_upload_references_before_inference() -> None:
    request = AnonymousChatStreamRequest(
        anonymous_id="anon-1",
        client_chat_id="chat-1",
        client_message_id="message-1",
        plaintext_message='```json\n{"type":"image","embed_id":"abc"}\n```',
        message_history=[
            {
                "role": "user",
                "content": '```json\n{"type":"image","embed_id":"abc"}\n```',
                "created_at": 1,
            }
        ],
    )

    with pytest.raises(HTTPException) as exc_info:
        reject_anonymous_file_payloads(request)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "signup_required"


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering
async def test_anonymous_chat_dispatches_ai_with_open_request_ledger(monkeypatch: pytest.MonkeyPatch) -> None:
    directus = FakeDirectus()
    service = AnonymousFreeUsageService(directus_service=directus, hmac_secret="test-secret")
    await service.save_budget(
        enabled=True,
        monthly_budget_credits=2_000,
        daily_hard_cap_percent=5,
        weekly_cap_percent=25,
        per_identity_daily_cap_credits=400,
        admin_user_id="admin-1",
    )

    class FakeRegistry:
        async def dispatch_skill(self, app_id: str, skill_id: str, request_body: dict) -> dict:
            assert app_id == "ai"
            assert skill_id == "ask"
            assert request_body["stream"] is True
            assert request_body["is_anonymous"] is True
            assert request_body["apps_enabled"] is True
            assert request_body["messages"][-1]["content"] == "Reply with exactly: anonymous inference ok"
            return {
                "model": "test-model",
                "category": "general_knowledge",
                "choices": [{"message": {"content": "anonymous inference ok"}}],
                "usage": {"total_credits": 7},
            }

    fake_skill_registry_module = ModuleType("backend.core.api.app.services.skill_registry")
    fake_skill_registry_module.get_global_registry = lambda: FakeRegistry()
    monkeypatch.setattr(anonymous_routes, "validate_request_domain", lambda _request: ("api.dev.openmates.org", False, "development"))
    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.skill_registry", fake_skill_registry_module)

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/v1/anonymous/chat/stream",
            "headers": [(b"host", b"api.dev.openmates.org"), (b"accept", b"text/event-stream")],
            "client": ("198.51.100.7", 443),
        }
    )
    payload = AnonymousChatStreamRequest(
        anonymous_id="anon-1",
        client_chat_id="chat-1",
        client_message_id="message-1",
        plaintext_message="Reply with exactly: anonymous inference ok",
    )

    response = await anonymous_chat_stream(request=request, payload=payload, directus_service=directus, cache_service=FakeCache())
    body = ""
    async for chunk in response.body_iterator:
        body += chunk.decode() if isinstance(chunk, bytes) else str(chunk)

    events = [
        json.loads(line.removeprefix("data: "))
        for line in body.splitlines()
        if line.startswith("data: ")
    ]
    assert [event["type"] for event in events] == [
        "ai_task_initiated",
        "ai_typing_started",
        "ai_message_chunk",
        "ai_task_ended",
        "post_processing_completed",
    ]
    final_chunk = events[2]
    assert final_chunk["message_id"] != payload.client_message_id
    assert final_chunk["message_id"].startswith("chat-1-")
    assert final_chunk["full_content_so_far"] == "anonymous inference ok"
    assert final_chunk["is_final_chunk"] is True
    post_processing = events[4]
    assert post_processing["chat_id"] == payload.client_chat_id
    assert post_processing["chat_summary"] == "anonymous inference ok"
    assert len(post_processing["follow_up_request_suggestions"]) == 6
    status = await service.get_budget_status()
    assert status.daily_used_credits == 0
    assert any(row.get("status") == "request_open" for row in directus.reservations.values())


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=chats.streaming.ordered-final,web-search.surface-parity
async def test_anonymous_sse_forwards_transient_app_skill_embeds(monkeypatch: pytest.MonkeyPatch) -> None:
    async def openai_stream():
        yield 'data: {"model":"openmates-ai","choices":[{"delta":{"content":"News with [source](embed:source-ref)"}}]}\n\n'
        yield (
            'data: {"model":"google/gemini-test","choices":[{"delta":{"embeds":['
            '{"embed_id":"parent-id","type":"app_skill_use","content":"app_id: news\\nskill_id: search\\nstatus: finished",'
            '"status":"finished","embed_ids":["child-id"]},'
            '{"embed_id":"child-id","type":"news_result","content":"type: news_result\\nembed_ref: source-ref\\ntitle: Source",'
            '"status":"finished","parent_embed_id":"parent-id"}'
            ']},"finish_reason":null}]}\n\n'
        )
        yield 'data: {"model":"google/gemini-test","choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
        yield 'data: [DONE]\n\n'

    class FakeRegistry:
        async def dispatch_skill(self, app_id: str, skill_id: str, request_body: dict) -> StreamingResponse:
            assert request_body["is_anonymous"] is True
            return StreamingResponse(openai_stream(), media_type="text/event-stream")

    fake_skill_registry_module = ModuleType("backend.core.api.app.services.skill_registry")
    fake_skill_registry_module.get_global_registry = lambda: FakeRegistry()
    monkeypatch.setattr(anonymous_routes, "validate_request_domain", lambda _request: ("api.dev.openmates.org", False, "development"))
    monkeypatch.setattr(
        AnonymousFreeUsageService,
        "open_request",
        lambda self, **kwargs: asyncio.sleep(0, result=AnonymousReservationResult(accepted=True, request_id=kwargs["request_id"])),
    )
    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.skill_registry", fake_skill_registry_module)

    request = Request({
        "type": "http",
        "method": "POST",
        "path": "/v1/anonymous/chat/stream",
        "headers": [(b"host", b"api.dev.openmates.org"), (b"accept", b"text/event-stream")],
        "client": ("198.51.100.7", 443),
    })
    payload = AnonymousChatStreamRequest(
        anonymous_id="anon-1",
        client_chat_id="anonymous-chat-1",
        client_message_id="message-1",
        plaintext_message="Search the news",
    )

    response = await anonymous_chat_stream(
        request=request,
        payload=payload,
        directus_service=FakeDirectus(),
        cache_service=FakeCache(),
    )
    body = ""
    async for chunk in response.body_iterator:
        body += chunk.decode() if isinstance(chunk, bytes) else str(chunk)

    events = [json.loads(line.removeprefix("data: ")) for line in body.splitlines() if line.startswith("data: ")]
    embed_events = [event for event in events if event["type"] == "send_embed_data"]
    assert [event["payload"]["embed_id"] for event in embed_events] == ["parent-id", "child-id"]
    assert [event["payload"]["type"] for event in embed_events] == ["app_skill_use", "news_result"]
    assert all(event["payload"]["chat_id"] == payload.client_chat_id for event in embed_events)
    assert all(event["payload"]["message_id"] != payload.client_message_id for event in embed_events)
    final_chunk = next(event for event in events if event["type"] == "ai_message_chunk" and event["is_final_chunk"])
    assert final_chunk["model_name"] == "google/gemini-test"


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering
async def test_anonymous_sse_does_not_double_finalize_worker_usage(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def failing_finalize(self: AnonymousFreeUsageService, request_id: str, *, actual_credits: int) -> None:
        raise ValueError("reservation not found")

    class FakeRegistry:
        async def dispatch_skill(self, app_id: str, skill_id: str, request_body: dict) -> dict:
            assert request_body["stream"] is True
            return {
                "model": "test-model",
                "category": "general_knowledge",
                "choices": [{"message": {"content": "anonymous inference ok"}}],
                "usage": {"total_credits": 7},
            }

    directus = FakeDirectus()
    service = AnonymousFreeUsageService(directus_service=directus, hmac_secret="test-secret")
    await service.save_budget(
        enabled=True,
        monthly_budget_credits=2_000,
        daily_hard_cap_percent=5,
        weekly_cap_percent=25,
        per_identity_daily_cap_credits=400,
        admin_user_id="admin-1",
    )
    fake_skill_registry_module = ModuleType("backend.core.api.app.services.skill_registry")
    fake_skill_registry_module.get_global_registry = lambda: FakeRegistry()
    monkeypatch.setattr(anonymous_routes, "validate_request_domain", lambda _request: ("api.dev.openmates.org", False, "development"))
    monkeypatch.setattr(AnonymousFreeUsageService, "finalize_reservation", failing_finalize)
    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.skill_registry", fake_skill_registry_module)

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/v1/anonymous/chat/stream",
            "headers": [(b"host", b"api.dev.openmates.org"), (b"accept", b"text/event-stream")],
            "client": ("198.51.100.7", 443),
        }
    )
    payload = AnonymousChatStreamRequest(
        anonymous_id="anon-1",
        client_chat_id="chat-1",
        client_message_id="message-1",
        plaintext_message="Reply with exactly: anonymous inference ok",
    )

    with caplog.at_level("ERROR"):
        response = await anonymous_chat_stream(request=request, payload=payload, directus_service=directus, cache_service=FakeCache())
        body = ""
        async for chunk in response.body_iterator:
            body += chunk.decode() if isinstance(chunk, bytes) else str(chunk)

    events = [json.loads(line.removeprefix("data: ")) for line in body.splitlines() if line.startswith("data: ")]
    assert [event["type"] for event in events] == [
        "ai_task_initiated",
        "ai_typing_started",
        "ai_message_chunk",
        "ai_task_ended",
        "post_processing_completed",
    ]
    assert events[2]["full_content_so_far"] == "anonymous inference ok"
    assert events[3]["status"] == "completed"
    assert "reservation not found" not in body
    assert "Anonymous free usage reservation finalization failed" not in caplog.text


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering
async def test_anonymous_sse_sanitizes_internal_inference_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    async def accepted_open_request(
        self: AnonymousFreeUsageService,
        *,
        request_id: str,
        anonymous_id: str,
        ip_address: str,
    ) -> AnonymousReservationResult:
        return AnonymousReservationResult(accepted=True, request_id=request_id)

    class FailingRegistry:
        async def dispatch_skill(self, app_id: str, skill_id: str, request_body: dict) -> dict:
            raise RuntimeError("private provider diagnostic")

    fake_skill_registry_module = ModuleType("backend.core.api.app.services.skill_registry")
    fake_skill_registry_module.get_global_registry = lambda: FailingRegistry()
    monkeypatch.setattr(anonymous_routes, "validate_request_domain", lambda _request: ("api.dev.openmates.org", False, "development"))
    monkeypatch.setattr(AnonymousFreeUsageService, "open_request", accepted_open_request)
    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.skill_registry", fake_skill_registry_module)

    request = Request({
        "type": "http",
        "method": "POST",
        "path": "/v1/anonymous/chat/stream",
        "headers": [(b"host", b"api.dev.openmates.org"), (b"accept", b"text/event-stream")],
        "client": ("198.51.100.7", 443),
    })
    payload = AnonymousChatStreamRequest(
        anonymous_id="anon-1",
        client_chat_id="chat-1",
        client_message_id="message-1",
        plaintext_message="hello",
    )

    response = await anonymous_chat_stream(request=request, payload=payload, directus_service=FakeDirectus(), cache_service=FakeCache())
    body = ""
    async for chunk in response.body_iterator:
        body += chunk.decode() if isinstance(chunk, bytes) else str(chunk)

    assert "private provider diagnostic" not in body
    assert "Anonymous inference failed. Please try again." in body


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering
async def test_anonymous_sse_emits_initial_lifecycle_before_budget_reservation(monkeypatch: pytest.MonkeyPatch) -> None:
    reserve_started = asyncio.Event()
    release_reservation = asyncio.Event()

    async def delayed_open_request(
        self: AnonymousFreeUsageService,
        *,
        request_id: str,
        anonymous_id: str,
        ip_address: str,
    ) -> AnonymousReservationResult:
        reserve_started.set()
        await release_reservation.wait()
        return AnonymousReservationResult(accepted=True, request_id=request_id)

    async def noop_finalize(self: AnonymousFreeUsageService, request_id: str, *, actual_credits: int) -> None:
        return None

    class FakeRegistry:
        async def dispatch_skill(self, app_id: str, skill_id: str, request_body: dict) -> dict:
            assert request_body["anonymous_reservation_id"]
            return {
                "model": "test-model",
                "choices": [{"message": {"content": "after reservation"}}],
                "usage": {"total_credits": 3},
            }

    fake_skill_registry_module = ModuleType("backend.core.api.app.services.skill_registry")
    fake_skill_registry_module.get_global_registry = lambda: FakeRegistry()
    monkeypatch.setattr(anonymous_routes, "validate_request_domain", lambda _request: ("api.dev.openmates.org", False, "development"))
    monkeypatch.setattr(AnonymousFreeUsageService, "open_request", delayed_open_request)
    monkeypatch.setattr(AnonymousFreeUsageService, "finalize_reservation", noop_finalize)
    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.skill_registry", fake_skill_registry_module)

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/v1/anonymous/chat/stream",
            "headers": [(b"host", b"api.dev.openmates.org"), (b"accept", b"text/event-stream")],
            "client": ("198.51.100.7", 443),
        }
    )
    payload = AnonymousChatStreamRequest(
        anonymous_id="anon-1",
        client_chat_id="chat-1",
        client_message_id="message-1",
        plaintext_message="Reply after delayed reservation",
    )

    response = await anonymous_chat_stream(request=request, payload=payload, directus_service=FakeDirectus(), cache_service=FakeCache())
    iterator = response.body_iterator
    first = await asyncio.wait_for(iterator.__anext__(), timeout=0.5)
    second = await asyncio.wait_for(iterator.__anext__(), timeout=0.5)

    assert json.loads(str(first).removeprefix("data: "))["type"] == "ai_task_initiated"
    typing_event = json.loads(str(second).removeprefix("data: "))
    assert typing_event["type"] == "ai_typing_started"
    assert typing_event["title"] == "Reply after delayed reservation"

    third_chunk_task = asyncio.create_task(iterator.__anext__())
    await asyncio.wait_for(reserve_started.wait(), timeout=0.5)
    await asyncio.sleep(0)
    assert third_chunk_task.done() is False

    release_reservation.set()
    third = await asyncio.wait_for(third_chunk_task, timeout=0.5)
    assert json.loads(str(third).removeprefix("data: "))["type"] == "ai_message_chunk"


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering
async def test_anonymous_chat_keeps_json_response_for_native_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    directus = FakeDirectus()
    service = AnonymousFreeUsageService(directus_service=directus, hmac_secret="test-secret")
    await service.save_budget(
        enabled=True,
        monthly_budget_credits=2_000,
        daily_hard_cap_percent=5,
        weekly_cap_percent=25,
        per_identity_daily_cap_credits=400,
        admin_user_id="admin-1",
    )

    class FakeRegistry:
        async def dispatch_skill(self, app_id: str, skill_id: str, request_body: dict) -> dict:
            assert app_id == "ai"
            assert skill_id == "ask"
            assert request_body["stream"] is False
            assert request_body["is_anonymous"] is True
            assert request_body["apps_enabled"] is True
            return {
                "model": "test-model",
                "category": "general_knowledge",
                "choices": [{"message": {"content": "anonymous json ok"}}],
                "usage": {"total_credits": 5},
            }

    fake_skill_registry_module = ModuleType("backend.core.api.app.services.skill_registry")
    fake_skill_registry_module.get_global_registry = lambda: FakeRegistry()
    monkeypatch.setattr(anonymous_routes, "validate_request_domain", lambda _request: ("api.dev.openmates.org", False, "development"))
    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.skill_registry", fake_skill_registry_module)

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/v1/anonymous/chat/stream",
            "headers": [(b"host", b"api.dev.openmates.org")],
            "client": ("198.51.100.7", 443),
        }
    )
    payload = AnonymousChatStreamRequest(
        anonymous_id="anon-1",
        client_chat_id="chat-1",
        client_message_id="message-1",
        plaintext_message="Reply with exactly: anonymous json ok",
    )

    response = await anonymous_chat_stream(request=request, payload=payload, directus_service=directus, cache_service=FakeCache())

    assert response.status == "completed"
    assert response.assistant == "anonymous json ok"
    assert response.creditsCharged == 5


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=billing.anonymous.hard-capped-provider-metering
async def test_anonymous_json_does_not_double_finalize_worker_usage(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def failing_finalize(self: AnonymousFreeUsageService, request_id: str, *, actual_credits: int) -> None:
        raise ValueError("reservation not found")

    directus = FakeDirectus()
    service = AnonymousFreeUsageService(directus_service=directus, hmac_secret="test-secret")
    await service.save_budget(
        enabled=True,
        monthly_budget_credits=2_000,
        daily_hard_cap_percent=5,
        weekly_cap_percent=25,
        per_identity_daily_cap_credits=400,
        admin_user_id="admin-1",
    )

    class FakeRegistry:
        async def dispatch_skill(self, app_id: str, skill_id: str, request_body: dict) -> dict:
            assert request_body["stream"] is False
            return {
                "model": "test-model",
                "category": "general_knowledge",
                "choices": [{"message": {"content": "anonymous json ok"}}],
                "usage": {"total_credits": 5},
            }

    fake_skill_registry_module = ModuleType("backend.core.api.app.services.skill_registry")
    fake_skill_registry_module.get_global_registry = lambda: FakeRegistry()
    monkeypatch.setattr(anonymous_routes, "validate_request_domain", lambda _request: ("api.dev.openmates.org", False, "development"))
    monkeypatch.setattr(AnonymousFreeUsageService, "finalize_reservation", failing_finalize)
    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.skill_registry", fake_skill_registry_module)

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/v1/anonymous/chat/stream",
            "headers": [(b"host", b"api.dev.openmates.org")],
            "client": ("198.51.100.7", 443),
        }
    )
    payload = AnonymousChatStreamRequest(
        anonymous_id="anon-1",
        client_chat_id="chat-1",
        client_message_id="message-1",
        plaintext_message="Reply with exactly: anonymous json ok",
    )

    with caplog.at_level("ERROR"):
        response = await anonymous_chat_stream(request=request, payload=payload, directus_service=directus, cache_service=FakeCache())

    assert response.status == "completed"
    assert response.assistant == "anonymous json ok"
    assert response.creditsCharged == 5
    assert "Anonymous free usage reservation finalization failed" not in caplog.text
