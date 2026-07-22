"""SDK saved-chat recovery route contracts.

These tests isolate API-key authorization from the atomic recovery extension.
They verify canonical inference dispatch, encrypted row identity, revocation,
scope enforcement, and ciphertext-only persistence without external services.
"""

from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock
import asyncio
import sys

import pytest
from fastapi import HTTPException

from backend.core.api.app.routes import sdk
from backend.core.api.app.services.directus.team_methods import hash_id
from backend.tests.test_token_broker_refs import FakeCache, FakeEncryption


USER_ID = "11111111-1111-4111-8111-111111111111"
TASK_ID = "77777777-7777-4777-8777-777777777777"


def _request() -> SimpleNamespace:
    return SimpleNamespace(
        headers={"Authorization": "Bearer test-key"},
        app=SimpleNamespace(state=SimpleNamespace(cache_service=object(), directus_service=object())),
    )


def _connected_account_request() -> SimpleNamespace:
    class FakeDirectus:
        async def get_items(self, _collection: str, params: dict | None = None):
            return [
                {
                    "id": params["filter[id][_eq]"],
                    "hashed_user_id": hash_id(USER_ID),
                    "provider_type_hash": hash_id("revolut_business"),
                }
            ]

    return SimpleNamespace(
        headers={"Authorization": "Bearer test-key"},
        app=SimpleNamespace(
            state=SimpleNamespace(
                cache_service=FakeCache(),
                encryption_service=FakeEncryption(),
                directus_service=FakeDirectus(),
            )
        ),
    )


def _auth() -> dict:
    return {
        "user_id": USER_ID,
        "device_hash": "device-hash",
        "api_key_hash": "key-hash",
        "api_key_metadata": {"full_access": True},
        "vault_key_id": "vault-key",
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


def test_create_marks_recovery_failed_when_dispatch_returns_no_task(monkeypatch):
    async def run_test():
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
                    inference_request={"messages": [{"role": "user", "content": "canonical"}], "model": "canonical-model"},
                ),
            )

        return exc

    registry = SimpleNamespace(dispatch_skill=AsyncMock(return_value={"status": "accepted_without_task"}))
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
    recovery_execute = AsyncMock(return_value={"failed": True})
    monkeypatch.setattr(sdk, "_execute_sdk_recovery", recovery_execute)

    exc = asyncio.run(run_test())

    assert exc.value.status_code == 502
    assert exc.value.detail == {
        "error": "ai_dispatch_failed",
        "message": "Message saved, but AI did not start. Please retry.",
        "chat_id": "chat-id",
        "message_id": "message-id",
        "retryable": True,
    }
    recovery_execute.assert_awaited_once()
    assert recovery_execute.await_args.args[1] == "mark_inference_failed"
    assert recovery_execute.await_args.args[2] == {
        "protocol_version": 1,
        "inference_task_id": TASK_ID,
        "failure_category": "dispatch_failed",
    }


@pytest.mark.asyncio
async def test_sdk_connected_account_skill_endpoint_brokers_refs_before_dispatch(monkeypatch):
    from backend.apps.ai.processing import connected_account_execution

    dispatched: dict[str, object] = {}

    async def exchange(refresh_token: str, scope_context: dict[str, object]) -> dict[str, object]:
        assert refresh_token == "refresh-secret"
        assert scope_context["provider_id"] == "revolut_business"
        return {"access_token": "access-secret", "expires_in": 3600}

    async def fake_call_app_skill(**kwargs):
        dispatched.update(kwargs)
        assert "refresh-secret" not in str(kwargs["input_data"])
        assert kwargs["input_data"]["_connected_account_access_tokens"]
        return {
            "ok": True,
            "account_count": 1,
            "owner_pii_mappings": [
                {
                    "placeholder": "[MERCHANT_SOFTWARE_001]",
                    "original": "SaaS Vendor Ltd",
                    "type": "COUNTERPARTY",
                }
            ],
        }

    apps_api_module = ModuleType("backend.core.api.app.routes.apps_api")
    apps_api_module.call_app_skill = fake_call_app_skill
    monkeypatch.setitem(sys.modules, apps_api_module.__name__, apps_api_module)
    monkeypatch.setattr(sdk, "_authenticate_sdk_request", AsyncMock(return_value=_auth()))
    monkeypatch.setattr(connected_account_execution, "exchange_refresh_token_for_provider", lambda _provider_id: exchange)

    result = await sdk.run_sdk_connected_account_skill(
        _connected_account_request(),
        "finance",
        "check_accounts",
        sdk.SdkConnectedAccountSkillRunRequest(
            input={
                "period": "monthly",
                "connected_account_requests": [{"source_ref": "revolut:sandbox"}],
                "csv_statements": [{"filename": "cash.csv", "content": "date,description,amount,currency\n2026-07-01,Cafe,-4.5,EUR"}],
                "security": {"prompt_injection_protection": "disabled"},
            },
            connected_account_token_ref_inputs=[
                {
                    "connected_account_id": "acct-1",
                    "app_id": "finance",
                    "provider_id": "revolut_business",
                    "allowed_actions": ["read"],
                    "action_scope": {"provider": "revolut_business"},
                    "refresh_token_envelope": {"refresh_token": "refresh-secret", "provider": "revolut_business"},
                }
            ],
            chat_id="chat-1",
            message_id="message-1",
        ),
    )

    assert result == {"ok": True, "account_count": 1}
    assert dispatched["app_id"] == "finance"
    assert dispatched["skill_id"] == "check_accounts"
    assert dispatched["enforce_rest_exposure_policy"] is False
    assert dispatched["input_data"]["security"] == {"prompt_injection_protection": "disabled"}


