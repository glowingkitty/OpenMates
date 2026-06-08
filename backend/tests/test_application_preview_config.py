# backend/tests/test_application_preview_config.py
#
# Tests for the application-preview backend contract before sandbox startup.
# The first implementation slice keeps E2B lifecycle code out of scope and
# proves the security-sensitive configuration, session ownership, timeout, and
# billing invariants that the later worker/gateway code will rely on.

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.core.api.app.routes.application_preview import (
    APPLICATION_PREVIEW_CREDITS_PER_STARTED_MINUTE,
    APPLICATION_PREVIEW_HARD_TIMEOUT_SECONDS,
    APPLICATION_PREVIEW_IDLE_TIMEOUT_SECONDS,
    ApplicationPreviewConfigError,
    ApplicationPreviewStartRequest,
    APPLICATION_PREVIEW_SESSION_TTL_SECONDS,
    application_preview_session_key,
    build_application_preview_status_response,
    build_application_preview_worker_payload_from_shared_context,
    build_preview_session_record,
    build_application_preview_worker_payload,
    collect_application_preview_worker_payload,
    create_application_preview_session,
    create_application_preview_session_and_dispatch,
    calculate_preview_charge_credits,
    get_application_preview_session,
    start_application_preview,
    stop_application_preview_session,
    validate_application_preview_origin,
)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}
        self.ttls: dict[str, int | None] = {}

    async def get(self, key: str):
        return self.values.get(key)

    async def set(self, key: str, value: str, ex: int | None = None):
        self.values[key] = value.encode("utf-8")
        self.ttls[key] = ex


class FakeCache:
    def __init__(self) -> None:
        self.redis = FakeRedis()
        self.chat_embed_ids: dict[str, list[str]] = {}
        self.embed_metadata: dict[str, dict] = {}

    @property
    def client(self):
        async def _client():
            return self.redis

        return _client()

    async def get_chat_embed_ids(self, chat_id: str):
        return list(self.chat_embed_ids.get(chat_id, []))

    async def get_embed_from_cache(self, embed_id: str):
        return self.embed_metadata.get(embed_id)


def _user(user_id: str = "alice-user", credits: int = 50):
    return SimpleNamespace(id=user_id, credits=credits, vault_key_id=f"vault-{user_id}")


class FakeEncryption:
    async def decrypt_with_user_key(self, encrypted_content: str, _vault_key_id: str):
        return encrypted_content


def _application_content() -> dict:
    return {
        "type": "application",
        "name": "Recipe Manager",
        "framework": "svelte",
        "runtime": "node",
        "file_refs": [
            {"path": "package.json", "embed_id": "file-package", "role": "dependency_manifest"},
            {"path": "src/App.svelte", "embed_id": "file-app", "role": "source"},
        ],
        "entrypoints": [{"name": "frontend", "command": "npm run dev", "port": 5173}],
    }


def _code_content(code: str, filename: str = "main.ts") -> dict:
    return {"type": "code-code", "code": code, "language": "typescript", "filename": filename}


def _metadata(user_id: str, chat_id: str) -> dict:
    return {
        "hashed_user_id": hashlib.sha256(user_id.encode()).hexdigest(),
        "hashed_chat_id": hashlib.sha256(chat_id.encode()).hexdigest(),
    }


def test_preview_origin_requires_configuration() -> None:
    with pytest.raises(ApplicationPreviewConfigError, match="APPLICATION_PREVIEW_ORIGIN"):
        validate_application_preview_origin("", app_origins=["https://app.openmates.org"], api_origin="https://api.openmates.org")


def test_preview_origin_rejects_openmates_app_site_subdomain() -> None:
    with pytest.raises(ApplicationPreviewConfigError, match="separate site"):
        validate_application_preview_origin(
            "https://preview.openmates.org",
            app_origins=["https://app.openmates.org"],
            api_origin="https://api.openmates.org",
        )


