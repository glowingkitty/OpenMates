"""Scheduled completion identity, target and independent channel regressions."""

from __future__ import annotations

from types import SimpleNamespace
import base64
import json
import uuid
from urllib.parse import parse_qs, urlsplit

import pytest

from backend.core.api.app.services import workflow_completion_notification_service as completion
from backend.core.api.app.services.workflow_models import (
    WorkflowNodeRun, WorkflowNodeRunStatus, WorkflowNodeType,
    WorkflowRunDetail, WorkflowRunStatus,
)
from backend.core.api.app.services.push_notification_service import (
    APNS_ENCRYPTION_INFO, APNS_ENCRYPTION_VERSION, PushNotificationService,
)
from backend.core.api.app.services.notification_event_service import NotificationEvent, NotificationEventService
from backend.core.api.app.tasks.workflow_tasks import reconcile_workflow_completions_now


class FakeDirectus:
    def __init__(self) -> None:
        self.outbox: dict | None = None
        self.deliveries: list[dict] = []
        self.fail_target_pin_once = False

    async def get_items(self, collection: str, params: dict, **_kwargs: object) -> list[dict]:
        if collection == completion.COLLECTION:
            return [dict(self.outbox)] if self.outbox and self.outbox["run_id"] == params["filter"]["run_id"]["_eq"] else []
        if collection == "workflow_chat_deliveries":
            wanted = params["filter"]["_and"][0]["delivery_id"]["_eq"]
            return [dict(row) for row in self.deliveries if row["delivery_id"] == wanted]
        raise AssertionError(collection)

    async def create_item(self, collection: str, row: dict, **_kwargs: object) -> tuple[bool, dict]:
        assert collection == completion.COLLECTION
        self.outbox = dict(row)
        return True, dict(row)

    async def update_item(self, collection: str, row_id: str, changes: dict, **_kwargs: object) -> bool:
        assert collection == completion.COLLECTION and self.outbox and self.outbox["id"] == row_id
        if self.fail_target_pin_once and "chat_id" in changes:
            self.fail_target_pin_once = False
            return False
        self.outbox.update(changes)
        return True


def _run(node_runs: list[WorkflowNodeRun]) -> WorkflowRunDetail:
    return WorkflowRunDetail(
        id="run-1", workflow_id="workflow-1", version_id="version-1",
        trigger_type="schedule", status=WorkflowRunStatus.COMPLETED, finished_at=123,
        node_runs=node_runs,
    )


def _send_node(node_id: str, delivery_id: str, *, status: WorkflowNodeRunStatus = WorkflowNodeRunStatus.COMPLETED) -> WorkflowNodeRun:
    return WorkflowNodeRun(
        id=node_id, run_id="run-1", workflow_id="workflow-1", node_id=node_id,
        node_type=WorkflowNodeType.SEND_CHAT_MESSAGE, status=status,
        output_summary={"delivery_id": delivery_id},
    )


