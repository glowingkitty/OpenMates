"""Regression tests for versioned embed update publication.

Diff edits update an already-finished embed in place. Normal finished updates are
deduplicated, but versioned updates must deliberately publish `send_embed_data`
again so web, CLI, and Apple clients encrypt and persist the latest snapshot.
"""

import json
import sys
import types
from types import SimpleNamespace

import pytest

redis_stub = types.ModuleType("redis")
redis_asyncio_stub = types.ModuleType("redis.asyncio")
redis_exceptions_stub = types.SimpleNamespace(RedisError=Exception, ConnectionError=Exception)
redis_asyncio_stub.Redis = object
redis_stub.asyncio = redis_asyncio_stub
redis_stub.exceptions = redis_exceptions_stub
sys.modules.setdefault("redis", redis_stub)
sys.modules.setdefault("redis.asyncio", redis_asyncio_stub)

cache_module_stub = types.ModuleType("backend.core.api.app.services.cache")
cache_module_stub.CacheService = object
sys.modules.setdefault("backend.core.api.app.services.cache", cache_module_stub)

directus_module_stub = types.ModuleType("backend.core.api.app.services.directus")
directus_module_stub.DirectusService = object
sys.modules.setdefault("backend.core.api.app.services.directus", directus_module_stub)

toon_stub = types.ModuleType("toon_format")
toon_stub.encode = lambda value: json.dumps(value)
toon_stub.decode = lambda value: json.loads(value)
sys.modules.setdefault("toon_format", toon_stub)

youtube_stub = types.ModuleType("backend.shared.providers.youtube.youtube_metadata")
youtube_stub.extract_youtube_id_from_url = lambda url: None
sys.modules.setdefault("backend.shared.providers.youtube.youtube_metadata", youtube_stub)

github_stub = types.ModuleType("backend.shared.providers.github")
github_stub.build_github_repo_embed = lambda url: None
github_stub.is_github_repo_url = lambda url: isinstance(url, str) and url.rstrip("/").count("/") == 4 and url.startswith("https://github.com/")
sys.modules.setdefault("backend.shared.providers.github", github_stub)

e2b_preview_stub = types.ModuleType("backend.shared.providers.e2b_application_preview")
e2b_preview_stub.ApplicationPreviewEntrypoint = object
e2b_preview_stub.ApplicationPreviewFile = object
e2b_preview_stub.ApplicationPreviewPlanningError = Exception
e2b_preview_stub.plan_application_preview_startup = lambda *args, **kwargs: None
sys.modules.setdefault("backend.shared.providers.e2b_application_preview", e2b_preview_stub)

from backend.core.api.app.services.embed_service import EmbedService  # noqa: E402  # Import after stubbing optional dependencies.
from backend.shared.python_utils.chat_completion_recovery import derive_recovery_keypair  # noqa: E402
from backend.shared.python_utils.chat_recovery_context import (  # noqa: E402
    RecoveryOutputContext, RequiredRecoveryOutputError, VerifiedOutputProducer,
    active_recovery_output_context, active_verified_output_producer,
)
from backend.apps.ai.processing.voice_async_skills import active_voice_worker_context  # noqa: E402
from backend.shared.python_utils import volatile_embed_authority  # noqa: E402

if sys.modules.get("backend.shared.providers.e2b_application_preview") is e2b_preview_stub:
    del sys.modules["backend.shared.providers.e2b_application_preview"]