def test_preview_origin_accepts_configured_user_content_site() -> None:
    origin = validate_application_preview_origin(
        "https://openmatesusercontent.org",
        app_origins=["https://app.openmates.org", "https://openmates.org"],
        api_origin="https://api.openmates.org",
    )

    assert origin == "https://openmatesusercontent.org"


def test_preview_origin_allows_localhost_dev_ports() -> None:
    origin = validate_application_preview_origin(
        "http://localhost:8787",
        app_origins=["http://localhost:5173"],
        api_origin="http://localhost:8000",
    )

    assert origin == "http://localhost:8787"


def test_preview_session_record_is_viewer_scoped_and_timeout_bounded() -> None:
    record = build_preview_session_record(
        session_id="session-1",
        viewer_user_id="bob-user",
        chat_id="shared-chat",
        application_embed_id="app-embed-1",
        now=1_000.0,
    )

    assert application_preview_session_key("session-1") == "application_preview_session:session-1"
    assert record["viewer_user_id"] == "bob-user"
    assert record["viewer_user_id_hash"] == hashlib.sha256(b"bob-user").hexdigest()
    assert record["chat_id_hash"] == hashlib.sha256(b"shared-chat").hexdigest()
    assert record["application_embed_id"] == "app-embed-1"
    assert record["status"] == "queued"
    assert record["idle_deadline"] == 1_000.0 + APPLICATION_PREVIEW_IDLE_TIMEOUT_SECONDS
    assert record["hard_deadline"] == 1_000.0 + APPLICATION_PREVIEW_HARD_TIMEOUT_SECONDS
    assert "creator_user_id" not in record


def test_preview_billing_reuses_code_run_started_minute_rate() -> None:
    assert APPLICATION_PREVIEW_CREDITS_PER_STARTED_MINUTE == 5
    assert calculate_preview_charge_credits(0) == 0
    assert calculate_preview_charge_credits(1) == 5
    assert calculate_preview_charge_credits(60) == 5
    assert calculate_preview_charge_credits(61) == 10


def test_preview_timeout_policy_matches_spec() -> None:
    assert APPLICATION_PREVIEW_IDLE_TIMEOUT_SECONDS == 5 * 60
    assert APPLICATION_PREVIEW_HARD_TIMEOUT_SECONDS == 30 * 60


def test_application_worker_payload_resolves_manifest_child_files() -> None:
    payload = build_application_preview_worker_payload(
        application_embed_id="app-embed-1",
        application_content=_application_content(),
        child_contents={
            "file-package": _code_content('{"scripts":{"dev":"vite"}}', "package.json"),
            "file-app": _code_content("<script>let name = 'Ada'</script><main>{name}</main>", "App.svelte"),
        },
    )

    assert payload == {
        "application_embed_id": "app-embed-1",
        "framework": "svelte",
        "runtime": "node",
        "files": [
            {"path": "package.json", "content": '{"scripts":{"dev":"vite"}}', "source_embed_id": "file-package", "role": "dependency_manifest"},
            {"path": "src/App.svelte", "content": "<script>let name = 'Ada'</script><main>{name}</main>", "source_embed_id": "file-app", "role": "source"},
        ],
        "entrypoints": [{"name": "frontend", "command": "npm run dev", "port": 5173}],
    }


def test_application_worker_payload_rejects_missing_child_embed() -> None:
    with pytest.raises(HTTPException) as exc_info:
        build_application_preview_worker_payload(
            application_embed_id="app-embed-1",
            application_content=_application_content(),
            child_contents={"file-package": _code_content("{}", "package.json")},
        )

    assert exc_info.value.status_code == 409


def test_application_worker_payload_rejects_non_application_parent() -> None:
    with pytest.raises(HTTPException) as exc_info:
        build_application_preview_worker_payload(
            application_embed_id="app-embed-1",
            application_content={"type": "code-code", "code": "print('no')"},
            child_contents={},
        )

    assert exc_info.value.status_code == 400


