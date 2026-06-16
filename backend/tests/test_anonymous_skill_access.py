"""
backend/tests/test_anonymous_skill_access.py

Contract tests for anonymous execution gating. Anonymous callers may use skills
classified as not requiring connected accounts, but file/upload payloads and
connected-account skills must be rejected before inference or provider work.
"""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import pytest
from fastapi import HTTPException

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
            assert request_body["is_anonymous"] is True
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

    request = SimpleNamespace(
        headers={"host": "api.dev.openmates.org"},
        client=SimpleNamespace(host="198.51.100.7"),
    )
    payload = AnonymousChatStreamRequest(
        anonymous_id="anon-1",
        client_chat_id="chat-1",
        client_message_id="message-1",
        plaintext_message="Reply with exactly: anonymous inference ok",
    )

    response = await anonymous_chat_stream(request, payload, directus)

    assert response.status == "completed"
    assert response.assistant == "anonymous inference ok"
    assert response.creditsCharged == 7
    status = await service.get_budget_status()
    assert status.daily_used_credits == 7
