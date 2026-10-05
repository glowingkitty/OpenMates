# contract-test-file: infrastructure
"""Serving-process inventory uses observed deployment state, not worker hints."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
import uuid

import pytest

from scripts.storage_runtime_inventory import serving_process_ids, validate_cohort, publish_inventory

SOURCE = "a" * 40


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
async def test_fresh_same_cohort_renews_nonce_and_changed_cohort_rotates(monkeypatch):
    import sys
    import time
    nonce = str(uuid.uuid4())
    existing = {"inventory_id": nonce, "source_commit": SOURCE, "instance_ids": ["container-a:1"], "expires_at": int(time.time()) + 120}
    redis = SimpleNamespace(get=AsyncMock(return_value=json.dumps(existing)), set=AsyncMock())
    task = SimpleNamespace(initialize_core_services=AsyncMock(), cleanup_services=AsyncMock(), directus_service=object())
    monkeypatch.setitem(sys.modules, "backend.core.api.app.tasks.base_task", SimpleNamespace(BaseServiceTask=lambda: task))
    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.storage_archive_client_compatibility", SimpleNamespace(_redis=AsyncMock(return_value=redis)))
    monkeypatch.setenv("BUILD_COMMIT_SHA", SOURCE)
    row = {"schema": "agentic-storage-api-process-inventory-v1", "source_commit": SOURCE, "instance_ids": ["container-a:1"]}
    assert (await publish_inventory([row]))["status"] == "published"
    assert json.loads(redis.set.call_args.args[1])["inventory_id"] == nonce
    await publish_inventory([{**row, "instance_ids": ["container-b:1"]}])
    assert json.loads(redis.set.call_args.args[1])["inventory_id"] != nonce
    assert task.cleanup_services.await_count == 2
