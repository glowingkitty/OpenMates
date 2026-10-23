"""Deletion faults retain speech cleanup authority and can safely be retried."""

from copy import deepcopy
from unittest.mock import AsyncMock, Mock

import pytest

from backend.apps.audio.pricing import ASSISTANT_RESPONSE_SPEECH_MODEL
from backend.apps.audio.assistant_speech.persistence import cleanup_generated_speech_asset, delete_speech_assets
from backend.core.api.app.services.account_content_deletion_service import delete_account_personal_speech


class Directus:
    def __init__(self):
        self.rows = {
            "chats": [{"id": "chat-1", "storage_state": "deleting", "hashed_user_id": "hash", "hashed_team_id": None}],
            "assistant_speech_segments": [{"id": "segment-row", "segment_id": "segment-1", "user_id": "owner",
                                            "chat_id": "chat-1", "assistant_message_id": "message-1", "status": "generating",
                                            "pending_generated_asset_id": "asset-1"}],
            "assistant_speech_manifests": [{"id": "manifest-row", "user_id": "owner", "chat_id": "chat-1", "assistant_message_id": "message-1"}],
            "upload_files": [{"id": "upload-row", "embed_id": "asset-1", "files_metadata": {"original": {"s3_key": "owner/assistant_speech/asset-1/original.mp3"}}}],
        }
        self.strict_reads = True
        self.fail_delete = None
        self.fail_read = None
        self.fail_cancel = False
        self.events = []

    async def get_items(self, collection, *, params, no_cache=True, raise_on_error=False, **kwargs):
        assert no_cache and (raise_on_error or not self.strict_reads)
        if collection == self.fail_read:
            raise RuntimeError("read unavailable")
        rows = self.rows.get(collection, [])
        for key, value in params.items():
            if key.startswith("filter["):
                field, operation = key.removeprefix("filter[").removesuffix("]").split("][")
                if operation == "_eq":
                    rows = [row for row in rows if row.get(field) == value]
                elif operation == "_nin":
                    rows = [row for row in rows if row.get(field) not in value]
                elif operation == "_null":
                    rows = [row for row in rows if (row.get(field) is None) == value]
        rows = sorted(rows, key=lambda row: row["id"])
        return deepcopy(rows[:params["limit"]] if params["limit"] >= 0 else rows)

    async def update_item(self, collection, row_id, patch):
        self.events.append(("cancel", row_id))
        if self.fail_cancel:
            return False
        next(row for row in self.rows[collection] if row["id"] == row_id).update(patch)
        return True

    async def delete_item(self, collection, row_id):
        self.events.append(("delete", collection))
        if collection == self.fail_delete:
            return False
        self.rows[collection] = [row for row in self.rows[collection] if row["id"] != row_id]
        return True


async def cleanup(directus, delete_file):
    async def delete_asset(segment):
        await cleanup_generated_speech_asset(directus, str(segment["pending_generated_asset_id"]), delete_file=delete_file)
    await delete_speech_assets(directus, user_id="owner", chat_id="chat-1", assistant_message_id="message-1", delete_asset=delete_asset)


# contract-test: direct surface=rest_api assertions=assistant-speech.lifecycle.disable-delete-invalidate
@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["object", "upload_files", "assistant_speech_segments", "assistant_speech_manifests", "read", "cancel"])
async def test_cleanup_fault_preserves_authority_and_retry_completes(fault):
    directus = Directus()
    delete_file = AsyncMock(side_effect=RuntimeError("object unavailable") if fault == "object" else None)
    directus.fail_delete = fault
    directus.fail_read = "upload_files" if fault == "read" else None
    directus.fail_cancel = fault == "cancel"
    with pytest.raises(RuntimeError):
        await cleanup(directus, delete_file)
    assert directus.rows["assistant_speech_manifests"]
    if fault in {"object", "upload_files", "read", "cancel"}:
        assert directus.rows["upload_files"]
        assert directus.rows["assistant_speech_segments"]
    directus.fail_delete = directus.fail_read = None
    directus.fail_cancel = False
    delete_file.side_effect = None
    await cleanup(directus, delete_file)
    await cleanup(directus, delete_file)
    assert all(not directus.rows[name] for name in ("assistant_speech_manifests", "assistant_speech_segments", "upload_files"))


