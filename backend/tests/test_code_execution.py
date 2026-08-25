# backend/tests/test_code_execution.py
#
# Regression tests for the web-app Code Run collector.
# Code Run must use server-readable Redis/Vault cache for recent chats, while
# Directus remains client-encrypted storage and is never decrypted with Vault.
# Older chats can retry with code decrypted on the authenticated client.

# contract-test-file: infrastructure

# ruff: noqa: E402

from __future__ import annotations

import hashlib
import base64
import importlib.machinery
import importlib.util
import json
import re
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

def _find_spec_or_none(name: str):
    try:
        return importlib.util.find_spec(name)
    except ValueError:
        return None


if _find_spec_or_none("toon_format") is None:
    toon_format_stub = types.ModuleType("toon_format")
    toon_format_stub.__spec__ = importlib.machinery.ModuleSpec("toon_format", loader=None)

    def _stub_encode(value: dict) -> str:
        return "\n".join(f"{key}: {item}" for key, item in value.items())

    def _stub_decode(value: str) -> dict:
        decoded: dict[str, str] = {}
        for line in value.splitlines():
            key, _, item = line.partition(": ")
            if key:
                decoded[key] = item
        return decoded

    toon_format_stub.encode = _stub_encode
    toon_format_stub.decode = _stub_decode
    sys.modules.setdefault("toon_format", toon_format_stub)

if _find_spec_or_none("celery") is None:
    tasks_stub = types.ModuleType("backend.core.api.app.tasks")
    tasks_stub.__path__ = [str(Path(__file__).resolve().parents[1] / "core/api/app/tasks")]
    celery_config_stub = types.ModuleType("backend.core.api.app.tasks.celery_config")

    class _CeleryAppStub:
        def send_task(self, *_args, **_kwargs):
            return None

        def task(self, *_args, **_kwargs):
            return lambda func: func

    async def _missing_worker_cache_service():
        raise AssertionError("worker cache service is not used by these unit tests")

    celery_config_stub.app = _CeleryAppStub()
    celery_config_stub.get_worker_cache_service = _missing_worker_cache_service
    sys.modules.setdefault("backend.core.api.app.tasks", tasks_stub)
    sys.modules.setdefault("backend.core.api.app.tasks.celery_config", celery_config_stub)

if _find_spec_or_none("redis") is None:
    redis_stub = types.ModuleType("redis")
    redis_asyncio_stub = types.ModuleType("redis.asyncio")
    redis_stub.__spec__ = importlib.machinery.ModuleSpec("redis", loader=None)
    redis_asyncio_stub.__spec__ = importlib.machinery.ModuleSpec("redis.asyncio", loader=None)

    class _RedisStub:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("real Redis is not used by these unit tests")

    redis_asyncio_stub.Redis = _RedisStub
    redis_stub.asyncio = redis_asyncio_stub
    redis_stub.exceptions = SimpleNamespace(
        ConnectionError=ConnectionError,
        TimeoutError=TimeoutError,
        RedisError=Exception,
    )
    sys.modules.setdefault("redis", redis_stub)
    sys.modules.setdefault("redis.asyncio", redis_asyncio_stub)

if _find_spec_or_none("aiohttp") is None:
    aiohttp_stub = types.ModuleType("aiohttp")
    aiohttp_stub.ClientSession = object
    sys.modules.setdefault("aiohttp", aiohttp_stub)
sys.modules.setdefault("regex", re)
googleapiclient_stub = types.ModuleType("googleapiclient")
googleapiclient_discovery_stub = types.ModuleType("googleapiclient.discovery")
googleapiclient_errors_stub = types.ModuleType("googleapiclient.errors")
googleapiclient_discovery_stub.build = lambda *_args, **_kwargs: None
googleapiclient_errors_stub.HttpError = Exception
sys.modules.setdefault("googleapiclient", googleapiclient_stub)
sys.modules.setdefault("googleapiclient.discovery", googleapiclient_discovery_stub)
sys.modules.setdefault("googleapiclient.errors", googleapiclient_errors_stub)

slowapi_stub = types.ModuleType("slowapi")
slowapi_util_stub = types.ModuleType("slowapi.util")


class _LimiterStub:
    def __init__(self, *_args, **_kwargs):
        pass

    def limit(self, *_args, **_kwargs):
        return lambda func: func


slowapi_stub.Limiter = _LimiterStub
slowapi_util_stub.get_remote_address = lambda request: "127.0.0.1"
sys.modules.setdefault("slowapi", slowapi_stub)
sys.modules.setdefault("slowapi.util", slowapi_util_stub)
from toon_format import encode

from backend.apps.code.tasks.run_code_task import RUN_CREDITS_PER_MINUTE as TASK_RUN_CREDITS_PER_MINUTE
from backend.apps.code.tasks import run_code_task as code_run_task
from backend.apps.code.tasks.run_code_task import _charge_run_credits
from backend.apps.code.tasks.run_code_task import _safe_artifact_metadata
from backend.core.api.app.routes.code_execution import (
    CLIENT_CONTENT_REQUIRED_CODE,
    CodeRunClientAttachment,
    CodeRunDependencyInstall as ApiCodeRunDependencyInstall,
    CodeRunClientFile,
    RUN_CREDITS_PER_MINUTE as ROUTE_RUN_CREDITS_PER_MINUTE,
    _collect_code_files,
    _dependency_installs_from_imports,
    _dependency_installs_from_install_snippets,
    _execution_key,
    _infer_import_packages,
    _looks_like_secret,
    _merge_dependency_installs,
    _safe_filename,
    _validate_dependency_manifest,
    cancel_code_run,
    stream_code_run_status,
)
from backend.core.api.app.routes.handlers.websocket_handlers.code_run_output_handlers import (
    _impl_upsert,
    code_run_output_cache_key,
)
from backend.core.api.app.services.embed_service import EmbedService