@pytest.mark.asyncio
async def test_sdk_connected_account_skill_maps_provider_token_exchange_failure(monkeypatch):
    from backend.apps.ai.processing import connected_account_execution
    from backend.shared.providers.revolut_business.oauth import RevolutBusinessTokenExchangeError

    async def exchange(_refresh_token: str, _scope_context: dict[str, object]) -> dict[str, object]:
        raise RevolutBusinessTokenExchangeError("Revolut Business token exchange failed with HTTP 401")

    monkeypatch.setattr(sdk, "_authenticate_sdk_request", AsyncMock(return_value=_auth()))
    monkeypatch.setattr(connected_account_execution, "exchange_refresh_token_for_provider", lambda _provider_id: exchange)

    with pytest.raises(HTTPException) as exc_info:
        await sdk.run_sdk_connected_account_skill(
            _connected_account_request(),
            "finance",
            "check_accounts",
            sdk.SdkConnectedAccountSkillRunRequest(
                input={
                    "period": "monthly",
                    "connected_account_requests": [{"source_ref": "revolut:sandbox"}],
                },
                connected_account_token_ref_inputs=[
                    {
                        "connected_account_id": "acct-1",
                        "app_id": "finance",
                        "provider_id": "revolut_business",
                        "allowed_actions": ["read"],
                        "action_scope": {"provider": "revolut_business"},
                        "refresh_token_envelope": {"refresh_token": "refresh-secret", "provider": "revolut_business"},
                    }
                ],
                chat_id="chat-1",
                message_id="message-1",
            ),
        )

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail == {
        "error": "provider_token_exchange_failed",
        "provider_id": "revolut_business",
    }


@pytest.mark.asyncio
async def test_connected_account_cleanup_does_not_require_provider_exchange() -> None:
    from backend.apps.ai.processing.connected_account_execution import cleanup_connected_account_token_artifacts

    await cleanup_connected_account_token_artifacts(
        token_artifacts=[
            {
                "turn_token_ref": "turn-ref-1",
                "access_token_handle": "access-handle-1",
                "provider_id": "revolut_business",
            }
        ],
        cache_service=FakeCache(),
        encryption_service=FakeEncryption(),
    )


@pytest.mark.asyncio
async def test_sdk_chat_route_converts_connected_account_inputs_to_safe_token_refs(monkeypatch):
    registry = SimpleNamespace(dispatch_skill=AsyncMock(return_value={"response": {"content": "ok"}}))
    registry_module = ModuleType("backend.core.api.app.services.skill_registry")
    registry_module.get_global_registry = lambda: registry
    monkeypatch.setitem(sys.modules, registry_module.__name__, registry_module)
    monkeypatch.setattr(sdk, "_authenticate_sdk_request", AsyncMock(return_value=_auth()))

    result = await sdk.create_sdk_chat(
        _connected_account_request(),
        sdk.SdkChatCreateRequest(
            message="Check my accounts",
            save_to_account=False,
            connected_account_directory=[
                {
                    "connected_account_id": "acct-1",
                    "app_id": "finance",
                    "provider_id": "revolut_business",
                    "account_ref": "revolut-sandbox",
                    "label": "Revolut Sandbox",
                    "capabilities": ["read"],
                }
            ],
            connected_account_token_ref_inputs=[
                {
                    "connected_account_id": "acct-1",
                    "app_id": "finance",
                    "provider_id": "revolut_business",
                    "allowed_actions": ["read"],
                    "action_scope": {"provider": "revolut_business"},
                    "refresh_token_envelope": {"refresh_token": "refresh-secret", "provider": "revolut_business"},
                }
            ],
        ),
    )

    assert result["response"]["content"] == "ok"
    payload = registry.dispatch_skill.await_args.args[2]
    assert payload["connected_account_directory"][0]["provider_id"] == "revolut_business"
    assert payload["connected_account_token_refs"][0]["provider_id"] == "revolut_business"
    assert payload["connected_account_token_refs"][0]["turn_token_ref"].startswith("tref_")
    assert "refresh-secret" not in str(payload)