encode = EmbedService.update_application_embed_thumbnail.__globals__["encode"]
decode = EmbedService.update_application_embed_thumbnail.__globals__["decode"]


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
@pytest.mark.asyncio
@pytest.mark.parametrize("fail_at", [1, 3, None])
async def test_incognito_finished_publication_rechecks_live_socket_before_cache_and_event(
    monkeypatch, fail_at,
):
    assert active_voice_worker_context.get() is None
    checks = []

    async def require_live_incognito_session(nonce, owner_hash):
        checks.append((nonce, owner_hash))
        if fail_at == len(checks):
            raise ValueError("socket_closed")

    monkeypatch.setattr(volatile_embed_authority, "require_live_incognito_session", require_live_incognito_session)
    cache = FakeCacheService({})
    service = EmbedService(cache, directus_service=object(), encryption_service=FakeEncryptionService())
    producer = SimpleNamespace(
        classification="authorized_volatile", intent_kind="incognito",
        session_nonce="nonce-1", owner_hash="a" * 64,
    )
    token = active_verified_output_producer.set(producer)
    try:
        publication = service.send_embed_data_to_client(
            embed_id="embed-1", embed_type="document", content_toon="private document",
            chat_id="chat-1", message_id="message-1", user_id="owner-1",
            user_id_hash="a" * 64, status="finished", check_cache_status=False,
            finished_cache_data={
                "embed_id": "embed-1", "status": "finished",
                "chat_id": "chat-1", "message_id": "message-1",
            },
        )
        if fail_at is None:
            assert await publication is True
            assert len(cache._client.published) == 1
            assert len(checks) == 3
            # Incognito output must not schedule a persistent fallback.
            service._schedule_embed_persistence_fallback("embed-1")
        else:
            with pytest.raises(RequiredRecoveryOutputError, match="no longer live"):
                await publication
            assert cache._client.published == []
            assert len(checks) == fail_at
    finally:
        active_verified_output_producer.reset(token)


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
@pytest.mark.asyncio
async def test_external_volatile_publication_does_not_require_websocket_nonce(monkeypatch):
    assert active_voice_worker_context.get() is None

    async def reject_if_called(*_args):
        raise AssertionError("External REST output has no incognito socket")

    monkeypatch.setattr(volatile_embed_authority, "require_live_incognito_session", reject_if_called)
    cache = FakeCacheService({})
    service = EmbedService(cache, directus_service=object(), encryption_service=FakeEncryptionService())
    token = active_verified_output_producer.set(SimpleNamespace(
        classification="authorized_volatile", intent_kind="external",
        session_nonce=None, owner_hash="a" * 64,
    ))
    try:
        assert await service.send_embed_data_to_client(
            embed_id="embed-1", embed_type="document", content_toon="external document",
            chat_id="chat-1", message_id="message-1", user_id="owner-1",
            user_id_hash="a" * 64, status="finished", check_cache_status=False,
        ) is True
        assert len(cache._client.published) == 1
    finally:
        active_verified_output_producer.reset(token)


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
@pytest.mark.asyncio
async def test_disconnected_incognito_error_cannot_be_reported_as_published(monkeypatch):
    assert active_voice_worker_context.get() is None

    async def disconnected(*_args):
        raise ValueError("socket_closed")

    monkeypatch.setattr(volatile_embed_authority, "require_live_incognito_session", disconnected)
    cache = FakeCacheService({})
    service = EmbedService(cache, directus_service=object(), encryption_service=FakeEncryptionService())
    token = active_verified_output_producer.set(SimpleNamespace(
        classification="authorized_volatile", intent_kind="incognito",
        session_nonce="nonce-1", owner_hash="a" * 64,
    ))
    try:
        with pytest.raises(RequiredRecoveryOutputError, match="no longer live"):
            await service.update_embed_status_to_error(
                embed_id="embed-1", app_id="docs", skill_id="document",
                error_message="local_generation_failed", chat_id="chat-1",
                message_id="message-1", user_id="owner-1",
                user_id_hash="a" * 64, user_vault_key_id="vault-1",
            )
        assert cache._client.published == []
    finally:
        active_verified_output_producer.reset(token)


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
@pytest.mark.asyncio
@pytest.mark.parametrize("classification,intent_kind", [
    ("authorized_direct", "direct_skill"),
    ("authorized_legacy", "legacy_chat"),
])
@pytest.mark.parametrize("revoke_at", [1, 3, None])
async def test_claimed_producer_rechecks_authority_before_cache_and_pubsub(
    monkeypatch, classification, intent_kind, revoke_at,
):
    from backend.core.api.app.services import chat_recovery_service

    calls = []
    task_uuid = "66666666-6666-4666-8666-666666666666"

    class ClaimedRecovery:
        def __init__(self, _directus):
            pass

        async def execute(self, operation, data):
            assert operation == "verify_claimed_output_producer"
            assert data == {
                "protocol_version": 1, "task_uuid": task_uuid,
                "task_name": "apps.docs.tasks.generate_docx_task", "kwargs_binding": "f" * 64,
            }
            calls.append(operation)
            return {
                "producer_intent_id": task_uuid,
                "authorized": revoke_at != len(calls),
                "status": "RUNNING" if revoke_at != len(calls) else "BLOCKED",
                "intent_kind": intent_kind,
            }

    monkeypatch.setattr(chat_recovery_service, "ChatRecoveryService", ClaimedRecovery)
    cache = FakeCacheService({})
    service = EmbedService(cache, directus_service=object(), encryption_service=FakeEncryptionService())
    token = active_verified_output_producer.set(SimpleNamespace(
        classification=classification, intent_kind=intent_kind,
        intent_id=task_uuid, task_id=task_uuid,
        task_name="apps.docs.tasks.generate_docx_task", kwargs_binding="f" * 64,
        owner_hash="a" * 64,
    ))
    try:
        publication = service.send_embed_data_to_client(
            embed_id="embed-1", embed_type="document", content_toon="private document",
            chat_id="chat-1", message_id="message-1", user_id="owner-1",
            user_id_hash="a" * 64, status="finished", check_cache_status=False,
            finished_cache_data={
                "embed_id": "embed-1", "status": "finished",
                "chat_id": "chat-1", "message_id": "message-1",
            },
        )
        if revoke_at is None:
            assert await publication is True
            assert len(cache._client.published) == 1
            assert len(calls) == 3
        else:
            with pytest.raises(RequiredRecoveryOutputError, match="no longer authorized"):
                await publication
            assert cache._client.published == []
            assert len(calls) == revoke_at
            if revoke_at == 1:
                assert ("set", "embed:embed-1") not in cache._client.operations
    finally:
        active_verified_output_producer.reset(token)


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
@pytest.mark.asyncio
async def test_revoked_claimed_producer_cannot_publish_error(monkeypatch):
    from backend.core.api.app.services import chat_recovery_service

    class RevokedRecovery:
        def __init__(self, _directus):
            pass

        async def execute(self, operation, _data):
            assert operation == "verify_claimed_output_producer"
            return {"producer_intent_id": "intent-1", "authorized": False,
                    "reason_code": "producer_not_running"}

    monkeypatch.setattr(chat_recovery_service, "ChatRecoveryService", RevokedRecovery)
    cache = FakeCacheService({})
    service = EmbedService(cache, directus_service=object(), encryption_service=FakeEncryptionService())
    token = active_verified_output_producer.set(SimpleNamespace(
        classification="authorized_direct", intent_kind="direct_skill",
        intent_id="intent-1", task_id="task-1", task_name="apps.docs.tasks.generate_docx_task",
        kwargs_binding="f" * 64, owner_hash="a" * 64,
    ))
    try:
        with pytest.raises(RequiredRecoveryOutputError, match="no longer authorized"):
            await service.send_embed_data_to_client(
                embed_id="embed-1", embed_type="document", content_toon="failed",
                chat_id="chat-1", message_id="message-1", user_id="owner-1",
                user_id_hash="a" * 64, status="error", check_cache_status=False,
            )
        assert cache._client.published == []
    finally:
        active_verified_output_producer.reset(token)


class FakeRedisClient:
    def __init__(self, embed_data: dict):
        self.values = {"embed:embed-1": json.dumps(embed_data)}
        self.published = []
        self.operations = []

    async def get(self, key: str):
        return self.values.get(key)

    async def set(self, key: str, value: str, ex: int | None = None, nx: bool = False):
        if nx and key in self.values:
            return False
        self.values[key] = value
        self.operations.append(("set", key))
        return True

    async def eval(self, _script: str, _key_count: int, key: str, token: str):
        if self.values.get(key) == token:
            del self.values[key]
            return 1
        return 0

    async def sadd(self, key: str, value: str):
        return 1

    async def expire(self, key: str, ttl: int):
        return True

    async def publish(self, channel: str, message: str):
        self.published.append((channel, json.loads(message)))
        self.operations.append(("publish", channel))
        return 1


class FakeCacheService:
    def __init__(self, embed_data: dict):
        self._client = FakeRedisClient(embed_data)

    @property
    async def client(self):
        return self._client

    async def cache_required_ai_embed(self, user_id, chat_id, embed_id, encrypted_json, *, payload_ttl, index_ttl):
        await self._client.set(f"embed:{embed_id}", encrypted_json, ex=payload_ttl)
        return True

    async def mark_ai_context_pending_persistence(self, user_id, chat_id):
        return True

    async def add_pending_embed(self, user_id, embed_id):
        return True


class FakeEncryptionService:
    async def encrypt_with_user_key(self, content: str, vault_key_id: str):
        return content, "test-key-version"

    async def decrypt_with_user_key(self, encrypted_content: str, vault_key_id: str):
        return encrypted_content


# contract-test: supporting surface=rest_api assertions=storage.versions.bounded-reconstruction
@pytest.mark.asyncio
async def test_first_finished_code_update_includes_v1_client_snapshot():
    initial_toon = encode({"type": "code", "language": "python", "filename": "main.py",
                           "code": "", "status": "processing"})
    cache = FakeCacheService({
        "embed_id": "embed-1", "encrypted_content": initial_toon,
        "status": "processing", "message_id": "message-1",
        "created_at": 1760000000, "updated_at": 1760000000,
    })
    service = EmbedService(cache, directus_service=object(), encryption_service=FakeEncryptionService())
    service._schedule_embed_persistence_fallback = lambda embed_id: None

    ok = await service.update_code_embed_content(
        embed_id="embed-1", code_content="print('ready')", chat_id="chat-1",
        user_id="user-1", user_id_hash="user-hash", user_vault_key_id="vault-1",
        status="finished",
    )

    assert ok is True
    payload = cache._client.published[0][1]["payload"]
    assert payload["version_history_rows"] == [{
        "embed_id": "embed-1", "version_number": 1,
        "snapshot": "print('ready')", "created_at": payload["updatedAt"],
    }]


