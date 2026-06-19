"""
backend/tests/test_anonymous_skill_access.py

Contract tests for anonymous execution gating. Anonymous callers may use skills
classified as not requiring connected accounts, but file/upload payloads and
connected-account skills must be rejected before inference or provider work.
"""

from __future__ import annotations

import sys
import json
from types import ModuleType

import pytest
from fastapi import HTTPException
from starlette.requests import Request

import backend.core.api.app.routes.anonymous as anonymous_routes
from backend.core.api.app.routes.anonymous import (
    AnonymousChatStreamRequest,
    anonymous_chat_stream,
    reject_anonymous_file_payloads,
    validate_anonymous_skill_allowed,
)
from backend.core.api.app.services.anonymous_free_usage_service import AnonymousFreeUsageService
from backend.tests.test_anonymous_free_usage_budget import FakeDirectus


def test_skill_without_connected_account_requirement_is_allowed() -> None:
    skill = {
        "id": "search",
        "connected_account_required": False,
    }

    validate_anonymous_skill_allowed("web", skill)


def test_connected_account_skill_is_rejected_for_anonymous_callers() -> None:
    skill = {
        "id": "get-events",
        "connected_account_required": True,
    }

    with pytest.raises(HTTPException) as exc_info:
        validate_anonymous_skill_allowed("calendar", skill)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "signup_required"


def test_missing_connected_account_classification_fails_closed() -> None:
    skill = {"id": "unknown"}

    with pytest.raises(HTTPException) as exc_info:
        validate_anonymous_skill_allowed("unknown", skill)

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail["code"] == "skill_metadata_missing"


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
async def test_anonymous_chat_dispatches_ai_and_finalizes_actual_credits(monkeypatch: pytest.MonkeyPatch) -> None:
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
            assert request_body["apps_enabled"] is False
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

    response = await anonymous_chat_stream(request=request, payload=payload, directus_service=directus)
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
    ]
    final_chunk = events[2]
    assert final_chunk["message_id"] != payload.client_message_id
    assert final_chunk["message_id"].startswith("chat-1-")
    assert final_chunk["full_content_so_far"] == "anonymous inference ok"
    assert final_chunk["is_final_chunk"] is True
    status = await service.get_budget_status()
    assert status.daily_used_credits == 7


@pytest.mark.asyncio
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
            assert request_body["apps_enabled"] is False
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

    response = await anonymous_chat_stream(request=request, payload=payload, directus_service=directus)

    assert response.status == "completed"
    assert response.assistant == "anonymous json ok"
    assert response.creditsCharged == 5
