"""Retirement of status alerts and independent notification transport invariants."""
from types import SimpleNamespace
import base64
import json
import pytest
from backend.core.api.app.services import workflow_completion_notification_service as completion
from backend.core.api.app.services.push_notification_service import APNS_ENCRYPTION_INFO, APNS_ENCRYPTION_VERSION, PushNotificationService
from backend.core.api.app.services.notification_event_service import NotificationEvent, NotificationEventService


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=notifications.workflow-run.completed-delivery
async def test_queued_legacy_channels_retire_without_touching_sent_history():
    row = {"id": "legacy", "run_id": "run", "event_state": "pending", "push_state": "accepted", "email_state": "sent"}
    class Directus:
        async def get_items(self, *args, **kwargs):
            return [dict(row)]
        async def update_item(self, collection, row_id, changes, **kwargs):
            row.update(changes)
            return True
    task = SimpleNamespace(directus_service=Directus())
    assert await completion.dispatch_completion(task, "run") == {"status": "retired"}
    assert row["event_state"] == "retired" and row["push_state"] == "accepted" and row["email_state"] == "sent"
    assert await completion.dispatch_completion(task, "run") == {"status": "retired"}
    assert await completion.owner_run_completion_projection(task.directus_service, object(), "owner") is None


# contract-test: supporting surface=rest_api assertions=notifications.content.privacy-boundary
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
        target, "OpenMates", "Completed", None, "OPENMATES_CHAT_MESSAGE", "tag",
        on_apns_result=result.append,
    )
    assert result == ["retryable_reject"]
    Client.fail_ambiguously = True
    result.clear()
    assert not service._send_apns_notification(
        target, "OpenMates", "Completed", None, "OPENMATES_CHAT_MESSAGE", "tag",
        on_apns_result=result.append,
    )
    assert result == ["uncertain"]

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
# contract-test: supporting surface=rest_api assertions=notifications.workflow-run.run-target,notifications.workflow-run.chat-target,notifications.content.privacy-boundary
async def test_legacy_projection_preserves_exact_owner_target_after_content_pruning_without_creating_rows():
    from backend.core.api.app.services.workflow_models import WorkflowRunDetail, WorkflowRunContentStorage
    run = WorkflowRunDetail(id="run-1", workflow_id="workflow-1", version_id="version-1", trigger_type="schedule",
        status="completed", content_available=False, content_storage=WorkflowRunContentStorage.DELETED)
    row = {"id": "old-row", "run_id": run.id, "workflow_id": run.workflow_id, "owner_user_id": "owner",
        "notification_id": "workflow-completed-" + run.id, "chat_id": "old-chat", "message_id": "old-message",
        "delivery_id": "old-delivery", "event_state": "published", "push_state": "accepted", "email_state": "sent"}
    class Directus:
        reads = 0
        async def get_items(self, collection, **kwargs):
            assert collection == completion.COLLECTION
            assert kwargs["no_cache"] and kwargs["raise_on_error"]
            self.reads += 1
            return [dict(row)]
    directus = Directus()
    assert await completion.owner_run_completion_projection(directus, run, "owner") == {
        "notification_id": "workflow-completed-run-1", "chat_id": "old-chat", "message_id": "old-message", "delivery_id": "old-delivery"}
    assert directus.reads == 1 and row["email_state"] == "sent"
    assert await completion.owner_run_completion_projection(directus, run, "other-owner") is None
    for key, wrong in (("run_id", "other-run"), ("workflow_id", "other-workflow"), ("notification_id", "forged-notification")):
        original = row[key]
        row[key] = wrong
        assert await completion.owner_run_completion_projection(directus, run, "owner") is None
        row[key] = original
    for changes in ({"status": "failed"}, {"trigger_type": "manual"}):
        assert await completion.owner_run_completion_projection(directus, run.model_copy(update=changes), "owner") is None
    # Legacy status-only rows retain their exact run identity, not a fabricated
    # chat target selected from a later or unrelated Send output.
    for key in ("chat_id", "message_id", "delivery_id"):
        row.pop(key)
    assert await completion.owner_run_completion_projection(directus, run, "owner") == {"notification_id": "workflow-completed-run-1"}
