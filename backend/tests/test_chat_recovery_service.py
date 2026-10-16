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


# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted,chats.message.identity-idempotent
@pytest.mark.anyio
async def test_atomic_first_personal_uses_real_service_transport_allowlist(monkeypatch) -> None:
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "test-internal-token")
    directus = FakeDirectus(FakeResponse(200, {"data": {"state": "ENQUEUED", "preflight_id": "canonical"}}))
    body = {"protocol_version": 1, "encrypted_user_message": {"encrypted_content": "private-ciphertext"}}

    result = await ChatRecoveryService(directus).execute("admit_first_personal", body)

    assert result == {"state": "ENQUEUED", "preflight_id": "canonical"}
    assert directus.calls == [{
        "method": "POST", "url": "http://cms:8055/chat-recovery-transaction",
        "headers": {"X-Internal-Service-Token": "test-internal-token"},
        "json": {"operation": "admit_first_personal", "data": body},
    }]


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


class BatchDirectus(FakeDirectus):
    def __init__(self) -> None:
        super().__init__(FakeResponse(200, {}))
        self.receipts: dict[str, dict] = {}

    async def _make_api_request(self, method: str, url: str, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        operation = kwargs["json"]["operation"]
        outputs = []
        for body in kwargs["json"]["data"]["outputs"]:
            record_id = body["record_id"]
            if operation == "get_replay_outputs":
                outputs.append({"record_id": record_id, "status": "ABSENT"})
            else:
                receipt = self.receipts.setdefault(record_id, {
                    "record_id": record_id, "state": "PENDING", "payload_storage": "inline",
                    "sealed_payload": body["sealed_payload"],
                })
                outputs.append(receipt)
        return FakeResponse(200, {"data": {"outputs": outputs}})


def batch_entries(count: int, payload: str | None = None) -> list[dict]:
    entries = [{"protocol_version": 1, "record_id": f"output-{i}",
                "hashed_user_id": "owner", "preflight_id": "preflight"} for i in range(count)]
    if payload is not None:
        for body in entries:
            body["sealed_payload"] = payload
    return entries


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
@pytest.mark.anyio
async def test_ten_inline_outputs_use_two_authenticated_rpcs_and_reuse_first_receipts(monkeypatch) -> None:
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "token")
    directus = BatchDirectus()
    service = ChatRecoveryService(directus)
    entries = batch_entries(10)
    assert await service.get_replay_outputs(entries) == [
        {"record_id": entry["record_id"], "status": "ABSENT"} for entry in entries
    ]
    original = await service.save_sealed_outputs(batch_entries(10, "first-randomized-envelope"))
    assert len(directus.calls) == 2
    assert all(call["headers"] == {"X-Internal-Service-Token": "token"} for call in directus.calls)
    reused = await service.save_sealed_outputs(batch_entries(10, "second-randomized-envelope"))
    assert reused == original
    assert all(receipt["sealed_payload"] == "first-randomized-envelope" for receipt in reused)


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
@pytest.mark.anyio
@pytest.mark.parametrize("count,payload,expected", [(65, "x", [32, 32, 1]), (3, "x" * (256 * 1024), [1, 1, 1]), (3, "é" * 60000, [1, 1, 1])])
async def test_inline_batches_bound_count_and_serialized_bytes(monkeypatch, count, payload, expected) -> None:
    import json
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "token")
    directus = BatchDirectus()
    receipts = await ChatRecoveryService(directus).save_sealed_outputs(batch_entries(count, payload))
    assert [receipt["record_id"] for receipt in receipts] == [entry["record_id"] for entry in batch_entries(count)]
    assert [len(call["json"]["data"]["outputs"]) for call in directus.calls] == expected
    assert all(len(json.dumps(call["json"]).encode("utf-8")) <= 512 * 1024 for call in directus.calls)


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
@pytest.mark.anyio
@pytest.mark.parametrize("response", [
    {}, {"outputs": []}, {"outputs": [None]},
    {"outputs": [{"record_id": "wrong", "status": "ABSENT"}]},
    {"outputs": [{"record_id": "output-0", "status": "BROKEN"}]},
    {"outputs": [{"record_id": "output-0", "status": []}]},
    {"outputs": [{"record_id": "output-0", "status": "PENDING", "payload_storage": []}]},
    {"outputs": [{"record_id": "output-0", "status": "PENDING", "state": "ACKNOWLEDGED"}]},
    {"outputs": [{"record_id": "output-0", "status": "PENDING", "payload_storage": "s3"}]},
    {"outputs": [{"record_id": "output-0", "status": "PENDING", "payload_s3_key": "unexpected"}]},
    {"outputs": [{"record_id": "output-0", "status": "PENDING", "sealed_payload": "x" * (256 * 1024 + 1)}]},
])
# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
async def test_batch_probes_reject_malformed_receipts(monkeypatch, response) -> None:
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "token")
    directus = FakeDirectus(FakeResponse(200, {"data": response}))
    with pytest.raises(RuntimeError):
        await ChatRecoveryService(directus).get_replay_outputs(batch_entries(1))


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
@pytest.mark.anyio
async def test_batch_response_order_and_write_state_fail_closed(monkeypatch) -> None:
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "token")
    directus = FakeDirectus(FakeResponse(200, {"data": {"outputs": [
        {"record_id": "output-1", "status": "ABSENT"},
        {"record_id": "output-0", "status": "ABSENT"},
    ]}}))
    with pytest.raises(RuntimeError, match="identity"):
        await ChatRecoveryService(directus).get_replay_outputs(batch_entries(2))
    directus.response = FakeResponse(200, {"data": {"outputs": [
        {"record_id": "output-0", "state": "PREPARING"},
    ]}})
    with pytest.raises(RuntimeError, match="state"):
        await ChatRecoveryService(directus).save_sealed_outputs(batch_entries(1, "sealed"))


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
@pytest.mark.anyio
@pytest.mark.parametrize("mutation", ["oversize", "mixed", "duplicate", "s3", "request_size"])
async def test_invalid_batch_is_rejected_before_any_rpc(monkeypatch, mutation) -> None:
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "token")
    directus = BatchDirectus()
    entries = batch_entries(33, "sealed")
    if mutation == "oversize":
        entries[-1]["sealed_payload"] = "é" * (128 * 1024 + 1)
    elif mutation == "mixed":
        entries[-1]["preflight_id"] = "other"
    elif mutation == "duplicate":
        entries[-1]["record_id"] = entries[0]["record_id"]
    elif mutation == "s3":
        entries[-1]["payload_s3_key"] = "key"
    else:
        entries[-1]["sealed_payload"] = "\x00" * 100000
    with pytest.raises(ValueError):
        await ChatRecoveryService(directus).save_sealed_outputs(entries)
    assert not directus.calls


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
@pytest.mark.anyio
@pytest.mark.parametrize("producer", [False, True])
async def test_inline_single_save_creates_atomically_without_redundant_probe(monkeypatch, producer) -> None:
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "token")
    first = {"record_id": "output", "state": "PENDING", "sealed_payload": "first"}
    directus = FakeDirectus(FakeResponse(200, {"data": first}))
    body = {"record_id": "output", "sealed_payload": "later", "content_commitment": "commitment"}
    if producer:
        body["producer_intent_id"] = "producer"
    assert await ChatRecoveryService(directus).save_sealed_output(body) == first
    assert [call["json"]["operation"] for call in directus.calls] == ["create_sealed_output"]


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
@pytest.mark.anyio
async def test_empty_batches_make_no_rpc_and_preparing_probes_are_explicit(monkeypatch) -> None:
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "token")
    directus = FakeDirectus(FakeResponse(200, {"data": {"outputs": [
        {"record_id": "output-0", "status": "PREPARING", "state": "PREPARING"},
    ]}}))
    service = ChatRecoveryService(directus)
    assert await service.get_replay_outputs([]) == []
    assert await service.save_sealed_outputs([]) == []
    assert directus.calls == []
    assert (await service.get_replay_outputs(batch_entries(1)))[0]["status"] == "PREPARING"


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
@pytest.mark.anyio
@pytest.mark.parametrize("status", ["PENDING", "ACKNOWLEDGED", "PREPARING"])
@pytest.mark.parametrize("encoded_regions", [False, True])
async def test_existing_s3_probe_returns_only_bounded_metadata_without_fetching(monkeypatch, status, encoded_regions) -> None:
    import json
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "token")
    receipt = {
        "record_id": "output-0", "status": status, "state": status,
        "payload_storage": "s3", "sealed_payload": None,
        "payload_s3_key": "chat-recovery/v2/key" if status == "PENDING" else None,
        "sealed_payload_digest": "a" * 64, "payload_size_bytes": 300000,
        "payload_verified_regions": json.dumps(["region-a", "region-b"]) if encoded_regions else ["region-a", "region-b"],
    }
    if status == "PREPARING":
        receipt["payload_s3_key"] = "chat-recovery/v2/key"
        receipt["payload_verified_regions"] = None
    directus = FakeDirectus(FakeResponse(200, {"data": {"outputs": [receipt]}}))
    service = ChatRecoveryService(directus)
    assert await service.get_replay_outputs(batch_entries(1)) == [receipt]
    assert len(directus.calls) == 1
    with pytest.raises(RuntimeError, match="state" if status == "PREPARING" else "inline storage"):
        await service.save_sealed_outputs(batch_entries(1, "sealed"))


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
@pytest.mark.anyio
@pytest.mark.parametrize("field,value", [
    ("sealed_payload", "unexpected"), ("payload_s3_key", "x" * 1025),
    ("sealed_payload_digest", "bad"), ("payload_size_bytes", 24 * 1024 * 1024 + 1),
    ("payload_size_bytes", True), ("payload_verified_regions", "invalid"),
    ("payload_verified_regions", ["x" * 129]),
])
async def test_existing_s3_probe_rejects_unbounded_or_invalid_metadata(monkeypatch, field, value) -> None:
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "token")
    receipt = {
        "record_id": "output-0", "status": "PENDING", "state": "PENDING",
        "payload_storage": "s3", "sealed_payload": None,
        "payload_s3_key": "key", "sealed_payload_digest": "a" * 64,
        "payload_size_bytes": 300000, "payload_verified_regions": ["region-a"],
    }
    receipt[field] = value
    directus = FakeDirectus(FakeResponse(200, {"data": {"outputs": [receipt]}}))
    with pytest.raises(RuntimeError, match="S3 metadata"):
        await ChatRecoveryService(directus).get_replay_outputs(batch_entries(1))


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
@pytest.mark.anyio
@pytest.mark.parametrize("receipt", [
    {"record_id": "output", "state": "PREPARING", "payload_storage": "s3"},
    {"record_id": "output", "state": "DELETED"},
    {"record_id": "other", "state": "PENDING"},
    {"record_id": "output"}, {},
    {"record_id": "output", "state": []},
])
async def test_inline_atomic_create_rejects_unsealed_or_malformed_receipt(monkeypatch, receipt) -> None:
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "token")
    directus = FakeDirectus(FakeResponse(200, {"data": receipt}))
    body = {"record_id": "output", "sealed_payload": "randomized-retry", "content_commitment": "same-commitment"}
    with pytest.raises(RuntimeError, match="inline sealed output receipt"):
        await ChatRecoveryService(directus).save_sealed_output(body)
    assert [call["json"]["operation"] for call in directus.calls] == ["create_sealed_output"]


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
@pytest.mark.anyio
async def test_inline_producer_retry_reuses_original_record_identity(monkeypatch) -> None:
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "token")
    receipt = {"record_id": "first-record", "state": "PENDING", "sealed_payload": "first-envelope"}
    directus = FakeDirectus(FakeResponse(200, {"data": receipt}))
    body = {"record_id": "retry-record", "producer_intent_id": "same-producer",
            "sealed_payload": "randomized-retry", "content_commitment": "same-commitment"}
    assert await ChatRecoveryService(directus).save_sealed_output(body) == receipt
    assert [call["json"]["operation"] for call in directus.calls] == ["create_sealed_output"]