# contract-test: supporting surface=rest_api assertions=storage.versions.bounded-reconstruction
@pytest.mark.asyncio
async def test_followup_edit_does_not_reencrypt_canonical_v1_snapshot():
    initial_toon = encode({"type": "code", "language": "python", "filename": "main.py",
                           "code": "print('old')", "status": "finished"})
    cache = FakeCacheService({
        "embed_id": "embed-1", "encrypted_content": initial_toon,
        "status": "finished", "version_number": 1,
        "message_id": "message-1", "created_at": 1760000000,
    })

    class Directus:
        async def get_items(self, collection, params, **kwargs):
            assert collection == "embed_diffs"
            assert params["filter[version_number][_eq]"] == 1
            assert kwargs["raise_on_error"] is True
            return [{"id": "canonical-v1"}]

    service = EmbedService(cache, directus_service=Directus(), encryption_service=FakeEncryptionService())
    service._schedule_embed_persistence_fallback = lambda embed_id: None
    rows = [
        {"embed_id": "embed-1", "version_number": 1, "snapshot": "print('old')", "created_at": 1},
        {"embed_id": "embed-1", "version_number": 2, "patch": "new", "created_at": 2},
    ]
    ok = await service.update_code_embed_content(
        embed_id="embed-1", code_content="print('new')", chat_id="chat-1",
        user_id="user-1", user_id_hash="user-hash", user_vault_key_id="vault-1",
        status="finished", version_number=2, version_history_rows=rows,
    )
    assert ok is True
    assert cache._client.published[0][1]["payload"]["version_history_rows"] == [rows[1]]


# contract-test: supporting surface=rest_api assertions=app-skills.execution.registered-validated
@pytest.mark.parametrize("transcription_status,transcript", [("complete", ""), ("complete", "Hello"), ("failed", None)])
def test_audio_llm_context_preserves_local_transcription_authority(transcription_status, transcript):
    service = EmbedService(FakeCacheService({}), directus_service=object(), encryption_service=FakeEncryptionService())
    filtered_toon, embed_ref = service._filter_toon_for_llm(encode({
        "type": "audio-recording", "filename": "voice.m4a", "status": "finished",
        "transcript": transcript, "transcription_source": "local",
        "transcription_status": transcription_status,
        "aes_key": "synthetic-key", "s3_base_url": "https://storage.invalid",
        "vault_wrapped_aes_key": "synthetic-wrapper", "files": {"original": {"s3_key": "synthetic-key"}},
    }), "audio-embed-1")
    filtered = decode(filtered_toon)
    assert embed_ref == "voice.m4a"
    assert filtered["transcript"] == transcript
    assert filtered["transcription_source"] == "local"
    assert filtered["transcription_status"] == transcription_status
    assert not {"aes_key", "s3_base_url", "vault_wrapped_aes_key", "files"} & filtered.keys()


# contract-test: supporting surface=rest_api assertions=code-run.artifacts.chat-bound-versioned,chats.message.identity-idempotent
@pytest.mark.asyncio
async def test_versioned_finished_code_update_publishes_same_embed_snapshot():
    initial_toon = encode(
        {
            "type": "code",
            "language": "python",
            "filename": "main.py",
            "code": "def old():\n    return 1",
            "embed_ref": "main.py",
            "status": "finished",
        }
    )
    cache = FakeCacheService(
        {
            "embed_id": "embed-1",
            "encrypted_content": initial_toon,
            "status": "finished",
            "message_id": "message-1",
            "hashed_task_id": "task-hash",
            "is_private": False,
            "is_shared": False,
            "created_at": 1760000000,
            "updated_at": 1760000000,
        }
    )
    service = EmbedService(cache, directus_service=object(), encryption_service=FakeEncryptionService())
    service._schedule_embed_persistence_fallback = lambda embed_id: None

    ok = await service.update_code_embed_content(
        embed_id="embed-1",
        code_content="def old() -> int:\n    return 2",
        chat_id="chat-1",
        user_id="user-1",
        user_id_hash="user-hash",
        user_vault_key_id="vault-1",
        status="finished",
        version_number=2,
        content_hash="content-hash-v2",
    )

    assert ok is True
    assert len(cache._client.published) == 1
    channel, message = cache._client.published[0]
    payload = message["payload"]
    assert channel == "websocket:user:user-hash"
    assert payload["embed_id"] == "embed-1"
    assert payload["version_number"] == 2
    assert payload["content_hash"] == "content-hash-v2"
    assert "def old() -> int" in payload["content"]

    cached_after = json.loads(cache._client.values["embed:embed-1"])
    assert cached_after["version_number"] == 2
    assert cached_after["content_hash"] == "content-hash-v2"


# contract-test: supporting surface=rest_api assertions=code-run.artifacts.chat-bound-versioned,code-run.artifacts.encrypted-indexed,chats.message.identity-idempotent
@pytest.mark.asyncio
async def test_application_thumbnail_update_publishes_versioned_finished_parent():
    initial_toon = encode(
        {
            "type": "application",
            "app_id": "code",
            "skill_id": "application",
            "name": "Counter",
            "framework": "svelte",
            "runtime": "node",
            "file_refs": [{"path": "src/App.svelte", "embed_id": "file-1"}],
            "entrypoints": [{"name": "frontend", "command": "npm run dev", "port": 5173}],
            "embed_ids": ["file-1"],
            "status": "finished",
            "version_number": 1,
        }
    )
    cache = FakeCacheService(
        {
            "embed_id": "embed-1",
            "type": "application",
            "encrypted_content": initial_toon,
            "status": "finished",
            "message_id": "message-1",
            "version_number": 1,
            "is_private": False,
            "is_shared": False,
            "created_at": 1760000000,
            "updated_at": 1760000000,
        }
    )
    service = EmbedService(cache, directus_service=object(), encryption_service=FakeEncryptionService())
    service._schedule_embed_persistence_fallback = lambda embed_id: None

    ok = await service.update_application_embed_thumbnail(
        embed_id="embed-1",
        screenshot_metadata={
            "asset_id": "embed-1",
            "variant": "preview",
            "files": {"preview": {"s3_key": "user/preview.png", "mime_type": "image/png"}},
            "s3_base_url": "https://chatfiles.example.invalid",
            "aes_key": "base64-key",
            "aes_nonce": "base64-nonce",
            "vault_wrapped_aes_key": "vault-only-key",
            "captured_at": "2026-08-31T17:00:00+00:00",
            "download_url": "https://api.example.invalid/expiring-owner-url",
        },
        chat_id="chat-1",
        user_id="user-1",
        user_id_hash="user-hash",
        user_vault_key_id="vault-1",
    )

    assert ok is True
    assert len(cache._client.published) == 1
    channel, message = cache._client.published[0]
    payload = message["payload"]
    content = decode(payload["content"])
    assert channel == "websocket:user:user-hash"
    assert payload["embed_id"] == "embed-1"
    assert payload["type"] == "application"
    assert payload["version_number"] == 2
    assert content["version_number"] == 2
    assert content["latest_screenshot"]["files"]["preview"]["s3_key"] == "user/preview.png"
    assert content["latest_screenshot"]["aes_key"] == "base64-key"
    assert "vault_wrapped_aes_key" not in content["latest_screenshot"]
    assert "download_url" not in content["latest_screenshot"]
    assert "latest_screenshot_url" not in content

    cached_after = json.loads(cache._client.values["embed:embed-1"])
    assert cached_after["version_number"] == 2
    assert "lock:embed:embed-1:application-thumbnail" not in cache._client.values