def test_application_worker_payload_rejects_secret_like_child_content() -> None:
    with pytest.raises(HTTPException) as exc_info:
        build_application_preview_worker_payload(
            application_embed_id="app-embed-1",
            application_content=_application_content(),
            child_contents={
                "file-package": _code_content("{}", "package.json"),
                "file-app": _code_content("const apiKey = 'sk-test-secret-token-1234567890';", "App.svelte"),
            },
        )

    assert exc_info.value.status_code == 400
    assert "secrets" in str(exc_info.value.detail)


def test_shared_context_payload_resolves_decrypted_application_files() -> None:
    payload = build_application_preview_worker_payload_from_shared_context(
        application_embed_id="app-embed-1",
        shared_context=json.dumps({
            "application_embed_id": "app-embed-1",
            "application_content": _application_content(),
            "child_contents": {
                "file-package": _code_content('{"scripts":{"dev":"vite"}}', "package.json"),
                "file-app": _code_content("<main>Shared</main>", "App.svelte"),
            },
        }),
    )

    assert payload["application_embed_id"] == "app-embed-1"
    assert payload["files"] == [
        {"path": "package.json", "content": '{"scripts":{"dev":"vite"}}', "source_embed_id": "file-package", "role": "dependency_manifest"},
        {"path": "src/App.svelte", "content": "<main>Shared</main>", "source_embed_id": "file-app", "role": "source"},
    ]


def test_shared_context_payload_rejects_mismatched_application_embed() -> None:
    with pytest.raises(HTTPException) as exc_info:
        build_application_preview_worker_payload_from_shared_context(
            application_embed_id="app-embed-1",
            shared_context=json.dumps({
                "application_embed_id": "other-app",
                "application_content": _application_content(),
                "child_contents": {},
            }),
        )

    assert exc_info.value.status_code == 400


@pytest.mark.anyio
async def test_collect_application_payload_reads_cached_encrypted_manifest_and_children() -> None:
    cache = FakeCache()
    cache.chat_embed_ids["chat-1"] = ["app-embed-1", "file-package", "file-app"]
    cache.embed_metadata["app-embed-1"] = _metadata("alice-user", "chat-1")
    await cache.redis.set("embed:app-embed-1", json.dumps({"encrypted_content": json.dumps(_application_content())}))
    await cache.redis.set("embed:file-package", json.dumps({"encrypted_content": json.dumps(_code_content('{"scripts":{"dev":"vite"}', "package.json"))}))
    await cache.redis.set("embed:file-app", json.dumps({"encrypted_content": json.dumps(_code_content("<main>Hello</main>", "App.svelte"))}))

    payload = await collect_application_preview_worker_payload(
        application_embed_id="app-embed-1",
        body=ApplicationPreviewStartRequest(chat_id="chat-1"),
        current_user=_user("alice-user"),
        cache_service=cache,
        directus_service=SimpleNamespace(),
        encryption_service=FakeEncryption(),
    )

    assert payload["application_embed_id"] == "app-embed-1"
    assert payload["files"] == [
        {"path": "package.json", "content": '{"scripts":{"dev":"vite"}', "source_embed_id": "file-package", "role": "dependency_manifest"},
        {"path": "src/App.svelte", "content": "<main>Hello</main>", "source_embed_id": "file-app", "role": "source"},
    ]
    assert payload["entrypoints"] == [{"name": "frontend", "command": "npm run dev", "port": 5173}]


