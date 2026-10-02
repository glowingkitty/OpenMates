"""Pure metadata envelope tests; all material is synthetic and no service is used."""
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.exceptions import InvalidTag

from backend.shared.python_utils.chat_completion_recovery import open_recovery_envelope
from backend.shared.python_utils.chat_metadata_recovery import (
    build_sealed_metadata_job_data, metadata_associated_data, open_metadata_envelope,
)
from backend.core.api.app.routes.handlers.websocket_handlers import chat_metadata_recovery_handlers as handlers

VECTOR = Path(__file__).parent / "fixtures/chat_metadata_recovery_vectors.json"


def vector():
    return json.loads(VECTOR.read_text())


# contract-test: supporting surface=rest_api assertions=chats.sync.key-gated-recovery,chats.persistence.client-encrypted
def test_metadata_envelope_matches_shared_deterministic_vector_and_contains_only_sealed_storage():
    v = vector()
    data = build_sealed_metadata_job_data(**v["build"])
    assert data == v["job"]
    assert metadata_associated_data(**v["identity"]).hex() == v["associated_data_hex"]
    opened = open_metadata_envelope(json.loads(data["sealed_payload"]),
                                    recovery_private_key=v["private_key"], **v["identity"])
    assert opened["metadata"] == v["build"]["metadata"]
    assert "Synthetic summary" not in json.dumps(data)
    assert set(data["encrypted_fields"]) == {"encrypted_title", "encrypted_chat_summary", "encrypted_category", "encrypted_icon"}


@pytest.mark.parametrize("field,value", [
    ("owner_id", "99999999-9999-4999-8999-999999999999"),
    ("chat_id", "99999999-9999-4999-8999-999999999999"),
    ("task_id", "99999999-9999-4999-8999-999999999999"),
    ("job_id", "99999999-9999-4999-8999-999999999999"),
    ("stage", "initial"), ("key_version", 2),
])
# contract-test: supporting surface=rest_api assertions=chats.message.identity-idempotent,chats.persistence.client-encrypted
def test_every_owner_chat_task_job_stage_key_binding_is_authenticated(field, value):
    v = vector()
    identity = {**v["identity"], field: value}
    with pytest.raises(InvalidTag):
        open_metadata_envelope(json.loads(v["job"]["sealed_payload"]),
                               recovery_private_key=v["private_key"], **identity)


# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted
def test_assistant_protocol_one_cannot_open_metadata_envelope():
    v = vector()
    with pytest.raises(InvalidTag):
        open_recovery_envelope(json.loads(v["job"]["sealed_payload"]), recovery_private_key=v["private_key"],
                               owner_id=v["identity"]["owner_id"], chat_id=v["identity"]["chat_id"],
                               turn_id=v["identity"]["task_id"], job_id=v["identity"]["job_id"],
                               assistant_message_id=v["identity"]["task_id"], key_version=1)


# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted
def test_unknown_metadata_and_noncanonical_envelopes_fail_closed():
    v = vector()
    build = deepcopy(v["build"])
    build["metadata"]["content"] = "private assistant body"
    with pytest.raises(ValueError, match="unsupported metadata field"):
        build_sealed_metadata_job_data(**build)
    envelope = json.loads(v["job"]["sealed_payload"])
    envelope["plaintext"] = "not allowed"
    with pytest.raises(ValueError, match="unsupported metadata envelope"):
        open_metadata_envelope(envelope, recovery_private_key=v["private_key"], **v["identity"])


class Manager:
    def __init__(self):
        self.messages = []
        self.broadcasts = []

    async def send_personal_message(self, message, user_id, device):
        self.messages.append(message)

    async def broadcast_to_user(self, **kwargs):
        self.broadcasts.append(kwargs)