# contract-test: supporting surface=rest_api assertions=code-run.artifacts.chat-bound-versioned,chats.message.identity-idempotent
@pytest.mark.asyncio
async def test_application_parent_is_cached_before_plaintext_publish():
    cache = FakeCacheService({})
    service = EmbedService(cache, directus_service=object(), encryption_service=FakeEncryptionService())
    service._schedule_embed_persistence_fallback = lambda embed_id: None

    result = await service.create_application_embed(
        name="Counter",
        framework="svelte",
        runtime="node",
        file_refs=[{"path": "src/App.svelte", "embed_id": "file-1"}],
        entrypoints=[{"name": "frontend", "command": "npm run dev", "port": 5173}],
        chat_id="chat-1",
        message_id="message-1",
        user_id="user-1",
        user_id_hash="user-hash",
        user_vault_key_id="vault-1",
        task_id="task-1",
    )

    assert result and result["embed_id"]
    embed_cache_key = f"embed:{result['embed_id']}"
    assert cache._client.operations.index(("set", embed_cache_key)) < cache._client.operations.index(
        ("publish", "websocket:user:user-hash")
    )


# contract-test: infrastructure
@pytest.mark.asyncio
async def test_embed_cache_budget_refusal_stops_publication():
    cache = FakeCacheService({})
    async def refuse(*args, **kwargs):
        return False
    cache.cache_required_ai_embed = refuse
    service = EmbedService(cache, directus_service=object(), encryption_service=FakeEncryptionService())
    service._schedule_embed_persistence_fallback = lambda embed_id: None

    result = await service.create_application_embed(
        name="Counter", framework="svelte", runtime="node",
        file_refs=[{"path": "src/App.svelte", "embed_id": "file-1"}],
        entrypoints=[{"name": "frontend", "command": "npm run dev", "port": 5173}],
        chat_id="chat-1", message_id="message-1", user_id="user-1",
        user_id_hash="user-hash", user_vault_key_id="vault-1", task_id="task-1",
    )
    assert result is None
    assert not cache._client.published
    assert not any(key.startswith("embed:") and key != "embed:embed-1" for key in cache._client.values)


# contract-test: infrastructure
@pytest.mark.asyncio
async def test_real_cache_admission_refusal_stops_application_embed(monkeypatch):
    from backend.tests.test_ai_working_cache_budget import Cache

    monkeypatch.setenv("AI_REQUIRED_EMBED_MAX_BYTES", "1")
    cache = Cache()
    service = EmbedService(cache, directus_service=object(), encryption_service=FakeEncryptionService())
    service._schedule_embed_persistence_fallback = lambda embed_id: None

    result = await service.create_application_embed(
        name="Counter", framework="svelte", runtime="node",
        file_refs=[{"path": "src/App.svelte", "embed_id": "file-1"}],
        entrypoints=[{"name": "frontend", "command": "npm run dev", "port": 5173}],
        chat_id="chat-1", message_id="message-1", user_id="user-1",
        user_id_hash="user-hash", user_vault_key_id="vault-1", task_id="task-1",
    )
    assert result is None
    assert not any(key.startswith("embed:") for key in cache.redis.strings)