CHAT_ID = "chat-1"
TARGET_EMBED_ID = "embed-target"
USER_ID = "user-1"
USER_HASH = hashlib.sha256(USER_ID.encode()).hexdigest()
CHAT_HASH = hashlib.sha256(CHAT_ID.encode()).hexdigest()
MESSAGE_ID = "message-1"


class FakeRedis:
    def __init__(self, embeds: dict[str, dict]):
        self.embeds = embeds
        self.values: dict[str, bytes] = {}

    async def get(self, key: str):
        if key in self.values:
            return self.values[key]
        embed_id = key.removeprefix("embed:")
        embed = self.embeds.get(embed_id)
        return json.dumps(embed).encode() if embed else None

    async def set(self, key: str, value: str, ex: int | None = None):
        self.values[key] = value.encode()


class FakeCache:
    def __init__(self, embed_ids: list[str], embeds: dict[str, dict]):
        self.embed_ids = embed_ids
        self.embeds = embeds
        self.redis = FakeRedis(embeds)

    @property
    def client(self):
        async def _client():
            return self.redis

        return _client()

    async def get_chat_embed_ids(self, chat_id: str) -> list[str]:
        return self.embed_ids if chat_id == CHAT_ID else []

    async def get_embed_from_cache(self, embed_id: str):
        return self.embeds.get(embed_id)

    async def publish_event(self, channel: str, payload: dict):
        return None


class FakeCodeRunStreamCache:
    def __init__(self, execution_id: str):
        self.execution_id = execution_id
        self.redis = FakeRedis({})
        self.redis.values[_execution_key(execution_id)] = json.dumps({
            "execution_id": execution_id,
            "user_id_hash": USER_HASH,
            "status": "running",
            "events": [],
        }).encode()

    @property
    def client(self):
        async def _client():
            return self.redis

        return _client()

    async def subscribe_to_channel(self, _channel: str):
        finished = {
            "execution_id": self.execution_id,
            "user_id_hash": USER_HASH,
            "status": "finished",
            "events": [
                {"kind": "stdout", "text": "Hello, World!\n", "timestamp": 1.0},
                {"kind": "status", "text": "Exited with code 0\n", "timestamp": 2.0},
            ],
        }
        self.redis.values[_execution_key(self.execution_id)] = json.dumps(finished).encode()
        yield {"data": {"type": "code_run_update", "payload": {"status": "finished"}}}


class FakeCodeRunWebSocket:
    def __init__(self, cache_service: FakeCodeRunStreamCache):
        self.app = SimpleNamespace(state=SimpleNamespace(cache_service=cache_service))
        self.sent: list[dict] = []
        self.accepted = False

    async def accept(self):
        self.accepted = True

    async def send_json(self, payload: dict):
        self.sent.append(payload)

    async def close(self, **_kwargs):
        return None


# contract-test: direct surface=rest_api assertions=code-run.execution.stream-status-visible
@pytest.mark.asyncio
async def test_code_run_stream_sends_authoritative_terminal_snapshot():
    execution_id = "execution-fast"
    cache = FakeCodeRunStreamCache(execution_id)
    websocket = FakeCodeRunWebSocket(cache)

    await stream_code_run_status(websocket, execution_id, {"user_id": USER_ID})

    assert websocket.accepted is True
    assert [message["type"] for message in websocket.sent] == [
        "code_run_snapshot",
        "code_run_update",
        "code_run_snapshot",
    ]
    final_snapshot = websocket.sent[-1]["payload"]
    assert final_snapshot["status"] == "finished"
    assert [event["text"] for event in final_snapshot["events"]] == [
        "Hello, World!\n",
        "Exited with code 0\n",
    ]


class FakeDirectusEmbed:
    def __init__(self, embeds: dict[str, dict]):
        self.embeds = embeds

    async def get_embed_by_id(self, embed_id: str):
        return self.embeds.get(embed_id)


class FakeDirectus:
    def __init__(self, embeds: dict[str, dict]):
        self.embed = FakeDirectusEmbed(embeds)


class FakeCodeRunDirectusChat:
    async def check_chat_ownership(self, chat_id: str, user_id: str) -> bool:
        return chat_id == CHAT_ID and user_id == USER_ID

    async def get_chat_metadata(self, chat_id: str):
        return {"id": chat_id}


class FakeCodeRunDirectus(FakeDirectus):
    def __init__(self, embeds: dict[str, dict]):
        super().__init__(embeds)
        self.chat = FakeCodeRunDirectusChat()
        self.items: dict[str, dict] = {}

    async def get_items(self, collection: str, params: dict, admin_required: bool = False):
        return []

    async def create_item(self, collection: str, row: dict, admin_required: bool = False):
        self.items[row["id"]] = row
        return row

    async def update_item(self, collection: str, item_id: str, row: dict):
        self.items[item_id] = {**self.items.get(item_id, {}), **row}
        return self.items[item_id]


class FakeManager:
    def __init__(self):
        self.personal_messages: list[dict] = []
        self.broadcasts: list[dict] = []

    async def send_personal_message(self, message: dict, user_id: str, device_fingerprint_hash: str):
        self.personal_messages.append(message)

    async def broadcast_to_user(self, message: dict, user_id: str, exclude_device_hash: str | None = None):
        self.broadcasts.append(message)


class FakeEncryption:
    async def encrypt_with_user_key(self, plaintext: str, key_id: str):
        return f"vault:{plaintext}", None

    async def decrypt_with_user_key(self, ciphertext: str, key_id: str):
        if ciphertext.startswith("vault:"):
            return ciphertext.removeprefix("vault:")
        raise AssertionError("Code Run must not try to Vault-decrypt Directus client ciphertext")


def _user():
    return SimpleNamespace(id=USER_ID, vault_key_id="vault-key")