# contract-test: direct surface=rest_api assertions=assistant-speech.lifecycle.disable-delete-invalidate
@pytest.mark.asyncio
async def test_cleanup_rereads_pending_asset_identity_after_cancellation():
    directus = Directus()
    directus.rows["assistant_speech_segments"][0].pop("pending_generated_asset_id")
    original = directus.update_item
    async def cancel(collection, row_id, patch):
        directus.rows[collection][0]["pending_generated_asset_id"] = "asset-1"
        return await original(collection, row_id, patch)
    directus.update_item = cancel
    delete_file = AsyncMock()
    await cleanup(directus, delete_file)
    delete_file.assert_awaited_once_with("owner/assistant_speech/asset-1/original.mp3")


# contract-test: direct surface=rest_api assertions=assistant-speech.lifecycle.disable-delete-invalidate,storage.cold.shared-team-authorized
@pytest.mark.asyncio
async def test_account_cleanup_cancels_and_deletes_personal_speech_preserving_team():
    directus = Directus()
    for collection in ("assistant_speech_segments", "assistant_speech_manifests"):
        directus.rows[collection].append({**directus.rows[collection][0], "id": "team-row", "chat_id": "team-chat"})
    directus.rows["chats"].append({"id": "team-chat", "hashed_user_id": "hash", "hashed_team_id": "team"})
    delete_file = AsyncMock()
    await delete_account_personal_speech(directus_service=directus, user_id="owner", user_id_hash="hash", delete_file=delete_file)
    delete_file.assert_awaited_once_with("owner/assistant_speech/asset-1/original.mp3")
    assert directus.rows["assistant_speech_segments"] == [next(row for row in directus.rows["assistant_speech_segments"] if row["id"] == "team-row")]
    assert directus.rows["assistant_speech_segments"][0]["status"] == "generating"
    assert directus.rows["assistant_speech_manifests"][0]["id"] == "team-row"
    assert len(directus.rows["chats"]) == 2
    assert directus.events[0] == ("cancel", "segment-row")


# contract-test: direct surface=rest_api assertions=assistant-speech.lifecycle.disable-delete-invalidate
@pytest.mark.asyncio
async def test_account_requires_fence_and_preserves_source_when_object_purge_fails():
    directus = Directus()
    directus.rows["chats"][0]["storage_state"] = "hot"
    with pytest.raises(RuntimeError, match="fences"):
        await delete_account_personal_speech(directus_service=directus, user_id="owner", user_id_hash="hash", delete_file=AsyncMock())
    assert directus.events == []
    directus.rows["chats"][0]["storage_state"] = "deleting"
    with pytest.raises(RuntimeError, match="object unavailable"):
        await delete_account_personal_speech(directus_service=directus, user_id="owner", user_id_hash="hash", delete_file=AsyncMock(side_effect=RuntimeError("object unavailable")))
    assert directus.rows["chats"] and directus.rows["upload_files"] and directus.rows["assistant_speech_manifests"]


# contract-test: direct surface=rest_api assertions=assistant-speech.lifecycle.disable-delete-invalidate
@pytest.mark.asyncio
async def test_dispatch_retry_after_broker_failure_includes_cancelled_empty_and_segment_only(monkeypatch):
    pytest.importorskip("celery")
    from backend.core.api.app.services.directus.chat_methods import ChatMethods
    from backend.core.api.app.tasks.celery_config import app
    directus = Directus()
    directus.rows["assistant_speech_manifests"].append({"id": "empty-manifest", "user_id": "owner", "chat_id": "chat-1", "assistant_message_id": "empty"})
    directus.rows["assistant_speech_segments"].append({**directus.rows["assistant_speech_segments"][0], "id": "orphan-segment", "assistant_message_id": "orphan"})
    sent = []
    def dispatch(name, *, kwargs, queue):
        sent.append(kwargs["arguments"]["assistant_message_id"])
        if len(sent) == 2:
            raise RuntimeError("broker unavailable")
    monkeypatch.setattr(app, "send_task", dispatch)
    with pytest.raises(RuntimeError, match="broker unavailable"):
        await ChatMethods(directus).cleanup_assistant_speech_for_chat("chat-1")
    assert directus.rows["assistant_speech_segments"][0]["status"] == "cancelled"
    sent.clear()
    monkeypatch.setattr(app, "send_task", lambda name, *, kwargs, queue: sent.append(kwargs["arguments"]["assistant_message_id"]))
    await ChatMethods(directus).cleanup_assistant_speech_for_chat("chat-1")
    assert set(sent) == {"empty", "message-1", "orphan"}