# contract-test: supporting surface=rest_api assertions=code-run.artifacts.chat-bound-versioned,chats.message.identity-idempotent
@pytest.mark.asyncio
async def test_application_thumbnail_update_rejects_stale_capture():
    initial_toon = encode(
        {
            "type": "application",
            "app_id": "code",
            "skill_id": "application",
            "name": "Counter",
            "status": "finished",
            "version_number": 2,
            "latest_screenshot": {
                "asset_id": "embed-1",
                "variant": "preview",
                "files": {"preview": {"s3_key": "user/newer.png"}},
                "s3_base_url": "https://chatfiles.example.invalid",
                "aes_key": "base64-key",
                "aes_nonce": "",
                "captured_at": "2026-08-31T17:05:00+00:00",
            },
        }
    )
    cache = FakeCacheService(
        {
            "embed_id": "embed-1",
            "type": "application",
            "encrypted_content": initial_toon,
            "status": "finished",
            "message_id": "message-1",
            "version_number": 2,
            "is_private": False,
            "is_shared": False,
        }
    )
    service = EmbedService(cache, directus_service=object(), encryption_service=FakeEncryptionService())
    service._schedule_embed_persistence_fallback = lambda embed_id: None

    ok = await service.update_application_embed_thumbnail(
        embed_id="embed-1",
        screenshot_metadata={
            "asset_id": "embed-1",
            "variant": "preview",
            "files": {"preview": {"s3_key": "user/older.png", "mime_type": "image/png"}},
            "s3_base_url": "https://chatfiles.example.invalid",
            "aes_key": "base64-key",
            "aes_nonce": "",
            "captured_at": "2026-08-31T17:00:00+00:00",
        },
        chat_id="chat-1",
        user_id="user-1",
        user_id_hash="user-hash",
        user_vault_key_id="vault-1",
    )

    assert ok is False
    assert cache._client.published == []
    cached_after = json.loads(cache._client.values["embed:embed-1"])
    content_after = decode(cached_after["encrypted_content"])
    assert cached_after["version_number"] == 2
    assert cached_after["encrypted_content"] == initial_toon
    assert content_after["latest_screenshot"]["files"]["preview"]["s3_key"] == "user/newer.png"


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery,code-run.artifacts.encrypted-indexed
@pytest.mark.asyncio
@pytest.mark.parametrize("save_fails", [False, True])
async def test_finished_embed_and_diff_save_before_publish_or_pause(monkeypatch, save_fails):
    from backend.core.api.app.services import chat_recovery_service

    root_id = "22222222-2222-4222-8222-222222222222"
    child_id = "99999999-9999-4999-8999-999999999999"
    _, public_key = derive_recovery_keypair(
        "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8", root_id, 1,
    )
    context = RecoveryOutputContext(
        owner_id="11111111-1111-4111-8111-111111111111", owner_hash="a" * 64,
        root_chat_id=root_id, target_chat_id=child_id,
        turn_id="33333333-3333-4333-8333-333333333333",
        preflight_id="77777777-7777-4777-8777-777777777777",
        inference_task_id="66666666-6666-4666-8666-666666666666",
        public_key=public_key, key_version=1,
    )
    order = []

    class RecoveryService:
        def __init__(self, _directus):
            pass

        @staticmethod
        def content_commitment(content):
            import hashlib
            return hashlib.sha256(content).hexdigest()

        async def execute(self, operation, data):
            assert operation == "get_replay_output"
            return {"status": "ABSENT"}

        async def save_sealed_output(self, data, *, s3_service=None):
            assert s3_service is None
            assert "private embed body" not in data["sealed_payload"]
            order.append(("save", data["output_kind"]))
            if save_fails:
                raise RuntimeError("unavailable durable store")
            return {"record_id": data["record_id"]}

    monkeypatch.setattr(chat_recovery_service, "ChatRecoveryService", RecoveryService)
    cache = FakeCacheService({})
    original_publish = cache._client.publish

    async def publish(channel, message):
        order.append(("publish", channel))
        return await original_publish(channel, message)

    cache._client.publish = publish
    class UnlinkedDirectus:
        async def get_items(self, collection, *, params, admin_required, no_cache):
            assert collection == "project_items"
            assert params["filter[item_type][_eq]"] == "embed"
            return []

    service = EmbedService(cache, directus_service=UnlinkedDirectus(), encryption_service=FakeEncryptionService())

    async def track_pending(*_args):
        return None

    service._track_pending_embed = track_pending
    token = active_recovery_output_context.set(context)
    try:
        coro = service.send_embed_data_to_client(
            embed_id="88888888-8888-4888-8888-888888888888", embed_type="code",
            content_toon="private embed body", chat_id=child_id,
            message_id="assistant-1", user_id=context.owner_id,
            user_id_hash=context.owner_hash, status="finished", version_number=2,
            version_history_rows=[{"embed_id": "88888888-8888-4888-8888-888888888888",
                                   "version_number": 2, "patch": "private patch"}],
            check_cache_status=False,
        )
        if save_fails:
            with pytest.raises(RequiredRecoveryOutputError):
                await coro
            assert cache._client.published == []
            assert order == [("save", "embed")]
        else:
            assert await coro is True
            assert [step[0] for step in order] == ["save", "save", "publish"]
            assert [step[1] for step in order[:2]] == ["embed", "diff"]
    finally:
        active_recovery_output_context.reset(token)


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
@pytest.mark.asyncio
async def test_registered_embed_reuses_durable_receipt_and_rejects_changed_retry(monkeypatch):
    from backend.core.api.app.services import chat_recovery_service

    owner = "11111111-1111-4111-8111-111111111111"
    root = "22222222-2222-4222-8222-222222222222"
    chat = "99999999-9999-4999-8999-999999999999"
    embed = "88888888-8888-4888-8888-888888888888"
    intent = "66666666-6666-4666-8666-666666666666"
    _, public_key = derive_recovery_keypair(
        "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8", root, 1,
    )
    context = RecoveryOutputContext(
        owner_id=owner, owner_hash="a" * 64, root_chat_id=root, target_chat_id=chat,
        turn_id="33333333-3333-4333-8333-333333333333",
        preflight_id="77777777-7777-4777-8777-777777777777",
        inference_task_id=intent, public_key=public_key, key_version=1,
    )
    producer = VerifiedOutputProducer(
        classification="registered_ai", intent_id=intent, task_id=intent,
        task_name="apps.docs.tasks.generate", kwargs_binding="f" * 64,
        primary_embed_id=embed, primary_message_id="message-1", target_chat_id=chat,
        owner_hash="a" * 64, hashed_team_id="b" * 64,
    )
    order = []
    stored_commitment = None
    fail_save = False
    revoked_team = False
    fail_publish = False

    class RecoveryService:
        def __init__(self, _directus):
            pass

        @staticmethod
        def content_commitment(content):
            import hashlib
            return hashlib.sha256(content).hexdigest()

        async def execute(self, operation, data):
            nonlocal revoked_team
            if revoked_team:
                raise RuntimeError("team role revoked")
            order.append(operation)
            if operation == "get_producer_output":
                if stored_commitment is None:
                    return {"status": "ABSENT"}
                if data["content_commitment"] != stored_commitment:
                    raise RuntimeError("changed result")
                return {"status": "PENDING", "record_id": "original-record"}
            if operation == "close_output_producer":
                assert data["expected_children"] == []
                return {"status": "PENDING"}
            raise AssertionError(operation)

        async def save_sealed_output(self, data, *, s3_service=None):
            nonlocal stored_commitment
            order.append("save")
            if fail_save:
                raise RuntimeError("durable store unavailable")
            stored_commitment = data["content_commitment"]
            return {"record_id": data["record_id"]}

    monkeypatch.setattr(chat_recovery_service, "ChatRecoveryService", RecoveryService)

    class Directus:
        async def get_items(self, collection, *, params, admin_required, no_cache):
            assert collection == "project_items"
            return []

    cache = FakeCacheService({})
    publish = cache._client.publish
    cache_write = cache.cache_required_ai_embed

    async def observed_cache(*args, **kwargs):
        order.append("cache")
        return await cache_write(*args, **kwargs)

    cache.cache_required_ai_embed = observed_cache

    async def observed_publish(channel, message):
        order.append("publish")
        if fail_publish:
            raise RuntimeError("pubsub unavailable")
        return await publish(channel, message)

    cache._client.publish = observed_publish
    service = EmbedService(cache, Directus(), FakeEncryptionService())
    owner_token = active_recovery_output_context.set(context)
    producer_token = active_verified_output_producer.set(producer)
    try:
        async def send(content="original body", user=owner):
            return await service.send_embed_data_to_client(
                embed_id=embed, embed_type="document", content_toon=content,
                chat_id=chat, message_id="message-1", user_id=user,
                user_id_hash="a" * 64, status="finished", check_cache_status=True,
                producer_final_children=[], created_at=1, updated_at=1,
                finished_cache_data={"embed_id": embed, "status": "finished", "encrypted_content": "vault"},
                finished_cache_vault_key_id="vault-key",
            )

        fail_save = True
        with pytest.raises(RequiredRecoveryOutputError):
            await send()
        assert "publish" not in order and "close_output_producer" not in order

        fail_save = False
        order.clear()
        assert await send() is True
        assert order == ["get_producer_output", "save", "close_output_producer", "cache", "publish"]

        order.clear()
        assert await send() is True  # Lost client ACK: same durable receipt, no reseal.
        assert order == ["get_producer_output", "close_output_producer", "cache", "publish"]

        fail_publish = True
        order.clear()
        with pytest.raises(RequiredRecoveryOutputError):
            await send()
        assert "save" not in order
        assert json.loads(cache._client.values[f"embed:{embed}"])["status"] == "finished"
        fail_publish = False

        order.clear()
        with pytest.raises(RequiredRecoveryOutputError):
            await send("changed body")
        assert "publish" not in order

        order.clear()
        with pytest.raises(RequiredRecoveryOutputError):
            await send(user="other-user")
        assert order == []

        revoked_team = True
        with pytest.raises(RequiredRecoveryOutputError):
            await send()
        assert "publish" not in order
    finally:
        active_verified_output_producer.reset(producer_token)
        active_recovery_output_context.reset(owner_token)


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
@pytest.mark.asyncio
async def test_required_finished_code_save_failure_cannot_mark_cache_finished():
    cache = FakeCacheService({
        "embed_id": "embed-1", "encrypted_content": encode({
            "type": "code", "language": "python", "filename": "main.py", "code": "",
        }),
        "status": "processing", "message_id": "message-1", "created_at": 1,
    })
    service = EmbedService(cache, directus_service=object(), encryption_service=FakeEncryptionService())

    async def reject_finished(*args, **kwargs):
        assert kwargs["status"] == "finished"
        assert json.loads(cache._client.values["embed:embed-1"])["status"] == "processing"
        raise RequiredRecoveryOutputError("sealing failed")

    service.send_embed_data_to_client = reject_finished
    with pytest.raises(RequiredRecoveryOutputError):
        await service.update_code_embed_content(
            embed_id="embed-1", code_content="print('private')", chat_id="chat-1",
            user_id="user-1", user_id_hash="user-hash", user_vault_key_id="vault-1",
            status="finished",
        )
    assert json.loads(cache._client.values["embed:embed-1"])["status"] == "processing"


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
@pytest.mark.asyncio
async def test_registered_media_retry_checks_durable_receipt_before_provider(monkeypatch):
    from backend.core.api.app.services import chat_recovery_service

    task_id = "66666666-6666-4666-8666-666666666666"
    embed_id = "88888888-8888-4888-8888-888888888888"
    producer = VerifiedOutputProducer(
        classification="registered_ai", intent_id=task_id, task_id=task_id,
        task_name="apps.images.tasks.skill_generate", kwargs_binding="f" * 64,
        primary_embed_id=embed_id, primary_message_id="message-1", target_chat_id="chat-1",
        owner_hash="a" * 64,
    )
    probe_fails = False
    class RecoveryService:
        def __init__(self, _directus):
            pass

        async def execute(self, operation, data):
            assert operation == "get_producer_output" and data["ordinal"] == 0
            if probe_fails:
                raise RuntimeError("storage unavailable")
            return {"status": "PENDING"}

    monkeypatch.setattr(chat_recovery_service, "ChatRecoveryService", RecoveryService)
    token = active_verified_output_producer.set(producer)
    try:
        with pytest.raises(RequiredRecoveryOutputError):
            await EmbedService.assert_registered_output_can_generate(
                object(), embed_id=embed_id, chat_id="chat-1", message_id="message-1",
                owner_hash="a" * 64,
            )
        with pytest.raises(RequiredRecoveryOutputError):
            await EmbedService.assert_registered_output_can_generate(
                object(), embed_id=embed_id, chat_id="other-chat", message_id="message-1",
                owner_hash="a" * 64,
            )
        probe_fails = True
        with pytest.raises(RequiredRecoveryOutputError):
            await EmbedService.assert_registered_output_can_generate(
                object(), embed_id=embed_id, chat_id="chat-1", message_id="message-1",
                owner_hash="a" * 64,
            )
    finally:
        active_verified_output_producer.reset(token)


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
@pytest.mark.asyncio
async def test_authorized_remotion_rerender_requires_canonical_version_and_emits_next_version(monkeypatch):
    import hashlib
    from backend.core.api.app.services import chat_recovery_service

    class ClaimedRecovery:
        def __init__(self, _directus):
            pass

        async def execute(self, operation, data):
            assert operation == "verify_claimed_output_producer"
            assert data["task_uuid"] == "66666666-6666-4666-8666-666666666666"
            return {
                "producer_intent_id": data["task_uuid"], "authorized": True,
                "status": "RUNNING", "intent_kind": "rerender",
            }

    monkeypatch.setattr(chat_recovery_service, "ChatRecoveryService", ClaimedRecovery)

    chat_id = "22222222-2222-4222-8222-222222222222"
    owner_hash = hashlib.sha256(b"user-1").hexdigest()
    embed_id = "88888888-8888-4888-8888-888888888888"
    cache = FakeCacheService({
        "embed_id": embed_id, "encrypted_content": encode({
            "type": "video_create", "filename": "Composition.tsx", "status": "finished",
        }),
        "status": "finished", "message_id": "message-1", "created_at": 1,
        "version_number": 1,
    })
    cache._client.values[f"embed:{embed_id}"] = cache._client.values.pop("embed:embed-1")

    class Directus:
        version = 1

        async def get_items(self, collection, *, params, admin_required, no_cache, raise_on_error):
            assert collection == "embeds" and raise_on_error is True
            assert params["filter[hashed_user_id][_eq]"] == owner_hash
            return [{
                "id": "db-row", "version_number": self.version,
                "hashed_chat_id": hashlib.sha256(chat_id.encode()).hexdigest(),
            }]

    directus = Directus()
    service = EmbedService(cache, directus, FakeEncryptionService())
    service._schedule_embed_persistence_fallback = lambda _embed_id: None
    producer = VerifiedOutputProducer(
        classification="authorized_direct", intent_id="66666666-6666-4666-8666-666666666666",
        task_id="66666666-6666-4666-8666-666666666666", task_name="apps.videos.tasks.render_remotion",
        kwargs_binding="f" * 64, primary_embed_id=embed_id, primary_message_id="message-1",
        target_chat_id=chat_id, owner_hash=owner_hash, intent_kind="rerender",
        expected_embed_version=1,
    )
    token = active_verified_output_producer.set(producer)
    try:
        ok = await service.update_remotion_video_embed_content(
            embed_id=embed_id, remotion_source="export default function Main() {}",
            chat_id=chat_id, message_id="message-1", user_id="user-1",
            user_id_hash=owner_hash, user_vault_key_id="vault-1", status="finished",
            final_producer_output=True,
        )
        assert ok is True
        assert cache._client.published[-1][1]["payload"]["version_number"] == 2
        assert json.loads(cache._client.values[f"embed:{embed_id}"])["version_number"] == 2

        directus.version = 2
        with pytest.raises(RequiredRecoveryOutputError):
            await service.update_remotion_video_embed_content(
                embed_id=embed_id, remotion_source="changed source", chat_id=chat_id,
                message_id="message-1", user_id="user-1", user_id_hash=owner_hash,
                user_vault_key_id="vault-1", status="finished", final_producer_output=True,
            )
        assert len(cache._client.published) == 1
    finally:
        active_verified_output_producer.reset(token)


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
@pytest.mark.asyncio
async def test_main_context_retry_uses_existing_record_before_randomized_seal(monkeypatch):
    from backend.core.api.app.services import chat_recovery_service
    from backend.shared.python_utils import chat_completion_recovery_job

    owner = "11111111-1111-4111-8111-111111111111"
    root = "22222222-2222-4222-8222-222222222222"
    chat = "99999999-9999-4999-8999-999999999999"
    _, public_key = derive_recovery_keypair(
        "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8", root, 1,
    )
    context = RecoveryOutputContext(
        owner_id=owner, owner_hash="a" * 64, root_chat_id=root, target_chat_id=chat,
        turn_id="33333333-3333-4333-8333-333333333333",
        preflight_id="77777777-7777-4777-8777-777777777777",
        inference_task_id="66666666-6666-4666-8666-666666666666",
        public_key=public_key, key_version=1,
    )

    class RecoveryService:
        def __init__(self, _directus):
            pass

        @staticmethod
        def content_commitment(content):
            import hashlib
            return hashlib.sha256(content).hexdigest()

        async def execute(self, operation, data):
            assert operation == "get_replay_output"
            assert data["preflight_id"] == context.preflight_id
            return {"status": "PENDING", "record_id": data["record_id"]}

    monkeypatch.setattr(chat_recovery_service, "ChatRecoveryService", RecoveryService)
    monkeypatch.setattr(chat_completion_recovery_job, "build_sealed_recovery_output_data",
                        lambda **_kwargs: pytest.fail("identical retry resealed ciphertext"))

    class Directus:
        async def get_items(self, collection, *, params, admin_required, no_cache):
            return []

    cache = FakeCacheService({})
    service = EmbedService(cache, Directus(), FakeEncryptionService())
    token = active_recovery_output_context.set(context)
    try:
        assert await service.send_embed_data_to_client(
            embed_id="88888888-8888-4888-8888-888888888888", embed_type="code",
            content_toon="same private body", chat_id=chat, message_id="message-1",
            user_id=owner, user_id_hash="a" * 64, status="finished",
            check_cache_status=False, created_at=1, updated_at=1,
        ) is True
        assert len(cache._client.published) == 1
    finally:
        active_recovery_output_context.reset(token)