def _metadata(encrypted_content: str = "client-ciphertext") -> dict:
    return {
        "embed_id": TARGET_EMBED_ID,
        "hashed_user_id": USER_HASH,
        "hashed_chat_id": CHAT_HASH,
        "encrypted_content": encrypted_content,
        "encryption_mode": "client",
        "message_id": MESSAGE_ID,
        "status": "finished",
    }


def test_code_run_artifact_status_metadata_strips_sensitive_fields() -> None:
    artifacts = _safe_artifact_metadata([
        {
            "path": "outputs/chart.png",
            "normalized_path": "outputs/chart.png",
            "mime_type": "image/png",
            "kind": "image",
            "size_bytes": 4,
            "content_base64": "ZGF0YQ==",
            "download_url": "https://api.dev.openmates.org/v1/generated-assets/id/files/original/download?token=secret",
            "token": "secret",
            "s3_key": "user/private.png",
            "aes_key": "secret",
            "aes_nonce": "secret",
            "vault_wrapped_aes_key": "secret",
            "sandbox_id": "sandbox-1",
        }
    ])

    assert artifacts == [
        {
            "path": "outputs/chart.png",
            "normalized_path": "outputs/chart.png",
            "mime_type": "image/png",
            "kind": "image",
            "size_bytes": 4,
            "status": "captured",
        }
    ]


# contract-test: direct surface=rest_api assertions=code-run.artifacts.encrypted-indexed,code-run.artifacts.child-renderer-routing
@pytest.mark.anyio
async def test_persist_code_run_artifacts_encrypts_indexes_and_returns_download_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    plaintext = b"name,value\nAlice,1\n"
    uploads: list[dict[str, object]] = []
    indexed: list[dict[str, object]] = []
    cached: list[dict[str, object]] = []
    s3_initialize_modes: list[bool] = []

    class FakeEncryptionService:
        def __init__(self, **_kwargs):
            pass

        async def initialize(self):
            return None

        async def encrypt_with_user_key(self, plaintext_key: str, vault_key_id: str):
            assert plaintext_key
            assert vault_key_id == "vault-key"
            return "wrapped-aes-key", None

    class FakeDirectusService:
        def __init__(self, **_kwargs):
            pass

        async def get_user_fields_direct(self, user_id: str, fields: list[str]):
            assert user_id == USER_ID
            assert fields == ["vault_key_id", "storage_used_bytes"]
            return {"vault_key_id": "vault-key", "storage_used_bytes": 0}

    class FakeS3Service:
        environment = "development"
        base_domain = "nbg1.your-objectstorage.com"

        def __init__(self, **_kwargs):
            pass

        async def initialize(self, *, configure_buckets: bool = True):
            s3_initialize_modes.append(configure_buckets)
            return None

        async def upload_file(self, **kwargs):
            uploads.append(kwargs)
            return {"url": "s3://stored"}

        async def delete_file(self, **kwargs):
            uploads.append({"deleted": kwargs})
            return True

    async def fake_index_generated_asset(_task, **kwargs):
        indexed.append(kwargs)
        return True

    async def fake_cache_s3_file_keys(_task, **kwargs):
        cached.append(kwargs)

    def fake_encrypt_media_variants(plaintext_by_variant, *, write_version: int):
        assert write_version == 2
        return SimpleNamespace(
            aes_key_b64="fake-aes-key",
            payloads={variant: b"encrypted:" + content for variant, content in plaintext_by_variant.items()},
            metadata={variant: {"encryption": "test"} for variant in plaintext_by_variant},
            legacy_nonce_b64=None,
        )

    monkeypatch.setattr(code_run_task, "EncryptionService", FakeEncryptionService)
    monkeypatch.setattr(code_run_task, "DirectusService", FakeDirectusService)
    monkeypatch.setattr(code_run_task, "S3UploadService", FakeS3Service)
    monkeypatch.setattr(code_run_task, "get_bucket_name", lambda _bucket, _environment=None: "dev-openmates-chatfiles")
    monkeypatch.setattr(code_run_task, "index_generated_asset", fake_index_generated_asset)
    monkeypatch.setattr(code_run_task, "cache_s3_file_keys", fake_cache_s3_file_keys)
    monkeypatch.setattr(code_run_task, "encrypt_media_variants", fake_encrypt_media_variants)
    monkeypatch.setattr(code_run_task, "load_media_write_version", lambda: 2)
    monkeypatch.setattr(code_run_task, "create_download_token", lambda **_kwargs: "signed-token")
    monkeypatch.setattr(code_run_task, "build_download_url", lambda **kwargs: f"{kwargs['base_url']}/download/{kwargs['asset_id']}/{kwargs['variant']}?token={kwargs['token']}")

    stored = await code_run_task._persist_code_run_artifacts(
        execution_id="execution-1",
        payload={"user_id": USER_ID, "chat_id": None, "target_embed_id": None, "target_path": "main.py"},
        artifacts=[{
            "path": "outputs/report.csv",
            "normalized_path": "outputs/report.csv",
            "mime_type": "text/csv",
            "kind": "data",
            "size_bytes": len(plaintext),
            "content_base64": base64.b64encode(plaintext).decode("ascii"),
        }],
        secrets_manager=object(),
        cache_service=FakeCache([], {}),
        now=2_030.0,
    )

    assert uploads and uploads[0]["content"] != plaintext
    assert uploads[0]["content_type"] == "application/octet-stream"
    assert indexed and indexed[0]["embed_id"] == "execution-1"
    variant_name = stored[0]["variant"]
    files_metadata = indexed[0]["files_metadata"]
    assert files_metadata[variant_name]["normalized_path"] == "outputs/report.csv"
    assert files_metadata[variant_name]["mime_type"] == "text/csv"
    assert files_metadata[variant_name]["s3_key"].endswith("_report.csv")
    assert indexed[0]["media_type"] == "code_run"
    assert indexed[0]["provenance_metadata"]["mode"] == "direct"
    assert cached and cached[0]["embed_id"] == "execution-1"
    assert stored == [
        {
            "path": "outputs/report.csv",
            "normalized_path": "outputs/report.csv",
            "mime_type": "text/csv",
            "kind": "data",
            "size_bytes": len(plaintext),
            "status": "captured",
            "asset_id": "execution-1",
            "variant": variant_name,
            "download_url": f"https://api.dev.openmates.org/download/execution-1/{variant_name}?token=signed-token",
            "download_expires_at": 2_930,
        }
    ]
    assert "content_base64" not in stored[0]
    assert "s3_key" not in stored[0]
    assert "token" not in stored[0]

    chat_bound = await code_run_task._persist_code_run_artifacts(
        execution_id="execution-2",
        payload={"user_id": USER_ID, "chat_id": "chat-1", "target_embed_id": TARGET_EMBED_ID, "target_path": "main.py"},
        artifacts=[{
            "path": "outputs/chart.png",
            "normalized_path": "outputs/chart.png",
            "mime_type": "image/png",
            "kind": "image",
            "size_bytes": len(plaintext),
            "content_base64": base64.b64encode(plaintext).decode("ascii"),
        }],
        secrets_manager=object(),
        cache_service=FakeCache([], {}),
        now=2_040.0,
    )

    assert "native_render_payload" not in stored[0]
    assert s3_initialize_modes == [False, False]
    assert chat_bound[0]["native_render_payload"] == {
        "app_id": "images",
        "frontend_type": "image",
        "content": {
            "filename": "chart.png",
            "s3_base_url": "https://dev-openmates-chatfiles.nbg1.your-objectstorage.com",
            "files": {
                "full": chat_bound[0]["native_render_payload"]["content"]["files"]["full"],
                "original": chat_bound[0]["native_render_payload"]["content"]["files"]["original"],
            },
            "aes_key": "fake-aes-key",
            "aes_nonce": "",
            "file_size": len(plaintext),
            "file_type": "image/png",
            "is_authenticated": True,
        },
    }
    assert chat_bound[0]["native_render_payload"]["content"]["files"]["full"]["s3_key"].endswith("_chart.png")
    assert chat_bound[0]["native_render_payload"]["content"]["files"]["full"]["encryption"] == "test"