@pytest.mark.anyio
@pytest.mark.parametrize(("trigger_type", "status"), [
    ("manual", "completed"),
    ("test", "completed"),
    ("schedule", "failed"),
    ("schedule", "cancelled"),
])
# contract-test: supporting surface=rest_api assertions=notifications.workflow-run.completed-delivery
async def test_non_scheduled_or_unsuccessful_run_emits_no_completion(
    monkeypatch: pytest.MonkeyPatch, trigger_type: str, status: str,
) -> None:
    class DirectusWithRun(FakeDirectus):
        async def get_items(self, collection: str, params: dict, **kwargs: object) -> list[dict]:
            if collection != "workflow_runs":
                return await super().get_items(collection, params, **kwargs)
            filters = params["filter"]["_and"]
            expected = {
                "run_id": "run-1", "workflow_id": "workflow-1",
                "trigger_type": trigger_type, "status": status,
            }
            from backend.core.api.app.services.workflow_service import _hash_owner_id
            expected["hashed_user_id"] = _hash_owner_id("alice")
            if any(expected.get(key) != condition["_eq"] for item in filters for key, condition in item.items()):
                return []
            return [{"run_id": "run-1", "status": status, "finished_at": 123}]

    directus = DirectusWithRun()
    # Even an erroneous or stale reservation must not bypass the durable run check.
    await completion.reserve_completion(directus, run_id="run-1", workflow_id="workflow-1", owner_user_id="alice")
    emitted: list[str] = []

    async def unexpected_event(*_args: object) -> bool:
        emitted.append("event")
        return True

    async def unexpected_push(*_args: object) -> str:
        emitted.append("push")
        return "accepted"

    async def unexpected_email(*_args: object) -> str:
        emitted.append("email")
        return "sent"

    monkeypatch.setattr(completion.NotificationEventService, "store_and_publish_once", unexpected_event)
    monkeypatch.setattr(completion, "_dispatch_push", unexpected_push)
    monkeypatch.setattr(completion, "_dispatch_email", unexpected_email)
    result = await completion.dispatch_completion(
        SimpleNamespace(directus_service=directus, cache_service=object()), "run-1",
        SimpleNamespace(get_run=lambda *_: pytest.fail("Invalid run was loaded for delivery")),
    )
    assert result == {"status": "not_completed"}
    assert emitted == []
    assert directus.outbox
    expected_state = "pending" if trigger_type != "schedule" else "skipped"
    assert directus.outbox["event_state"] == expected_state
    assert directus.outbox["push_state"] == expected_state
    assert directus.outbox["email_state"] == expected_state


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=notifications.workflow-run.chat-target
async def test_completion_pins_first_actual_send_message_and_exact_route() -> None:
    directus = FakeDirectus()
    await completion.reserve_completion(directus, run_id="run-1", workflow_id="workflow-1", owner_user_id="alice")
    from backend.core.api.app.services.workflow_service import _hash_owner_id
    owner_hash = _hash_owner_id("alice").removeprefix("user_sha256:")
    directus.deliveries = [
        {"delivery_id": "delivery-1", "chat_id": "chat-1", "message_id": "message-1", "status": "delivery_pending"},
        {"delivery_id": "delivery-2", "chat_id": "chat-2", "message_id": "message-2", "status": "acknowledged"},
    ]
    assert owner_hash
    await completion.record_first_chat_target(directus, _run([
        _send_node("skipped", "absent", status=WorkflowNodeRunStatus.SKIPPED),
        _send_node("first", "delivery-1"), _send_node("second", "delivery-2"),
    ]), "alice")
    assert directus.outbox and directus.outbox["chat_id"] == "chat-1"
    assert directus.outbox["delivery_id"] == "delivery-1"
    url = completion.completion_url(directus.outbox)
    assert parse_qs(urlsplit(url).fragment) == {
        "workflow-id": ["workflow-1"], "workflow-tab": ["runs"],
        "run-id": ["run-1"], "workflow-completion": ["1"],
        "chat-id": ["chat-1"], "message-id": ["message-1"], "delivery-id": ["delivery-1"],
    }


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=notifications.workflow-run.run-target
async def test_completed_run_without_send_targets_exact_run() -> None:
    directus = FakeDirectus()
    await completion.reserve_completion(directus, run_id="run-1", workflow_id="workflow-1", owner_user_id="alice")
    await completion.record_first_chat_target(directus, _run([
        _send_node("skipped", "absent", status=WorkflowNodeRunStatus.SKIPPED),
    ]), "alice")
    assert directus.outbox
    assert parse_qs(urlsplit(completion.completion_url(directus.outbox)).fragment) == {
        "workflow-id": ["workflow-1"], "workflow-tab": ["runs"],
        "run-id": ["run-1"], "workflow-completion": ["1"],
    }


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=notifications.workflow-run.chat-target
async def test_owner_run_projection_survives_pruned_content_but_rejects_wrong_owner() -> None:
    directus = FakeDirectus()
    await completion.reserve_completion(directus, run_id="run-1", workflow_id="workflow-1", owner_user_id="alice")
    assert directus.outbox
    directus.outbox.update(chat_id="chat-1", message_id="message-1", delivery_id="delivery-1")
    pruned_run = _run([]).model_copy(update={"content_available": False, "node_runs": []})
    projection = await completion.owner_run_completion_projection(directus, pruned_run, "alice")
    assert projection == {
        "notification_id": "workflow-completed-run-1",
        "chat_id": "chat-1", "message_id": "message-1", "delivery_id": "delivery-1",
    }
    assert await completion.owner_run_completion_projection(directus, pruned_run, "mallory") is None
    assert await completion.owner_run_completion_projection(
        directus, pruned_run.model_copy(update={"status": WorkflowRunStatus.FAILED}), "alice",
    ) is None


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=notifications.workflow-run.chat-target,notifications.workflow-run.completed-delivery
async def test_pruned_before_pin_recovers_first_send_from_stable_execution_identity() -> None:
    directus = FakeDirectus()
    await completion.reserve_completion(directus, run_id="run-1", workflow_id="workflow-1", owner_user_id="alice")
    first_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "openmates:workflow:run-1:iteration-1:delivery"))
    second_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "openmates:workflow:run-1:iteration-2:delivery"))
    directus.deliveries = [
        {"delivery_id": first_id, "chat_id": "first-chat", "message_id": "first-message", "status": "acknowledged"},
        {"delivery_id": second_id, "chat_id": "second-chat", "message_id": "second-message", "status": "delivery_pending"},
    ]
    pruned = _run([
        _send_node("iteration-1", "ignored").model_copy(update={"output_summary": {}}),
        _send_node("iteration-2", "ignored").model_copy(update={"output_summary": {}}),
    ]).model_copy(update={"content_available": False})
    await completion.record_first_chat_target(directus, pruned, "alice")
    assert directus.outbox and directus.outbox["chat_id"] == "first-chat"
    assert directus.outbox["delivery_id"] == first_id


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=notifications.workflow-run.chat-target,notifications.workflow-run.completed-delivery
async def test_failed_target_pin_sends_nothing_until_retry_resolves_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    directus = FakeDirectus()
    await completion.reserve_completion(directus, run_id="run-1", workflow_id="workflow-1", owner_user_id="alice")
    directus.deliveries = [{
        "delivery_id": "delivery-1", "chat_id": "chat-1",
        "message_id": "message-1", "status": "delivery_pending",
    }]
    directus.fail_target_pin_once = True
    emitted: list[str] = []

    async def confirmed(*_args: object) -> bool:
        return True

    async def published(*_args: object) -> bool:
        emitted.append("event")
        return True

    async def push(*_args: object) -> str:
        emitted.append("push")
        return "accepted"

    async def email(*_args: object) -> str:
        emitted.append("email")
        return "sent"

    monkeypatch.setattr(completion, "_confirmed_run", confirmed)
    monkeypatch.setattr(completion.NotificationEventService, "store_and_publish_once", published)
    monkeypatch.setattr(completion, "_dispatch_push", push)
    monkeypatch.setattr(completion, "_dispatch_email", email)
    task = SimpleNamespace(directus_service=directus, cache_service=object())
    service = SimpleNamespace(
        resolve_user_vault_key_id=lambda *_: None,
        get_run=lambda *_: _run([_send_node("send", "delivery-1")]),
    )
    assert await completion.dispatch_completion(task, "run-1", service) == {"status": "target_pending"}
    assert emitted == [] and directus.outbox and directus.outbox["event_state"] == "pending"
    result = await completion.dispatch_completion(task, "run-1", service)
    assert result["status"] == "completed"
    assert emitted == ["event", "push", "email"]
    assert directus.outbox and directus.outbox["chat_id"] == "chat-1"


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=notifications.workflow-run.completed-delivery
async def test_push_failure_does_not_block_email(monkeypatch: pytest.MonkeyPatch) -> None:
    directus = FakeDirectus()
    await completion.reserve_completion(directus, run_id="run-1", workflow_id="workflow-1", owner_user_id="alice")

    async def confirmed(*_args: object) -> bool:
        return True

    async def published(*_args: object) -> bool:
        return True

    async def failed_push(*_args: object) -> str:
        raise RuntimeError("APNs unavailable")

    async def sent_email(*_args: object) -> str:
        return "sent"

    monkeypatch.setattr(completion, "_confirmed_run", confirmed)
    monkeypatch.setattr(completion.NotificationEventService, "store_and_publish_once", published)
    monkeypatch.setattr(completion, "_dispatch_push", failed_push)
    monkeypatch.setattr(completion, "_dispatch_email", sent_email)
    result = await completion.dispatch_completion(
        SimpleNamespace(directus_service=directus, cache_service=object()),
        "run-1", SimpleNamespace(resolve_user_vault_key_id=lambda *_: None,
                                 get_run=lambda *_: _run([])),
    )
    assert result["push"] == "failed" and result["email"] == "sent"
    assert directus.outbox and directus.outbox["event_state"] == "published"