@pytest.mark.anyio
async def test_collect_application_payload_accepts_shared_recipient_context_without_owner_metadata() -> None:
    cache = FakeCache()

    payload = await collect_application_preview_worker_payload(
        application_embed_id="app-embed-1",
        body=ApplicationPreviewStartRequest(
            chat_id="shared-chat-1",
            shared_context=json.dumps({
                "application_embed_id": "app-embed-1",
                "application_content": _application_content(),
                "child_contents": {
                    "file-package": _code_content('{"scripts":{"dev":"vite"}}', "package.json"),
                    "file-app": _code_content("<main>Recipient</main>", "App.svelte"),
                },
            }),
        ),
        current_user=_user("bob-user"),
        cache_service=cache,
        directus_service=SimpleNamespace(),
        encryption_service=FakeEncryption(),
    )

    assert payload["application_embed_id"] == "app-embed-1"
    assert payload["files"][1]["content"] == "<main>Recipient</main>"


@pytest.mark.anyio
async def test_collect_application_payload_rejects_embed_outside_chat_index() -> None:
    cache = FakeCache()
    cache.chat_embed_ids["chat-1"] = ["other-embed"]

    with pytest.raises(HTTPException) as exc_info:
        await collect_application_preview_worker_payload(
            application_embed_id="app-embed-1",
            body=ApplicationPreviewStartRequest(chat_id="chat-1"),
            current_user=_user("alice-user"),
            cache_service=cache,
            directus_service=SimpleNamespace(),
            encryption_service=FakeEncryption(),
        )

    assert exc_info.value.status_code == 404


@pytest.mark.anyio
async def test_create_preview_session_stores_viewer_owned_queued_record() -> None:
    cache = FakeCache()
    response = await create_application_preview_session(
        cache_service=cache,
        session_id="session-1",
        application_embed_id="app-embed-1",
        body=ApplicationPreviewStartRequest(chat_id="chat-1"),
        current_user=_user("alice-user"),
        preview_origin="https://openmatesusercontent.org",
        now=2_000.0,
    )

    assert response.session_id == "session-1"
    assert response.status == "queued"
    assert response.preview_url.startswith("https://openmatesusercontent.org/p/session-1/")
    assert response.credits_per_minute == 5

    key = application_preview_session_key("session-1")
    stored = json.loads((await cache.redis.get(key)).decode("utf-8"))
    assert cache.redis.ttls[key] == APPLICATION_PREVIEW_SESSION_TTL_SECONDS
    assert stored["viewer_user_id_hash"] == hashlib.sha256(b"alice-user").hexdigest()
    assert stored["preview_token_hash"]
    assert "preview_url" not in stored
    assert "shared_context" not in stored
    assert stored["events"][0]["text"] == "Queued application preview..."


@pytest.mark.anyio
async def test_create_preview_session_dispatches_worker_payload_after_record_creation() -> None:
    cache = FakeCache()
    calls: list[dict] = []

    def fake_sender(name: str, args: list, queue: str):
        calls.append({"name": name, "args": args, "queue": queue})

    response = await create_application_preview_session_and_dispatch(
        cache_service=cache,
        session_id="session-1",
        application_embed_id="app-embed-1",
        body=ApplicationPreviewStartRequest(chat_id="chat-1"),
        current_user=_user("alice-user"),
        preview_origin="https://openmatesusercontent.org",
        worker_payload={"files": [], "entrypoints": []},
        task_sender=fake_sender,
        now=2_000.0,
        preview_token="token-abc",
    )

    assert response.preview_url == "https://openmatesusercontent.org/p/session-1/token-abc/"
    assert calls == [
        {
            "name": "code.run_application_preview",
            "args": ["session-1", {"files": [], "entrypoints": []}],
            "queue": "app_code",
        }
    ]
    assert await cache.redis.get(application_preview_session_key("session-1")) is not None


