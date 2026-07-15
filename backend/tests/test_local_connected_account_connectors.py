# backend/tests/test_local_connected_account_connectors.py
#
# Contract tests for online-only local connected-account connector sessions.
# Proton Bridge credentials must remain local to the CLI; backend routes store
# encrypted metadata, status, and session ownership only.
#
# Spec: docs/specs/proton-bridge-cli-connector/spec.yml

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_mail_app_metadata_declares_parent_child_search_embeds() -> None:
    app_yml = yaml.safe_load((REPO_ROOT / "backend/apps/mail/app.yml").read_text())
    search_embed = next(embed for embed in app_yml["embed_types"] if embed["id"] == "search")
    child_embed = next(embed for embed in app_yml["embed_types"] if embed["id"] == "email")

    assert search_embed["category"] == "app-skill-use"
    assert search_embed["skill_id"] == "search"
    assert search_embed["has_children"] is True
    assert search_embed["child_type"] == "email"
    assert search_embed["child_frontend_type"] == "mail-email"
    assert child_embed["category"] == "direct"
    assert child_embed["frontend_type"] == "mail-email"


class FakeDirectus:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    async def get_items(self, collection: str, params: dict[str, Any] | None = None):
        assert collection == "connected_accounts"
        params = params or {}
        rows = list(self.rows.values())
        account_id = params.get("filter[id][_eq]")
        hashed_user_id = params.get("filter[hashed_user_id][_eq]")
        session_id = params.get("filter[local_connector_session_id][_eq]")
        if account_id:
            rows = [row for row in rows if row.get("id") == account_id]
        if hashed_user_id:
            rows = [row for row in rows if row.get("hashed_user_id") == hashed_user_id]
        if session_id:
            rows = [row for row in rows if row.get("local_connector_session_id") == session_id]
        return rows[: int(params.get("limit", len(rows)))]

    async def create_item(self, collection: str, payload: dict[str, Any]):
        assert collection == "connected_accounts"
        self.rows[payload["id"]] = dict(payload)
        return True, dict(payload)

    async def update_item(self, collection: str, item_id: str, payload: dict[str, Any]):
        assert collection == "connected_accounts"
        self.rows[item_id].update(payload)
        return dict(self.rows[item_id])


@pytest.mark.anyio
async def test_local_connector_registration_stores_no_credentials() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.core.api.app.models.user import User
    from backend.core.api.app.routes import connected_accounts

    directus = FakeDirectus()
    user = User(id="user-1", username="alice", vault_key_id="vault-1")
    hashed_user_id = hashlib.sha256(user.id.encode()).hexdigest()
    app = FastAPI()
    app.include_router(connected_accounts.router)
    app.dependency_overrides[connected_accounts.get_current_user] = lambda: user
    app.dependency_overrides[connected_accounts.get_directus_service] = lambda: directus
    client = TestClient(app)

    response = client.post("/v1/connected-accounts/local-connectors", json=local_connector_payload(hashed_user_id))

    assert response.status_code == 200
    payload = response.json()
    assert payload["connected_account_id"] == "acct-local-1"
    assert payload["connector_session_id"].startswith("lcs_")
    stored = directus.rows["acct-local-1"]
    assert stored["execution_mode"] == "local_connector"
    assert stored["connector_provider_id"] == "protonmail_bridge"
    assert stored["connector_status"] == "online"
    assert stored["encrypted_refresh_token_bundle"] is None
    assert_no_secret_text(stored)


@pytest.mark.anyio
async def test_local_connector_registration_rejects_plaintext_bridge_credentials() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.core.api.app.models.user import User
    from backend.core.api.app.routes import connected_accounts

    directus = FakeDirectus()
    user = User(id="user-1", username="alice", vault_key_id="vault-1")
    hashed_user_id = hashlib.sha256(user.id.encode()).hexdigest()
    app = FastAPI()
    app.include_router(connected_accounts.router)
    app.dependency_overrides[connected_accounts.get_current_user] = lambda: user
    app.dependency_overrides[connected_accounts.get_directus_service] = lambda: directus
    client = TestClient(app)

    response = client.post(
        "/v1/connected-accounts/local-connectors",
        json=local_connector_payload(hashed_user_id) | {"bridge_password": "secret"},
    )

    assert response.status_code == 400
    assert "secret" not in response.text
    assert directus.rows == {}


