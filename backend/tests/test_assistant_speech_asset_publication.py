"""Exercise actual encrypted speech storage and media publication together."""

import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock
import uuid

import pytest

# Load the real helper without importing the unrelated Celery task package.
spec = importlib.util.spec_from_file_location(
    "speech_asset_common", Path(__file__).parents[1] / "apps/audio/tasks/common.py",
)
common = importlib.util.module_from_spec(spec)
spec.loader.exec_module(common)


# contract-test: supporting surface=rest_api assertions=assistant-speech.segmentation.one-file-per-segment,assistant-speech.privacy.transient-plaintext-encrypted-audio,assistant-speech.execution.first-segment-progressive
@pytest.mark.asyncio
@pytest.mark.parametrize("app_id,skill_id", [("audio", "speak"), ("assistant_response_speech", "segment")])
async def test_stored_speech_publishes_its_encrypted_audio_asset(monkeypatch, app_id, skill_id):
    embed_id = str(uuid.uuid4())
    audio = b"private-generated-speech"
    task = SimpleNamespace(
        _cache_service=object(),
        _directus_service=object(),
        _encryption_service=SimpleNamespace(
            encrypt_with_user_key=AsyncMock(return_value=("wrapped-key", None)),
        ),
        _s3_service=SimpleNamespace(
            base_domain="storage.invalid", upload_file=AsyncMock(),
        ),
    )
    index = AsyncMock(return_value=True)
    publish = AsyncMock(return_value=True)
    embed_module = ModuleType("backend.core.api.app.services.embed_service")
    embed_module.EmbedService = lambda **_kwargs: SimpleNamespace(send_embed_data_to_client=publish)
    monkeypatch.setitem(sys.modules, embed_module.__name__, embed_module)
    storage_module = ModuleType("backend.core.api.app.services.s3.config")
    storage_module.get_bucket_name = lambda _key: "private-test"
    monkeypatch.setitem(sys.modules, storage_module.__name__, storage_module)
    monkeypatch.setattr(common, "index_generated_asset", index)
    monkeypatch.setattr(common, "cache_s3_file_keys", AsyncMock())
    monkeypatch.setattr(common, "create_download_token", lambda **_kwargs: "test-token")

    result = await common.store_generated_audio_asset(
        task, app_id=app_id, skill_id=skill_id, user_id="owner",
        user_vault_key_id="owner-vault-key", chat_id="chat", message_id="message",
        external_request=False, embed_id=embed_id, audio_bytes=audio,
        mime_type="audio/mpeg", duration_seconds=1.0, model="test-speech",
        generation_type="assistant_response_speech_segment", prompt=None,
        text_preview=None, extra_content={}, original_filename_prefix="speech",
        log_prefix="[test]",
    )

    assert task._s3_service.upload_file.await_args.kwargs["content"] != audio
    assert index.await_args.kwargs["embed_id"] == embed_id
    assert index.await_args.kwargs["media_type"] == "audio"
    publish.assert_awaited_once()
    published = publish.await_args.kwargs
    assert published["embed_type"] == "generated_audio"
    assert published["embed_id"] == embed_id
    assert published["parent_embed_id"] is None
    assert published["encryption_mode"] == "client"
    assert (published["user_id"], published["chat_id"], published["message_id"]) == ("owner", "chat", "message")
    assert result["child_embed_ids"] == [embed_id]
    assert result["files"]["original"]["s3_key"]
    assert result["aes_key"]