# contract-test: supporting surface=rest_api assertions=chats.message.identity-idempotent,chats.persistence.client-encrypted
@pytest.mark.anyio
async def test_authenticated_owner_overrides_supplied_identity_and_commit_precedes_ack(monkeypatch):
    calls = []
    manager = Manager()

    class Service:
        def __init__(self, directus):
            pass

        async def execute(self, operation, data):
            assert not manager.messages
            calls.append((operation, data))
            return {"job_id": "job", "chat_id": "chat", "state": "TERMINAL",
                    "versions": {"title_v": 1, "metadata_v": 1},
                    "encrypted_metadata": {"encrypted_title": "cipher"}}

    class Cache:
        async def delete_chat_list_item_data(self, *args):
            pass

        async def set_chat_version_component(self, *args):
            pass

    monkeypatch.setattr(handlers, "ChatRecoveryService", Service)
    await handlers.handle_metadata_recovery(
        manager=manager, cache_service=Cache(), directus_service=object(), user_id="owner",
        user_id_hash="server-owner-hash", device_fingerprint_hash="server-device", persist=True,
        payload={"protocol_version": 1, "job_id": "job", "hashed_user_id": "other-owner",
                 "device_hash": "other-device", "request_id": "request", "chat_key_version": 1,
                 "wrapped_chat_key": "wrapped", "encrypted_metadata": {"encrypted_title": "cipher"}},
    )
    assert calls[0][0] == "persist_metadata_job"
    assert calls[0][1]["hashed_user_id"] == "server-owner-hash"
    assert "device_hash" not in calls[0][1]
    assert manager.messages[0]["type"] == "metadata_job_persisted"
    assert manager.messages[0]["payload"]["request_id"] == "request"


# contract-test: supporting surface=rest_api assertions=chats.message.identity-idempotent,chats.persistence.client-encrypted
@pytest.mark.anyio
async def test_transaction_rejection_never_emits_success_ack(monkeypatch):
    from backend.core.api.app.services.chat_recovery_service import ChatRecoveryProtocolError

    class Service:
        def __init__(self, directus):
            pass

        async def execute(self, operation, data):
            raise ChatRecoveryProtocolError(404, "metadata_job_not_found")

    monkeypatch.setattr(handlers, "ChatRecoveryService", Service)
    manager = Manager()
    await handlers.handle_metadata_recovery(manager=manager, cache_service=None, directus_service=None,
        user_id="owner", user_id_hash="owner-hash", device_fingerprint_hash="device", persist=False,
        payload={"protocol_version": 1, "job_id": "job", "request_id": "request"})
    assert manager.messages == [{"type": "error", "payload": {
        "code": "metadata_job_not_found", "job_id": "job", "request_id": "request"}}]
    assert not manager.broadcasts


# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted
@pytest.mark.anyio
@pytest.mark.parametrize("stage", ["initial", "postprocessing"])
async def test_metadata_outage_queues_only_sealed_retry_and_does_not_fail_answer(monkeypatch, stage):
    import sys
    from types import ModuleType
    from backend.shared.python_utils import chat_metadata_recovery as recovery
    from backend.core.api.app.services import chat_recovery_service

    v = vector()
    queued = []
    directus_module = ModuleType("backend.core.api.app.services.directus")

    class Directus:
        async def close(self):
            pass

    directus_module.DirectusService = Directus
    monkeypatch.setitem(sys.modules, directus_module.__name__, directus_module)

    class OutageService:
        def __init__(self, directus):
            pass

        async def execute(self, operation, data):
            raise RuntimeError("injected transaction outage")

    monkeypatch.setattr(chat_recovery_service, "ChatRecoveryService", OutageService)
    monkeypatch.setattr(recovery, "queue_metadata_retry", queued.append)
    build = v["build"]
    request = SimpleNamespace(user_id=build["owner_id"], user_id_hash=build["owner_hash"], chat_id=build["chat_id"],
        recovery_preflight_id=build["preflight_id"], recovery_public_key=build["recovery_public_key"],
        chat_key_version=1, resolved_recovery_inference_task_id=lambda: build["inference_task_id"])
    from unittest.mock import AsyncMock
    inference = AsyncMock(return_value="completed assistant body")
    body_complete = AsyncMock()
    failure_cleanup = AsyncMock()
    # The caller executes each paid stage once; an injected persistence error
    # must return to its existing body publication path, never its failure path.
    try:
        if stage == "initial":
            admission = await recovery.persist_generated_metadata(request=request, task_id=build["task_id"],
                stage=stage, metadata=build["metadata"])
        body = await inference()
        if stage == "postprocessing":
            admission = await recovery.persist_generated_metadata(request=request, task_id=build["task_id"],
                stage=stage, metadata=build["metadata"])
        await body_complete(body)
    except Exception:
        await failure_cleanup()
    assert admission is None
    inference.assert_awaited_once()
    body_complete.assert_awaited_once_with("completed assistant body")
    failure_cleanup.assert_not_awaited()
    assert len(queued) == 1 and queued[0]["sealed_payload"]
    assert "Synthetic summary" not in json.dumps(queued)
    assert queued[0]["stage"] == stage