class _CompositeRecoveryDirectus:
    base_url = "http://cms:8055"

    def __init__(self):
        self.rows = {}
        self.calls = []
        self.order = []
        self.memberships = []
        self.classifications = 0
        self.fail_save = False

    async def get_items(self, collection, *, params, admin_required, no_cache):
        assert collection == "project_items" and admin_required and no_cache
        assert params["filter[item_type][_eq]"] == "embed"
        self.classifications += 1
        return self.memberships

    async def _make_api_request(self, method, url, **kwargs):
        from backend.tests.test_chat_recovery_service import FakeResponse
        assert method == "POST" and url.endswith("/chat-recovery-transaction")
        body = kwargs["json"]
        op = body["operation"]
        self.calls.append(body)
        self.order.append(op)
        outputs = body["data"]["outputs"]
        if op == "get_replay_outputs":
            receipts = []
            for output in outputs:
                existing = self.rows.get(output["record_id"])
                if existing and existing["content_commitment"] != output["content_commitment"]:
                    return FakeResponse(409, {"error": {"code": "replay_output_mismatch"}})
                receipts.append({"record_id": output["record_id"],
                                 "status": "PENDING" if existing else "ABSENT"})
        elif op == "create_sealed_outputs":
            if self.fail_save:
                return FakeResponse(503, {"error": {"code": "storage_unavailable"}})
            self.rows.update({output["record_id"]: dict(output) for output in outputs})
            receipts = [{"record_id": output["record_id"], "state": "PENDING"} for output in outputs]
        else:
            raise AssertionError(op)
        return FakeResponse(200, {"data": {"outputs": receipts}})