@pytest.mark.anyio
async def test_local_connector_registration_rejects_nested_camelcase_credentials() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.core.api.app.models.user import User
    from backend.core.api.app.routes import connected_accounts

    directus = FakeDirectus()
    user = User(id="user-1", username="alice", vault_key_id="vault-1")
    hashed_user_id = hashlib.sha256(user.id.encode()).hexdigest()
    app = FastAPI()
    app.include_router(connected_accounts.router)
    app.dependency_overrides[connected_accounts.get_current_user] = lambda: user
    app.dependency_overrides[connected_accounts.get_directus_service] = lambda: directus
    client = TestClient(app)

    response = client.post(
        "/v1/connected-accounts/local-connectors",
        json=local_connector_payload(hashed_user_id)
        | {"connector_public_metadata": {"bridge_host": "localhost", "capabilities": ["read"], "imapPassword": "secret"}},
    )

    assert response.status_code == 400
    assert "secret" not in response.text
    assert directus.rows == {}


@pytest.mark.anyio
async def test_local_connector_heartbeat_requires_owner_session_and_active_account() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.core.api.app.models.user import User
    from backend.core.api.app.routes import connected_accounts

    directus = FakeDirectus()
    user = User(id="user-1", username="alice", vault_key_id="vault-1")
    hashed_user_id = hashlib.sha256(user.id.encode()).hexdigest()
    app = FastAPI()
    app.include_router(connected_accounts.router)
    app.dependency_overrides[connected_accounts.get_current_user] = lambda: user
    app.dependency_overrides[connected_accounts.get_directus_service] = lambda: directus
    client = TestClient(app)
    registration = client.post("/v1/connected-accounts/local-connectors", json=local_connector_payload(hashed_user_id)).json()
    session_id = registration["connector_session_id"]

    heartbeat = client.post(
        f"/v1/connected-accounts/local-connectors/{session_id}/heartbeat",
        json={"connected_account_id": "acct-local-1", "status": "online", "capabilities": ["read"], "health_summary": {"imap": "ok"}},
    )
    assert heartbeat.status_code == 200
    assert heartbeat.json()["accepted"] is True

    wrong_session = client.post(
        "/v1/connected-accounts/local-connectors/lcs_wrong/heartbeat",
        json={"connected_account_id": "acct-local-1", "status": "online", "capabilities": ["read"]},
    )
    assert wrong_session.status_code == 403

    escalated = client.post(
        f"/v1/connected-accounts/local-connectors/{session_id}/heartbeat",
        json={"connected_account_id": "acct-local-1", "status": "online", "capabilities": ["read", "write"]},
    )
    assert escalated.status_code == 400
    assert "capabilities" in escalated.text

    directus.rows["acct-local-1"]["connector_status"] = "revoked"
    revoked = client.post(
        f"/v1/connected-accounts/local-connectors/{session_id}/heartbeat",
        json={"connected_account_id": "acct-local-1", "status": "online", "capabilities": ["read"]},
    )
    assert revoked.status_code == 409


def test_heartbeat_expiry_marks_local_connectors_offline() -> None:
    from backend.core.api.app.services.connected_accounts_service import mark_expired_local_connectors_offline

    now = 2_000
    rows = [
        {"id": "active", "execution_mode": "local_connector", "connector_status": "online", "local_connector_deadline_at": now + 30},
        {"id": "expired", "execution_mode": "local_connector", "connector_status": "online", "local_connector_deadline_at": now - 1},
        {"id": "oauth", "execution_mode": "oauth", "connector_status": "online", "local_connector_deadline_at": now - 1},
    ]

    expired = mark_expired_local_connectors_offline(rows, now=now)

    assert expired == ["expired"]
    assert rows[0]["connector_status"] == "online"
    assert rows[1]["connector_status"] == "offline"
    assert rows[2]["connector_status"] == "online"


def test_offline_local_connector_request_fails_closed() -> None:
    from backend.core.api.app.services.connected_accounts_service import assert_local_connector_online

    assert_local_connector_online({"execution_mode": "local_connector", "connector_status": "online"})
    with pytest.raises(PermissionError, match="connector_offline"):
        assert_local_connector_online({"execution_mode": "local_connector", "connector_status": "offline"})