# contract-test: direct surface=rest_api assertions=assistant-speech.lifecycle.disable-delete-invalidate
@pytest.mark.asyncio
async def test_delete_task_retries_failures_and_releases_services_on_storage_init_failure(monkeypatch):
    pytest.importorskip("celery")
    from types import SimpleNamespace
    from backend.apps.audio.assistant_speech import delete_task
    task = SimpleNamespace(initialize_core_services=AsyncMock(), cleanup_services=AsyncMock())
    monkeypatch.setattr(delete_task, "initialize_task_storage", AsyncMock(side_effect=RuntimeError("storage unavailable")))
    with pytest.raises(RuntimeError, match="storage unavailable"):
        await delete_task._async_delete_assistant_speech(task, {})
    task.cleanup_services.assert_awaited_once()
    registered = delete_task.assistant_speech_delete_task
    assert registered.autoretry_for == (Exception,)
    assert registered.retry_backoff == 30 and not registered.retry_jitter and registered.max_retries == 5
    assert registered.acks_late and registered.reject_on_worker_lost


# contract-test: direct surface=rest_api assertions=assistant-speech.lifecycle.disable-delete-invalidate
@pytest.mark.asyncio
async def test_delete_task_cleans_distinct_ready_and_pending_assets(monkeypatch):
    pytest.importorskip("celery")
    from types import SimpleNamespace
    from backend.apps.audio.assistant_speech import delete_task
    directus = Directus()
    directus.rows["assistant_speech_segments"][0]["generated_asset_id"] = "asset-2"
    directus.rows["upload_files"].append({"id": "upload-row-2", "embed_id": "asset-2", "files_metadata": {"original": {"s3_key": "owner/assistant_speech/asset-1/original.mp3-2"}}})
    storage = SimpleNamespace(delete_file=AsyncMock())
    task = SimpleNamespace(_directus_service=directus, initialize_core_services=AsyncMock(), cleanup_services=AsyncMock())
    monkeypatch.setattr(delete_task, "initialize_task_storage", AsyncMock(return_value=storage))
    await delete_task._async_delete_assistant_speech(task, {"user_id": "owner", "chat_id": "chat-1", "assistant_message_id": "message-1"})
    assert {call.kwargs["file_key"] for call in storage.delete_file.await_args_list} == {"owner/assistant_speech/asset-1/original.mp3", "owner/assistant_speech/asset-1/original.mp3-2"}
    assert not directus.rows["upload_files"]


# contract-test: direct surface=rest_api assertions=assistant-speech.lifecycle.disable-delete-invalidate
@pytest.mark.asyncio
@pytest.mark.parametrize("metadata", [None, {}, {"original": {}}, {"original": "missing identity"}])
async def test_unknown_upload_metadata_retains_cleanup_authority(metadata):
    directus = Directus()
    directus.rows["upload_files"][0]["files_metadata"] = metadata
    with pytest.raises(RuntimeError, match="unavailable"):
        await cleanup(directus, AsyncMock())
    assert directus.rows["upload_files"] and directus.rows["assistant_speech_segments"] and directus.rows["assistant_speech_manifests"]