def _ordinary_composite_fixture(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "bounded-composite-test-secret")
    chat = "22222222-2222-4222-8222-222222222222"
    _, public_key = derive_recovery_keypair("AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8", chat, 1)
    context = RecoveryOutputContext(
        owner_id="11111111-1111-4111-8111-111111111111", owner_hash="a" * 64,
        root_chat_id=chat, target_chat_id=chat,
        turn_id="33333333-3333-4333-8333-333333333333",
        preflight_id="77777777-7777-4777-8777-777777777777",
        inference_task_id="66666666-6666-4666-8666-666666666666",
        public_key=public_key, key_version=1,
    )
    directus = _CompositeRecoveryDirectus()
    cache = FakeCacheService({"embed_id": "embed-1", "status": "processing",
                              "encrypted_content": encode({"query": "AI events in Berlin"})})
    service = EmbedService(cache, directus, FakeEncryptionService())
    service._schedule_embed_persistence_fallback = lambda _embed: None
    publish = cache._client.publish

    async def observed_publish(channel, message):
        directus.order.append("publish")
        return await publish(channel, message)

    cache._client.publish = observed_publish
    return service, cache, directus, context


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery,chats.persistence.client-encrypted
@pytest.mark.asyncio
@pytest.mark.parametrize("app_id,skill_id,create", [
    ("events", "search", False), ("web", "search", False),
    ("news", "search", True), ("travel", "search_connections", True),
])
async def test_composite_recovery_batches_children_and_parent_before_ordered_publication(
    monkeypatch, app_id, skill_id, create,
):
    service, cache, directus, context = _ordinary_composite_fixture(monkeypatch)
    async def child_type(*_args, **_kwargs):
        return "event"
    monkeypatch.setattr(EmbedService, "get_composite_child_embed_type", child_type)
    results = [{"title": f"Private event {i}", "embed_ref": f"event-{i}"} for i in range(10)]
    token = active_recovery_output_context.set(context)
    try:
        args = dict(app_id=app_id, skill_id=skill_id, results=results, chat_id=context.target_chat_id,
                    message_id="message-1", user_id=context.owner_id, user_id_hash=context.owner_hash,
                    user_vault_key_id="vault-key", request_metadata={"query": "AI events in Berlin"})
        if create:
            result = await service.create_embeds_from_skill_results(**args)
            parent = result["parent_embed_id"]
        else:
            result = await service.update_embed_with_results(embed_id="embed-1", **args)
            parent = result["embed_id"]
        assert len(result["child_embed_ids"]) == 10
        assert [call["operation"] for call in directus.calls] == ["get_replay_outputs", "create_sealed_outputs"]
        assert directus.classifications == 1 and len(directus.rows) == 11
        assert directus.order[:2] == ["get_replay_outputs", "create_sealed_outputs"]
        assert directus.order[2:] == ["publish"] * 11
        published = [event["payload"] for _, event in cache._client.published]
        assert [event["embed_id"] for event in published] == [*result["child_embed_ids"], parent]
        assert all(event["parent_embed_id"] == parent for event in published[:-1])
        assert [decode(event["content"])["embed_ref"] for event in published[:-1]] == [f"event-{i}" for i in range(10)]
        assert published[-1]["embed_ids"] == result["child_embed_ids"]
        assert "Private event" not in json.dumps(directus.calls)
        assert all(f"embed:{embed}" in cache._client.values for embed in [parent, *result["child_embed_ids"]])
    finally:
        active_recovery_output_context.reset(token)


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["save", "project", "unknown_project"])
async def test_composite_batch_failure_cannot_cache_or_publish_finished_results(monkeypatch, failure):
    service, cache, directus, context = _ordinary_composite_fixture(monkeypatch)
    directus.fail_save = failure == "save"
    directus.memberships = [{"id": "project-owned"}] if failure == "project" else None if failure == "unknown_project" else []
    async def child_type(*_args, **_kwargs):
        return "event"
    monkeypatch.setattr(EmbedService, "get_composite_child_embed_type", child_type)
    token = active_recovery_output_context.set(context)
    try:
        with pytest.raises(RequiredRecoveryOutputError):
            await service.update_embed_with_results(
                embed_id="embed-1", app_id="events", skill_id="search",
                results=[{"title": f"Event {i}"} for i in range(10)],
                chat_id=context.target_chat_id, message_id="message-1", user_id=context.owner_id,
                user_id_hash=context.owner_hash, user_vault_key_id="vault-key",
            )
        assert cache._client.published == [] and directus.rows == {}
        assert list(cache._client.values) == ["embed:embed-1"]
        assert json.loads(cache._client.values["embed:embed-1"])["status"] == "processing"
    finally:
        active_recovery_output_context.reset(token)
    # A failed task must not leave a collector active in this coroutine.
    assert service.send_embed_data_to_client.__globals__["_pending_finished_embed_batch"].get() is None


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery
@pytest.mark.asyncio
async def test_composite_batch_retry_reuses_first_seal_before_randomized_sealing(monkeypatch):
    service, cache, directus, context = _ordinary_composite_fixture(monkeypatch)
    payload = {"payload": {"embed_id": "stable-embed", "chat_id": context.target_chat_id,
                           "message_id": "message-1", "user_id": context.owner_id,
                           "content": "original private result", "createdAt": 1}}
    token = active_recovery_output_context.set(context)
    try:
        await service._save_completed_embed_recovery_batch([payload])
        first = {key: dict(value) for key, value in directus.rows.items()}
        from backend.shared.python_utils import chat_completion_recovery_job
        def reject_sealing(**_kwargs):
            raise AssertionError("same-result retry must reuse its original sealed receipt")
        monkeypatch.setattr(chat_completion_recovery_job, "build_sealed_recovery_output_data", reject_sealing)
        await service._save_completed_embed_recovery_batch([payload])
        assert directus.rows == first
        assert [call["operation"] for call in directus.calls] == [
            "get_replay_outputs", "create_sealed_outputs", "get_replay_outputs",
        ]
        changed = {"payload": {**payload["payload"], "content": "different result"}}
        with pytest.raises(Exception, match="replay_output_mismatch"):
            await service._save_completed_embed_recovery_batch([changed])
    finally:
        active_recovery_output_context.reset(token)


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery,chats.message.identity-idempotent
@pytest.mark.asyncio
@pytest.mark.parametrize("provided_refs", [False, True])
async def test_composite_reexecution_cannot_replace_sealed_parent_with_new_child_ids(monkeypatch, provided_refs):
    service, cache, directus, context = _ordinary_composite_fixture(monkeypatch)
    async def child_type(*_args, **_kwargs):
        return "event"
    monkeypatch.setattr(EmbedService, "get_composite_child_embed_type", child_type)
    publish = cache._client.publish
    fail_publish = True
    async def disconnected(channel, message):
        if fail_publish:
            raise RuntimeError("disconnected")
        return await publish(channel, message)
    cache._client.publish = disconnected
    args = dict(embed_id="embed-1", app_id="events", skill_id="search",
                results=[{"title": f"Event {i}", **({"embed_ref": f"event-{i}"} if provided_refs else {})} for i in range(10)],
                chat_id=context.target_chat_id, message_id="message-1", user_id=context.owner_id,
                user_id_hash=context.owner_hash, user_vault_key_id="vault-key")
    token = active_recovery_output_context.set(context)
    try:
        with pytest.raises(RequiredRecoveryOutputError):
            await service.update_embed_with_results(**args)
        assert len(directus.rows) == 11 and cache._client.published == []
        first = {key: dict(value) for key, value in directus.rows.items()}
        fail_publish = False
        # Reexecuting the builder allocates new ordinary child identities; it
        # must not pretend that their changed parent references are a replay.
        with pytest.raises(RequiredRecoveryOutputError, match="Composite embed recovery save or delivery failed"):
            await service.update_embed_with_results(**args)
        assert cache._client.published == []
        assert directus.rows == first
        assert [call["operation"] for call in directus.calls] == [
            "get_replay_outputs", "create_sealed_outputs", "get_replay_outputs",
        ]
    finally:
        active_recovery_output_context.reset(token)


