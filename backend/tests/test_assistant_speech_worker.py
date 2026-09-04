# backend/tests/test_assistant_speech_worker.py
#
# Contract coverage for one-file-per-segment assistant-response speech work.
# The worker receives only one transient segment and delegates provider, private
# storage, and billing dependencies without creating message-level audio.
#

from pathlib import Path

import pytest

from backend.apps.audio.assistant_speech.worker import generate_speech_segment
from backend.apps.audio.pricing import (
    ASSISTANT_RESPONSE_SPEECH_MODEL,
    DEFAULT_SPEECH_MODEL,
    calculate_assistant_response_speech_credits,
)
from backend.apps.audio.assistant_speech.persistence import (
    claim_speech_segment_execution,
    cancel_queued_speech_assets,
    cleanup_generated_speech_asset,
    create_manifest_and_segments,
    delete_speech_assets,
    finalize_speech_segment_execution,
    invalidate_speech_segment,
    prepare_manifest_billing,
    safe_segment_status,
    update_segment_status,
)


# contract-test: supporting surface=rest_api assertions=assistant-speech.billing.segment-success-once,assistant-speech.privacy.transient-plaintext-encrypted-audio
def test_live_mock_audio_is_exactly_scoped_to_the_marked_nonproduction_flow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.apps.audio.assistant_speech import live_mock

    arguments = {
        "live_mock_mode": "mock",
        "live_mock_group": live_mock.ASSISTANT_SPEECH_LIVE_MOCK_GROUP,
        "live_mock_required": "true",
    }
    monkeypatch.setenv("SERVER_ENVIRONMENT", "development")
    monkeypatch.setenv("MOCK_EXTERNAL_APIS", "true")
    fixture = live_mock.assistant_speech_live_mock_audio(arguments)
    assert fixture == live_mock.ASSISTANT_SPEECH_LIVE_MOCK_AUDIO
    assert fixture.read_bytes().startswith(b"ID3") or fixture.read_bytes().startswith(b"\xff")

    assert live_mock.assistant_speech_live_mock_audio({}) is None
    with pytest.raises(RuntimeError, match="group is unavailable"):
        live_mock.assistant_speech_live_mock_audio({**arguments, "live_mock_group": "another_test"})
    monkeypatch.setenv("SERVER_ENVIRONMENT", "production")
    with pytest.raises(RuntimeError, match="disabled in production"):
        live_mock.assistant_speech_live_mock_audio(arguments)


# contract-test: supporting surface=rest_api assertions=assistant-speech.billing.segment-success-once,assistant-speech.privacy.transient-plaintext-encrypted-audio
def test_live_mock_marker_context_is_server_validated_and_required_by_the_speech_task() -> None:
    backend_root = Path(__file__).resolve().parents[1]
    ask_source = (backend_root / "apps/ai/tasks/ask_skill_task.py").read_text(encoding="utf-8")
    stream_source = (backend_root / "apps/ai/tasks/stream_consumer.py").read_text(encoding="utf-8")

    assert "request_data.live_mock_mode = None" in ask_source
    assert "resolve_live_marker_or_raise(marker_content, request_data.user_id)" in ask_source
    assert 'LIVE_MOCK_CANDIDATE_ROOT' in ask_source
    assert "request_data.live_mock_mode = live_mode" in ask_source
    assert "request_data.live_mock_group = live_group" in ask_source
    assert "live_mock_mode=request_data.live_mock_mode" in stream_source
    assert '"live_mock_required": "true"' in stream_source


# contract-test: direct surface=rest_api assertions=assistant-speech.segmentation.one-file-per-segment,assistant-speech.privacy.transient-plaintext-encrypted-audio,assistant-speech.billing.segment-success-once
@pytest.mark.asyncio
async def test_generates_one_encrypted_asset_and_records_exact_submitted_characters_without_segment_billing() -> None:
    calls: list[tuple[str, object]] = []

    async def safety_check(*, text: str) -> dict[str, object]:
        calls.append(("safety", text))
        return {"approved": True}

    async def provider_generate(*, text: str, voice_profile: dict[str, object]) -> dict[str, object]:
        calls.append(("provider", text))
        assert voice_profile == {"profile_id": "mate-a-v1", "provider": "elevenlabs"}
        return {"audio_bytes": b"segment-mp3", "duration_seconds": 1.2}

    async def store_encrypted(*, audio_bytes: bytes, segment_id: str) -> dict[str, str]:
        calls.append(("store", audio_bytes))
        assert segment_id == "segment-0"
        return {"generated_asset_id": segment_id}

    async def record_submission(*, submitted_characters: int) -> None:
        calls.append(("submission", submitted_characters))

    result = await generate_speech_segment(
        segment={
            "segment_id": "segment-0",
            "chat_id": "chat-1",
            "assistant_message_id": "message-1",
            "source_hash": "source-hash",
            "speakable_text": "First paragraph.",
        },
        voice_profile={"profile_id": "mate-a-v1", "provider": "elevenlabs"},
        safety_check=safety_check,
        provider_generate=provider_generate,
        store_encrypted=store_encrypted,
        record_submission=record_submission,
    )

    assert calls == [
        ("safety", "First paragraph."),
        ("provider", "First paragraph."),
        ("submission", len("First paragraph.")),
        ("store", b"segment-mp3"),
    ]
    assert result == {
        "segment_id": "segment-0",
        "status": "ready",
        "generated_asset_id": "segment-0",
        "duration_seconds": 1.2,
    }
    assert "speakable_text" not in result
    assert "audio_bytes" not in result