# contract-test: direct surface=rest_api assertions=assistant-speech.lifecycle.disable-delete-invalidate
@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["cleanup", "dispatch", "account"])
async def test_real_directus_none_patch_failure_stops_deletion_and_dispatch(surface, monkeypatch):
    directus = Directus()
    directus.update_item = AsyncMock(return_value=None)
    delete_file = AsyncMock()
    if surface == "dispatch":
        pytest.importorskip("celery")
        from backend.core.api.app.services.directus.chat_methods import ChatMethods
        from backend.core.api.app.tasks.celery_config import app
        send = Mock()
        monkeypatch.setattr(app, "send_task", send)
        operation = ChatMethods(directus).cleanup_assistant_speech_for_chat("chat-1")
    elif surface == "account":
        operation = delete_account_personal_speech(directus_service=directus, user_id="owner", user_id_hash="hash", delete_file=delete_file)
    else:
        operation = cleanup(directus, delete_file)
    with pytest.raises(RuntimeError, match="cancellation failed"):
        await operation
    delete_file.assert_not_awaited()
    assert directus.rows["assistant_speech_segments"][0]["status"] == "generating"
    assert directus.rows["assistant_speech_manifests"] and directus.rows["upload_files"]
    assert directus.events == []
    if surface == "dispatch":
        send.assert_not_called()


