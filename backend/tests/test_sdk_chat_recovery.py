"""SDK saved-chat recovery route contracts.

These tests isolate API-key authorization from the atomic recovery extension.
They verify canonical inference dispatch, encrypted row identity, revocation,
scope enforcement, and ciphertext-only persistence without external services.
"""

from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock
import sys

import pytest
from fastapi import HTTPException

from backend.core.api.app.routes import sdk


USER_ID = "11111111-1111-4111-8111-111111111111"
TASK_ID = "77777777-7777-4777-8777-777777777777"


def _request() -> SimpleNamespace:
    return SimpleNamespace(
        headers={"Authorization": "Bearer test-key"},
        app=SimpleNamespace(state=SimpleNamespace(cache_service=object(), directus_service=object())),
    )


def _auth() -> dict:
    return {
        "user_id": USER_ID,
        "device_hash": "device-hash",
        "api_key_hash": "key-hash",
        "api_key_metadata": {"full_access": True},
    }


@pytest.fixture(autouse=True)
def epoch_one_cutover(monkeypatch):
    class EpochOneCutover:
        def __init__(self, _cache_service, _directus_service):
            pass

        async def get_state(self, *, authoritative: bool = False):
            assert authoritative is True
            return {"protocol_epoch": 1, "sends_paused": False, "legacy_in_flight": 0}

    monkeypatch.setattr(sdk, "ChatRecoveryCutoverController", EpochOneCutover)


@pytest.mark.asyncio
async def test_claim_and_persist_reauthenticate_and_exclude_plaintext(monkeypatch):
    authenticate = AsyncMock(side_effect=[_auth(), _auth()])
    execute = AsyncMock(side_effect=[{"state": "LEASED"}, {"state": "TERMINAL"}])
    monkeypatch.setattr(sdk, "_authenticate_sdk_request", authenticate)
    monkeypatch.setattr(sdk, "_execute_sdk_recovery", execute)

    await sdk.claim_sdk_chat_recovery(_request(), TASK_ID, sdk.SdkRecoveryClaimRequest())
    await sdk.persist_sdk_chat_recovery(
        _request(),
        TASK_ID,
        sdk.SdkRecoveryPersistRequest(
            lease_generation=1,
            lease_token="opaque-lease",
            expected_messages_v=2,
            encrypted_assistant_message={
                "client_message_id": TASK_ID,
                "chat_id": "chat-id",
                "encrypted_content": "ciphertext",
            },
        ),
    )

    assert authenticate.await_count == 2
    claim_data = execute.await_args_list[0].args[2]
    persist_data = execute.await_args_list[1].args[2]
    assert claim_data["hashed_user_id"] == persist_data["hashed_user_id"]
    assert claim_data["device_hash"] == persist_data["device_hash"] == "device-hash"
    assert "content" not in persist_data["encrypted_assistant_message"]
    assert persist_data["encrypted_assistant_message"]["encrypted_content"] == "ciphertext"


@pytest.mark.asyncio
async def test_api_key_or_device_revocation_between_claim_and_persist_is_rejected(monkeypatch):
    authenticate = AsyncMock(side_effect=[_auth(), HTTPException(status_code=401, detail="revoked")])
    execute = AsyncMock(return_value={"state": "LEASED"})
    monkeypatch.setattr(sdk, "_authenticate_sdk_request", authenticate)
    monkeypatch.setattr(sdk, "_execute_sdk_recovery", execute)

    await sdk.claim_sdk_chat_recovery(_request(), TASK_ID, sdk.SdkRecoveryClaimRequest())
    with pytest.raises(HTTPException) as exc:
        await sdk.persist_sdk_chat_recovery(
            _request(),
            TASK_ID,
            sdk.SdkRecoveryPersistRequest(
                lease_generation=1,
                lease_token="opaque-lease",
                expected_messages_v=2,
                encrypted_assistant_message={"client_message_id": TASK_ID, "encrypted_content": "ciphertext"},
            ),
        )
    assert exc.value.status_code == 401
    assert execute.await_count == 1


@pytest.mark.asyncio
async def test_claim_rejects_missing_saved_chat_scope(monkeypatch):
    restricted = _auth() | {"api_key_metadata": {"full_access": False, "scopes": {"chats": []}}}
    monkeypatch.setattr(sdk, "_authenticate_sdk_request", AsyncMock(return_value=restricted))
    execute = AsyncMock()
    monkeypatch.setattr(sdk, "_execute_sdk_recovery", execute)

    with pytest.raises(HTTPException) as exc:
        await sdk.claim_sdk_chat_recovery(_request(), TASK_ID, sdk.SdkRecoveryClaimRequest())
    assert exc.value.status_code == 403
    execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_rejects_encrypted_row_and_inference_identity_mismatch(monkeypatch):
    monkeypatch.setattr(sdk, "_authenticate_sdk_request", AsyncMock(return_value=_auth()))
    monkeypatch.setattr(sdk, "build_inference_commitment", lambda _request: "commitment")
    body = sdk.SdkChatCreateRequest(
        message="canonical",
        save_to_account=True,
        protocol_version=1,
        chat_id="chat-id",
        turn_id="turn-id",
        message_id="message-id",
        chat_key_version=1,
        encrypted_chat_key="wrapped-key",
        recovery_public_key="public-key",
        expected_messages_v=0,
        encrypted_user_message={"chat_id": "other-chat", "client_message_id": "message-id", "encrypted_content": "ciphertext"},
        inference_request={"messages": [{"role": "user", "content": "canonical"}]},
    )
    with pytest.raises(HTTPException) as exc:
        await sdk.create_sdk_chat(_request(), body)
    assert exc.value.detail["error"] == "encrypted_user_message_identity_mismatch"