@pytest.mark.anyio
async def test_shared_recipient_preview_session_is_distinct_and_billed_to_recipient() -> None:
    cache = FakeCache()
    creator_response = await create_application_preview_session(
        cache_service=cache,
        session_id="creator-session",
        application_embed_id="app-embed-1",
        body=ApplicationPreviewStartRequest(chat_id="chat-1"),
        current_user=_user("alice-user"),
        preview_origin="https://openmatesusercontent.org",
        now=2_000.0,
    )
    recipient_response = await create_application_preview_session(
        cache_service=cache,
        session_id="recipient-session",
        application_embed_id="app-embed-1",
        body=ApplicationPreviewStartRequest(chat_id="shared-chat-1", shared_context="client-decrypted"),
        current_user=_user("bob-user"),
        preview_origin="https://openmatesusercontent.org",
        now=2_010.0,
    )

    assert creator_response.session_id != recipient_response.session_id
    creator_record = json.loads((await cache.redis.get(application_preview_session_key("creator-session"))).decode("utf-8"))
    recipient_record = json.loads((await cache.redis.get(application_preview_session_key("recipient-session"))).decode("utf-8"))
    assert creator_record["viewer_user_id_hash"] == hashlib.sha256(b"alice-user").hexdigest()
    assert recipient_record["viewer_user_id_hash"] == hashlib.sha256(b"bob-user").hexdigest()
    assert recipient_record["billing_state"]["credits_per_started_minute"] == 5
    assert recipient_record["session_id"] != creator_record["session_id"]
    assert recipient_record["uses_client_shared_context"] is True
    assert "client-decrypted" not in json.dumps(recipient_record)


@pytest.mark.anyio
async def test_start_application_preview_route_resolves_payload_and_dispatches_worker(monkeypatch) -> None:
    cache = FakeCache()
    calls: list[dict] = []
    fake_directus = SimpleNamespace()
    fake_encryption = SimpleNamespace()

    async def fake_resolver(application_embed_id, body, current_user, cache_service, directus_service, encryption_service):
        assert application_embed_id == "app-embed-1"
        assert body.chat_id == "chat-1"
        assert current_user.id == "alice-user"
        assert cache_service is cache
        assert directus_service is fake_directus
        assert encryption_service is fake_encryption
        return {"files": [{"path": "package.json", "content": "{}"}], "entrypoints": []}

    def fake_sender(name: str, args: list, queue: str):
        calls.append({"name": name, "args": args, "queue": queue})

    fake_request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                allowed_origins=["https://app.openmates.org"],
                application_preview_payload_resolver=fake_resolver,
                application_preview_task_sender=fake_sender,
            )
        )
    )
    monkeypatch.setenv("APPLICATION_PREVIEW_ORIGIN", "https://openmatesusercontent.org")

    response = await start_application_preview(
        application_embed_id="app-embed-1",
        body=ApplicationPreviewStartRequest(chat_id="chat-1"),
        request=fake_request,
        current_user=_user("alice-user"),
        cache_service=cache,
        directus_service=fake_directus,
        encryption_service=fake_encryption,
    )

    assert response.status == "queued"
    assert response.preview_url.startswith("https://openmatesusercontent.org/p/")
    assert len(calls) == 1
    assert calls[0]["name"] == "code.run_application_preview"
    assert calls[0]["queue"] == "app_code"
    assert calls[0]["args"][0] == response.session_id
    assert calls[0]["args"][1] == {"files": [{"path": "package.json", "content": "{}"}], "entrypoints": []}

    stored = json.loads((await cache.redis.get(application_preview_session_key(response.session_id))).decode("utf-8"))
    assert stored["application_embed_id"] == "app-embed-1"
    assert stored["status"] == "queued"


@pytest.mark.anyio
async def test_get_preview_session_hides_records_from_other_viewers() -> None:
    cache = FakeCache()
    await create_application_preview_session(
        cache_service=cache,
        session_id="session-1",
        application_embed_id="app-embed-1",
        body=ApplicationPreviewStartRequest(chat_id="chat-1"),
        current_user=_user("alice-user"),
        preview_origin="https://openmatesusercontent.org",
        now=2_000.0,
    )

    assert (await get_application_preview_session(cache, "session-1", _user("alice-user")))["session_id"] == "session-1"
    with pytest.raises(HTTPException) as exc_info:
        await get_application_preview_session(cache, "session-1", _user("bob-user"))

    assert exc_info.value.status_code == 404