# contract-test: direct surface=rest_api assertions=assistant-speech.lifecycle.disable-delete-invalidate
@pytest.mark.asyncio
@pytest.mark.parametrize("completion", ["compensated", "lease_expired"])
async def test_cancelled_upload_keeps_authority_until_worker_finishes_or_lease_expires(completion):
    from datetime import datetime, timedelta, timezone
    directus = Directus()
    segment = directus.rows["assistant_speech_segments"][0]
    segment.update({"lease_id": "active-worker", "lease_expires_at": (datetime.now(timezone.utc) + timedelta(seconds=210)).isoformat()})
    upload = directus.rows["upload_files"].pop()
    delete_file = AsyncMock()
    # The upload is still in flight: an empty lookup must never erase its
    # reserved identity or manifest while this worker can publish storage.
    with pytest.raises(RuntimeError, match="execution lease"):
        await cleanup(directus, delete_file)
    delete_file.assert_not_awaited()
    assert segment["status"] == "cancelled"
    assert directus.rows["assistant_speech_manifests"] and directus.rows["assistant_speech_segments"]
    if completion == "compensated":
        segment.update({"lease_id": None, "lease_expires_at": None, "pending_generated_asset_id": None})
    else:
        directus.rows["upload_files"].append(upload)
        segment["lease_expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    await cleanup(directus, delete_file)
    if completion == "lease_expired":
        delete_file.assert_awaited_once_with("owner/assistant_speech/asset-1/original.mp3")
    assert not directus.rows["assistant_speech_manifests"] and not directus.rows["assistant_speech_segments"]


# contract-test: direct surface=rest_api assertions=assistant-speech.lifecycle.disable-delete-invalidate
@pytest.mark.asyncio
async def test_pending_asset_without_upload_index_deletes_reserved_key_and_preserves_authority_on_failure(monkeypatch):
    pytest.importorskip("celery")
    from types import SimpleNamespace
    from backend.apps.audio.assistant_speech import delete_task
    directus = Directus()
    directus.rows["upload_files"] = []
    storage = SimpleNamespace(delete_file=AsyncMock(side_effect=RuntimeError("purge unavailable")))
    task = SimpleNamespace(_directus_service=directus, initialize_core_services=AsyncMock(), cleanup_services=AsyncMock())
    monkeypatch.setattr(delete_task, "initialize_task_storage", AsyncMock(return_value=storage))
    arguments = {"user_id": "owner", "chat_id": "chat-1", "assistant_message_id": "message-1"}
    with pytest.raises(RuntimeError, match="purge unavailable"):
        await delete_task._async_delete_assistant_speech(task, arguments)
    assert directus.rows["assistant_speech_segments"] and directus.rows["assistant_speech_manifests"]
    storage.delete_file.assert_awaited_once_with(bucket_key="chatfiles", file_key="owner/assistant_speech/asset-1/original.mp3")
    storage.delete_file.side_effect = None
    await delete_task._async_delete_assistant_speech(task, arguments)
    assert not directus.rows["assistant_speech_segments"] and not directus.rows["assistant_speech_manifests"]


# contract-test: direct surface=rest_api assertions=assistant-speech.lifecycle.disable-delete-invalidate
@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["before_index", "after_index", "compensation_failure_retry", "expired_prior", None])
async def test_real_manual_worker_reserves_asset_before_storage_and_compensates_failures(monkeypatch, failure):
    pytest.importorskip("celery")
    from types import SimpleNamespace
    from backend.apps.audio.assistant_speech import segment_task
    directus = Directus()
    directus.strict_reads = False
    record = directus.rows["assistant_speech_segments"][0]
    record.update({"status": "queued", "execution_version": 0, "pending_generated_asset_id": None})
    directus.rows["upload_files"] = []
    if failure == "expired_prior":
        from datetime import datetime, timedelta, timezone
        record.update({"status": "generating", "lease_id": "expired-worker",
                       "lease_expires_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
                       "pending_generated_asset_id": "old-asset"})
    reserved = []
    generation_calls = []
    async def cas(collection, row_id, patch, version, **kwargs):
        assert row_id == "segment-row"
        assert record["execution_version"] == version
        if any(record.get(key) != value for key, value in kwargs.get("extra_filters", {}).items()):
            return None
        record.update(patch)
        # Real PATCH acknowledgements can be lost after the write committed.
        return None if "pending_generated_asset_id" in patch else deepcopy(record)
    directus.update_item_if_version = cas
    async def store(_task, **kwargs):
        asset_id = kwargs["embed_id"]
        assert record["pending_generated_asset_id"] == asset_id
        assert record["lease_id"] and record["status"] == "generating"
        reserved.append(asset_id)
        if failure == "after_index":
            directus.rows["upload_files"].append({"id": "upload-new", "embed_id": asset_id,
                "files_metadata": {"original": {"s3_key": f"owner/assistant_speech/{asset_id}/original.mp3"}}})
        if failure in {"before_index", "after_index", "compensation_failure_retry"}:
            raise RuntimeError("upload completion interrupted")
        return {}
    async def generate(**kwargs):
        generation_calls.append("generate")
        result = await kwargs["store_encrypted"](audio_bytes=b"mp3", segment_id="segment-1")
        return {"segment_id": "segment-1", "status": "ready", **result}
    storage = SimpleNamespace(delete_file=AsyncMock(
        side_effect=RuntimeError("purge unavailable") if failure == "compensation_failure_retry" else None))
    task = SimpleNamespace(_directus_service=directus, _s3_service=storage, _secrets_manager=object(),
                           _cache_service=SimpleNamespace(publish_event=AsyncMock()), initialize_core_services=AsyncMock())
    monkeypatch.setattr(segment_task, "initialize_task_storage", AsyncMock(return_value=storage))
    monkeypatch.setattr(segment_task, "require_storage_available", AsyncMock())
    monkeypatch.setattr(segment_task, "ensure_audio_credit_headroom", AsyncMock())
    monkeypatch.setattr(segment_task, "store_generated_audio_asset", store)
    monkeypatch.setattr(segment_task, "generate_speech_segment", generate)
    monkeypatch.setattr(segment_task, "resolve_assistant_voice_profile", lambda *_a, **_k: SimpleNamespace(key="voice", version=1, model=ASSISTANT_RESPONSE_SPEECH_MODEL, provider="mistral"))
    monkeypatch.setattr(segment_task, "assistant_speech_live_mock_audio", lambda _arguments: None)
    arguments = {
        "segment_id": "segment-1", "user_id": "owner", "chat_id": "chat-1", "assistant_message_id": "message-1",
        "speakable_text": "Hello", "voice_profile_key": "voice", "voice_profile_version": 1,
    }
    result = await segment_task._async_generate_assistant_speech_segment(task, arguments)
    assert len(reserved) == 1
    if failure == "compensation_failure_retry":
        original_asset = reserved[0]
        assert record["pending_generated_asset_id"] == original_asset
        result = await segment_task._async_generate_assistant_speech_segment(task, arguments)
        assert len(reserved) == 1 and len(generation_calls) == 1 and record["pending_generated_asset_id"] == original_asset
        assert result["status"] == "error"
        storage.delete_file.side_effect = None
        failure = None
        result = await segment_task._async_generate_assistant_speech_segment(task, arguments)
        assert len(reserved) == 2 and result["status"] == "ready"
        assert record["pending_generated_asset_id"] == reserved[1]
        return
    if failure == "expired_prior":
        storage.delete_file.assert_awaited_once_with(bucket_key="chatfiles", file_key="owner/assistant_speech/old-asset/original.mp3")
        assert result["status"] == "ready" and record["pending_generated_asset_id"] == reserved[0]
        return
    if failure:
        storage.delete_file.assert_awaited_once_with(bucket_key="chatfiles", file_key=f"owner/assistant_speech/{reserved[0]}/original.mp3")
        assert not directus.rows["upload_files"]
        assert record["pending_generated_asset_id"] is None and record["lease_id"] is None
        assert result["status"] == "error"
    else:
        storage.delete_file.assert_not_awaited()
        assert result["generated_asset_id"] == reserved[0]