def test_run_code_execution_stores_artifacts_without_provider_internals(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeClient:
        def __init__(self):
            self.values: dict[str, bytes] = {}
            self.removed: list[tuple[str, str]] = []

        async def get(self, key: str):
            return self.values.get(key)

        async def set(self, key: str, value: str, ex: int | None = None):
            self.values[key] = value.encode("utf-8")

        async def srem(self, key: str, value: str):
            self.removed.append((key, value))

    class FakeWorkerCache:
        def __init__(self):
            self.client_instance = FakeClient()
            self.published: list[dict[str, object]] = []

        @property
        def client(self):
            async def _client():
                return self.client_instance

            return _client()

        async def publish_event(self, channel: str, payload: dict):
            self.published.append({"channel": channel, "payload": payload})

    class FakeSecretsManager:
        async def initialize(self):
            return None

        async def aclose(self):
            return None

    fake_cache = FakeWorkerCache()
    raw_artifact = {
        "path": "outputs/chart.png",
        "normalized_path": "outputs/chart.png",
        "mime_type": "image/png",
        "kind": "image",
        "size_bytes": 4,
        "content_base64": "ZGF0YQ==",
        "sandbox_id": "sandbox-1",
    }
    persisted_artifact = {
        "path": "outputs/chart.png",
        "normalized_path": "outputs/chart.png",
        "mime_type": "image/png",
        "kind": "image",
        "size_bytes": 4,
        "status": "captured",
        "asset_id": "execution-1",
        "variant": "outputs-chart-png",
        "download_url": "https://api.dev.openmates.org/download/execution-1/outputs-chart-png?token=signed",
        "download_expires_at": 999,
    }

    async def fake_get_worker_cache_service():
        return fake_cache

    async def fake_get_e2b_api_key_async(_secrets_manager):
        return "e2b-key"

    def fake_run_code_in_e2b(*_args, **_kwargs):
        return SimpleNamespace(
            exit_code=0,
            duration_seconds=1.2,
            output_truncated=False,
            sandbox_id="sandbox-1",
            artifacts=[raw_artifact],
            skipped_artifacts=[{"path": "outputs/.env", "reason": "hidden_or_secret_path"}],
        )

    async def fake_charge_run_credits(*_args, **_kwargs):
        return 5

    async def fake_persist_code_run_artifacts(**kwargs):
        assert kwargs["artifacts"] == [raw_artifact]
        return [persisted_artifact]

    continuations: list[dict[str, object]] = []

    async def fake_dispatch_code_run_async_continuation(**kwargs):
        continuations.append(kwargs)

    monkeypatch.setattr(code_run_task, "get_worker_cache_service", fake_get_worker_cache_service)
    monkeypatch.setattr(code_run_task, "SecretsManager", FakeSecretsManager)
    monkeypatch.setattr(code_run_task, "get_e2b_api_key_async", fake_get_e2b_api_key_async)
    monkeypatch.setattr(code_run_task, "run_code_in_e2b", fake_run_code_in_e2b)
    monkeypatch.setattr(code_run_task, "_charge_run_credits", fake_charge_run_credits)
    monkeypatch.setattr(code_run_task, "_persist_code_run_artifacts", fake_persist_code_run_artifacts)
    monkeypatch.setattr(code_run_task, "_dispatch_code_run_async_continuation", fake_dispatch_code_run_async_continuation)

    code_run_task._run_code_execution(
        "execution-1",
        {
            "user_id": USER_ID,
            "user_id_hash": USER_HASH,
            "chat_id": None,
            "message_id": None,
            "target_embed_id": None,
            "target_path": "main.py",
            "enable_internet": True,
            "files": [{"path": "main.py", "content": "print('ok')", "language": "python", "is_target": True}],
            "dependency_installs": [],
            "active_run_key": "active-runs",
            "active_run_owner": "execution-1",
            "provider_active_run_key": "provider-runs",
            "provider_active_run_owner": "execution-1",
            "assistant_async_task": True,
        },
    )

    stored = json.loads(fake_cache.client_instance.values["code_run_execution:execution-1"].decode("utf-8"))
    assert stored["status"] == "finished"
    assert stored["artifacts"] == [persisted_artifact]
    assert stored["skipped_artifacts"] == [{"path": "outputs/.env", "reason": "hidden_or_secret_path"}]
    assert "sandbox_id" not in stored
    assert "content_base64" not in json.dumps(stored)
    assert fake_cache.client_instance.removed == [("active-runs", "execution-1"), ("provider-runs", "execution-1")]
    assert continuations
    assert continuations[0]["async_task_id"] == "execution-1"
    completed = continuations[0]["completed_results"][0]
    assert completed["status"] == "finished"
    assert completed["artifacts"] == [
        {
            "path": "outputs/chart.png",
            "normalized_path": "outputs/chart.png",
            "mime_type": "image/png",
            "kind": "image",
            "size_bytes": 4,
            "status": "captured",
            "asset_id": "execution-1",
            "variant": "outputs-chart-png",
            "download_expires_at": 999,
        }
    ]
    assert "download_url" not in json.dumps(completed)


@pytest.mark.anyio
async def test_collect_code_files_uses_vault_encrypted_recent_cache() -> None:
    toon = encode({"type": "code", "code": "print('ok')", "language": "python", "filename": "main.py"})
    cached = _metadata(encrypted_content=f"vault:{toon}")

    files, target_path = await _collect_code_files(
        CHAT_ID,
        TARGET_EMBED_ID,
        [],
        [],
        None,
        _user(),
        FakeCache([TARGET_EMBED_ID], {TARGET_EMBED_ID: cached}),
        FakeDirectus({}),
        FakeEncryption(),
    )

    assert target_path == "main.py"
    assert files == [{"path": "main.py", "content": "print('ok')", "language": "python", "is_target": True}]


@pytest.mark.anyio
async def test_code_run_output_upsert_caches_vault_encrypted_inference_payload() -> None:
    cache = FakeCache([TARGET_EMBED_ID], {})
    manager = FakeManager()

    await _impl_upsert(
        manager,
        cache,
        FakeCodeRunDirectus({}),
        FakeEncryption(),
        USER_ID,
        "vault-key",
        "device-1",
        {
            "chat_id": CHAT_ID,
            "embed_id": TARGET_EMBED_ID,
            "id": "output-1",
            "key_version": 1,
            "encrypted_payload": "client-ciphertext",
            "inference_payload": {
                "output": "hello from code\n",
                "status": "exited",
                "files": ["main.py"],
                "saved_at": 123,
                "created_at": 120,
                "updated_at": 123,
            },
            "created_at": 120,
            "updated_at": 123,
        },
    )

    client = await cache.client
    cached = json.loads((await client.get(code_run_output_cache_key(USER_HASH, CHAT_HASH, TARGET_EMBED_ID))).decode())
    decrypted = await FakeEncryption().decrypt_with_user_key(cached["encrypted_content"], "vault-key")

    assert '"type": "code_run_output"' in decrypted or "type: code_run_output" in decrypted
    assert "hello from code" in decrypted
    assert manager.broadcasts[0]["type"] == "code_run_output_synced"


@pytest.mark.anyio
async def test_code_run_output_upsert_rejects_unknown_embed() -> None:
    cache = FakeCache([], {})
    manager = FakeManager()

    await _impl_upsert(
        manager,
        cache,
        FakeCodeRunDirectus({}),
        FakeEncryption(),
        USER_ID,
        "vault-key",
        "device-1",
        {
            "chat_id": CHAT_ID,
            "embed_id": TARGET_EMBED_ID,
            "id": "output-1",
            "encrypted_payload": "client-ciphertext",
            "created_at": 120,
            "updated_at": 123,
        },
    )

    assert manager.broadcasts == []
    assert manager.personal_messages[0]["payload"]["message"] == "Code Run output does not belong to this chat."


@pytest.mark.anyio
async def test_code_run_output_upsert_rejects_unowned_chat() -> None:
    cache = FakeCache([TARGET_EMBED_ID], {})
    manager = FakeManager()

    await _impl_upsert(
        manager,
        cache,
        FakeCodeRunDirectus({}),
        FakeEncryption(),
        USER_ID,
        "vault-key",
        "device-1",
        {
            "chat_id": "missing-chat",
            "embed_id": TARGET_EMBED_ID,
            "id": "output-1",
            "encrypted_payload": "client-ciphertext",
            "created_at": 120,
            "updated_at": 123,
        },
    )

    assert manager.broadcasts == []
    assert manager.personal_messages[0]["payload"]["message"] == "You do not have permission to sync this Code Run output."


@pytest.mark.anyio
async def test_resolve_code_embed_references_appends_cached_code_run_output() -> None:
    code_toon = encode({"type": "code", "code": "print('ok')", "language": "python", "filename": "main.py"})
    output_toon = encode({"type": "code_run_output", "status": "exited", "output": "ok\n", "files": ["main.py"], "saved_at": 123})
    cache = FakeCache([TARGET_EMBED_ID], {TARGET_EMBED_ID: _metadata(encrypted_content=f"vault:{code_toon}")})
    client = await cache.client
    await client.set(
        code_run_output_cache_key(USER_HASH, CHAT_HASH, TARGET_EMBED_ID),
        json.dumps({"encrypted_content": f"vault:{output_toon}", "chat_id": CHAT_ID, "embed_id": TARGET_EMBED_ID}),
    )
    service = EmbedService(cache, FakeDirectus({}), FakeEncryption())

    resolved, _ = await service.resolve_embed_references_in_content(
        f'```json\n{{"type":"code","embed_id":"{TARGET_EMBED_ID}"}}\n```',
        "vault-key",
    )

    assert '"type": "code"' in resolved or "type: code" in resolved
    assert '"type": "code_run_output"' in resolved or "type: code_run_output" in resolved
    assert "ok" in resolved


@pytest.mark.anyio
async def test_resolve_code_embed_references_accepts_json_embed_fence() -> None:
    code_toon = encode({"type": "code", "code": "print('ok')", "language": "python", "filename": "main.py"})
    cache = FakeCache([TARGET_EMBED_ID], {TARGET_EMBED_ID: _metadata(encrypted_content=f"vault:{code_toon}")})
    service = EmbedService(cache, FakeDirectus({}), FakeEncryption())

    resolved, file_path_index = await service.resolve_embed_references_in_content(
        f'```json_embed\n{{"type":"code","embed_id":"{TARGET_EMBED_ID}"}}\n```',
        "vault-key",
    )

    assert '"type": "code"' in resolved or "type: code" in resolved
    assert '"embed_ref": "main.py' in resolved or "embed_ref: main.py" in resolved
    assert list(file_path_index.values()) == [TARGET_EMBED_ID]
    assert next(iter(file_path_index)) in resolved


@pytest.mark.anyio
async def test_collect_code_files_requests_client_content_for_directus_only_embed() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await _collect_code_files(
            CHAT_ID,
            TARGET_EMBED_ID,
            [],
            [],
            None,
            _user(),
            FakeCache([], {}),
            FakeDirectus({TARGET_EMBED_ID: _metadata()}),
            FakeEncryption(),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == CLIENT_CONTENT_REQUIRED_CODE


@pytest.mark.anyio
async def test_collect_code_files_accepts_validated_client_fallback() -> None:
    files, target_path = await _collect_code_files(
        CHAT_ID,
        TARGET_EMBED_ID,
        [CodeRunClientFile(embed_id=TARGET_EMBED_ID, code="print('client')", language="python", filename="client.py", is_target=True)],
        [],
        None,
        _user(),
        FakeCache([], {}),
        FakeDirectus({TARGET_EMBED_ID: _metadata()}),
        FakeEncryption(),
    )

    assert target_path == "client.py"
    assert files == [{"path": "client.py", "content": "print('client')", "language": "python", "is_target": True}]


@pytest.mark.anyio
async def test_collect_code_files_accepts_target_client_file_when_metadata_is_not_indexed_yet() -> None:
    files, target_path = await _collect_code_files(
        CHAT_ID,
        TARGET_EMBED_ID,
        [CodeRunClientFile(embed_id=TARGET_EMBED_ID, code="print('client')", language="python", filename="client.py", is_target=True)],
        [],
        None,
        _user(),
        FakeCache([], {}),
        FakeDirectus({}),
        FakeEncryption(),
    )

    assert target_path == "client.py"
    assert files == [{"path": "client.py", "content": "print('client')", "language": "python", "is_target": True}]


@pytest.mark.anyio
async def test_collect_code_files_accepts_compiled_language_client_fallback() -> None:
    files, target_path = await _collect_code_files(
        CHAT_ID,
        TARGET_EMBED_ID,
        [CodeRunClientFile(embed_id=TARGET_EMBED_ID, code="fn main() {}", language="rust", is_target=True)],
        [],
        None,
        _user(),
        FakeCache([], {}),
        FakeDirectus({TARGET_EMBED_ID: _metadata()}),
        FakeEncryption(),
    )

    assert target_path == "snippet-embed-ta.rs"
    assert files == [{"path": "snippet-embed-ta.rs", "content": "fn main() {}", "language": "rust", "is_target": True}]


@pytest.mark.anyio
async def test_collect_code_files_rejects_atopile_client_fallback() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await _collect_code_files(
            CHAT_ID,
            TARGET_EMBED_ID,
            [CodeRunClientFile(embed_id=TARGET_EMBED_ID, code="module Board:", language="atopile", filename="board.ato", is_target=True)],
            [],
            None,
            _user(),
            FakeCache([], {}),
            FakeDirectus({TARGET_EMBED_ID: _metadata()}),
            FakeEncryption(),
        )

    assert exc_info.value.status_code == 400


@pytest.mark.parametrize(
    ("language", "expected_filename"),
    [
        ("c", "snippet-embed-ta.c"),
        ("cpp", "snippet-embed-ta.cpp"),
        ("rust", "snippet-embed-ta.rs"),
        ("go", "snippet-embed-ta.go"),
        ("atopile", "snippet-embed-ta.txt"),
    ],
)
def test_safe_filename_defaults_match_code_run_support(language: str, expected_filename: str) -> None:
    assert _safe_filename(None, TARGET_EMBED_ID, language) == expected_filename


@pytest.mark.anyio
async def test_collect_code_files_filters_cached_files_to_selected_embeds() -> None:
    target_toon = encode({"type": "code", "code": "print('target')", "language": "python", "filename": "main.py"})
    helper_toon = encode({"type": "code", "code": "print('helper')", "language": "python", "filename": "helper.py"})
    skipped_toon = encode({"type": "code", "code": "print('skip')", "language": "python", "filename": "skip.py"})
    embeds = {
        TARGET_EMBED_ID: _metadata(encrypted_content=f"vault:{target_toon}"),
        "embed-helper": {**_metadata(encrypted_content=f"vault:{helper_toon}"), "embed_id": "embed-helper"},
        "embed-skip": {**_metadata(encrypted_content=f"vault:{skipped_toon}"), "embed_id": "embed-skip"},
    }

    files, target_path = await _collect_code_files(
        CHAT_ID,
        TARGET_EMBED_ID,
        [],
        [],
        [TARGET_EMBED_ID, "embed-helper"],
        _user(),
        FakeCache([TARGET_EMBED_ID, "embed-helper", "embed-skip"], embeds),
        FakeDirectus({}),
        FakeEncryption(),
    )

    assert target_path == "main.py"
    assert [file["path"] for file in files] == ["main.py", "helper.py"]


@pytest.mark.anyio
async def test_collect_code_files_accepts_selected_client_attachment_fallback() -> None:
    target_toon = encode({"type": "code", "code": "print('target')", "language": "python", "filename": "main.py"})
    attachment_id = "embed-attachment"
    attachment_metadata = {**_metadata(), "embed_id": attachment_id}

    files, target_path = await _collect_code_files(
        CHAT_ID,
        TARGET_EMBED_ID,
        [],
        [
            CodeRunClientAttachment(
                embed_id=attachment_id,
                path="data/input.txt",
                content_base64=base64.b64encode(b"hello").decode("ascii"),
                mime_type="text/plain",
            )
        ],
        [TARGET_EMBED_ID, attachment_id],
        _user(),
        FakeCache([TARGET_EMBED_ID], {TARGET_EMBED_ID: _metadata(encrypted_content=f"vault:{target_toon}")}),
        FakeDirectus({attachment_id: attachment_metadata}),
        FakeEncryption(),
    )

    assert target_path == "main.py"
    assert files[0]["path"] == "main.py"
    assert files[1]["path"] == "inputs/data/input.txt"
    assert base64.b64decode(files[1]["content_base64"]) == b"hello"


def test_code_run_cost_is_five_credits_per_minute() -> None:
    assert ROUTE_RUN_CREDITS_PER_MINUTE == 5
    assert TASK_RUN_CREDITS_PER_MINUTE == 5


def test_dependency_install_request_rejects_shell_values() -> None:
    with pytest.raises(ValueError):
        ApiCodeRunDependencyInstall(ecosystem="python", packages=["requests;curl"])


def test_requirements_manifest_rejects_external_urls() -> None:
    with pytest.raises(HTTPException) as exc_info:
        _validate_dependency_manifest("requirements.txt", "requests\nhttps://example.com/pkg.tar.gz\n")

    assert exc_info.value.status_code == 400


def test_package_json_manifest_rejects_scripts_and_file_deps() -> None:
    with pytest.raises(HTTPException) as exc_info:
        _validate_dependency_manifest(
            "package.json",
            json.dumps({"scripts": {"postinstall": "curl example.com"}, "dependencies": {"left-pad": "^1.3.0"}}),
        )
    assert exc_info.value.status_code == 400

    with pytest.raises(HTTPException) as file_dep_exc:
        _validate_dependency_manifest("package.json", json.dumps({"dependencies": {"left-pad": "file:../left-pad"}}))
    assert file_dep_exc.value.status_code == 400


def test_dependency_manifests_accept_plain_registry_packages() -> None:
    _validate_dependency_manifest("requirements.txt", "requests==2.32.0\npandas>=2.2\n")
    _validate_dependency_manifest("package.json", json.dumps({"dependencies": {"@sveltejs/kit": "^2.0.0", "vite": "latest"}}))


def test_code_run_secret_detection_allows_environment_variable_placeholders() -> None:
    code = """
import os
import requests

api_key = os.getenv("OPENWEATHER_API_KEY")
params = {"q": "Berlin", "appid": api_key, "units": "metric"}
response = requests.get("https://api.openweathermap.org/data/2.5/weather", params=params)
print(response.status_code)
"""

    assert not _looks_like_secret(code)


def test_code_run_secret_detection_blocks_high_confidence_tokens() -> None:
    assert _looks_like_secret("OPENAI_API_KEY='sk-abcdefghijklmnopqrstuvwxyz123456'")
    assert _looks_like_secret("GITHUB_TOKEN='ghp_abcdefghijklmnopqrstuvwxyz123456'")
    assert _looks_like_secret("AWS_ACCESS_KEY_ID='AKIAABCDEFGHIJKLMNOP'")


def test_dependency_installs_from_selected_install_snippets() -> None:
    installs = _dependency_installs_from_install_snippets([
        {"path": "install.sh", "language": "bash", "content": "# deps\npip install requests pandas==2.2.3\n"},
        {"path": "main.py", "language": "python", "content": "import requests\n"},
    ])

    assert [install.model_dump() for install in installs] == [
        {"ecosystem": "python", "packages": ["requests", "pandas==2.2.3"]}
    ]


def test_dependency_installs_ignore_complex_shell_snippets() -> None:
    installs = _dependency_installs_from_install_snippets([
        {"path": "install.sh", "language": "bash", "content": "pip install requests && python main.py\n"},
    ])

    assert installs == []


def test_infer_import_packages_maps_python_imports_and_ignores_stdlib() -> None:
    inferred = _infer_import_packages([
        {
            "path": "main.py",
            "language": "python",
            "content": "import os, json\nimport requests\nfrom sklearn.model_selection import train_test_split\nfrom PIL import Image\n",
        }
    ])

    assert inferred == [
        ("python", "requests", "requests", "main.py"),
        ("python", "sklearn", "scikit-learn", "main.py"),
        ("python", "PIL", "Pillow", "main.py"),
    ]


def test_dependency_installs_from_imports_adds_python_packages_without_manifest() -> None:
    installs = _dependency_installs_from_imports([
        {
            "path": "main.py",
            "language": "python",
            "content": "import os\nimport requests\n",
        }
    ])

    assert [install.model_dump() for install in installs] == [
        {"ecosystem": "python", "packages": ["requests"]}
    ]


def test_dependency_installs_from_imports_skips_when_manifest_exists() -> None:
    installs = _dependency_installs_from_imports([
        {
            "path": "main.py",
            "language": "python",
            "content": "import requests\n",
        },
        {
            "path": "requirements.txt",
            "language": "",
            "content": "requests==2.32.5\n",
        },
    ])

    assert installs == []


def test_infer_import_packages_normalizes_javascript_packages() -> None:
    inferred = _infer_import_packages([
        {
            "path": "main.ts",
            "language": "typescript",
            "content": "import axios from 'axios';\nconst _ = require('lodash/fp');\nimport fs from 'node:fs';\nimport timers from 'timers/promises';\nimport local from './local';\nimport { createClient } from '@supabase/supabase-js';\n",
        }
    ])

    assert inferred == [
        ("npm", "axios", "axios", "main.ts"),
        ("npm", "lodash/fp", "lodash", "main.ts"),
        ("npm", "@supabase/supabase-js", "@supabase/supabase-js", "main.ts"),
    ]


def test_merge_dependency_installs_deduplicates_client_and_snippet_packages() -> None:
    installs = _merge_dependency_installs(
        [ApiCodeRunDependencyInstall(ecosystem="python", packages=["requests"])],
        [ApiCodeRunDependencyInstall(ecosystem="python", packages=["requests", "pandas"])]
    )

    assert [install.model_dump() for install in installs] == [
        {"ecosystem": "python", "packages": ["requests", "pandas"]}
    ]


def test_merge_dependency_installs_prefers_pinned_python_spec_over_inferred_import() -> None:
    installs = _merge_dependency_installs(
        [ApiCodeRunDependencyInstall(ecosystem="python", packages=["numpy==2.5.1"])],
        [ApiCodeRunDependencyInstall(ecosystem="python", packages=["numpy"])],
    )

    assert [install.model_dump() for install in installs] == [
        {"ecosystem": "python", "packages": ["numpy==2.5.1"]}
    ]


def test_merge_dependency_installs_normalizes_python_package_identity() -> None:
    installs = _merge_dependency_installs(
        [ApiCodeRunDependencyInstall(ecosystem="python", packages=["Requests[security]>=2.32.0"])],
        [ApiCodeRunDependencyInstall(ecosystem="python", packages=["requests"])],
    )

    assert [install.model_dump() for install in installs] == [
        {"ecosystem": "python", "packages": ["Requests[security]>=2.32.0"]}
    ]


def test_merge_dependency_installs_normalizes_scoped_npm_package_identity() -> None:
    installs = _merge_dependency_installs(
        [ApiCodeRunDependencyInstall(ecosystem="npm", packages=["@supabase/supabase-js@2.47.0"])],
        [ApiCodeRunDependencyInstall(ecosystem="npm", packages=["@supabase/supabase-js"])],
    )

    assert [install.model_dump() for install in installs] == [
        {"ecosystem": "npm", "packages": ["@supabase/supabase-js@2.47.0"]}
    ]


@pytest.mark.anyio
async def test_cancel_code_run_marks_execution_cancelling() -> None:
    cache = FakeCache([], {})
    client = await cache.client
    execution_id = "execution-1"
    await client.set(
        _execution_key(execution_id),
        json.dumps({"execution_id": execution_id, "user_id_hash": USER_HASH, "status": "running"}),
    )

    response = await cancel_code_run(execution_id, _user(), cache)
    stored = json.loads((await client.get(_execution_key(execution_id))).decode())

    assert response.status == "cancelling"
    assert stored["status"] == "cancelling"
    assert stored["cancel_requested"] is True


@pytest.mark.anyio
async def test_charge_run_credits_links_usage_to_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[dict] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

    class FakeAsyncClient:
        def __init__(self, timeout: int):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url: str, json: dict, headers: dict):
            requests.append({"url": url, "json": json, "headers": headers})
            return FakeResponse()

    monkeypatch.setattr("backend.apps.code.tasks.run_code_task.httpx.AsyncClient", FakeAsyncClient)

    charged = await _charge_run_credits(
        {
            "user_id": USER_ID,
            "user_id_hash": USER_HASH,
            "chat_id": CHAT_ID,
            "message_id": MESSAGE_ID,
            "target_embed_id": TARGET_EMBED_ID,
            "target_path": "main.py",
            "files": [{"path": "main.py"}],
        },
        5,
        "execution-1",
        {"billing_phase": "initial_minute", "charged_minutes": 1},
    )

    assert charged == 5
    assert requests[0]["json"]["credits"] == 5
    assert requests[0]["json"]["app_id"] == "code"
    assert requests[0]["json"]["skill_id"] == "run"
    assert requests[0]["json"]["idempotency_key"].startswith("code-run:execution-1:")
    assert requests[0]["json"]["usage_details"]["chat_id"] == CHAT_ID
    assert requests[0]["json"]["usage_details"]["message_id"] == MESSAGE_ID
    usage_details = requests[0]["json"]["usage_details"]
    assert usage_details["credits_per_minute"] == 5
    assert usage_details["code_run_filenames"] == ["main.py"]


@pytest.mark.anyio
async def test_charge_run_credits_includes_code_run_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[dict] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

    class FakeAsyncClient:
        def __init__(self, timeout: int):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url: str, json: dict, headers: dict):
            requests.append({"url": url, "json": json, "headers": headers})
            return FakeResponse()

    monkeypatch.setattr("backend.apps.code.tasks.run_code_task.httpx.AsyncClient", FakeAsyncClient)

    await _charge_run_credits(
        {
            "user_id": USER_ID,
            "user_id_hash": USER_HASH,
            "chat_id": CHAT_ID,
            "message_id": MESSAGE_ID,
            "target_embed_id": TARGET_EMBED_ID,
            "target_path": "main.py",
            "files": [{"path": "main.py"}, {"path": "helper.py"}],
        },
        10,
        "execution-1",
        {"billing_phase": "completed", "duration_seconds": 61.234, "charged_minutes": 2},
    )

    usage_details = requests[0]["json"]["usage_details"]
    assert usage_details["code_run_filenames"] == ["main.py", "helper.py"]
    assert usage_details["duration_seconds"] == 61.234
