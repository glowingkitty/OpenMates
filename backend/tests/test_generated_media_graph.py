"""The registered generation task seals one parent around ordered output children."""

from types import SimpleNamespace
from types import ModuleType
from unittest.mock import AsyncMock
import sys
import uuid

import pytest

from backend.shared.python_utils.generated_media_graph import (
    run_generated_media_batch,
    send_generated_media_child,
)


# contract-test: supporting surface=gui.web assertions=app-skills.media.parent-children-and-attribution
@pytest.mark.asyncio
async def test_media_batch_seals_successful_children_and_notifies_once_after_parent(monkeypatch):
    parent_id = str(uuid.uuid4())
    task_id = str(uuid.uuid4())
    sent = []
    callback = AsyncMock()

    class FakeEmbedService:
        def __init__(self, *_args):
            pass

        @staticmethod
        def _registered_child_embed_id(embed_id, index):
            return str(uuid.uuid5(uuid.UUID(embed_id), f"embed-child:{index}"))

        async def send_embed_data_to_client(self, **kwargs):
            sent.append(kwargs)
            return True

    embed_service_module = ModuleType("backend.core.api.app.services.embed_service")
    embed_service_module.EmbedService = FakeEmbedService
    monkeypatch.setitem(sys.modules, embed_service_module.__name__, embed_service_module)
    continuation_module = ModuleType("backend.apps.ai.tasks.async_skill_continuation")
    continuation_module.dispatch_async_skill_continuation = callback
    monkeypatch.setitem(sys.modules, continuation_module.__name__, continuation_module)

    class FakeTask:
        request = SimpleNamespace(id=task_id)
        _cache_service = object()
        _directus_service = object()
        _encryption_service = object()

        async def initialize_core_services(self):
            pass

        async def cleanup_services(self):
            pass

    async def generate_one(_task, app_id, _skill_id, child_args):
        if child_args["media_child_index"] == 1:
            raise RuntimeError("provider detail must stay private")
        child_id = child_args["embed_id"]
        await send_generated_media_child(
            FakeEmbedService(), parent_embed_id=child_args["producer_embed_id"],
            child_embed_id=child_id, child_index=child_args["media_child_index"],
            content={"app_id": app_id, "prompt": child_args["prompt"], "model": "actual-model"},
            chat_id="chat", message_id="message", user_id="user", user_id_hash="hash",
            created_at=1, log_prefix="[test]",
        )
        return {
            "status": "finished", "embed_id": child_id,
            "prompt": child_args["prompt"], "model": "actual-model",
            "aes_key": "secret", "files": {"original": {"download_url": "signed-token"}},
        }

    result = await run_generated_media_batch(
        FakeTask(), app_id="images", skill_id="generate",
        arguments={
            "embed_id": parent_id, "user_id": "user", "chat_id": "chat", "message_id": "message",
            "requests": [{"prompt": "first"}, {"prompt": "second"}, {"prompt": "third"}],
        },
        generate_one=generate_one,
    )

    expected_children = [FakeEmbedService._registered_child_embed_id(parent_id, index) for index in (0, 2)]
    assert result["child_embed_ids"] == expected_children
    assert [item["embed_id"] for item in sent] == [*expected_children, parent_id]
    assert sent[-1]["embed_ids"] == expected_children
    assert sent[-1]["content_toon"]
    assert [item["subject_id"] for item in sent[-1]["producer_final_children"]] == expected_children
    callback.assert_awaited_once()
    callback_args = callback.await_args.kwargs
    assert callback_args["async_task_id"] == task_id
    assert callback_args["result_status"] == "failed"
    assert [row["request_index"] for row in callback_args["completed_results"]] == [0, 1, 2]
    assert callback_args["completed_results"][0]["embed_ref"]
    assert callback_args["completed_results"][0]["parent_embed_id"] == parent_id
    assert callback_args["completed_results"][0]["parent_embed_ref"].startswith("generated-media-images-")
    assert callback_args["request_metadata"]["parent_embed_id"] == parent_id
    assert callback_args["request_metadata"]["parent_embed_ref"] == callback_args["completed_results"][0]["parent_embed_ref"]
    assert "aes_key" not in callback_args["completed_results"][0]
    assert "files" not in callback_args["completed_results"][0]
    assert callback_args["completed_results"][1] == {
        "parent_embed_id": parent_id,
        "parent_embed_ref": callback_args["completed_results"][0]["parent_embed_ref"],
        "request_index": 1, "status": "error", "error": "Generation failed",
    }


# contract-test: supporting surface=gui.web assertions=app-skills.media.parent-children-and-attribution
@pytest.mark.asyncio
async def test_standalone_media_child_never_self_parents():
    sent = []

    class FakeEmbedService:
        async def send_embed_data_to_client(self, **kwargs):
            sent.append(kwargs)

    embed_id = str(uuid.uuid4())
    await send_generated_media_child(
        FakeEmbedService(), parent_embed_id=embed_id, child_embed_id=embed_id,
        child_index=0, content={"app_id": "images", "prompt": "a bird", "model": "actual-model"},
        chat_id="chat", message_id="message", user_id="user", user_id_hash="hash",
        created_at=1, log_prefix="[test]",
    )
    assert sent[0]["parent_embed_id"] is None
    assert sent[0]["embed_id"] == embed_id