# contract-test: direct surface=rest_api assertions=assistant-speech.billing.segment-success-once
def test_assistant_response_speech_uses_one_message_level_character_rounding_step() -> None:
    assert calculate_assistant_response_speech_credits(submitted_characters=1) == 1
    assert calculate_assistant_response_speech_credits(submitted_characters=14) == 1
    assert calculate_assistant_response_speech_credits(submitted_characters=15) == 2
    assert calculate_assistant_response_speech_credits(submitted_characters=1_000) == 72
    assert calculate_assistant_response_speech_credits(submitted_characters=8 + 8) == 2
    assert ASSISTANT_RESPONSE_SPEECH_MODEL == "eleven_v3_conversational"
    assert DEFAULT_SPEECH_MODEL == "eleven_v3"


# contract-test: direct surface=rest_api assertions=assistant-speech.safety.provider-after-approval,assistant-speech.failure.nonblocking-visible-resumable
@pytest.mark.asyncio
async def test_safety_rejection_does_not_call_provider_storage_or_billing() -> None:
    called = False

    async def safety_check(*, text: str) -> dict[str, object]:
        assert text == "Rejected paragraph."
        return {"approved": False, "safe_error": "Speech is unavailable for this paragraph."}

    async def must_not_run(**_kwargs):
        nonlocal called
        called = True
        raise AssertionError("rejected speech must not reach a side-effect dependency")

    result = await generate_speech_segment(
        segment={"segment_id": "segment-1", "speakable_text": "Rejected paragraph."},
        voice_profile={"profile_id": "mate-a-v1"},
        safety_check=safety_check,
        provider_generate=must_not_run,
        store_encrypted=must_not_run,
        record_submission=must_not_run,
    )

    assert called is False
    assert result == {
        "segment_id": "segment-1",
        "status": "error",
        "error": "Speech is unavailable for this paragraph.",
        "retryable": False,
    }


# contract-test: direct surface=rest_api assertions=assistant-speech.billing.segment-success-once,assistant-speech.failure.nonblocking-visible-resumable
@pytest.mark.asyncio
async def test_provider_failure_records_no_billable_characters() -> None:
    async def safety_check(**_kwargs) -> dict[str, object]:
        return {"approved": True}

    async def provider_generate(**_kwargs) -> dict[str, object]:
        raise RuntimeError("provider unavailable")

    async def store_encrypted(**_kwargs) -> dict[str, str]:
        return {"generated_asset_id": "segment-2"}

    async def record_submission(**_kwargs) -> None:
        raise AssertionError("failed provider output must not be billable")

    with pytest.raises(RuntimeError, match="provider unavailable"):
        await generate_speech_segment(
            segment={"segment_id": "segment-2", "speakable_text": "Bill me."},
            voice_profile={"profile_id": "mate-a-v1"},
            safety_check=safety_check,
            provider_generate=provider_generate,
            store_encrypted=store_encrypted,
            record_submission=record_submission,
        )