# contract-test: supporting surface=rest_api assertions=storage.background.complete-sealed-recovery,projects.files.concurrent-chat-safety
def test_ordinary_child_ids_do_not_enter_the_registered_or_project_uuid5_namespace(monkeypatch):
    import uuid
    from backend.core.api.app.services.embed_version_transaction_service import is_hosted_project_embed_id

    _service, _cache, _directus, context = _ordinary_composite_fixture(monkeypatch)
    parent = "22222222-2222-4222-8222-222222222222"
    context_token = active_recovery_output_context.set(context)
    producer_token = active_verified_output_producer.set(None)
    try:
        ordinary = [EmbedService._registered_child_embed_id(parent, index) for index in range(10)]
        assert len(set(ordinary)) == 10
        assert all(uuid.UUID(child).version == 4 and not is_hosted_project_embed_id(child) for child in ordinary)
        intent = "33333333-3333-4333-8333-333333333333"
        producer = VerifiedOutputProducer(
            classification="registered_ai", intent_id=intent, task_id=intent,
            task_name="apps.images.tasks.generate", kwargs_binding="f" * 64,
            primary_embed_id=parent, primary_message_id="message-1", target_chat_id=context.target_chat_id,
            owner_hash=context.owner_hash, hashed_team_id=None,
        )
        active_verified_output_producer.set(producer)
        child = EmbedService._registered_child_embed_id(parent, 1)
        assert uuid.UUID(child).version == 5
        assert child == str(uuid.uuid5(uuid.UUID(intent), "embed-child:1"))
        assert EmbedService._registered_child_embed_id(parent, 1) == child
        with pytest.raises(RequiredRecoveryOutputError, match="registered producer intent"):
            EmbedService._registered_child_embed_id(parent, 32)
        with pytest.raises(RequiredRecoveryOutputError, match="registered producer intent"):
            EmbedService._registered_child_embed_id("other-parent", 1)
    finally:
        active_verified_output_producer.reset(producer_token)
        active_recovery_output_context.reset(context_token)