# contract-test: supporting surface=gui.apple assertions=notifications.workflow-run.completed-delivery,notifications.content.privacy-boundary
def test_workflow_apns_title_is_device_encrypted() -> None:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import x25519
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    def decode(value: str) -> bytes:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

    private = x25519.X25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw,
    )
    subscription = {
        "notification_public_key": base64.urlsafe_b64encode(public).rstrip(b"=").decode(),
        "encryption_version": APNS_ENCRYPTION_VERSION,
    }
    envelope = PushNotificationService()._build_encrypted_apns_payload(
        subscription, "Your scheduled workflow completed.", title="Private rain check",
    )
    assert envelope and "Private rain check" not in json.dumps(envelope)
    ephemeral = x25519.X25519PublicKey.from_public_bytes(decode(envelope["ephemeral_public_key"]))
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=APNS_ENCRYPTION_INFO).derive(
        private.exchange(ephemeral),
    )
    decrypted = json.loads(AESGCM(key).decrypt(
        decode(envelope["nonce"]), decode(envelope["ciphertext"]), None,
    ))
    assert decrypted == {"title": "Private rain check", "body": "Your scheduled workflow completed."}


# contract-test: supporting surface=gui.apple assertions=notifications.workflow-run.completed-delivery
def test_watch_target_is_excluded_until_it_has_workflow_routing() -> None:
    targets = completion._apple_completion_targets({"type": "multi", "targets": [
        {"type": "apns", "platform": "watchos", "token": "watch"},
        {"type": "apns", "platform": "ios", "token": "phone"},
        {"type": "apns", "platform": "macos", "token": "mac"},
    ]})
    assert [target["token"] for target in targets] == ["phone", "mac"]


