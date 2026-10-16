# contract-test-file: infrastructure
"""Serving-process inventory uses observed deployment state, not worker hints."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import uuid

import pytest

from scripts.storage_runtime_inventory import serving_process_ids, validate_cohort, publish_inventory

SOURCE = "a" * 40


@pytest.fixture
def celery_app(monkeypatch):
    import sys
    from celery import Celery
    app = Celery("isolated-inventory-test", set_as_current=False)
    monkeypatch.setitem(sys.modules, "backend.core.api.app.tasks.celery_config", SimpleNamespace(app=app))
    return app


def root(workers="1", argv=None):
    return {"argv": argv or ["/usr/local/bin/uvicorn", "backend.core.api.main:app"], "parent": 0, "web_concurrency": workers}


def child(parent=1):
    return {"argv": ["python", "-c", "from multiprocessing.spawn import spawn_main; spawn_main()", "--multiprocessing-fork"], "parent": parent}


def test_actual_serving_workers_include_uvicorn_prefork_and_reject_incomplete_count():
    assert serving_process_ids({1: root()}) == [1]
    with pytest.raises(ValueError, match="incomplete"):
        serving_process_ids({1: root("2"), 9: child()})
    assert serving_process_ids({1: root("2"), 9: child(), 10: child()}) == [9, 10]
    assert serving_process_ids({1: root("2", ["uvicorn", "backend.core.api.main:app", "--workers", "1"])}) == [1]
    with pytest.raises(ValueError, match="unexpected"):
        serving_process_ids({1: root(), 9: child()})
    with pytest.raises(ValueError, match="count"):
        serving_process_ids({1: root("invalid")})


def test_cohort_requires_complete_distinct_source_bound_process_ids():
    first = {"schema": "agentic-storage-api-process-inventory-v1", "source_commit": SOURCE, "instance_ids": ["container-a:1"]}
    second = {**first, "instance_ids": ["container-b:1"]}
    result = validate_cohort([first, second], now=100)
    assert result["source_commit"] == SOURCE
    assert result["instance_ids"] == ["container-a:1", "container-b:1"]
    assert result["expires_at"] == 280
    assert str(uuid.UUID(result["inventory_id"], version=4)) == result["inventory_id"]
    for rows in ([], [first, first], [first, {**second, "source_commit": "b" * 40}], [{**first, "instance_ids": []}]):
        with pytest.raises(ValueError):
            validate_cohort(rows)


@pytest.mark.asyncio
async def test_fresh_same_cohort_renews_nonce_and_changed_cohort_rotates(monkeypatch, celery_app):
    import sys
    import time
    nonce = str(uuid.uuid4())
    existing = {"inventory_id": nonce, "source_commit": SOURCE, "instance_ids": ["container-a:1"], "expires_at": int(time.time()) + 120}
    redis = SimpleNamespace(get=AsyncMock(return_value=json.dumps(existing)), set=AsyncMock())
    task = SimpleNamespace(bind=Mock(), initialize_core_services=AsyncMock(), cleanup_services=AsyncMock(), directus_service=object())
    monkeypatch.setitem(sys.modules, "backend.core.api.app.tasks.base_task", SimpleNamespace(BaseServiceTask=lambda: task))
    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.storage_archive_client_compatibility", SimpleNamespace(_redis=AsyncMock(return_value=redis)))
    monkeypatch.setenv("BUILD_COMMIT_SHA", SOURCE)
    row = {"schema": "agentic-storage-api-process-inventory-v1", "source_commit": SOURCE, "instance_ids": ["container-a:1"]}
    assert (await publish_inventory([row]))["status"] == "published"
    assert json.loads(redis.set.call_args.args[1])["inventory_id"] == nonce
    await publish_inventory([{**row, "instance_ids": ["container-b:1"]}])
    assert json.loads(redis.set.call_args.args[1])["inventory_id"] != nonce
    assert task.cleanup_services.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("failing_stage", ["bootstrap", "publish"])
async def test_publisher_failures_keep_source_fences_and_emit_only_typed_diagnostics(monkeypatch, celery_app, failing_stage):
    import sys
    from scripts import storage_runtime_inventory as collector
    private = "private-token-and-user-content"
    initialize = AsyncMock(side_effect=RuntimeError(private)) if failing_stage == "bootstrap" else AsyncMock()
    redis = SimpleNamespace(get=AsyncMock(side_effect=ConnectionError(private)), set=AsyncMock())
    task = SimpleNamespace(bind=Mock(), initialize_core_services=initialize, cleanup_services=AsyncMock(), directus_service=object())
    monkeypatch.setitem(sys.modules, "backend.core.api.app.tasks.base_task", SimpleNamespace(BaseServiceTask=lambda: task))
    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.storage_archive_client_compatibility", SimpleNamespace(_redis=AsyncMock(return_value=redis)))
    monkeypatch.setenv("BUILD_COMMIT_SHA", SOURCE)
    row = {"schema": collector.INSPECTION_SCHEMA, "source_commit": SOURCE, "instance_ids": ["container-a:1"]}
    with pytest.raises(collector.InventoryFailure) as failure:
        await collector.publish_inventory([row])
    assert failure.value.diagnostic == {"status": "paused", "reason": f"runtime_inventory_{failing_stage}_failed",
        "stage": failing_stage, "error_class": "RuntimeError" if failing_stage == "bootstrap" else "ConnectionError"}
    assert private not in json.dumps(failure.value.diagnostic)
    redis.set.assert_not_awaited()
    task.cleanup_services.assert_awaited_once()


@pytest.mark.parametrize("failure_stage", ["inspect", "publish"])
def test_host_refresh_propagates_safe_remote_failure_stage_and_discards_private_fields(monkeypatch, failure_stage):
    from scripts import storage_runtime_inventory as collector
    inspected = {"schema": collector.INSPECTION_SCHEMA, "source_commit": SOURCE, "instance_ids": ["container-a:1"]}
    paused = {"status": "paused", "reason": "runtime_inventory_bootstrap_failed", "stage": "bootstrap",
              "error_class": "ModuleNotFoundError", "stderr": "private-secret", "api_processes": 999999, "exit_code": -999999}
    replies = [SimpleNamespace(stdout="a" * 64)]
    replies.append(SimpleNamespace(stdout=json.dumps(paused if failure_stage == "inspect" else inspected)))
    if failure_stage == "publish":
        replies.append(SimpleNamespace(stdout=json.dumps(paused)))
    monkeypatch.setattr(collector.subprocess, "run", lambda *args, **kwargs: replies.pop(0))
    with pytest.raises(collector.InventoryFailure) as failure:
        collector.refresh_host_inventory(["compose", "-f", "isolated.yml"])
    assert failure.value.diagnostic == {"status": "paused", "reason": "runtime_inventory_bootstrap_failed",
        "stage": "bootstrap", "error_class": "ModuleNotFoundError", "container_count": 1}
    assert "private" not in json.dumps(failure.value.diagnostic)
    assert replies == []


def test_publisher_json_contamination_is_a_typed_closed_gate_without_raw_log_output(monkeypatch):
    from scripts import storage_runtime_inventory as collector
    inspected = {"schema": collector.INSPECTION_SCHEMA, "source_commit": SOURCE, "instance_ids": ["container-a:1"]}
    replies = [SimpleNamespace(stdout="a" * 64), SimpleNamespace(stdout=json.dumps(inspected)),
               SimpleNamespace(stdout='private service startup log\n{"status":"published"}')]
    monkeypatch.setattr(collector.subprocess, "run", lambda *args, **kwargs: replies.pop(0))
    with pytest.raises(collector.InventoryFailure) as failure:
        collector.refresh_host_inventory(["compose", "-f", "isolated.yml"])
    assert failure.value.diagnostic == {"status": "paused", "reason": "runtime_inventory_json_invalid",
        "stage": "publish", "error_class": "JSONDecodeError", "container_count": 1}
    assert "private" not in json.dumps(failure.value.diagnostic)


def test_subprocess_diagnostics_expose_bounded_exit_code_without_command_or_logs():
    from scripts import storage_runtime_inventory as collector
    exception = collector.subprocess.CalledProcessError(7, ["private-command"], output="private-output", stderr="private-stderr")
    assert collector.failure_status(exception, stage="compose", container_count=1) == {
        "status": "paused", "reason": "runtime_inventory_subprocess_failed", "stage": "compose",
        "error_class": "CalledProcessError", "exit_code": 7, "container_count": 1}
    unknown = collector.failure_status(ValueError("private-token"), stage="invented-private-stage", container_count=999999)
    assert unknown == {"status": "paused", "reason": "runtime_inventory_unverified", "stage": "inspect", "error_class": "ValueError"}


@pytest.mark.parametrize("bootstrap_failure", [False, True])
def test_actual_publish_main_emits_one_safe_json_despite_noisy_service_bootstrap(monkeypatch, capsys, celery_app, bootstrap_failure):
    import io
    import logging
    import sys
    from scripts import storage_runtime_inventory as collector
    from celery import Task
    class StandalonePublisherTask(Task):
        abstract = True
    task = StandalonePublisherTask()
    # This is the same real Celery property touched by production initialization.
    assert StandalonePublisherTask.request_stack is None
    with pytest.raises(AttributeError):
        _ = task.request.id
    private = "private-service-output-must-not-be-retained"
    async def initialize():
        assert StandalonePublisherTask.request_stack is not None
        assert task.app is celery_app
        assert task.request.id is None
        print(private)
        print(private, file=sys.stderr)
        logger = logging.Logger("isolated-collector-fixture")
        logger.addHandler(logging.StreamHandler(sys.stdout))
        logger.warning(private)
        if bootstrap_failure:
            raise RuntimeError(private)
    async def cleanup():
        print(private)
        print(private, file=sys.stderr)
    task.initialize_core_services = AsyncMock(side_effect=initialize)
    task.cleanup_services = AsyncMock(side_effect=cleanup)
    task.directus_service = object()
    def bootstrap_task():
        print(private)
        return task
    redis = SimpleNamespace(get=AsyncMock(return_value=None), set=AsyncMock())
    monkeypatch.setitem(sys.modules, "backend.core.api.app.tasks.base_task", SimpleNamespace(BaseServiceTask=bootstrap_task))
    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.storage_archive_client_compatibility", SimpleNamespace(_redis=AsyncMock(return_value=redis)))
    monkeypatch.setenv("BUILD_COMMIT_SHA", SOURCE)
    row = {"schema": collector.INSPECTION_SCHEMA, "source_commit": SOURCE, "instance_ids": ["container-a:1"]}
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(json.dumps([row]).encode())))
    monkeypatch.setattr(sys, "argv", ["storage_runtime_inventory.py", "publish"])
    collector.main()
    captured = capsys.readouterr()
    assert captured.err == ""
    assert len(captured.out.splitlines()) == 1
    result = json.loads(captured.out)
    assert private not in captured.out
    if bootstrap_failure:
        assert result == {"status": "paused", "reason": "runtime_inventory_bootstrap_failed",
                          "stage": "bootstrap", "error_class": "RuntimeError"}
        redis.set.assert_not_awaited()
    else:
        assert result == {"status": "published", "source_commit": SOURCE, "api_processes": 1, "expires_in_seconds": 180}
        inventory = json.loads(redis.set.call_args.args[1])
        assert inventory["source_commit"] == SOURCE and inventory["instance_ids"] == row["instance_ids"]
        assert str(uuid.UUID(inventory["inventory_id"], version=4)) == inventory["inventory_id"]
        assert inventory["expires_at"] - inventory["observed_at"] == 180
    task.cleanup_services.assert_awaited_once()
