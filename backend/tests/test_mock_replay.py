# backend/tests/test_mock_replay.py
#
# Unit tests for E2E mock replay timing helpers.
#
# Mock replay publishes Redis events through the same channels as real AI
# streaming. These tests keep the default timing contract explicit so replay
# fixtures do not race ahead of the browser's active-chat subscription setup.

import asyncio

import pytest

try:
    from backend.apps.ai.testing.mock_replay import (
        DEFAULT_INITIAL_CHUNK_DELAY_MS,
        get_fixture_initial_delay_seconds,
        replay_fixture,
    )
    from backend.apps.ai.testing import mock_replay
    from backend.apps.ai.skills.ask_skill import AskSkillRequest
    from backend.core.api.app.schemas.chat import AIHistoryMessage
    from backend.shared.python_utils.chat_completion_recovery import derive_recovery_keypair
except ImportError as _exc:
    pytestmark = pytest.mark.skip(reason=f"Backend dependencies not installed: {_exc}")


class _StubCacheService:
    def __init__(self) -> None:
        self.events = []

    async def publish_event(self, channel: str, payload: dict) -> None:
        self.events.append((channel, payload))


class _StubDirectusResponse:
    status_code = 200

    def __init__(self, data: dict) -> None:
        self._data = data

    def json(self) -> dict:
        return self._data


class _StubDirectusService:
    base_url = "http://directus.test"

    def __init__(self) -> None:
        self.requests = []

    async def _make_api_request(self, method: str, url: str, **kwargs) -> _StubDirectusResponse:
        request_json = kwargs["json"]
        self.requests.append({"method": method, "url": url, **request_json})
        return _StubDirectusResponse({"data": {"job_id": request_json["data"]["job_id"]}})


def test_fixture_initial_delay_defaults_to_readiness_delay() -> None:
    assert get_fixture_initial_delay_seconds({}) == DEFAULT_INITIAL_CHUNK_DELAY_MS / 1000.0


def test_fixture_initial_delay_can_be_overridden_to_zero() -> None:
    assert get_fixture_initial_delay_seconds({"initial_delay_ms": 0}) == 0.0


def test_fixture_initial_delay_uses_fixture_value() -> None:
    assert get_fixture_initial_delay_seconds({"initial_delay_ms": 750}) == 0.75


def test_replay_fixture_recovery_final_chunk_includes_sealed_job_metadata(monkeypatch) -> None:
    chat_id = "22222222-2222-4222-8222-222222222222"
    task_id = "66666666-6666-4666-8666-666666666666"
    _, public_key = derive_recovery_keypair(
        "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8",
        chat_id,
        7,
    )
    fixture = {
        "response": "Recovered hello",
        "initial_delay_ms": 0,
        "preprocessing": {
            "category": "general_knowledge",
            "selected_model_name": "Mock model",
        },
        "usage": {"model_name": "Mock model", "total_credits": 1},
    }
    request_data = AskSkillRequest(
        chat_id=chat_id,
        message_id="55555555-5555-4555-8555-555555555555",
        user_id="11111111-1111-4111-8111-111111111111",
        user_id_hash="owner-hash",
        message_history=[AIHistoryMessage(role="user", content="hello", created_at=1)],
        recovery_task_id=task_id,
        recovery_preflight_id="77777777-7777-4777-8777-777777777777",
        recovery_turn_id="33333333-3333-4333-8333-333333333333",
        recovery_public_key=public_key,
        chat_key_version=7,
    )
    cache_service = _StubCacheService()
    directus_service = _StubDirectusService()

    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "test-token")
    monkeypatch.setattr(mock_replay, "load_fixture", lambda _fixture_id: fixture)

    asyncio.run(
        replay_fixture(
            fixture_id="connection_resilience",
            task_id=task_id,
            request_data=request_data,
            cache_service=cache_service,
            directus_service=directus_service,
            encryption_service=object(),
            user_vault_key_id="vault-key",
        )
    )

    final_chunks = [
        payload
        for _channel, payload in cache_service.events
        if payload.get("type") == "ai_message_chunk" and payload.get("is_final_chunk")
    ]
    assert len(final_chunks) == 1
    assert directus_service.requests[0]["operation"] == "create_sealed_job"
    assert directus_service.requests[0]["data"]["inference_task_id"] == task_id
    assert "Recovered hello" not in str(directus_service.requests[0]["data"])

    final_chunk = final_chunks[0]
    assert final_chunk["recovery_provisional"] is False
    assert final_chunk["recovery_turn_id"] == "33333333-3333-4333-8333-333333333333"
    assert final_chunk["chat_key_version"] == 7
    assert final_chunk["recovery_protocol_version"] == 1
    assert final_chunk["recovery_job_id"] == directus_service.requests[0]["data"]["job_id"]