def test_local_connector_mail_read_request_contains_no_credentials() -> None:
    from backend.core.api.app.services.connected_accounts_service import build_local_connector_mail_read_request

    request = build_local_connector_mail_read_request(
        row={
            "id": "acct-local-1",
            "execution_mode": "local_connector",
            "connector_provider_id": "protonmail_bridge",
            "connector_status": "online",
            "local_connector_session_id": "lcs_1",
        },
        request_id="mail_search_1",
        query="invoice",
        mailbox="INBOX",
        start_date="2026-07-01",
        end_date="2026-07-15",
        limit=500,
    )

    assert request["type"] == "local_connector_request"
    assert request["action"] == "mail.search"
    assert request["arguments"]["limit"] == 50
    assert request["arguments"]["start_date"] == "2026-07-01"
    assert request["arguments"]["end_date"] == "2026-07-15"
    assert_no_secret_text(request)


@pytest.mark.anyio
async def test_mail_search_skill_routes_online_local_connector_without_self_hosted_bridge(monkeypatch) -> None:
    from types import SimpleNamespace

    from backend.apps.mail.skills import search_skill
    from backend.apps.mail.skills.search_skill import SearchSkill
    from backend.core.api.app.services.connected_accounts_service import LocalConnectorRequestResult

    async def fail_if_called(*_args: Any, **_kwargs: Any):
        raise AssertionError("self-hosted Proton Bridge config should not be used for local connector requests")

    dispatched_requests: list[dict[str, Any]] = []

    async def fake_dispatch_local_connector_request(*, user_id: str, request: dict[str, Any], timeout_seconds: int = 45):
        assert user_id == "user-1"
        dispatched_requests.append(request)
        return LocalConnectorRequestResult(
            request_id=request["request_id"],
            status="ok",
            result={"messages": [{"subject": "Invoice", "snippet": "No secrets here"}]},
        )

    async def identity_sanitize(**kwargs: Any):
        return kwargs["payload"]

    monkeypatch.setattr(search_skill, "get_protonmail_bridge_config", fail_if_called)
    monkeypatch.setattr(search_skill, "dispatch_local_connector_request", fake_dispatch_local_connector_request)
    monkeypatch.setattr(search_skill, "sanitize_long_text_fields_in_payload", identity_sanitize)
    skill = SearchSkill(
        app=SimpleNamespace(celery_producer=None),
        app_id="mail",
        skill_id="search",
        skill_name="Search Mail",
        skill_description="Search mail",
    )

    _request_id, payload, error = await skill._process_single_request(
        req={
            "query": "invoice",
            "start_date": "2026-07-01",
            "end_date": "2026-07-15",
            "limit": 4,
            "connected_account": {
                "id": "acct-local-1",
                "execution_mode": "local_connector",
                "connector_provider_id": "protonmail_bridge",
                "connector_status": "online",
                "local_connector_session_id": "lcs_1",
            },
        },
        request_id="req-1",
        user_id="user-1",
        secrets_manager=SimpleNamespace(),
        cache_service=SimpleNamespace(),
    )

    assert error is None
    assert payload["status"] == "completed"
    assert payload["result_count"] == 1
    assert payload["time_range"] == "2026-07-01 to 2026-07-15"
    assert payload["results"] == [{"subject": "Invoice", "snippet": "No secrets here"}]
    assert dispatched_requests[0]["action"] == "mail.search"
    assert dispatched_requests[0]["arguments"] == {
        "query": "invoice",
        "mailbox": None,
        "start_date": "2026-07-01",
        "end_date": "2026-07-15",
        "limit": 4,
    }
    assert_no_secret_text(payload)


@pytest.mark.anyio
async def test_local_connector_complete_request_rejects_unknown_result_and_secret_fields() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.core.api.app.models.user import User
    from backend.core.api.app.routes import connected_accounts

    directus = FakeDirectus()
    user = User(id="user-1", username="alice", vault_key_id="vault-1")
    hashed_user_id = hashlib.sha256(user.id.encode()).hexdigest()
    app = FastAPI()
    app.include_router(connected_accounts.router)
    app.dependency_overrides[connected_accounts.get_current_user] = lambda: user
    app.dependency_overrides[connected_accounts.get_directus_service] = lambda: directus
    client = TestClient(app)
    registration = client.post("/v1/connected-accounts/local-connectors", json=local_connector_payload(hashed_user_id)).json()
    session_id = registration["connector_session_id"]

    response = client.post(
        f"/v1/connected-accounts/local-connectors/{session_id}/complete-request",
        json={
            "connected_account_id": "acct-local-1",
            "request_id": "mail_search_1",
            "status": "ok",
            "result": {"messages": [{"subject": "Hello"}]},
        },
    )
    assert response.status_code == 404
    assert "not found or expired" in response.text

    secret_response = client.post(
        f"/v1/connected-accounts/local-connectors/{session_id}/complete-request",
        json={
            "connected_account_id": "acct-local-1",
            "request_id": "mail_search_2",
            "status": "ok",
            "result": {"imap_password": "secret"},
        },
    )
    assert secret_response.status_code == 400
    assert "secret" not in secret_response.text