# contract-test: supporting surface=rest_api assertions=assistant-speech.failure.nonblocking-visible-resumable,assistant-speech.on-demand.generate-missing-only,assistant-speech.segmentation.one-file-per-segment
@pytest.mark.asyncio
async def test_retry_survives_an_indexed_failed_upload_and_redelivery_reuses_ready_audio(monkeypatch, tmp_path):
    segment_id = str(uuid.uuid4())
    row = {"id": "segment-row", "segment_id": segment_id, "sequence": 0, "status": "queued"}
    orphan = {"embed_id": segment_id, "user_id": "owner", "files_metadata": {"original": {"s3_key": "old-audio"}}}
    uploads = {segment_id: orphan}

    class Directus:
        async def get_items(self, collection, *, params, no_cache):
            assert collection == "assistant_speech_segments"
            return [row] if params["filter[segment_id][_eq]"] == segment_id else []

        async def update_item_if_version(self, _collection, _id, data, version, **kwargs):
            if row.get("execution_version", 0) != version:
                return None
            if any(row.get(key) != value for key, value in kwargs.get("extra_filters", {}).items()):
                return None
            row.update(data)
            return row

        async def create_item(self, collection, data):
            assert collection == "upload_files"
            if data["embed_id"] in uploads:
                return False, "unique embed_id constraint"
            uploads[data["embed_id"]] = data
            return True, None

        async def get_user_fields_direct(self, _user_id, _fields):
            return {"storage_used_bytes": 0}

        async def update_user(self, _user_id, _fields):
            return True

    publish = AsyncMock(return_value=True)
    provider = Mock(side_effect=AssertionError("no real speech provider in this regression"))
    app = SimpleNamespace(task=lambda **_kwargs: lambda function: function, send_task=Mock())
    # Replace infrastructure boundaries while running the real task, storage,
    # encryption, unique index handling, manifest finalization and media graph.
    for name, values in {
        "backend.apps.audio.tasks.common": common.__dict__,
        "backend.core.api.app.tasks.base_task": {"BaseServiceTask": object},
        "backend.core.api.app.tasks.celery_config": {"app": app},
        "backend.shared.providers.elevenlabs": {"ElevenLabsClient": provider},
        "backend.shared.python_utils.storage_availability": {
            "initialize_task_storage": AsyncMock(), "require_storage_available": AsyncMock(),
            "is_storage_unavailable_error": lambda _error: False,
        },
        "backend.core.api.app.services.embed_service": {
            "EmbedService": lambda **_kwargs: SimpleNamespace(send_embed_data_to_client=publish),
        },
        "backend.core.api.app.services.s3.config": {"get_bucket_name": lambda _key: "private-test"},
    }.items():
        module = ModuleType(name)
        module.__dict__.update(values)
        monkeypatch.setitem(sys.modules, name, module)
    task_spec = importlib.util.spec_from_file_location(
        "speech_segment_task_test", Path(__file__).parents[1] / "apps/audio/assistant_speech/segment_task.py",
    )
    segment_task = importlib.util.module_from_spec(task_spec)
    task_spec.loader.exec_module(segment_task)
    fixture = tmp_path / "speech.mp3"
    fixture.write_bytes(b"test-speech-audio")
    monkeypatch.setattr(segment_task, "assistant_speech_live_mock_audio", lambda _args: fixture)
    monkeypatch.setattr(common, "cache_s3_file_keys", AsyncMock())
    monkeypatch.setattr(common, "create_download_token", lambda **_kwargs: "test-token")
    task = SimpleNamespace(
        initialize_core_services=AsyncMock(), _directus_service=Directus(),
        _cache_service=SimpleNamespace(publish_event=AsyncMock()),
        _encryption_service=SimpleNamespace(encrypt_with_user_key=AsyncMock(return_value=("wrapped-key", None))),
        _s3_service=SimpleNamespace(base_domain="storage.invalid", upload_file=AsyncMock(), delete_file=AsyncMock()),
    )
    arguments = {
        "segment_id": segment_id, "user_id": "owner", "user_vault_key_id": "owner-key",
        "chat_id": "chat", "assistant_message_id": "message", "speakable_text": "A retry.",
        "voice_profile_key": "george", "voice_profile_version": 1,
    }
    first = await segment_task._async_generate_assistant_speech_segment(task, arguments)
    second = await segment_task._async_generate_assistant_speech_segment(task, arguments)
    assert first["status"] == second["status"] == "ready"
    asset_id = first["generated_asset_id"]
    assert asset_id != segment_id
    assert second["generated_asset_id"] == asset_id
    assert uploads[segment_id] is orphan
    assert set(uploads) == {segment_id, asset_id}
    task._s3_service.upload_file.assert_awaited_once()
    task._s3_service.delete_file.assert_not_awaited()
    publish.assert_awaited_once()
    assert publish.await_args.kwargs["embed_id"] == asset_id
    assert publish.await_args.kwargs["embed_type"] == "generated_audio"
    provider.assert_not_called()
