"""Regression coverage for the upload VM's scoped periodic Vault token."""

# contract-test-file: infrastructure
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from backend.upload.vault import setup_vault, token_maintenance


def _lookup_response(*, periodic: bool = True) -> dict:
    return {
        "data": {
            "ttl": 3600,
            "renewable": True,
            "policies": ["uploads-service"],
            "explicit_max_ttl": 0,
            "meta": {"uploads_token_kind": "periodic_v1"} if periodic else None,
        }
    }


@pytest.mark.asyncio
async def test_setup_replaces_legacy_token_with_scoped_periodic_token(monkeypatch, tmp_path):
    token_path = tmp_path / "api.token"
    token_path.write_text("legacy-token")
    monkeypatch.setattr(setup_vault, "API_TOKEN_FILE", str(token_path))
    monkeypatch.setattr(setup_vault, "vault_get", AsyncMock(return_value=_lookup_response(periodic=False)))
    create = AsyncMock(return_value={"auth": {"client_token": "periodic-token"}})
    monkeypatch.setattr(setup_vault, "vault_post", create)

    assert await setup_vault.create_or_reuse_api_token(None, "root-token") == "periodic-token"
    assert token_path.read_text() == "periodic-token"
    assert token_path.stat().st_mode & 0o777 == 0o600
    _, path, root_token, payload = create.await_args.args
    assert path == "auth/token/create"
    assert root_token == "root-token"
    assert payload["period"] == "168h"
    assert "ttl" not in payload
    assert payload["policies"] == ["uploads-service"]
    assert payload["no_default_policy"] is True
    assert payload["meta"]["uploads_token_kind"] == "periodic_v1"


@pytest.mark.asyncio
async def test_setup_reuses_valid_periodic_token(monkeypatch, tmp_path):
    token_path = tmp_path / "api.token"
    token_path.write_text("periodic-token")
    monkeypatch.setattr(setup_vault, "API_TOKEN_FILE", str(token_path))
    monkeypatch.setattr(setup_vault, "vault_get", AsyncMock(return_value=_lookup_response()))
    create = AsyncMock()
    monkeypatch.setattr(setup_vault, "vault_post", create)

    assert await setup_vault.create_or_reuse_api_token(None, "root-token") == "periodic-token"
    create.assert_not_awaited()


@pytest.mark.asyncio
async def test_setup_policy_grants_only_self_renewal(monkeypatch):
    update_policy = AsyncMock()
    monkeypatch.setattr(setup_vault, "vault_post", update_policy)

    await setup_vault.create_policy(None, "root-token")

    policy = update_policy.await_args.args[3]["policy"]
    assert 'path "auth/token/renew-self"' in policy
    assert 'capabilities = ["update"]' in policy
    assert 'path "auth/token/create"' not in policy
    assert 'path "kv/data/providers/*"' in policy


@pytest.mark.asyncio
async def test_renew_uses_only_scoped_token_and_self_endpoint(tmp_path):
    token_path = tmp_path / "api.token"
    token_path.write_text("scoped-token")
    requests = []

    def vault_api(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["X-Vault-Token"] == "scoped-token"
        if request.url.path.endswith("lookup-self"):
            return httpx.Response(200, json=_lookup_response())
        assert request.url.path.endswith("renew-self")
        return httpx.Response(200, json={"auth": {"renewable": True, "lease_duration": 604800}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(vault_api)) as client:
        ttl = await token_maintenance.renew_api_token(client, "http://vault:8200", str(token_path))

    assert ttl == 604800
    assert [request.method for request in requests] == ["GET", "POST"]


@pytest.mark.asyncio
async def test_renew_rejects_legacy_token_before_calling_renew_self(tmp_path):
    token_path = tmp_path / "api.token"
    token_path.write_text("legacy-token")
    requests = []

    def vault_api(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_lookup_response(periodic=False))

    async with httpx.AsyncClient(transport=httpx.MockTransport(vault_api)) as client:
        with pytest.raises(token_maintenance.TokenRenewalError, match="rerun vault-setup"):
            await token_maintenance.renew_api_token(client, "http://vault:8200", str(token_path))

    assert len(requests) == 1
    assert requests[0].url.path.endswith("lookup-self")


@pytest.mark.asyncio
async def test_renew_rejects_403_without_exposing_vault_response(tmp_path):
    token_path = tmp_path / "api.token"
    token_path.write_text("scoped-token")

    def vault_api(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="sensitive Vault response")

    async with httpx.AsyncClient(transport=httpx.MockTransport(vault_api)) as client:
        with pytest.raises(token_maintenance.TokenRenewalError) as error:
            await token_maintenance.renew_api_token(client, "http://vault:8200", str(token_path))

    assert "HTTP 403" in str(error.value)
    assert "sensitive" not in str(error.value)
    assert "scoped-token" not in str(error.value)


@pytest.mark.asyncio
async def test_renewal_loop_retries_and_cancels_cleanly(monkeypatch):
    attempts = 0
    retried = asyncio.Event()

    async def renew(*_args):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise token_maintenance.TokenRenewalError("temporary")
        retried.set()
        return 604800

    monkeypatch.setattr(token_maintenance, "renew_api_token", renew)
    monkeypatch.setattr(token_maintenance, "RENEW_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(token_maintenance, "RETRY_INTERVAL_SECONDS", 0.01)
    task = asyncio.create_task(token_maintenance.maintain_api_token("http://vault:8200", "/token"))
    try:
        await asyncio.wait_for(retried.wait(), timeout=1)
        assert attempts >= 2
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


def test_upload_compose_does_not_mount_root_token_into_app():
    import yaml

    upload_dir = Path(__file__).resolve().parents[1] / "upload"
    repo_root = upload_dir.parents[1]
    compose_files = (
        upload_dir / "docker-compose.yml",
        upload_dir / "docker-compose.selfhost.yml",
        repo_root / "frontend/packages/openmates-cli/templates/upload/docker-compose.yml",
    )
    for compose_file in compose_files:
        compose = yaml.safe_load(compose_file.read_text())
        app_volumes = compose["services"]["app-uploads"]["volumes"]
        setup_volumes = compose["services"]["vault-setup"]["volumes"]
        assert "vault-app-data:/vault-data:ro" in app_volumes
        assert "vault-setup-data:/vault-data:ro" not in app_volumes
        assert "vault-setup-data:/app/data" in setup_volumes
        assert "vault-app-data:/app/app-data" in setup_volumes