@pytest.mark.asyncio
async def test_create_saved_chat_requires_authoritative_epoch_one_before_preflight(monkeypatch):
    class EpochZeroCutover:
        def __init__(self, _cache_service, _directus_service):
            pass

        async def get_state(self, *, authoritative: bool = False):
            assert authoritative is True
            return {"protocol_epoch": 0, "sends_paused": False, "legacy_in_flight": 0}

    monkeypatch.setattr(sdk, "ChatRecoveryCutoverController", EpochZeroCutover)
    monkeypatch.setattr(sdk, "_authenticate_sdk_request", AsyncMock(return_value=_auth()))
    execute = AsyncMock()
    monkeypatch.setattr(sdk.ChatRecoveryService, "execute", execute)

    with pytest.raises(HTTPException) as exc:
        await sdk.create_sdk_chat(
            _request(),
            sdk.SdkChatCreateRequest(
                message="canonical",
                save_to_account=True,
                protocol_version=1,
                chat_id="chat-id",
                turn_id="turn-id",
                message_id="message-id",
                chat_key_version=1,
                encrypted_chat_key="wrapped-key",
                recovery_public_key="public-key",
                expected_messages_v=0,
                encrypted_user_message={"chat_id": "chat-id", "client_message_id": "message-id", "encrypted_content": "ciphertext"},
                inference_request={"messages": [{"role": "user", "content": "canonical"}]},
            ),
        )

    assert exc.value.status_code == 426
    assert exc.value.detail["error"] == "client_update_required"
    execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_persist_rejects_assistant_row_identity_mismatch(monkeypatch):
    monkeypatch.setattr(sdk, "_authenticate_sdk_request", AsyncMock(return_value=_auth()))
    execute = AsyncMock()
    monkeypatch.setattr(sdk, "_execute_sdk_recovery", execute)
    with pytest.raises(HTTPException) as exc:
        await sdk.persist_sdk_chat_recovery(
            _request(),
            TASK_ID,
            sdk.SdkRecoveryPersistRequest(
                lease_generation=1,
                lease_token="opaque-lease",
                expected_messages_v=2,
                encrypted_assistant_message={"client_message_id": "other-id", "encrypted_content": "ciphertext"},
            ),
        )
    assert exc.value.detail["error"] == "encrypted_assistant_message_identity_mismatch"
    execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_dispatches_only_canonical_inference_values_with_stable_auth_identity(monkeypatch):
    registry = SimpleNamespace(dispatch_skill=AsyncMock(return_value={"task_id": TASK_ID}))
    registry_module = ModuleType("backend.core.api.app.services.skill_registry")
    registry_module.get_global_registry = lambda: registry
    monkeypatch.setitem(sys.modules, registry_module.__name__, registry_module)
    monkeypatch.setattr(sdk, "_authenticate_sdk_request", AsyncMock(return_value=_auth()))
    monkeypatch.setattr(sdk, "build_inference_commitment", lambda _request: "commitment")
    monkeypatch.setattr(
        sdk.ChatRecoveryService,
        "execute",
        AsyncMock(return_value={"preflight_id": "preflight-id"}),
    )
    monkeypatch.setattr(
        sdk,
        "enqueue_chat_turn",
        AsyncMock(return_value={"inference_task_id": TASK_ID, "outbox_id": "outbox-id"}),
    )
    mark_dispatched = AsyncMock(return_value={"state": "DISPATCHED"})
    monkeypatch.setattr(sdk, "_execute_sdk_recovery", mark_dispatched)
    inference_request = {
        "messages": [{"role": "user", "content": "canonical"}],
        "model": "canonical-model",
        "focus_mode": {"focus_mode_id": "canonical-focus"},
        "memory_ids": ["canonical-memory"],
    }

    result = await sdk.create_sdk_chat(
        _request(),
        sdk.SdkChatCreateRequest(
            message="canonical",
            save_to_account=True,
            protocol_version=1,
            chat_id="chat-id",
            turn_id="turn-id",
            message_id="message-id",
            chat_key_version=1,
            encrypted_chat_key="wrapped-key",
            recovery_public_key="public-key",
            expected_messages_v=0,
            encrypted_user_message={"chat_id": "chat-id", "client_message_id": "message-id", "encrypted_content": "ciphertext"},
            inference_request=inference_request,
        ),
    )
    retry = await sdk.create_sdk_chat(
        _request(),
        sdk.SdkChatCreateRequest(
            message="canonical",
            save_to_account=True,
            protocol_version=1,
            chat_id="chat-id",
            turn_id="turn-id",
            message_id="message-id",
            chat_key_version=1,
            encrypted_chat_key="wrapped-key",
            recovery_public_key="public-key",
            expected_messages_v=0,
            encrypted_user_message={"chat_id": "chat-id", "client_message_id": "message-id", "encrypted_content": "ciphertext"},
            inference_request=inference_request,
        ),
    )

    assert result["task_id"] == retry["task_id"] == TASK_ID
    assert registry.dispatch_skill.await_count == 2
    dispatch = registry.dispatch_skill.await_args.args[2]
    assert dispatch["current_user_content"] == "canonical"
    assert dispatch["user_preferences"]["model"] == "canonical-model"
    assert dispatch["active_focus_id"] == "canonical-focus"
    assert dispatch["memory_ids"] == ["canonical-memory"]
    assert dispatch["user_id"] == USER_ID
    assert dispatch["_api_key_hash"] == "key-hash"
    assert "inference_request" not in dispatch
