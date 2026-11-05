"""A Code Run finishing before callback registration retains its sealed result."""

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.tests.runtime_import_stubs import install_code_route_import_stubs

install_code_route_import_stubs()

from backend.apps.ai.skills.ask_skill import AskSkillRequest  # noqa: E402
from backend.apps.code.tasks.run_code_task import _dispatch_code_run_async_continuation  # noqa: E402


class Cache:
    def __init__(self):
        self.values = {}

    @property
    async def client(self):
        return self

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, *, ttl=None, nx=False, ex=None):
        if nx and key in self.values:
            return False
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                pass
        self.values[key] = value
        return True

    async def delete(self, key):
        return self.values.pop(key, None) is not None


def load_module(name, path, monkeypatch):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setitem(sys.modules, name, module)
    return module


@pytest.mark.parametrize("first_batch", ["batch-1", "unrelated-batch"])
@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=code-run.assistant.auto-debug-bounded,app-skills.assistant.idempotent-resume,app-skills.assistant.bounded-private-failure
async def test_code_run_early_checked_completion_is_sealed_then_replayed_once(monkeypatch, first_batch):
    tasks = Path(__file__).resolve().parents[1] / "apps/ai/tasks"
    module = load_module("backend.apps.ai.tasks.async_skill_continuation", tasks / "async_skill_continuation.py", monkeypatch)
    load_module("backend.apps.ai.tasks.same_turn_skill_barrier", tasks / "same_turn_skill_barrier.py", monkeypatch)
    cache, sealed = Cache(), {}
    released = AsyncMock(return_value=True)

    async def seal(payload, *, request_id, **_kwargs):
        assert request_id == "execution"
        reference = f"sealed-{len(sealed)}"
        sealed[reference] = payload
        return {"agentic_context_ref": reference}

    async def restore(payload):
        assert payload["user_id"] == "owner" and payload["chat_id"] == "chat"
        assert payload["agentic_context_request_id"] == "execution"
        return sealed[payload["agentic_context_ref"]]

    from backend.shared.python_utils import recent_work_summary_client as private_module

    monkeypatch.setattr(private_module, "seal_private_context_payload", seal)
    monkeypatch.setattr(private_module, "restore_private_context_payload", restore)
    monkeypatch.setattr(private_module, "RecentWorkSummaryClient", lambda: SimpleNamespace(release_context=released))
    delivery = AsyncMock(return_value=None)
    monkeypatch.setattr(module, "dispatch_same_turn_barrier", delivery)
    request = AskSkillRequest(
        user_id="owner", user_id_hash="hash", chat_id="chat", message_id="message",
        message_history=[], current_user_content="run generated Rust code",
    )
    await cache.set(module.async_skill_latest_user_turn_key("owner", "chat"), "message")
    result = [{"execution_id": "execution", "target_embed_id": "source", "status": "finished",
               "exit_code": 0, "output": "checked actual sum=55\n",
               "output_safety_receipt": {"scan_status": "scanned"},
               "artifacts": [{"path": "outputs/result.csv", "asset_id": "asset"}]}]
    assert await _dispatch_code_run_async_continuation(
        cache_service=cache, async_task_id="execution", completed_results=result,
        request_metadata={"user_id": "owner", "chat_id": "chat", "message_id": "message",
                          "same_turn_batch_id": "batch-1", "target_filename": "main.rs"},
    ) is None
    early_key = "same_turn_skill:early:execution"
    early = await cache.get(early_key)
    assert early["batch_id"] == "batch-1"
    assert early["payload_ref"] in sealed
    assert "checked actual sum=55" not in repr(cache.values)
    assert delivery.await_count == 0

    async def register(batch):
        await module.cache_async_skill_continuation_context(
            cache_service=cache, async_task_id="execution", request_data=request,
            app_id="code", skill_id="run", tool_name="code-run", tool_arguments={},
            same_turn_batch_id=batch,
        )

    await register(first_batch)
    if first_batch != "batch-1":
        assert await cache.get(early_key) == early
        assert delivery.await_count == 0
        await register("batch-1")
    assert await cache.get(early_key) is None
    slot = await cache.get("same_turn_skill:batch-1:slot:execution")
    assert slot["status"] == "finished"
    completion = sealed[slot["payload_ref"]]["async_tool_completion"]
    assert completion["results"] == result
    assert completion["request_metadata"] == {"target_filename": "main.rs"}
    assert "checked actual sum=55" not in repr(cache.values)
    assert delivery.await_count == released.await_count == 1
    seal_count = len(sealed)
    await register("batch-1")
    assert len(sealed) == seal_count
    assert delivery.await_count == released.await_count == 1