# contract-test: direct surface=rest_api assertions=assistant-speech.billing.segment-success-once,assistant-speech.access.first-party-owner-scoped,assistant-speech.privacy.transient-plaintext-encrypted-audio
@pytest.mark.asyncio
async def test_real_segment_task_reuses_ready_redelivery_and_links_the_decryptable_asset(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("celery", reason="real Celery task wiring requires the worker dependency")
    from backend.apps.audio.assistant_speech import segment_task

    records = {"segment-3": {"id": "row-3", "segment_id": "segment-3", "sequence": 0, "status": "queued"}}
    calls: list[dict[str, object]] = []

    class Directus:
        async def get_items(self, _collection, *, params, no_cache):
            segment_id = params["filter[segment_id][_eq]"]
            return [records[segment_id]] if segment_id in records else []

        async def update_item(self, _collection, _row_id, data):
            records["segment-3"].update(data)

        async def update_item_if_version(self, _collection, _row_id, data, expected_version, **_kwargs):
            if int(records["segment-3"].get("execution_version") or 0) != expected_version:
                return None
            records["segment-3"].update(data)
            return records["segment-3"]

    class Client:
        count = 0

        async def incr(self, _key):
            self.count += 1
            return self.count

        async def expire(self, *_args):
            return True

        async def set(self, *_args, **_kwargs):
            return True

    class Cache:
        client = Client()
        events: list[tuple[str, dict[str, object]]] = []

        async def publish_event(self, channel: str, payload: dict[str, object]):
            self.events.append((channel, payload))
            return None

    class Task:
        _directus_service = Directus()
        _cache_service = Cache()
        _secrets_manager = object()

        async def initialize_core_services(self):
            return None

    async def fake_store(_task, **kwargs):
        calls.append(kwargs)
        return {"files": {"original": {"s3_key": "private/key"}}, "aes_key": "key", "aes_nonce": "nonce", "vault_wrapped_aes_key": "wrapped"}

    async def fake_safety(**_kwargs):
        return type("Decision", (), {"approved": True, "user_facing_message": ""})()

    class Provider:
        def __init__(self, **_kwargs):
            pass

        async def text_to_speech(self, **_kwargs):
            return type("Generated", (), {"audio_bytes": b"mp3", "duration_seconds": 1.0, "mime_type": "audio/mpeg"})()

    class Profile:
        key = "voice"
        version = 1
        model = "eleven_v3_conversational"
        provider = "provider"

        def elevenlabs_request(self):
            return {"voice_id": "voice-id", "model": self.model, "output_format": "mp3_44100_128", "voice_settings": {"speed": 1.0}}

    monkeypatch.setattr(segment_task, "initialize_task_storage", lambda _task: __import__("asyncio").sleep(0, result=object()))
    monkeypatch.setattr(segment_task, "require_storage_available", lambda _storage: __import__("asyncio").sleep(0))
    monkeypatch.setattr(segment_task, "store_generated_audio_asset", fake_store)
    monkeypatch.setattr(segment_task, "ElevenLabsClient", Provider)
    monkeypatch.setattr(segment_task, "resolve_assistant_voice_profile", lambda *_args, **_kwargs: Profile())
    monkeypatch.setattr("backend.apps.audio.skills.speak_skill.classify_audio_speech_safety", fake_safety)

    arguments = {"segment_id": "segment-3", "user_id": "owner-1", "chat_id": "chat-1", "assistant_message_id": "message-1", "source_hash": "hash", "speakable_text": "Hello.", "voice_profile_key": "warm_neutral", "voice_profile_version": 1}
    first = await segment_task._async_generate_assistant_speech_segment(Task(), arguments)
    second = await segment_task._async_generate_assistant_speech_segment(Task(), arguments)

    assert first["status"] == second["status"] == "ready"
    assert len(calls) == 1
    assert calls[0]["chat_id"] == "chat-1"
    assert calls[0]["message_id"] == "message-1"
    assert calls[0]["external_request"] is False
    assert Task._cache_service.events == [
        (
            "chat_stream::chat-1",
            {
                "type": "assistant_speech_status",
                "chat_id": "chat-1",
                "user_id_hash": __import__("hashlib").sha256(b"owner-1").hexdigest(),
                "message_id": "message-1",
                "payload": {
                    "segment_id": "segment-3",
                    "status": "ready",
                    "generated_asset_id": "segment-3",
                    "duration_seconds": 1.0,
                    "kind": "prose_paragraph",
                    "sequence": 0,
                    "chat_id": "chat-1",
                    "message_id": "message-1",
                },
            },
        ),
    ]


# contract-test: direct surface=rest_api assertions=assistant-speech.segmentation.one-file-per-segment,assistant-speech.segmentation.immutable-source,assistant-speech.privacy.transient-plaintext-encrypted-audio
@pytest.mark.asyncio
async def test_persists_owner_scoped_manifest_and_one_plaintext_free_record_per_segment() -> None:
    created: list[tuple[str, dict[str, object]]] = []

    class Directus:
        async def create_item(self, collection: str, data: dict[str, object]):
            created.append((collection, data))
            return True, data

        async def get_items(self, collection: str, *, params: dict[str, object], no_cache: bool):
            if collection == "assistant_speech_manifests":
                identity = params.get("filter[manifest_id][_eq]")
                return [record for name, record in created if name == collection and record["manifest_id"] == identity]
            identity = params.get("filter[segment_id][_eq]")
            return [record for name, record in created if name == collection and record["segment_id"] == identity]

    manifest = await create_manifest_and_segments(
        Directus(),
        user_id="owner-1",
        chat_id="chat-1",
        assistant_message_id="message-1",
        source_version=2,
        voice_profile={"key": "warm_neutral", "version": 1},
        segments=[
            {"segment_id": "segment-0", "sequence": 0, "source_hash": "hash-0", "speakable_text": "First."},
            {"segment_id": "segment-1", "sequence": 1, "source_hash": "hash-1", "speakable_text": "Second."},
        ],
    )

    assert manifest["ordered_segment_ids"] == ["segment-0", "segment-1"]
    assert [collection for collection, _ in created] == [
        "assistant_speech_manifests",
        "assistant_speech_segments",
        "assistant_speech_segments",
    ]
    segment_record = created[-1][1]
    assert all("speakable_text" not in record for _, record in created)
    assert all("First." not in repr(record) and "Second." not in repr(record) for _, record in created)
    assert {"execution_version", "lease_expires_at"}.issubset(segment_record)

    repeated = await create_manifest_and_segments(
        Directus(),
        user_id="owner-1",
        chat_id="chat-1",
        assistant_message_id="message-1",
        source_version=2,
        voice_profile={"key": "warm_neutral", "version": 1},
        segments=[{"segment_id": "segment-0", "sequence": 0, "source_hash": "hash-0", "speakable_text": "First."}],
    )
    assert repeated["dispatch_segment_ids"] == []


# contract-test: direct surface=rest_api assertions=assistant-speech.segmentation.immutable-source,assistant-speech.lifecycle.disable-delete-invalidate
@pytest.mark.asyncio
async def test_rewritten_segment_is_invalidated_and_replaces_only_its_manifest_entry() -> None:
    created: dict[str, list[dict[str, object]]] = {
        "assistant_speech_manifests": [],
        "assistant_speech_segments": [],
    }

    class Directus:
        async def create_item(self, collection: str, data: dict[str, object]):
            record = {**data, "id": data.get("manifest_id") or data.get("segment_id")}
            created[collection].append(record)
            return True, record

        async def get_items(self, collection: str, *, params: dict[str, object], no_cache: bool):
            field = "manifest_id" if collection == "assistant_speech_manifests" else "segment_id"
            identity = params.get(f"filter[{field}][_eq]")
            return [record for record in created[collection] if record[field] == identity]

        async def update_item(self, collection: str, row_id: str, data: dict[str, object]):
            for record in created[collection]:
                if record["id"] == row_id:
                    record.update(data)

    directus = Directus()
    base = {
        "user_id": "owner-1",
        "chat_id": "chat-1",
        "assistant_message_id": "message-1",
        "source_version": 2,
        "voice_profile": {"key": "warm_neutral", "version": 1},
    }
    await create_manifest_and_segments(
        directus,
        **base,
        segments=[{"segment_id": "old", "sequence": 0, "source_hash": "old-hash", "speakable_text": "Old."}],
    )
    await invalidate_speech_segment(directus, "old")
    replacement = await create_manifest_and_segments(
        directus,
        **base,
        segments=[
            {
                "segment_id": "new",
                "replaces_segment_id": "old",
                "sequence": 0,
                "source_hash": "new-hash",
                "speakable_text": "New.",
            },
        ],
    )

    assert created["assistant_speech_segments"][0]["status"] == "invalidated"
    assert replacement["dispatch_segment_ids"] == ["new"]
    assert created["assistant_speech_manifests"][0]["ordered_segment_ids"] == ["new"]


# contract-test: direct surface=rest_api assertions=assistant-speech.lifecycle.disable-delete-invalidate
@pytest.mark.asyncio
async def test_delete_tombstones_records_before_asset_cleanup() -> None:
    records = [{"id": "row-1", "segment_id": "segment-1", "status": "ready"}]
    events: list[str] = []

    class Directus:
        async def get_items(self, collection: str, *, params: dict[str, object], no_cache: bool):
            if collection == "assistant_speech_segments":
                return records
            return []

        async def update_item(self, _collection: str, _row_id: str, data: dict[str, object]):
            events.append(str(data["status"]))
            records[0].update(data)

        async def delete_item(self, _collection: str, _row_id: str):
            events.append("delete")

    async def delete_asset(row: dict[str, object]) -> None:
        assert row["status"] == "cancelled"
        events.append("asset")

    await delete_speech_assets(
        Directus(), user_id="owner-1", chat_id="chat-1", assistant_message_id="message-1", delete_asset=delete_asset,
    )

    assert events == ["cancelled", "asset", "delete"]


# contract-test: direct surface=rest_api assertions=assistant-speech.privacy.transient-plaintext-encrypted-audio,assistant-speech.failure.nonblocking-visible-resumable
def test_status_serialization_excludes_plaintext_provider_and_internal_storage_fields() -> None:
    status = safe_segment_status(
        {
            "segment_id": "segment-0",
            "status": "ready",
            "generated_asset_id": "segment-0",
            "duration_seconds": 1.2,
            "billable_character_count": 16,
            "sequence": 0,
            "speakable_text": "never send this",
            "provider_request_id": "provider-only",
            "billing_usage_id": "usage-only",
            "vault_wrapped_aes_key": "internal",
        },
    )

    assert status == {
        "segment_id": "segment-0",
        "status": "ready",
        "generated_asset_id": "segment-0",
        "duration_seconds": 1.2,
        "sequence": 0,
    }


# contract-test: supporting surface=rest_api assertions=assistant-speech.segmentation.one-file-per-segment,assistant-speech.privacy.transient-plaintext-encrypted-audio,assistant-speech.lifecycle.disable-delete-invalidate
def test_additive_schema_and_tasks_keep_one_upload_backed_object_per_segment_without_plaintext() -> None:
    backend_root = Path(__file__).resolve().parents[1]
    schema = (backend_root / "core/directus/schemas/assistant_speech.yml").read_text(encoding="utf-8")
    segment_task = (backend_root / "apps/audio/assistant_speech/segment_task.py").read_text(encoding="utf-8")
    delete_task = (backend_root / "apps/audio/assistant_speech/delete_task.py").read_text(encoding="utf-8")

    assert "assistant_speech_manifests:" in schema
    assert "assistant_speech_segments:" in schema
    assert "speakable_text" not in schema
    assert "execution_version:" in schema
    assert "lease_expires_at:" in schema
    assert "aes_key" not in schema
    assert "aes_nonce" not in schema
    assert "vault_wrapped_aes_key" not in schema
    assert "embed_id=segment_id" in segment_task
    assert '"assistant_speech_segment"' in segment_task
    assert "cleanup_generated_speech_asset" in delete_task


# contract-test: supporting surface=rest_api assertions=assistant-speech.execution.text-stream-independent,assistant-speech.lifecycle.disable-delete-invalidate
def test_celery_segment_billing_and_deletion_tasks_are_registered_on_the_audio_worker_queue() -> None:
    backend_root = Path(__file__).resolve().parents[1]
    segment_task = (backend_root / "apps/audio/assistant_speech/segment_task.py").read_text(encoding="utf-8")
    delete_task = (backend_root / "apps/audio/assistant_speech/delete_task.py").read_text(encoding="utf-8")
    billing_task = (backend_root / "apps/audio/assistant_speech/billing_task.py").read_text(encoding="utf-8")
    celery_config = (backend_root / "core/api/app/tasks/celery_config.py").read_text(encoding="utf-8")

    assert 'name="apps.audio.tasks.assistant_speech_segment"' in segment_task
    assert 'name="apps.audio.tasks.assistant_speech_delete"' in delete_task
    assert 'name="apps.audio.tasks.assistant_speech_billing"' in billing_task
    assert 'queue="app_music"' in segment_task
    assert 'queue="app_music"' in delete_task
    assert 'queue="app_music"' in billing_task
    assert "backend.apps.audio.assistant_speech.billing_task" in celery_config


# contract-test: direct surface=rest_api assertions=assistant-speech.execution.text-stream-independent
@pytest.mark.asyncio
async def test_expired_lease_is_reclaimed_with_a_new_deadline() -> None:
    record = {
        "id": "row-1",
        "segment_id": "segment-1",
        "status": "generating",
        "lease_id": "expired",
        "lease_expires_at": "2000-01-01T00:00:00+00:00",
        "execution_version": 3,
    }

    class Directus:
        async def get_items(self, _collection, *, params, no_cache):
            return [record] if params["filter[segment_id][_eq]"] == "segment-1" else []

        async def update_item_if_version(self, _collection, _row_id, patch, expected_version, **_kwargs):
            assert expected_version == 3
            record.update(patch)
            return record

    claimed = await claim_speech_segment_execution(Directus(), "segment-1", lease_id="replacement")

    assert claimed is not None
    assert claimed["lease_id"] == "replacement"
    assert claimed["lease_expires_at"] > "2000-01-01T00:00:00+00:00"
    assert claimed["execution_version"] == 4


# contract-test: direct surface=rest_api assertions=assistant-speech.lifecycle.disable-delete-invalidate
@pytest.mark.asyncio
async def test_cancellation_storage_compensation_deletes_upload_before_tombstone_can_be_removed() -> None:
    deleted: list[str] = []

    class Directus:
        async def get_items(self, _collection, *, params, no_cache):
            assert params["filter[embed_id][_eq]"] == "segment-1"
            return [{"id": "upload-1", "files_metadata": {"original": {"s3_key": "private/audio"}}}]

        async def delete_item(self, collection, row_id):
            deleted.append(f"{collection}:{row_id}")

    async def delete_file(file_key: str) -> None:
        deleted.append(f"chatfiles:{file_key}")

    await cleanup_generated_speech_asset(Directus(), "segment-1", delete_file=delete_file)

    assert deleted == ["chatfiles:private/audio", "upload_files:upload-1"]


# contract-test: direct surface=rest_api assertions=assistant-speech.privacy.transient-plaintext-encrypted-audio
@pytest.mark.asyncio
async def test_segment_status_persists_only_asset_reference_and_never_key_material() -> None:
    persisted: dict[str, object] = {}

    class Directus:
        async def get_items(self, _collection, *, params, no_cache):
            return [{"id": "row-1", "segment_id": params["filter[segment_id][_eq]"]}]

        async def update_item(self, _collection, _row_id, patch):
            persisted.update(patch)

    await update_segment_status(
        Directus(),
        "segment-1",
        {
            "segment_id": "segment-1",
            "status": "ready",
            "generated_asset_id": "segment-1",
            "duration_seconds": 1.2,
            "billable_character_count": 16,
            "aes_key": "raw-key",
            "aes_nonce": "raw-nonce",
            "vault_wrapped_aes_key": "wrapped-key",
            "encrypted_audio": {"aes_key": "raw-key"},
        },
    )

    assert persisted == {
        "status": "ready",
        "generated_asset_id": "segment-1",
        "duration_seconds": 1.2,
        "billable_character_count": 16,
        "lease_id": None,
        "lease_expires_at": None,
    }


# contract-test: direct surface=rest_api assertions=assistant-speech.billing.segment-success-once
@pytest.mark.asyncio
async def test_manifest_billing_sums_ready_segments_once_without_per_segment_rounding() -> None:
    class Directus:
        async def get_items(self, collection, *, params, no_cache):
            if collection == "assistant_speech_manifests":
                return [{
                    "id": "manifest-row", "manifest_id": "manifest-1", "user_id": "user-1",
                    "chat_id": "chat-1", "assistant_message_id": "message-1", "sealed": True,
                    "billing_status": "pending", "model": ASSISTANT_RESPONSE_SPEECH_MODEL,
                    "ordered_segment_ids": ["segment-1", "segment-2"],
                }]
            return [
                {"segment_id": "segment-1", "status": "ready", "billable_character_count": 8, "duration_seconds": 1.0},
                {"segment_id": "segment-2", "status": "ready", "billable_character_count": 8, "duration_seconds": 2.0},
            ]

    billing = await prepare_manifest_billing(Directus(), "manifest-1")

    assert billing is not None
    assert billing["submitted_characters"] == 16
    assert billing["duration_seconds"] == 3.0
    assert calculate_assistant_response_speech_credits(submitted_characters=int(billing["submitted_characters"])) == 2


# contract-test: direct surface=rest_api assertions=assistant-speech.billing.segment-success-once
@pytest.mark.asyncio
async def test_manifest_billing_rejects_ready_segments_without_character_metadata() -> None:
    class Directus:
        async def get_items(self, collection, *, params, no_cache):
            if collection == "assistant_speech_manifests":
                return [{
                    "id": "manifest-row", "manifest_id": "manifest-1", "user_id": "user-1",
                    "chat_id": "chat-1", "assistant_message_id": "message-1", "sealed": True,
                    "billing_status": "pending", "model": ASSISTANT_RESPONSE_SPEECH_MODEL,
                    "ordered_segment_ids": ["segment-1"],
                }]
            return [{"segment_id": "segment-1", "status": "ready", "duration_seconds": 1.0}]

    with pytest.raises(RuntimeError, match="billable character metadata"):
        await prepare_manifest_billing(Directus(), "manifest-1")


# contract-test: direct surface=rest_api assertions=assistant-speech.lifecycle.disable-delete-invalidate
@pytest.mark.asyncio
async def test_cancellation_after_storage_deletes_the_new_upload_before_worker_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("celery", reason="Celery task wiring requires the worker dependency")
    from backend.apps.audio.assistant_speech import segment_task

    record = {"id": "row-1", "segment_id": "segment-1", "status": "queued", "execution_version": 0}
    deleted: list[str] = []

    class Directus:
        async def get_items(self, collection, *, params, no_cache):
            if collection == "assistant_speech_segments":
                return [record]
            return [{"id": "upload-1", "files_metadata": {"original": {"s3_key": "private/audio"}}}]

        async def update_item(self, _collection, _row_id, patch):
            record.update(patch)

        async def delete_item(self, collection, row_id):
            deleted.append(f"{collection}:{row_id}")

    class Storage:
        async def delete_file(self, *, bucket_key, file_key):
            deleted.append(f"{bucket_key}:{file_key}")

    class Task:
        _directus_service = Directus()
        _cache_service = type("Cache", (), {"publish_event": staticmethod(lambda *_args: __import__("asyncio").sleep(0))})()
        _secrets_manager = object()
        _s3_service = Storage()

        async def initialize_core_services(self):
            return None

    async def fake_store(*_args, **_kwargs):
        record["status"] = "cancelled"
        return {"files": {}}

    async def fake_safety(**_kwargs):
        return type("Decision", (), {"approved": True, "user_facing_message": ""})()

    class Provider:
        def __init__(self, **_kwargs):
            pass

        async def text_to_speech(self, **_kwargs):
            return type("Generated", (), {"audio_bytes": b"mp3", "duration_seconds": 1.0, "mime_type": "audio/mpeg"})()

    class Profile:
        key = "voice"
        version = 1
        model = "eleven_v3"
        provider = "provider"

        def elevenlabs_request(self):
            return {"voice_id": "voice-id", "model": self.model, "output_format": "mp3_44100_128", "voice_settings": {"speed": 1.0}}

    monkeypatch.setattr(segment_task, "initialize_task_storage", lambda _task: __import__("asyncio").sleep(0, result=object()))
    monkeypatch.setattr(segment_task, "require_storage_available", lambda _storage: __import__("asyncio").sleep(0))
    monkeypatch.setattr(segment_task, "store_generated_audio_asset", fake_store)
    monkeypatch.setattr(segment_task, "ElevenLabsClient", Provider)
    monkeypatch.setattr(segment_task, "resolve_assistant_voice_profile", lambda *_args, **_kwargs: Profile())
    monkeypatch.setattr("backend.apps.audio.skills.speak_skill.classify_audio_speech_safety", fake_safety)

    result = await segment_task._async_generate_assistant_speech_segment(
        Task(),
        {"segment_id": "segment-1", "user_id": "owner-1", "chat_id": "chat-1", "assistant_message_id": "message-1", "source_hash": "hash", "speakable_text": "Hello.", "voice_profile_key": "voice", "voice_profile_version": 1},
    )

    assert result == {"segment_id": "segment-1", "status": "cancelled"}
    assert deleted == ["chatfiles:private/audio", "upload_files:upload-1"]


# contract-test: direct surface=rest_api assertions=assistant-speech.lifecycle.disable-delete-invalidate
@pytest.mark.asyncio
async def test_cancel_only_tombstones_queued_undispatched_segments() -> None:
    records = [
        {"id": "queued", "status": "queued"},
        {"id": "generating", "status": "generating", "lease_id": "worker-1", "execution_version": 2},
    ]

    class Directus:
        async def get_items(self, _collection, *, params, no_cache):
            status = params.get("filter[status][_eq]")
            return [record for record in records if status is None or record["status"] == status]

        async def update_item_if_version(self, _collection, row_id, patch, expected_version, **kwargs):
            record = next(record for record in records if record["id"] == row_id)
            assert expected_version == int(record.get("execution_version") or 0)
            assert kwargs["extra_filters"] == {"status": "queued"}
            record.update(patch)
            return record

        async def update_item(self, _collection, row_id, patch):
            next(record for record in records if record["id"] == row_id).update(patch)

    await cancel_queued_speech_assets(Directus(), user_id="owner-1", chat_id="chat-1", assistant_message_id="message-1")

    assert records[0]["status"] == "cancelled"
    assert records[1]["status"] == "generating"


# contract-test: direct surface=rest_api assertions=assistant-speech.lifecycle.disable-delete-invalidate,assistant-speech.billing.segment-success-once
@pytest.mark.asyncio
async def test_final_ready_requires_claim_lease_and_version_and_compensates_when_tombstoned(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("celery", reason="Celery task wiring requires the worker dependency")
    from backend.apps.audio.assistant_speech import segment_task

    record = {"id": "row-1", "segment_id": "segment-1", "status": "queued", "execution_version": 0}
    deleted: list[str] = []

    class Directus:
        async def get_items(self, collection, *, params, no_cache):
            if collection == "assistant_speech_segments":
                return [record]
            return [{"id": "upload-1", "files_metadata": {"original": {"s3_key": "private/audio"}}}]

        async def update_item_if_version(self, _collection, _row_id, patch, expected_version, **kwargs):
            if patch.get("status") == "ready":
                assert kwargs["extra_filters"] == {"status": "generating", "lease_id": record["lease_id"]}
                record["status"] = "cancelled"
                return None
            assert expected_version == 0
            record.update(patch)
            return record

        async def delete_item(self, collection, row_id):
            deleted.append(f"{collection}:{row_id}")

        async def update_item(self, _collection, _row_id, patch):
            record.update(patch)

    class Storage:
        async def delete_file(self, *, bucket_key, file_key):
            deleted.append(f"{bucket_key}:{file_key}")

    class Task:
        _directus_service = Directus()
        _cache_service = type("Cache", (), {"publish_event": staticmethod(lambda *_args: __import__("asyncio").sleep(0))})()
        _secrets_manager = object()
        _s3_service = Storage()

        async def initialize_core_services(self):
            return None

    async def fake_store(*_args, **_kwargs):
        return {"files": {}}

    async def fake_safety(**_kwargs):
        return type("Decision", (), {"approved": True, "user_facing_message": ""})()

    class Provider:
        def __init__(self, **_kwargs):
            pass

        async def text_to_speech(self, **_kwargs):
            return type("Generated", (), {"audio_bytes": b"mp3", "duration_seconds": 1.0, "mime_type": "audio/mpeg"})()

    class Profile:
        key = "voice"
        version = 1
        model = "eleven_v3_conversational"
        provider = "provider"

        def elevenlabs_request(self):
            return {"voice_id": "voice-id", "model": self.model, "output_format": "mp3_44100_128", "voice_settings": {"speed": 1.0}}

    monkeypatch.setattr(segment_task, "initialize_task_storage", lambda _task: __import__("asyncio").sleep(0, result=object()))
    monkeypatch.setattr(segment_task, "require_storage_available", lambda _storage: __import__("asyncio").sleep(0))
    monkeypatch.setattr(segment_task, "store_generated_audio_asset", fake_store)
    monkeypatch.setattr(segment_task, "ElevenLabsClient", Provider)
    monkeypatch.setattr(segment_task, "resolve_assistant_voice_profile", lambda *_args, **_kwargs: Profile())
    monkeypatch.setattr("backend.apps.audio.skills.speak_skill.classify_audio_speech_safety", fake_safety)

    result = await segment_task._async_generate_assistant_speech_segment(
        Task(),
        {"segment_id": "segment-1", "user_id": "owner-1", "chat_id": "chat-1", "assistant_message_id": "message-1", "source_hash": "hash", "speakable_text": "Hello.", "voice_profile_key": "voice", "voice_profile_version": 1},
    )

    assert result == {"segment_id": "segment-1", "status": "cancelled"}
    assert deleted == ["chatfiles:private/audio", "upload_files:upload-1"]


# contract-test: direct surface=rest_api assertions=assistant-speech.lifecycle.disable-delete-invalidate,assistant-speech.billing.segment-success-once
@pytest.mark.asyncio
async def test_ready_finalization_uses_claim_lease_version_and_generating_status() -> None:
    record = {"id": "row-1", "segment_id": "segment-1", "status": "generating", "lease_id": "lease-1", "execution_version": 4}

    class Directus:
        async def get_items(self, _collection, *, params, no_cache):
            return [record]

        async def update_item_if_version(self, _collection, _row_id, patch, expected_version, **kwargs):
            assert expected_version == 4
            assert kwargs["extra_filters"] == {"status": "generating", "lease_id": "lease-1"}
            record.update(patch)
            return record

    finalized = await finalize_speech_segment_execution(
        Directus(),
        "segment-1",
        {"segment_id": "segment-1", "status": "ready", "generated_asset_id": "asset-1", "duration_seconds": 1.2},
        lease_id="lease-1",
        execution_version=4,
    )

    assert finalized is True
    assert record["status"] == "ready"
    assert record["lease_id"] is None


# contract-test: direct surface=rest_api assertions=assistant-speech.lifecycle.disable-delete-invalidate,assistant-speech.billing.segment-success-once
@pytest.mark.asyncio
async def test_ready_finalization_confirms_empty_conditional_update_response_before_compensation() -> None:
    record = {"id": "row-1", "segment_id": "segment-1", "status": "generating", "lease_id": "lease-1", "execution_version": 4}

    class Directus:
        get_calls = 0

        async def get_items(self, _collection, *, params, no_cache):
            self.get_calls += 1
            return [record]

        async def update_item_if_version(self, _collection, _row_id, patch, expected_version, **kwargs):
            assert expected_version == 4
            assert kwargs["extra_filters"] == {"status": "generating", "lease_id": "lease-1"}
            record.update(patch)
            return None

    directus = Directus()
    finalized = await finalize_speech_segment_execution(
        directus,
        "segment-1",
        {"segment_id": "segment-1", "status": "ready", "generated_asset_id": "asset-1", "duration_seconds": 1.2},
        lease_id="lease-1",
        execution_version=4,
    )

    assert finalized is True
    assert directus.get_calls == 2
    assert record["status"] == "ready"
    assert record["generated_asset_id"] == "asset-1"