# contract-test: direct surface=rest_api assertions=assistant-speech.lifecycle.disable-delete-invalidate
@pytest.mark.asyncio
@pytest.mark.parametrize("app_id", ["assistant_response_speech", "audio"])
async def test_real_audio_storage_uses_reserved_key_only_for_assistant_speech(monkeypatch, app_id):
    pytest.importorskip("celery")
    from types import SimpleNamespace
    from backend.apps.audio.tasks import common
    storage = SimpleNamespace(upload_file=AsyncMock(side_effect=RuntimeError("captured upload")))
    task = SimpleNamespace(_s3_service=storage, _encryption_service=SimpleNamespace(encrypt_with_user_key=AsyncMock(return_value=("wrapped", None))))
    monkeypatch.setattr(common, "resolve_user_vault_key_id", AsyncMock(return_value="vault"))
    monkeypatch.setattr(common, "encrypt_media_variants", lambda *_a, **_k: SimpleNamespace(aes_key_b64="key", payloads={"original": b"encrypted"}))
    monkeypatch.setattr(common, "load_media_write_version", lambda: 2)
    with pytest.raises(RuntimeError, match="captured upload"):
        await common.store_generated_audio_asset(
            task, app_id=app_id, skill_id="segment", user_id="owner", user_vault_key_id="vault",
            chat_id="chat", message_id="message", external_request=False, embed_id="asset-id",
            audio_bytes=b"mp3", mime_type="audio/mpeg", duration_seconds=1, model="model", generation_type="speech",
            prompt=None, text_preview=None, extra_content={}, original_filename_prefix="speech", log_prefix="test",
        )
    key = storage.upload_file.await_args.kwargs["file_key"]
    if app_id == "assistant_response_speech":
        assert key == "owner/assistant_speech/asset-id/original.mp3"
    else:
        assert key.startswith("owner/") and key.endswith("_segment_original.mp3") and "/assistant_speech/" not in key


# contract-test: direct surface=rest_api assertions=assistant-speech.lifecycle.disable-delete-invalidate
@pytest.mark.asyncio
@pytest.mark.parametrize("known_deadline", [True, False])
async def test_active_execution_without_reserved_upload_deletes_immediately(known_deadline):
    from datetime import datetime, timedelta, timezone
    directus = Directus()
    directus.rows["upload_files"] = []
    segment = directus.rows["assistant_speech_segments"][0]
    segment.update({"pending_generated_asset_id": None, "lease_id": "active-worker",
                    "lease_expires_at": (datetime.now(timezone.utc) + timedelta(seconds=210)).isoformat() if known_deadline else None})
    await delete_speech_assets(directus, user_id="owner", chat_id="chat-1", assistant_message_id="message-1")
    assert segment["status"] == "cancelled"
    assert not directus.rows["assistant_speech_segments"] and not directus.rows["assistant_speech_manifests"]
    # The provider may still return bytes, but its generating/lease reservation
    # CAS cannot match this cancelled, deleted row and storage cannot start.
    assert not any(row.get("status") == "generating" and row.get("lease_id") == "active-worker"
                   for row in directus.rows["assistant_speech_segments"])
