"""
Unit contract for the Python-to-Directus recovery transaction boundary.

The service must fail closed without internal authentication, preserve typed
protocol errors, and never log or return request payloads containing encrypted
messages, sealed envelopes, or lease tokens.
"""

import pytest

from backend.core.api.app.services.chat_recovery_service import (
    ChatRecoveryProtocolError,
    ChatRecoveryService,
)


class FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class FakeDirectus:
    base_url = "http://cms:8055"

    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls: list[dict] = []

    async def _make_api_request(self, method: str, url: str, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        return self.response


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
@pytest.mark.anyio
async def test_execute_posts_internal_operation_and_returns_committed_data(monkeypatch) -> None:
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "test-internal-token")
    directus = FakeDirectus(FakeResponse(200, {"data": {"state": "PREPARED"}}))
    service = ChatRecoveryService(directus)

    result = await service.execute("prepare_preflight", {"protocol_version": 1, "turn_id": "turn"})

    assert result == {"state": "PREPARED"}
    assert directus.calls == [
        {
            "method": "POST",
            "url": "http://cms:8055/chat-recovery-transaction",
            "headers": {"X-Internal-Service-Token": "test-internal-token"},
            "json": {
                "operation": "prepare_preflight",
                "data": {"protocol_version": 1, "turn_id": "turn"},
            },
        }
    ]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "operation",
    [
        "mark_legacy_inference_completed",
        "acknowledge_legacy_persistence",
        "authorize_legacy_completion",
    ],
)
# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
async def test_execute_allows_bounded_legacy_completion_operations(
    monkeypatch, operation: str
) -> None:
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "test-internal-token")
    directus = FakeDirectus(FakeResponse(200, {"data": {"accepted": True}}))

    result = await ChatRecoveryService(directus).execute(
        operation,
        {"protocol_version": 1, "task_identity": "task-identity"},
    )

    assert result == {"accepted": True}
    assert directus.calls[0]["json"] == {
        "operation": operation,
        "data": {"protocol_version": 1, "task_identity": "task-identity"},
    }


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
@pytest.mark.anyio
async def test_execute_fails_closed_without_internal_token(monkeypatch) -> None:
    monkeypatch.delenv("INTERNAL_API_SHARED_TOKEN", raising=False)
    directus = FakeDirectus(FakeResponse(200, {"data": {}}))

    with pytest.raises(RuntimeError, match="INTERNAL_API_SHARED_TOKEN"):
        await ChatRecoveryService(directus).execute("prepare_preflight", {"protocol_version": 1})

    assert directus.calls == []


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
@pytest.mark.anyio
async def test_execute_raises_typed_sanitized_protocol_error(monkeypatch) -> None:
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "test-internal-token")
    directus = FakeDirectus(FakeResponse(409, {"error": {"code": "preflight_mismatch"}}))

    with pytest.raises(ChatRecoveryProtocolError) as raised:
        await ChatRecoveryService(directus).execute(
            "prepare_preflight",
            {"protocol_version": 1, "encrypted_user_message": "private-ciphertext"},
        )

    assert raised.value.status_code == 409
    assert raised.value.code == "preflight_mismatch"
    assert "private-ciphertext" not in str(raised.value)


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
@pytest.mark.anyio
async def test_execute_rejects_malformed_success_response(monkeypatch) -> None:
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "test-internal-token")
    directus = FakeDirectus(FakeResponse(200, {"unexpected": True}))

    with pytest.raises(RuntimeError, match="malformed"):
        await ChatRecoveryService(directus).execute("cleanup_expired", {"protocol_version": 1})


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery,chats.persistence.client-encrypted
@pytest.mark.anyio
@pytest.mark.parametrize("operation", ["invalidate_rewind", "lookup_chat_deletion_fences"])
async def test_execute_exposes_only_internal_bounded_chat_fence_operations(monkeypatch, operation: str) -> None:
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "test-internal-token")
    directus = FakeDirectus(FakeResponse(200, {"data": {"fenced_chat_ids": []}}))
    body = {"protocol_version": 1, "hashed_user_id": "a" * 64}
    if operation == "invalidate_rewind":
        body["chat_id"] = "018f4444-4444-7444-8444-444444444444"
    else:
        body["chat_ids"] = []

    assert await ChatRecoveryService(directus).execute(operation, body) == {"fenced_chat_ids": []}
    assert directus.calls[0]["json"] == {"operation": operation, "data": body}


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
def test_output_content_commitment_uses_existing_server_secret_and_domain(monkeypatch) -> None:
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "secret-one")
    first = ChatRecoveryService.content_commitment(b"private-output")
    assert len(first) == 64
    assert first == ChatRecoveryService.content_commitment("private-output")
    assert first != ChatRecoveryService.content_commitment(b"other-output")
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "secret-two")
    assert first != ChatRecoveryService.content_commitment(b"private-output")
    monkeypatch.delenv("INTERNAL_API_SHARED_TOKEN")
    with pytest.raises(RuntimeError, match="INTERNAL_API_SHARED_TOKEN"):
        ChatRecoveryService.content_commitment(b"private-output")


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
@pytest.mark.anyio
@pytest.mark.parametrize("operation", [
    "register_output_producer", "resolve_output_producer",
    "register_output_producer_child", "close_output_producer",
    "get_producer_output", "get_replay_output",
    "register_authorized_direct_skill", "complete_authorized_direct_by_embed",
    "complete_authorized_standalone_asset",
    "reconcile_authorized_direct_completions",
])
# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
async def test_producer_operations_are_internal_and_preserve_exact_payload(monkeypatch, operation: str) -> None:
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "test-internal-token")
    directus = FakeDirectus(FakeResponse(200, {"data": {"accepted": True}}))
    body = {"protocol_version": 1, "marker": "opaque"}

    assert await ChatRecoveryService(directus).execute(operation, body) == {"accepted": True}
    assert directus.calls[0]["json"] == {"operation": operation, "data": body}
