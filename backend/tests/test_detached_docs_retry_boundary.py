"""A duplicate broker delivery cannot enter the local document generator twice."""

# contract-test-file: infrastructure

from types import SimpleNamespace
from unittest.mock import Mock, patch
import hashlib

import pytest


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
@pytest.mark.asyncio
async def test_docx_worker_initializes_storage_without_unrelated_billing_services(monkeypatch) -> None:
    pytest.importorskip("fitz")
    pytest.importorskip("docx")

    from backend.apps.docs.tasks import generate_task

    directus = object()
    secrets = object()
    core_calls = 0
    s3_instances = []

    class FakeTask:
        _directus_service = directus
        _secrets_manager = secrets
        _s3_service = None

        async def initialize_core_services(self):
            nonlocal core_calls
            core_calls += 1

        async def initialize_services(self):
            raise AssertionError("Docs must not initialize billing and payment services")

    class FakeS3:
        def __init__(self, *, secrets_manager, directus_service):
            assert secrets_manager is secrets
            assert directus_service is directus
            self.initialize_calls = []
            s3_instances.append(self)

        async def initialize(self, *, configure_buckets):
            self.initialize_calls.append(configure_buckets)

    monkeypatch.setattr(generate_task, "S3UploadService", FakeS3)
    task = FakeTask()

    await generate_task._initialize_document_services(task)
    await generate_task._initialize_document_services(task)

    assert core_calls == 2
    assert task._s3_service is s3_instances[0]
    assert s3_instances[0].initialize_calls == [False]


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
def test_same_task_id_enters_docx_generation_once_after_worker_admission(monkeypatch) -> None:
    pytest.importorskip("celery")
    pytest.importorskip("fitz")
    pytest.importorskip("docx")

    from backend.apps.docs.tasks import generate_task
    from backend.shared.python_utils import embed_producer_worker
    from celery.exceptions import Ignore

    task = generate_task.generate_docx_task
    body_calls: list[dict] = []
    admission_calls: list[str] = []

    async def fake_generate(_task, arguments):
        body_calls.append(arguments)
        return {"embed_id": arguments["embed_id"], "status": "finished"}

    async def admitted(**kwargs):
        admission_calls.append(kwargs["task_id"])
        return SimpleNamespace(classification="registered_ai"), None

    monkeypatch.setattr(generate_task, "_async_generate_docx", fake_generate)
    monkeypatch.setattr(embed_producer_worker, "verify_output_producer", admitted)

    arguments = {
        "embed_id": "919e542c-692e-4d4c-9ac1-801947284bd8",
        "user_id": "85144cd0-45aa-400d-8fa3-541ad15e5ae6",
        "chat_id": "03429bfd-394a-4bea-b4d6-83343e9d2469",
        "message_id": "message-1",
    }
    task_id = "5fb3a949-b103-4982-a107-c49be2783742"
    task.push_request(id=task_id, headers={"openmates_output_producer": {
        "version": 1, "intent_id": task_id,
    }})
    try:
        with patch(
            "backend.core.api.app.tasks.base_task.acquire_celery_task_dedup_lock",
            side_effect=[True, False],
        ):
            assert task(arguments) == {"embed_id": arguments["embed_id"], "status": "finished"}
            with pytest.raises(Ignore):
                task(arguments)
    finally:
        task.pop_request()

    assert body_calls == [arguments]
    assert admission_calls == [task_id]


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
def test_sealed_docx_retry_stops_before_generation_even_after_dedup_lock_loss(monkeypatch) -> None:
    """The durable seal, rather than Redis dedup, excludes a repeated provider body."""
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "docs-retry-test-binding-key-at-least-32-bytes")
    pytest.importorskip("celery")
    pytest.importorskip("fitz")
    pytest.importorskip("docx")

    from backend.apps.docs.tasks import generate_task
    from backend.shared.python_utils import embed_producer_dispatch, embed_producer_worker
    from celery.exceptions import Ignore

    task = generate_task.generate_docx_task
    task_id = "5fb3a949-b103-4982-a107-c49be2783742"
    owner = "85144cd0-45aa-400d-8fa3-541ad15e5ae6"
    arguments = {
        "embed_id": "919e542c-692e-4d4c-9ac1-801947284bd8",
        "user_id": owner,
        "chat_id": "03429bfd-394a-4bea-b4d6-83343e9d2469",
        "message_id": "message-1",
    }
    binding = embed_producer_dispatch.bind_task_invocation(
        task_name=task.name, task_uuid=task_id, args=[arguments], kwargs={},
    )
    resolutions = []
    generation_calls = []

    async def authoritative_resolution(operation, data):
        assert operation == "resolve_output_producer"
        assert data == {
            "protocol_version": 1, "task_uuid": task_id,
            "task_name": task.name, "kwargs_binding": binding,
        }
        resolutions.append(operation)
        return {"status": "PENDING" if len(resolutions) == 1 else "SEALED", "context": {
            "hashed_user_id": hashlib.sha256(owner.encode()).hexdigest(),
            "root_chat_id": arguments["chat_id"],
            "target_chat_id": arguments["chat_id"],
            "turn_id": "turn-1", "preflight_id": "preflight-1",
            "inference_task_id": "inference-1",
            "chat_key_version": 1, "recovery_public_key": "synthetic-test-public-key",
            "primary_embed_id": arguments["embed_id"],
            "primary_message_id": arguments["message_id"],
            "hashed_team_id": None,
        }}

    async def local_generate(_task, item):
        generation_calls.append(item)
        return {"embed_id": item["embed_id"], "status": "finished"}

    monkeypatch.setattr(embed_producer_worker, "_transaction", authoritative_resolution)
    monkeypatch.setattr(generate_task, "_async_generate_docx", local_generate)
    header = {embed_producer_dispatch.PRODUCER_HEADER: {
        "version": 1, "intent_id": task_id,
    }}
    task.push_request(id=task_id, headers=header)
    backend_read = Mock()
    backend_write = Mock()
    state_write = Mock()
    try:
        # Both deliveries enter worker admission: a lost Redis dedup key cannot
        # make a SEALED authoritative output run the local generator again.
        with (
            patch(
                "backend.core.api.app.tasks.base_task.acquire_celery_task_dedup_lock",
                side_effect=[True, True],
            ) as lock,
            patch.object(task.backend, "get_task_meta", backend_read),
            patch.object(task.backend, "store_result", backend_write),
            patch.object(task, "update_state", state_write),
        ):
            assert task(arguments) == {"embed_id": arguments["embed_id"], "status": "finished"}
            with pytest.raises(Ignore):
                task(arguments)
        assert lock.call_count == 2
    finally:
        task.pop_request()

    assert len(resolutions) == 2
    assert generation_calls == [arguments]
    backend_read.assert_not_called()
    backend_write.assert_not_called()
    state_write.assert_not_called()


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
def test_sealed_docx_retry_without_backend_result_does_not_create_failure(monkeypatch) -> None:
    """A SEALED retry holds when the Celery result has expired or never appeared."""
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "docs-retry-test-binding-key-at-least-32-bytes")
    pytest.importorskip("celery")
    pytest.importorskip("fitz")
    pytest.importorskip("docx")

    from backend.apps.docs.tasks import generate_task
    from backend.shared.python_utils import embed_producer_dispatch, embed_producer_worker
    from celery.exceptions import Ignore

    task = generate_task.generate_docx_task
    task_id = "0fa8e902-e20b-4704-b0ee-e6cc089248bb"
    arguments = {
        "embed_id": "c9236d41-a8b8-472f-8c25-b8d529b021ca",
        "user_id": "a97e7d53-4aa2-48c7-a89f-1a788db82506",
        "chat_id": "72c1437f-7755-4cbb-97e9-96819ec8c32c",
        "message_id": "message-without-result",
    }
    binding = embed_producer_dispatch.bind_task_invocation(
        task_name=task.name, task_uuid=task_id, args=[arguments], kwargs={},
    )
    generation = Mock()

    async def sealed(operation, data):
        assert operation == "resolve_output_producer"
        assert data == {
            "protocol_version": 1,
            "task_uuid": task_id,
            "task_name": task.name,
            "kwargs_binding": binding,
        }
        return {"status": "SEALED", "context": {
            "hashed_user_id": hashlib.sha256(arguments["user_id"].encode()).hexdigest(),
            "root_chat_id": arguments["chat_id"],
            "target_chat_id": arguments["chat_id"],
            "turn_id": "turn-without-result",
            "preflight_id": "preflight-without-result",
            "inference_task_id": "inference-without-result",
            "chat_key_version": 1,
            "recovery_public_key": "synthetic-test-public-key",
            "primary_embed_id": arguments["embed_id"],
            "primary_message_id": arguments["message_id"],
            "hashed_team_id": None,
        }}

    monkeypatch.setattr(embed_producer_worker, "_transaction", sealed)
    monkeypatch.setattr(generate_task, "_async_generate_docx", generation)
    header = {embed_producer_dispatch.PRODUCER_HEADER: {
        "version": 1, "intent_id": task_id,
    }}
    task.push_request(id=task_id, headers=header)
    backend_read = Mock()
    backend_write = Mock()
    state_write = Mock()
    try:
        with (
            patch(
                "backend.core.api.app.tasks.base_task.acquire_celery_task_dedup_lock",
                return_value=True,
            ),
            patch.object(task.backend, "get_task_meta", backend_read),
            patch.object(task.backend, "store_result", backend_write),
            patch.object(task, "update_state", state_write),
        ):
            with pytest.raises(Ignore):
                task(arguments)
    finally:
        task.pop_request()

    generation.assert_not_called()
    backend_read.assert_not_called()
    backend_write.assert_not_called()
    state_write.assert_not_called()
