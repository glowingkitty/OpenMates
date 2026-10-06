# contract-test-file: infrastructure
"""A large sealed output must be inventoried before regional bytes can be written."""

import hashlib

import pytest

from backend.core.api.app.services import bounded_archive_io
from backend.core.api.app.services.chat_recovery_service import ChatRecoveryService
from backend.core.api.app.routes.handlers.websocket_handlers import chat_recovery_job_handlers


class _RecordingRecovery(ChatRecoveryService):
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, operation: str, data: dict) -> dict:
        self.calls.append((operation, dict(data)))
        return {"record_id": data["record_id"], "state":
                "PREPARING" if operation == "prepare_sealed_output" else "PENDING"}


# contract-test: direct surface=rest_api assertions=storage.background.complete-sealed-recovery
@pytest.mark.asyncio
async def test_large_output_upload_failure_keeps_durable_intent(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _RecordingRecovery()
    payload = "x" * 300_000
    record_id = "018f8888-8888-7888-8888-888888888888"

    async def failed_put(_s3, key: str, _raw: bytes, **_kwargs):
        assert [operation for operation, _ in service.calls] == ["prepare_sealed_output"]
        assert service.calls[0][1]["payload_s3_key"] == key
        raise RuntimeError("one region unavailable")

    monkeypatch.setattr(bounded_archive_io, "put_verified_bytes", failed_put)
    with pytest.raises(RuntimeError, match="one region unavailable"):
        await service.save_sealed_output({"record_id": record_id, "sealed_payload": payload}, s3_service=object())
    assert [operation for operation, _ in service.calls] == ["prepare_sealed_output"]
    prepared = service.calls[0][1]
    assert prepared["payload_size_bytes"] == len(payload)
    assert prepared["sealed_payload_digest"] == hashlib.sha256(payload.encode()).hexdigest()


# contract-test: direct surface=rest_api assertions=storage.background.complete-sealed-recovery
@pytest.mark.asyncio
async def test_large_output_is_published_only_after_verified_regional_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _RecordingRecovery()
    payload = "y" * 300_000
    checksum = hashlib.sha256(payload.encode()).hexdigest()

    async def verified_put(_s3, key: str, raw: bytes, **_kwargs):
        assert [operation for operation, _ in service.calls] == ["prepare_sealed_output"]
        assert service.calls[0][1]["payload_s3_key"] == key
        return {"checksum": checksum, "size_bytes": len(raw), "verified_regions": ["region-a", "region-b"]}

    monkeypatch.setattr(bounded_archive_io, "put_verified_bytes", verified_put)
    result = await service.save_sealed_output({
        "record_id": "018f8888-8888-7888-8888-888888888888", "sealed_payload": payload,
    }, s3_service=object())
    assert result["state"] == "PENDING"
    assert [operation for operation, _ in service.calls] == ["prepare_sealed_output", "create_sealed_output"]
    assert service.calls[1][1]["payload_verified_regions"] == ["region-a", "region-b"]
    assert "sealed_payload" not in service.calls[1][1]


# contract-test: direct surface=rest_api assertions=storage.background.complete-sealed-recovery
@pytest.mark.asyncio
async def test_discovery_scans_inaccessible_page_before_sending_later_output(monkeypatch: pytest.MonkeyPatch) -> None:
    class PagedRecovery:
        calls: list[dict] = []

        def __init__(self, _directus: object) -> None:
            pass

        async def execute(self, operation: str, data: dict) -> dict:
            assert operation == "list_pending_outputs"
            self.calls.append(dict(data))
            if len(self.calls) == 1:
                return {"outputs": [], "next_cursor": {
                    "after_created_at": "2029-01-01T00:00:00.000Z",
                    "after_record_id": "018f8888-8888-7888-8888-888888888888",
                }}
            return {"outputs": [{"record_id": "018f9999-9999-7999-9999-999999999999"}],
                    "next_cursor": None}

    class Manager:
        def __init__(self) -> None:
            self.messages: list[dict] = []

        def supports_typed_recovery_outputs(self, user_id: str, device_hash: str) -> bool:
            assert (user_id, device_hash) == ("user-1", "device-hash")
            return True

        def is_connection_completion_capable(self, _user_id: str, _device_hash: str) -> bool:
            return True

        async def send_personal_message(self, message: dict, _user_id: str, _device_hash: str) -> None:
            self.messages.append(message)

    monkeypatch.setattr(chat_recovery_job_handlers, "ChatRecoveryService", PagedRecovery)
    manager = Manager()
    await chat_recovery_job_handlers.send_available_recovery_outputs(
        manager=manager, directus_service=object(), user_id="user-1",
        user_id_hash="owner-hash", device_fingerprint_hash="device-hash",
    )
    assert len(PagedRecovery.calls) == 2
    assert PagedRecovery.calls[1]["after_record_id"] == "018f8888-8888-7888-8888-888888888888"
    assert [frame["type"] for frame in manager.messages] == [
        "recovery_outputs_available", "recovery_outputs_discovery_complete",
    ]
    assert manager.messages[0]["payload"]["outputs"][0]["record_id"] == "018f9999-9999-7999-9999-999999999999"
    assert manager.messages[1]["payload"]["status"] == "completed"


# contract-test: direct surface=rest_api assertions=storage.background.complete-sealed-recovery
@pytest.mark.asyncio
async def test_discovery_failure_emits_failed_fence_instead_of_false_completion(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailedRecovery:
        def __init__(self, _directus: object) -> None:
            pass

        async def execute(self, _operation: str, _data: dict) -> dict:
            raise RuntimeError("regional discovery unavailable")

    class Manager:
        def __init__(self) -> None:
            self.messages: list[dict] = []

        def supports_typed_recovery_outputs(self, user_id: str, device_hash: str) -> bool:
            assert (user_id, device_hash) == ("user-1", "device-hash")
            return True

        def is_connection_completion_capable(self, _user_id: str, _device_hash: str) -> bool:
            return True

        async def send_personal_message(self, message: dict, _user_id: str, _device_hash: str) -> None:
            self.messages.append(message)

    monkeypatch.setattr(chat_recovery_job_handlers, "ChatRecoveryService", FailedRecovery)
    manager = Manager()
    with pytest.raises(RuntimeError, match="regional discovery unavailable"):
        await chat_recovery_job_handlers.send_available_recovery_outputs(
            manager=manager, directus_service=object(), user_id="user-1",
            user_id_hash="owner-hash", device_fingerprint_hash="device-hash",
        )
    assert [frame["type"] for frame in manager.messages] == ["recovery_outputs_discovery_complete"]
    assert manager.messages[0]["payload"]["status"] == "failed"