# contract-test: supporting surface=rest_api assertions=chats.sync.key-gated-recovery,chats.persistence.client-encrypted
@pytest.mark.anyio
async def test_admission_read_failure_leaves_transient_fallback_active(monkeypatch):
    class Service:
        def __init__(self, directus):
            pass

        async def execute(self, operation, data):
            raise RuntimeError("injected admission outage")

    monkeypatch.setattr(handlers, "ChatRecoveryService", Service)
    assert not await handlers.has_durable_metadata(directus_service=None, user_id_hash="owner", chat_id="chat", task_id="task")


# contract-test: supporting surface=rest_api assertions=chats.message.identity-idempotent,chats.persistence.client-encrypted
@pytest.mark.anyio
@pytest.mark.parametrize("admitted,supported", [(False, True), (True, True), (True, False)])
async def test_generated_storage_strips_only_admitted_capable_owner_job(monkeypatch, admitted, supported):
    class Service:
        def __init__(self, directus):
            pass

        async def execute(self, operation, data):
            assert operation == "metadata_job_admitted"
            assert data["hashed_user_id"] == "authenticated-owner"
            return {"admitted": admitted}

    monkeypatch.setattr(handlers, "ChatRecoveryService", Service)
    payload = {"chat_id": "chat", "task_id": "task", "encrypted_content": "user-body",
               "encrypted_title": "title", "encrypted_icon": "icon", "encrypted_chat_category": "chat-category",
               "encrypted_category": "message-category"}
    result = await handlers.filter_generated_metadata_storage(payload=payload, supports_recovery=supported,
        directus_service=None, user_id_hash="authenticated-owner")
    assert result["encrypted_content"] == "user-body"
    assert result["encrypted_category"] == "message-category"
    assert ("encrypted_title" not in result) == (admitted and supported)
    assert payload["encrypted_title"] == "title"


# contract-test: supporting surface=rest_api assertions=chats.sync.key-gated-recovery,chats.persistence.client-encrypted
@pytest.mark.anyio
@pytest.mark.parametrize("unsupported", ["team", "no-recovery", "external", "incognito"])
async def test_unsupported_metadata_admission_keeps_existing_transient_fields(monkeypatch, unsupported):
    from backend.shared.python_utils import chat_metadata_recovery as recovery
    request = SimpleNamespace(team_id="team" if unsupported == "team" else None,
        is_external=unsupported == "external", is_incognito=unsupported == "incognito",
        resolved_recovery_inference_task_id=lambda: None if unsupported == "no-recovery" else "task")
    monkeypatch.setattr(recovery, "queue_metadata_retry", lambda data: pytest.fail("Unsupported job cannot enqueue"))
    assert await recovery.persist_generated_metadata(request=request, task_id="task", stage="initial", metadata={"title": "Title"}) is None
    class Service:
        def __init__(self, directus):
            pass
        async def execute(self, operation, data):
            return {"admitted": False}
    monkeypatch.setattr(handlers, "ChatRecoveryService", Service)
    payload = {"chat_id": "chat", "task_id": "task", "encrypted_content": "body", "encrypted_title": "title",
               "encrypted_icon": "icon", "encrypted_chat_category": "category"}
    assert await handlers.filter_generated_metadata_storage(payload=payload, supports_recovery=True,
        directus_service=None, user_id_hash="owner") == payload

# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted
@pytest.mark.anyio
async def test_independent_retry_uses_original_sealed_generation_and_only_metadata_operation(monkeypatch):
    import importlib
    import sys
    from types import ModuleType

    calls, events = [], []
    configuration = ModuleType("backend.core.api.app.tasks.celery_config")
    registered = []

    class Celery:
        def task(self, **options):
            registered.append(options)
            return lambda function: function

    configuration.app = Celery()
    monkeypatch.setitem(sys.modules, configuration.__name__, configuration)
    directus = ModuleType("backend.core.api.app.services.directus")
    cache = ModuleType("backend.core.api.app.services.cache")

    class Connection:
        async def close(self):
            pass

    class Cache(Connection):
        async def publish_event(self, channel, event):
            events.append((channel, event))

    directus.DirectusService = Connection
    cache.CacheService = Cache
    monkeypatch.setitem(sys.modules, directus.__name__, directus)
    monkeypatch.setitem(sys.modules, cache.__name__, cache)
    # Load this dedicated task directly; importing the package would register
    # unrelated email/worker tasks and require their external dependencies.
    task_path = Path(__file__).parents[1] / "core/api/app/tasks/chat_metadata_recovery_tasks.py"
    spec = importlib.util.spec_from_file_location("metadata_retry_under_test", task_path)
    retry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(retry)

    class Service:
        def __init__(self, directus):
            pass

        async def execute(self, operation, data):
            calls.append((operation, deepcopy(data)))
            if len(calls) == 1:
                raise RuntimeError("Injected storage outage")
            return {key: data[key] for key in ("job_id", "chat_id", "task_id", "stage", "chat_key_version")}

    monkeypatch.setattr(retry, "ChatRecoveryService", Service)
    data = build_sealed_metadata_job_data(**vector()["build"])
    with pytest.raises(RuntimeError, match="Injected storage outage"):
        await retry.persist_pending_metadata(data)
    result = await retry.persist_pending_metadata(data)
    assert [operation for operation, _ in calls] == ["create_metadata_job"] * 2
    assert calls[0][1] == calls[1][1] == data
    assert result["job_id"] == data["job_id"]
    assert registered == [{"bind": True, "name": "app.tasks.persistence_tasks.persist_chat_metadata_recovery", "max_retries": 5}]
    assert events[0][1]["type"] == "chat_metadata_recovery_available"
    assert "Synthetic summary" not in json.dumps(events)


# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted,chats.sync.key-gated-recovery
@pytest.mark.anyio
async def test_discovery_outage_does_not_abort_ordinary_socket_setup(monkeypatch):
    class Service:
        def __init__(self, directus):
            pass
        async def execute(self, operation, data):
            assert operation == "list_metadata_jobs"
            raise RuntimeError("Injected discovery outage")
    monkeypatch.setattr(handlers, "ChatRecoveryService", Service)
    manager = Manager()
    await handlers.send_available_metadata_jobs(manager=manager, directus_service=None,
        user_id="owner", user_id_hash="owner-hash", device_fingerprint_hash="device")
    # Subsequent ordinary socket work is still reachable; no false empty/success
    # discovery result is sent while existing encrypted jobs remain durable.
    await manager.send_personal_message({"type": "ordinary_socket_ready"}, "owner", "device")
    assert manager.messages == [{"type": "ordinary_socket_ready"}]
