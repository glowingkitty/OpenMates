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
async def test_deletion_and_revocation_use_atomic_invalidation(monkeypatch, scope: str, extra: dict) -> None:
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "internal-token")
    directus = Directus()
    data = {"protocol_version": 1, "hashed_user_id": "owner-hash", "scope": scope, **extra}

    await ChatRecoveryService(directus).execute("invalidate_deletion", data)

    assert directus.calls == [{"operation": "invalidate_deletion", "data": data}]


@pytest.mark.asyncio
async def test_retention_cleanup_has_server_side_entry_point(monkeypatch) -> None:
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "internal-token")
    directus = Directus()

    await chat_recovery_job_handlers.cleanup_expired_recovery_jobs(directus_service=directus)

    assert directus.calls == [{"operation": "cleanup_expired", "data": {"protocol_version": 1}}]


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


def test_terminal_persistence_is_the_durable_acknowledgement_boundary() -> None:
    assert callable(chat_recovery_job_handlers.handle_recovery_job_persist)
