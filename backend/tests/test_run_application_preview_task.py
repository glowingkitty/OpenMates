# backend/tests/test_run_application_preview_task.py
#
# Tests for the application preview worker lifecycle.
# They use the same Redis-like fake cache as the API tests and inject a fake E2B
# provider, so no sandbox or network call is made while proving session updates.

from __future__ import annotations

import json
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from toon_format import encode as toon_encode

from backend.core.api.app.routes.application_preview import (
    ApplicationPreviewStartRequest,
    application_preview_session_key,
    create_application_preview_session,
)
from backend.shared.providers.e2b_application_preview import ApplicationPreviewRuntime
from backend.tests.test_application_preview_config import FakeCache, _user


def _load_worker_module():
    module_path = Path(__file__).resolve().parents[1] / "apps" / "code" / "tasks" / "run_application_preview_task.py"
    spec = importlib.util.spec_from_file_location("run_application_preview_task_under_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.anyio
async def test_run_application_preview_session_marks_session_running_with_upstream_url() -> None:
    worker = _load_worker_module()
    cache = FakeCache()
    await create_application_preview_session(
        cache_service=cache,
        session_id="session-1",
        application_embed_id="app-embed-1",
        body=ApplicationPreviewStartRequest(chat_id="chat-1"),
        current_user=_user("alice-user"),
        preview_origin="https://openmatesusercontent.org",
        now=2_000.0,
        preview_token="token-abc",
    )

    async def fake_provider(**_kwargs):
        return ApplicationPreviewRuntime(
            sandbox_id="sandbox-1",
            upstream_base_url="https://sandbox-1-5173.e2b.dev",
            ports={"frontend": 5173},
            latest_screenshot_url="https://openmatesusercontent.org/thumbs/session-1.png",
        )

    await worker.run_application_preview_session(
        cache_service=cache,
        session_id="session-1",
        payload={
            "files": [{"path": "package.json", "content": '{"scripts":{"dev":"vite"}}'}],
            "entrypoints": [{"name": "frontend", "command": "npm run dev", "port": 5173}],
        },
        provider_start=fake_provider,
        now=2_030.0,
    )

    stored = json.loads((await cache.redis.get(application_preview_session_key("session-1"))).decode("utf-8"))
    assert stored["status"] == "running"
    assert stored["sandbox_id"] == "sandbox-1"
    assert stored["upstream_base_url"] == "https://sandbox-1-5173.e2b.dev"
    assert stored["ports"] == {"frontend": 5173}
    assert stored["latest_screenshot_url"] == "https://openmatesusercontent.org/thumbs/session-1.png"
    assert stored["latest_screenshot_captured_at"] == 2_030.0
    assert stored["billing_state"]["billable_started_at"] == 2_030.0
    assert [event["text"] for event in stored["events"]][-2:] == [
        "Starting application preview sandbox...",
        "Application preview is running.",
    ]
    assert "token-abc" not in json.dumps(stored)


@pytest.mark.anyio
async def test_run_application_preview_session_stores_encrypted_screenshot_metadata() -> None:
    worker = _load_worker_module()
    cache = FakeCache()
    await create_application_preview_session(
        cache_service=cache,
        session_id="session-1",
        application_embed_id="app-embed-1",
        body=ApplicationPreviewStartRequest(chat_id="chat-1"),
        current_user=_user("alice-user"),
        preview_origin="https://openmatesusercontent.org",
        now=2_000.0,
        preview_token="token-abc",
    )

    async def fake_provider(**_kwargs):
        return ApplicationPreviewRuntime(
            sandbox_id="sandbox-1",
            upstream_base_url="https://sandbox-1-5173.e2b.dev",
            ports={"frontend": 5173},
        )

    async def fake_thumbnail_store(**kwargs):
        assert kwargs["session_id"] == "session-1"
        assert kwargs["runtime"].sandbox_id == "sandbox-1"
        return {
            "download_url": "https://api.dev.openmates.org/v1/generated-assets/session-1/files/preview/download?token=signed",
            "metadata": {
                "asset_id": "session-1",
                "variant": "preview",
                "files": {"preview": {"s3_key": "alice/preview.png", "format": "png"}},
                "s3_base_url": "https://dev-openmates-chatfiles.nbg1.your-objectstorage.com",
                "aes_key": "base64-key",
                "aes_nonce": "base64-nonce",
            },
        }

    await worker.run_application_preview_session(
        cache_service=cache,
        session_id="session-1",
        payload={
            "files": [{"path": "package.json", "content": '{"scripts":{"dev":"vite"}}'}],
            "entrypoints": [{"name": "frontend", "command": "npm run dev", "port": 5173}],
        },
        provider_start=fake_provider,
        thumbnail_store=fake_thumbnail_store,
        now=2_030.0,
    )

    stored = json.loads((await cache.redis.get(application_preview_session_key("session-1"))).decode("utf-8"))
    assert stored["status"] == "running"
    assert stored["latest_screenshot_url"].startswith("https://api.dev.openmates.org/v1/generated-assets/session-1/")
    assert stored["latest_screenshot"]["asset_id"] == "session-1"
    assert stored["latest_screenshot"]["files"]["preview"]["s3_key"] == "alice/preview.png"
    assert stored["latest_screenshot_captured_at"] == 2_030.0
    assert "token-abc" not in json.dumps(stored)


@pytest.mark.anyio
async def test_store_application_preview_thumbnail_encrypts_s3_and_updates_application_embed(monkeypatch) -> None:
    worker = _load_worker_module()
    cache = FakeCache()
    await create_application_preview_session(
        cache_service=cache,
        session_id="session-1",
        application_embed_id="app-embed-1",
        body=ApplicationPreviewStartRequest(chat_id="chat-1"),
        current_user=_user("alice-user"),
        preview_origin="https://openmatesusercontent.org",
        now=2_000.0,
        preview_token="token-abc",
    )
    application_content = toon_encode({"type": "application", "name": "Recipe App"})
    await cache.redis.set("embed:app-embed-1", json.dumps({"encrypted_content": application_content}))
    cache.redis.values.pop("embed:app-embed-1")
    uploads: list[dict] = []
    indexed: list[dict] = []
    cached_s3_keys: list[dict] = []
    updated_embeds: list[dict] = []

    class FakeEncryptionService:
        def __init__(self, **_kwargs):
            pass

        async def initialize(self):
            return None

        async def encrypt_with_user_key(self, value, _vault_key_id):
            return f"vault:{value}", None

        async def decrypt_with_user_key(self, value, _vault_key_id):
            return value.removeprefix("vault:")

    class FakeDirectusService:
        def __init__(self, **_kwargs):
            self.embed = SimpleNamespace(update_embed=self.update_embed, get_embed_by_id=self.get_embed_by_id)

        async def get_user_fields_direct(self, _user_id, _fields):
            return {"vault_key_id": "vault-alice", "storage_used_bytes": 0}

        async def get_embed_by_id(self, embed_id):
            assert embed_id == "app-embed-1"
            return {"encrypted_content": application_content}

        async def create_item(self, _collection, record):
            indexed.append(record)
            return True, None

        async def update_user(self, *_args, **_kwargs):
            return True

        async def update_embed(self, embed_id, update_data):
            updated_embeds.append({"embed_id": embed_id, "update_data": update_data})
            return update_data

    class FakeS3Service:
        environment = "development"
        base_domain = "nbg1.your-objectstorage.com"

        def __init__(self, **_kwargs):
            pass

        async def initialize(self):
            return None

        async def upload_file(self, **kwargs):
            uploads.append(kwargs)
            return {"url": "s3://stored"}

        async def delete_file(self, **_kwargs):
            return True

    async def fake_cache_s3_file_keys(_task, **kwargs):
        cached_s3_keys.append(kwargs)
        return None

    async def fake_index_generated_asset(_task, **kwargs):
        indexed.append({"embed_id": kwargs["embed_id"], **kwargs})
        return True

    monkeypatch.setattr(worker, "EncryptionService", FakeEncryptionService)
    monkeypatch.setattr(worker, "DirectusService", FakeDirectusService)
    monkeypatch.setattr(worker, "S3UploadService", FakeS3Service)
    monkeypatch.setattr(worker, "get_bucket_name", lambda _bucket, _env: "dev-openmates-chatfiles")
    monkeypatch.setattr(worker, "cache_s3_file_keys", fake_cache_s3_file_keys)
    monkeypatch.setattr(worker, "index_generated_asset", fake_index_generated_asset)
    monkeypatch.setattr(worker, "create_download_token", lambda **_kwargs: "signed-token")
    monkeypatch.setattr(worker, "build_download_url", lambda **kwargs: f"{kwargs['base_url']}/download/{kwargs['asset_id']}/{kwargs['variant']}?token={kwargs['token']}")
    monkeypatch.setattr(worker, "_build_application_preview_thumbnail_png", lambda **_kwargs: b"fake-png-bytes")

    result = await worker.store_application_preview_thumbnail(
        cache_service=cache,
        session_id="session-1",
        payload={
            "application_embed_id": "app-embed-1",
            "framework": "svelte",
            "files": [{"path": "src/App.svelte", "content": "<main />"}],
        },
        runtime=ApplicationPreviewRuntime(
            sandbox_id="sandbox-1",
            upstream_base_url="https://sandbox-1-5173.e2b.dev",
            ports={"frontend": 5173},
        ),
        now=2_030.0,
        secrets_manager=object(),
    )

    assert result is not None
    assert result["download_url"] == "https://api.dev.openmates.org/download/app-embed-1/preview?token=signed-token"
    assert result["metadata"]["asset_id"] == "app-embed-1"
    assert result["metadata"]["files"]["preview"]["s3_key"].endswith("_application_preview.png")
    assert uploads and uploads[0]["content_type"] == "application/octet-stream"
    assert b"OpenMates" not in uploads[0]["content"]
    assert indexed and indexed[0]["embed_id"] == "app-embed-1"
    assert cached_s3_keys and cached_s3_keys[0]["embed_id"] == "app-embed-1"
    assert updated_embeds and updated_embeds[0]["embed_id"] == "app-embed-1"

    cached_embed = json.loads((await cache.redis.get("embed:app-embed-1")).decode("utf-8"))
    assert cached_embed["encrypted_content"].startswith("vault:")


@pytest.mark.anyio
async def test_store_application_preview_thumbnail_skips_shared_context_sessions(monkeypatch) -> None:
    worker = _load_worker_module()
    cache = FakeCache()
    await create_application_preview_session(
        cache_service=cache,
        session_id="session-1",
        application_embed_id="shared-app-embed-1",
        body=ApplicationPreviewStartRequest(chat_id="chat-1", shared_context="encrypted-shared-context"),
        current_user=_user("recipient-user"),
        preview_origin="https://openmatesusercontent.org",
        now=2_000.0,
        preview_token="token-abc",
    )

    monkeypatch.setattr(worker, "EncryptionService", object)
    monkeypatch.setattr(worker, "DirectusService", object)
    monkeypatch.setattr(worker, "S3UploadService", object)
    monkeypatch.setattr(worker, "get_bucket_name", lambda *_args: "dev-openmates-chatfiles")
    monkeypatch.setattr(worker, "build_download_url", lambda **_kwargs: "")
    monkeypatch.setattr(worker, "create_download_token", lambda **_kwargs: "")
    monkeypatch.setattr(worker, "cache_s3_file_keys", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(worker, "index_generated_asset", lambda *_args, **_kwargs: None)

    result = await worker.store_application_preview_thumbnail(
        cache_service=cache,
        session_id="session-1",
        payload={"application_embed_id": "shared-app-embed-1"},
        runtime=ApplicationPreviewRuntime(
            sandbox_id="sandbox-1",
            upstream_base_url="https://sandbox-1-5173.e2b.dev",
            ports={"frontend": 5173},
        ),
        now=2_030.0,
        secrets_manager=object(),
    )

    assert result is None


@pytest.mark.anyio
async def test_run_application_preview_session_marks_planning_error_failed_without_secret_leak() -> None:
    worker = _load_worker_module()
    cache = FakeCache()
    await create_application_preview_session(
        cache_service=cache,
        session_id="session-1",
        application_embed_id="app-embed-1",
        body=ApplicationPreviewStartRequest(chat_id="chat-1"),
        current_user=_user("alice-user"),
        preview_origin="https://openmatesusercontent.org",
        now=2_000.0,
        preview_token="token-abc",
    )

    await worker.run_application_preview_session(
        cache_service=cache,
        session_id="session-1",
        payload={
            "files": [{"path": "src/main.ts", "content": "const token = 'sk-test-secret-token-1234567890';"}],
            "entrypoints": [{"name": "frontend", "command": "npm run dev", "port": 5173}],
        },
        provider_start=None,
        now=2_030.0,
    )

    stored = json.loads((await cache.redis.get(application_preview_session_key("session-1"))).decode("utf-8"))
    serialized = json.dumps(stored)
    assert stored["status"] == "failed"
    assert "secrets" in stored["error"]
    assert "sk-test-secret" not in serialized
    assert "token-abc" not in serialized


@pytest.mark.anyio
async def test_stop_application_preview_sandbox_records_cleanup_event() -> None:
    worker = _load_worker_module()
    cache = FakeCache()
    await create_application_preview_session(
        cache_service=cache,
        session_id="session-1",
        application_embed_id="app-embed-1",
        body=ApplicationPreviewStartRequest(chat_id="chat-1"),
        current_user=_user("alice-user"),
        preview_origin="https://openmatesusercontent.org",
        now=2_000.0,
        preview_token="token-abc",
    )
    calls: list[dict[str, str]] = []

    async def fake_stop(**kwargs) -> bool:
        calls.append(kwargs)
        return True

    await worker.stop_application_preview_sandbox(
        cache_service=cache,
        session_id="session-1",
        sandbox_id="sandbox-1",
        api_key="e2b-key",
        provider_stop=fake_stop,
        now=2_090.0,
    )

    stored = json.loads((await cache.redis.get(application_preview_session_key("session-1"))).decode("utf-8"))
    assert calls == [{"sandbox_id": "sandbox-1", "api_key": "e2b-key"}]
    assert stored["sandbox_stopped_at"] == 2_090.0
    assert stored["events"][-1]["text"] == "Application preview sandbox stopped."


@pytest.mark.anyio
async def test_stop_application_preview_sandbox_charges_usage_once(monkeypatch) -> None:
    worker = _load_worker_module()
    cache = FakeCache()
    await create_application_preview_session(
        cache_service=cache,
        session_id="session-1",
        application_embed_id="app-embed-1",
        body=ApplicationPreviewStartRequest(chat_id="chat-1"),
        current_user=_user("alice-user"),
        preview_origin="https://openmatesusercontent.org",
        now=2_000.0,
        preview_token="token-abc",
    )
    stored = json.loads((await cache.redis.get(application_preview_session_key("session-1"))).decode("utf-8"))
    stored["billing_state"]["billable_started_at"] = 2_030.0
    await cache.redis.set(application_preview_session_key("session-1"), json.dumps(stored))

    charges: list[dict] = []

    async def fake_charge(**kwargs) -> None:
        charges.append(kwargs)

    monkeypatch.setattr(worker, "_charge_preview_credits", fake_charge)

    await worker.stop_application_preview_sandbox(
        cache_service=cache,
        session_id="session-1",
        sandbox_id="sandbox-1",
        api_key="e2b-key",
        provider_stop=lambda **_kwargs: True,
        now=2_091.0,
    )

    charged = json.loads((await cache.redis.get(application_preview_session_key("session-1"))).decode("utf-8"))
    assert charges[0]["session_id"] == "session-1"
    assert charges[0]["credits"] == 10
    assert charges[0]["usage_details"] == {
        "billing_phase": "stopped",
        "duration_seconds": 61.0,
        "charged_minutes": 2,
        "total_charged_minutes": 2,
    }
    assert charges[0]["session"]["viewer_user_id"] == "alice-user"
    assert charges[0]["session"]["usage_context"] == {"chat_id": "chat-1", "application_embed_id": "app-embed-1"}
    assert charged["billing_state"]["charged_credits"] == 10
    assert charged["billing_state"]["charged_minutes"] == 2

    await worker.stop_application_preview_sandbox(
        cache_service=cache,
        session_id="session-1",
        sandbox_id="sandbox-1",
        api_key="e2b-key",
        provider_stop=lambda **_kwargs: True,
        now=2_120.0,
    )
    assert len(charges) == 1


@pytest.mark.anyio
async def test_charge_preview_credits_posts_internal_billing_payload(monkeypatch) -> None:
    worker = _load_worker_module()
    requests: list[dict] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

    class FakeAsyncClient:
        def __init__(self, *, timeout: int) -> None:
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            return None

        async def post(self, url: str, *, json: dict, headers: dict) -> FakeResponse:
            requests.append({"url": url, "json": json, "headers": headers, "timeout": self.timeout})
            return FakeResponse()

    monkeypatch.setattr(worker.httpx, "AsyncClient", FakeAsyncClient)

    await worker._charge_preview_credits(
        session={
            "viewer_user_id": "alice-user",
            "viewer_user_id_hash": "alice-hash",
            "application_embed_id": "app-embed-1",
            "usage_context": {"chat_id": "chat-1", "application_embed_id": "app-embed-1"},
        },
        session_id="session-1",
        credits=10,
        usage_details={"billing_phase": "stopped", "duration_seconds": 61.0, "charged_minutes": 2},
    )

    assert requests[0]["headers"]["Content-Type"] == "application/json"
    if worker.INTERNAL_API_SHARED_TOKEN:
        assert requests[0]["headers"]["X-Internal-Service-Token"] == worker.INTERNAL_API_SHARED_TOKEN
    else:
        assert "X-Internal-Service-Token" not in requests[0]["headers"]
    assert [{"url": item["url"], "json": item["json"], "timeout": item["timeout"]} for item in requests] == [
        {
            "url": "http://api:8000/internal/billing/charge",
            "json": {
                "user_id": "alice-user",
                "user_id_hash": "alice-hash",
                "credits": 10,
                "skill_id": "application_preview",
                "app_id": "code",
                "usage_details": {
                    "preview_session_id": "session-1",
                    "application_embed_id": "app-embed-1",
                    "chat_id": "chat-1",
                    "credits_per_minute": 5,
                    "billing_phase": "stopped",
                    "duration_seconds": 61.0,
                    "charged_minutes": 2,
                },
                "api_key_hash": None,
                "device_hash": None,
            },
            "timeout": 30,
        }
    ]