# contract-test: supporting surface=gui.apple assertions=notifications.workflow-run.completed-delivery,notifications.delivery.idempotent
def test_apns_reject_and_ambiguous_transport_are_classified_separately(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APNS_TEAM_ID", "test-team")
    monkeypatch.setenv("APNS_KEY_ID", "test-key")
    monkeypatch.setenv("APNS_PRIVATE_KEY", "test-private")
    service = PushNotificationService()
    monkeypatch.setattr(service, "_build_apns_jwt", lambda **_kwargs: "test-jwt")
    target = {"type": "apns", "platform": "ios", "token": "test-token"}

    class Client:
        fail_ambiguously = False

        def __init__(self, **_kwargs: object) -> None:
            pass

        def __enter__(self) -> "Client":
            return self

        def __exit__(self, *_args: object) -> None:
            pass

        def post(self, *_args: object, **_kwargs: object) -> SimpleNamespace:
            if self.fail_ambiguously:
                raise TimeoutError("response lost after write")
            return SimpleNamespace(status_code=503, text="unavailable")

    monkeypatch.setattr("httpx.Client", Client)
    result: list[str] = []
    assert not service._send_apns_notification(
        target, "OpenMates", "Completed", None, completion.APNS_CATEGORY, "tag",
        on_apns_result=result.append,
    )
    assert result == ["retryable_reject"]
    Client.fail_ambiguously = True
    result.clear()
    assert not service._send_apns_notification(
        target, "OpenMates", "Completed", None, completion.APNS_CATEGORY, "tag",
        on_apns_result=result.append,
    )
    assert result == ["uncertain"]


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=notifications.workflow-run.completed-delivery
async def test_reconciler_rotates_past_more_than_one_page_of_running_outboxes() -> None:
    class PendingDirectus:
        async def get_items(self, _collection: str, params: dict, **_kwargs: object) -> list[dict]:
            start = (params["page"] - 1) * params["limit"]
            return [{"run_id": f"run-{number}"} for number in range(start, min(start + params["limit"], 205))]

    class Cursor:
        value = 1

        async def get(self, _key: str) -> int:
            return self.value

        async def set(self, _key: str, value: int, **_kwargs: object) -> None:
            self.value = value

    cursor = Cursor()
    queued: list[str] = []
    for _ in range(3):
        await reconcile_workflow_completions_now(PendingDirectus(), cursor, queued.append, limit=100)
    assert len(queued) == 205
    assert queued[-1] == "run-204"
    assert cursor.value == 1


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=notifications.delivery.idempotent
async def test_stable_event_republishes_after_failed_transport_without_duplicate_history() -> None:
    class Client:
        stored = False
        eval_calls = 0

        async def eval(self, *_args: object) -> int:
            self.eval_calls += 1
            if self.stored:
                return 0
            self.stored = True
            return 1

    class Cache:
        _client = Client()
        published = False
        attempts = 0

        @property
        async def client(self) -> Client:
            return self._client

        async def publish_event(self, *_args: object) -> bool:
            self.attempts += 1
            return self.published

    cache = Cache()
    service = NotificationEventService(cache)
    event = NotificationEvent(
        id="workflow-completed-run-1", user_id="alice", type="workflow.run_completed",
        safe_title_key="apps.openmates", safe_body_key="notifications.workflow_run.completed",
    )
    with pytest.raises(RuntimeError, match="publication unavailable"):
        await service.store_and_publish_once(event)
    cache.published = True
    assert await service.store_and_publish_once(event) is False
    assert cache._client.eval_calls == 2 and cache.attempts == 2


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=notifications.workflow-run.completed-delivery
async def test_transient_user_lookup_stays_retryable() -> None:
    class Directus:
        base_url = "http://cms:8055"

        async def _make_api_request(self, *_args: object, **_kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(status_code=503)

    with pytest.raises(RuntimeError, match="HTTP 503"):
        await completion._load_user_strict(Directus(), "alice", ["id", "status"])