def test_public_preview_status_excludes_gateway_secrets_and_raw_upstream() -> None:
    response = build_application_preview_status_response({
        "session_id": "session-1",
        "status": "running",
        "viewer_user_id": "alice-user",
        "viewer_user_id_hash": "hash-alice",
        "preview_token_hash": "hash-token",
        "upstream_base_url": "https://sandbox-1-5173.e2b.dev",
        "latest_screenshot_url": "https://openmatesusercontent.org/thumbs/session-1.png",
        "latest_screenshot": {
            "asset_id": "app-embed-1",
            "variant": "preview",
            "aes_key": "base64-key",
            "aes_nonce": "base64-nonce",
            "vault_wrapped_aes_key": "wrapped-key",
        },
        "billing_state": {"charged_credits": 5},
        "events": [{"kind": "status", "text": "Application preview is running.", "timestamp": 2_010.0}],
    })

    assert response.session_id == "session-1"
    assert response.status == "running"
    assert response.charged_credits == 5
    assert response.latest_screenshot_url == "https://openmatesusercontent.org/thumbs/session-1.png"
    assert response.latest_screenshot == {
        "asset_id": "app-embed-1",
        "variant": "preview",
        "aes_key": "base64-key",
        "aes_nonce": "base64-nonce",
    }
    assert response.events[0].text == "Application preview is running."
    public_payload = response.model_dump() if hasattr(response, "model_dump") else response.dict()
    assert "viewer_user_id" not in public_payload
    assert "viewer_user_id_hash" not in public_payload
    assert "preview_token_hash" not in public_payload
    assert "upstream_base_url" not in public_payload
    assert "vault_wrapped_aes_key" not in json.dumps(public_payload)


@pytest.mark.anyio
async def test_stop_preview_session_updates_owner_record_without_cross_user_access() -> None:
    cache = FakeCache()
    calls: list[dict] = []

    def fake_sender(name: str, args: list, queue: str) -> None:
        calls.append({"name": name, "args": args, "queue": queue})

    await create_application_preview_session(
        cache_service=cache,
        session_id="session-1",
        application_embed_id="app-embed-1",
        body=ApplicationPreviewStartRequest(chat_id="chat-1"),
        current_user=_user("alice-user"),
        preview_origin="https://openmatesusercontent.org",
        now=2_000.0,
    )
    session = await cache.redis.get(application_preview_session_key("session-1"))
    stored = json.loads(session.decode("utf-8"))
    stored.update({
        "status": "running",
        "sandbox_id": "sandbox-1",
        "latest_screenshot_url": "https://openmatesusercontent.org/thumbs/session-1.png",
        "latest_screenshot_captured_at": 2_045.0,
    })
    await cache.redis.set(application_preview_session_key("session-1"), json.dumps(stored))

    with pytest.raises(HTTPException) as exc_info:
        await stop_application_preview_session(cache, "session-1", _user("bob-user"), now=2_030.0)
    assert exc_info.value.status_code == 404

    response = await stop_application_preview_session(cache, "session-1", _user("alice-user"), now=2_060.0, task_sender=fake_sender)
    assert response.session_id == "session-1"
    assert response.status == "stopped"

    stored = await get_application_preview_session(cache, "session-1", _user("alice-user"))
    assert stored["status"] == "stopped"
    assert stored["stop_reason"] == "user_requested"
    assert stored["sandbox_stop_requested_at"] == 2_060.0
    assert stored["updated_at"] == 2_060.0
    assert stored["latest_screenshot_url"] == "https://openmatesusercontent.org/thumbs/session-1.png"
    assert stored["latest_screenshot_captured_at"] == 2_045.0
    assert calls == [
        {
            "name": "code.stop_application_preview",
            "args": ["session-1", "sandbox-1"],
            "queue": "app_code",
        }
    ]
