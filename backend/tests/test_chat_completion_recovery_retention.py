"""
Retention and deletion contracts for sealed completion recovery jobs.

Tests use the Python transaction boundary rather than a live database. They
require explicit lifecycle entry points so expiry and deletion cannot depend on
client activity or accidentally trigger inference replay.
"""

import pytest

from backend.core.api.app.services.chat_recovery_service import ChatRecoveryService
from backend.core.api.app.routes.handlers.websocket_handlers import chat_recovery_job_handlers


class Response:
    status_code = 200

    def __init__(self, data: dict) -> None:
        self.data = data

    def json(self) -> dict:
        return {"data": self.data}


class Directus:
    base_url = "http://directus:8055"

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def _make_api_request(self, _method: str, _url: str, **kwargs) -> Response:
        self.calls.append(kwargs["json"])
        return Response({"expired_jobs": 1, "expired_tombstones": 1})


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover
async def test_expiry_cleanup_is_explicit_and_never_requests_inference_replay(monkeypatch) -> None:
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "internal-token")
    directus = Directus()

    result = await ChatRecoveryService(directus).execute("cleanup_expired", {"protocol_version": 1})

    assert result == {"expired_jobs": 1, "expired_tombstones": 1}
    assert directus.calls == [{"operation": "cleanup_expired", "data": {"protocol_version": 1}}]
    assert "inference" not in repr(directus.calls).lower()
    assert "replay" not in repr(directus.calls).lower()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scope", "extra"),
    [
        ("chat", {"chat_id": "11111111-1111-4111-8111-111111111111"}),
        ("account", {}),
        ("device", {"device_hash": "revoked-device"}),
    ],
)
# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover
async def test_deletion_and_revocation_use_atomic_invalidation(monkeypatch, scope: str, extra: dict) -> None:
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "internal-token")
    directus = Directus()
    data = {"protocol_version": 1, "hashed_user_id": "owner-hash", "scope": scope, **extra}

    await ChatRecoveryService(directus).execute("invalidate_deletion", data)

    assert directus.calls == [{"operation": "invalidate_deletion", "data": data}]


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=chats.completion.lease-fenced
async def test_retention_cleanup_has_server_side_entry_point(monkeypatch) -> None:
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "internal-token")
    monkeypatch.setattr(chat_recovery_job_handlers, "notification_environment", lambda: "self_hosted")
    directus = Directus()

    await chat_recovery_job_handlers.cleanup_expired_recovery_jobs(directus_service=directus)

    assert directus.calls == [{
        "operation": "cleanup_expired",
        "data": {"protocol_version": 1, "failure_alerts_enabled": False},
    }]


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=operational-monitoring.chat-failures.email-trigger
async def test_cleanup_replays_unacknowledged_alert_and_acks_only_definite_enqueue(monkeypatch) -> None:
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "internal-token")
    monkeypatch.setattr(chat_recovery_job_handlers, "notification_environment", lambda: "production")
    preflight_id = "77777777-7777-4777-8777-777777777777"
    task_id = "88888888-8888-4888-8888-888888888888"
    candidate = {
        "preflight_id": preflight_id,
        "inference_task_id": task_id,
        "chat_id": "99999999-9999-4999-8999-999999999999",
        "user_message_id": "user-message-1",
        "failure_category": "future_transport_error",
    }

    class AlertDirectus:
        base_url = "http://directus:8055"

        def __init__(self) -> None:
            self.calls: list[dict] = []
            self.acknowledged = False

        async def _make_api_request(self, _method: str, _url: str, **kwargs) -> Response:
            request = kwargs["json"]
            self.calls.append(request)
            if request["operation"] == "acknowledge_failure_alert":
                self.acknowledged = True
                return Response({"acknowledged": True})
            return Response({
                "expired_jobs": 0,
                "expired_tombstones": 0,
                "failure_alert_candidates": [] if self.acknowledged else [candidate],
            })

    enqueue_results = iter([False, True])
    notifications: list[tuple[str, str, str]] = []

    async def fake_notify(identity: str, *, stage: str, category: str) -> bool:
        notifications.append((identity, stage, category))
        return next(enqueue_results)

    monkeypatch.setattr(chat_recovery_job_handlers, "notify_chat_failure", fake_notify)
    directus = AlertDirectus()

    first = await chat_recovery_job_handlers.cleanup_expired_recovery_jobs(directus_service=directus)
    second = await chat_recovery_job_handlers.cleanup_expired_recovery_jobs(directus_service=directus)
    third = await chat_recovery_job_handlers.cleanup_expired_recovery_jobs(directus_service=directus)

    assert first["failure_alerts_queued"] == 0
    assert first["failure_alerts_pending"] == 1
    assert second["failure_alerts_queued"] == 1
    assert second["failure_alerts_pending"] == 0
    assert third["failure_alerts_queued"] == 0
    assert "failure_alert_candidates" not in first | second | third
    assert notifications == [
        ("99999999-9999-4999-8999-999999999999:user-message-1", "inference", "processing_error"),
        ("99999999-9999-4999-8999-999999999999:user-message-1", "inference", "processing_error"),
    ]
    assert [call for call in directus.calls if call["operation"] == "acknowledge_failure_alert"] == [{
        "operation": "acknowledge_failure_alert",
        "data": {
            "protocol_version": 1,
            "preflight_id": preflight_id,
            "inference_task_id": task_id,
            "failure_category": "future_transport_error",
        },
    }]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler_name", "kwargs", "expected_data"),
    [
        (
            "invalidate_recovery_jobs_for_chat_deletion",
            {"chat_id": "11111111-1111-4111-8111-111111111111"},
            {"scope": "chat", "chat_id": "11111111-1111-4111-8111-111111111111"},
        ),
        ("invalidate_recovery_jobs_for_account_deletion", {}, {"scope": "account"}),
    ],
)
# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover
async def test_deletion_entry_points_bind_server_owner(
    monkeypatch, handler_name: str, kwargs: dict, expected_data: dict
) -> None:
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "internal-token")
    directus = Directus()

    await getattr(chat_recovery_job_handlers, handler_name)(
        directus_service=directus,
        user_id_hash="authenticated-owner-hash",
        **kwargs,
    )

    assert directus.calls == [{
        "operation": "invalidate_deletion",
        "data": {
            "protocol_version": 1,
            "hashed_user_id": "authenticated-owner-hash",
            **expected_data,
        },
    }]


# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted,chats.completion.lease-fenced
def test_terminal_persistence_is_the_durable_acknowledgement_boundary() -> None:
    assert callable(chat_recovery_job_handlers.handle_recovery_job_persist)
