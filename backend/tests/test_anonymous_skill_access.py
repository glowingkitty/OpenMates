"""
backend/tests/test_anonymous_skill_access.py

Contract tests for anonymous execution gating. Anonymous callers may use skills
classified as not requiring connected accounts, but file/upload payloads and
connected-account skills must be rejected before inference or provider work.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from backend.core.api.app.routes.anonymous import (
    AnonymousChatStreamRequest,
    reject_anonymous_file_payloads,
    validate_anonymous_skill_allowed,
)


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