@pytest.mark.anyio
async def test_local_connector_dispatch_resolves_completed_request(monkeypatch) -> None:
    import asyncio

    from backend.core.api.app.services import connected_accounts_service as service
    from backend.core.api.app.routes import websockets

    class FakeManager:
        async def broadcast_to_user_specific_event(self, *, user_id: str, event_name: str, payload: dict[str, Any]):
            assert user_id == "user-1"
            assert event_name == "local_connector_request"
            asyncio.create_task(service.complete_pending_local_connector_request(
                connector_session_id=payload["connector_session_id"],
                request_id=payload["request_id"],
                status="ok",
                result={"messages": [{"subject": "Invoice"}]},
                error_code=None,
                error_message=None,
            ))

    monkeypatch.setattr(websockets, "manager", FakeManager())

    result = await service.dispatch_local_connector_request(
        user_id="user-1",
        request={
            "type": "local_connector_request",
            "connector_session_id": "lcs_dispatch_test",
            "connected_account_id": "acct-local-1",
            "request_id": "mail_search_dispatch_test",
            "action": "mail.search",
            "arguments": {"query": "invoice", "limit": 1},
        },
        timeout_seconds=2,
    )

    assert result.status == "ok"
    assert result.result == {"messages": [{"subject": "Invoice"}]}


@pytest.mark.anyio
async def test_local_connector_dispatch_ignores_stale_cached_result(monkeypatch) -> None:
    import asyncio

    from backend.core.api.app.services import connected_accounts_service as service
    from backend.core.api.app.services.cache import CacheService
    from backend.core.api.app.routes import websockets

    request_id = "mail_search_stale_result_test"
    session_id = "lcs_stale_result_test"
    cache = CacheService()
    await cache.set(
        f"local_connector:result:{session_id}:{request_id}",
        {"request_id": request_id, "status": "ok", "result": {"messages": [{"subject": "STALE"}]}},
        ttl=60,
    )

    class FakeManager:
        async def broadcast_to_user_specific_event(self, *, user_id: str, event_name: str, payload: dict[str, Any]):
            asyncio.create_task(service.complete_pending_local_connector_request(
                connector_session_id=payload["connector_session_id"],
                request_id=payload["request_id"],
                status="ok",
                result={"messages": [{"subject": "Fresh"}]},
                error_code=None,
                error_message=None,
            ))

    monkeypatch.setattr(websockets, "manager", FakeManager())

    result = await service.dispatch_local_connector_request(
        user_id="user-1",
        request={
            "type": "local_connector_request",
            "connector_session_id": session_id,
            "connected_account_id": "acct-local-1",
            "request_id": request_id,
            "action": "mail.search",
            "arguments": {"query": "invoice", "limit": 1},
        },
        timeout_seconds=2,
    )

    assert result.result == {"messages": [{"subject": "Fresh"}]}


def local_connector_payload(hashed_user_id: str) -> dict[str, Any]:
    return {
        "id": "acct-local-1",
        "hashed_user_id": hashed_user_id,
        "encrypted_provider_type": "enc:provider",
        "provider_type_hash": hashlib.sha256(b"protonmail_bridge").hexdigest(),
        "encrypted_account_label": "enc:label",
        "encrypted_capabilities": "enc:caps",
        "encrypted_app_permissions": "enc:perms",
        "encrypted_account_directory_hint": "enc:hint",
        "execution_mode": "local_connector",
        "connector_provider_id": "protonmail_bridge",
        "connector_instance_id": "connector-1",
        "connector_status": "online",
        "connector_public_metadata": {"bridge_host": "localhost", "bridge_transport": "imap_smtp", "capabilities": ["read"]},
    }


def assert_no_secret_text(value: Any) -> None:
    serialized = str(value).lower()
    for forbidden in ["bridge-secret", "smtp-secret", "imap_password", "smtp_password", "bridge_password", "proton_password"]:
        assert forbidden not in serialized
