# backend/tests/test_figma_oauth_adapter.py
#
# Tests for the Figma connected-account OAuth adapter: PKCE authorize URL with
# minimal scopes, confidential code exchange (Basic auth), one-time handoff,
# refresh exchange error mapping and registry wiring.
#
# Specification: specifications/features/app-skills/design-figma/specification.yml

from __future__ import annotations

import base64
import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from backend.tests.test_google_calendar_oauth_adapter import FakeCache, FakeEncryption


def import_route_module():
    from backend.tests.test_google_calendar_oauth_adapter import import_route_module as google_import

    google_import()  # installs and removes dependency stubs around the Google import
    from backend.core.api.app.routes import provider_oauth_figma

    return provider_oauth_figma


def make_client(cache: FakeCache):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.core.api.app.models.user import User

    route = import_route_module()
    from backend.core.api.app.services.limiter import limiter

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(route.router)
    user = User(id="user-1", username="alice", vault_key_id="vault-1")
    app.dependency_overrides[route.get_current_user] = lambda: user
    app.dependency_overrides[route.get_cache_service] = lambda: cache
    app.dependency_overrides[route.get_encryption_service] = lambda: FakeEncryption()
    app.state.allowed_origins = ["https://app.dev.openmates.org"]
    return TestClient(app), route


def _patch_credentials(monkeypatch, route):
    async def creds():
        return "figma-client-id", "figma-client-secret"

    monkeypatch.setattr(route, "get_figma_oauth_credentials", creds)


# contract-test: supporting surface=rest_api assertions=design-figma.connection.minimal-scopes,design-figma.connection.oauth
def test_figma_start_builds_authorize_url_with_minimal_scopes_and_s256(monkeypatch) -> None:
    monkeypatch.setenv("FIGMA_OAUTH_REDIRECT_URI", "https://api.dev.openmates.org/v1/provider-oauth/figma/callback")
    cache = FakeCache()
    client, route = make_client(cache)
    _patch_credentials(monkeypatch, route)

    response = client.post(
        "/v1/provider-oauth/figma/start",
        json={"capabilities": ["read"], "return_path": "/#settings/apps/design"},
        headers={"Origin": "https://app.dev.openmates.org"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["scopes"] == ["file_content:read", "current_user:read"]
    parsed = urlparse(payload["authorization_url"])
    params = parse_qs(parsed.query)
    assert parsed.netloc == "www.figma.com" and parsed.path == "/oauth"
    assert params["client_id"] == ["figma-client-id"]
    assert params["scope"] == ["file_content:read,current_user:read"]
    assert params["response_type"] == ["code"]
    assert params["code_challenge_method"] == ["S256"]
    stored = cache.values[route._state_key(params["state"][0])]
    assert params["code_challenge"] == [route._pkce_challenge(stored["code_verifier"])]
    assert stored["user_id"] == "user-1"
    assert stored["webapp_url"] == "https://app.dev.openmates.org"
    assert cache.ttls[route._state_key(params["state"][0])] == route.FIGMA_STATE_TTL_SECONDS
    assert "client_secret" not in payload["authorization_url"]


# contract-test: supporting surface=rest_api assertions=design-figma.connection.minimal-scopes
def test_figma_start_variables_capability_adds_variables_scope(monkeypatch) -> None:
    client, route = make_client(FakeCache())
    _patch_credentials(monkeypatch, route)

    response = client.post("/v1/provider-oauth/figma/start", json={"capabilities": ["read", "variables"]})

    assert response.status_code == 200
    assert response.json()["scopes"] == ["file_content:read", "current_user:read", "file_variables:read"]


# contract-test: supporting surface=rest_api assertions=design-figma.connection.minimal-scopes
@pytest.mark.parametrize("capabilities", [["variables"], ["read", "write"]])
def test_figma_start_rejects_missing_read_or_unknown_capability(monkeypatch, capabilities) -> None:
    client, route = make_client(FakeCache())
    _patch_credentials(monkeypatch, route)

    response = client.post("/v1/provider-oauth/figma/start", json={"capabilities": capabilities})

    assert response.status_code == 400


# contract-test: supporting surface=rest_api assertions=design-figma.connection.oauth
def test_figma_start_not_configured_returns_503(monkeypatch) -> None:
    from backend.shared.providers.figma.oauth import FigmaOAuthNotConfiguredError

    client, route = make_client(FakeCache())

    async def missing():
        raise FigmaOAuthNotConfiguredError("missing")

    monkeypatch.setattr(route, "get_figma_oauth_credentials", missing)

    response = client.post("/v1/provider-oauth/figma/start", json={"capabilities": ["read"]})

    assert response.status_code == 503
    assert response.json() == {"detail": "figma_oauth_not_configured"}


# contract-test: supporting surface=rest_api assertions=design-figma.connection.oauth
def test_figma_callback_rejects_unknown_state() -> None:
    client, _route = make_client(FakeCache())

    response = client.get("/v1/provider-oauth/figma/callback?code=c&state=nope", follow_redirects=False)

    assert response.status_code == 400


# contract-test: supporting surface=rest_api assertions=design-figma.connection.oauth
def test_figma_callback_creates_handoff_without_token_in_redirect_and_rejects_reuse(monkeypatch) -> None:
    cache = FakeCache()
    client, route = make_client(cache)
    seen: dict[str, object] = {}

    async def fake_exchange(*, code, code_verifier, redirect_uri):
        seen.update(code=code, code_verifier=code_verifier, redirect_uri=redirect_uri)
        return {"access_token": "secret-access", "refresh_token": "secret-refresh", "user_id_string": "u-1"}

    async def fake_me(access_token):
        assert access_token == "secret-access"
        return {"id": "u-1", "handle": "Ada", "email": "ada@example.org"}

    monkeypatch.setattr(route, "exchange_figma_authorization_code", fake_exchange)
    monkeypatch.setattr(route, "fetch_figma_current_user", fake_me)
    cache.values[route._state_key("state-1")] = {
        "user_id": "user-1",
        "capabilities": ["read"],
        "scopes": ["file_content:read", "current_user:read"],
        "code_verifier": "verifier-1",
        "redirect_uri": "https://api.dev.openmates.org/v1/provider-oauth/figma/callback",
        "return_path": "/#settings/apps/design",
        "webapp_url": "https://app.dev.openmates.org",
    }

    response = client.get("/v1/provider-oauth/figma/callback?code=code-1&state=state-1", follow_redirects=False)

    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith("https://app.dev.openmates.org/?oauth_handoff_id=oauth_handoff_")
    assert "secret-refresh" not in location and "secret-access" not in location
    assert seen["code_verifier"] == "verifier-1"
    handoff_keys = [key for key in cache.values if key.startswith("connected_account:oauth_handoff:")]
    assert len(handoff_keys) == 1
    cached = cache.values[handoff_keys[0]]
    assert cached["user_id"] == "user-1"
    assert "secret-refresh" not in str(cached)
    # The refresh-token bundle exists only inside the Vault-encrypted payload.
    envelope = cached["encrypted_handoff_payload"]
    assert envelope.startswith("enc:vault-1:")
    decrypted = json.loads(base64.b64decode(envelope.removeprefix("enc:vault-1:")))
    assert decrypted["provider_id"] == "figma"
    assert decrypted["refresh_token_bundle"]["refresh_token"] == "secret-refresh"
    assert decrypted["refresh_token_bundle"]["scope_context"]["scopes"] == ["file_content:read", "current_user:read"]

    reused = client.get("/v1/provider-oauth/figma/callback?code=code-1&state=state-1", follow_redirects=False)
    assert reused.status_code == 400


# contract-test: supporting surface=rest_api assertions=design-figma.connection.oauth
@pytest.mark.anyio
async def test_figma_code_exchange_uses_basic_auth_and_code_verifier(monkeypatch) -> None:
    from backend.shared.providers.figma import oauth

    async def creds():
        return "figma-client-id", "figma-client-secret"

    monkeypatch.setattr(oauth, "get_figma_oauth_credentials", creds)
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers["authorization"]
        captured["form"] = parse_qs(request.content.decode())
        return httpx.Response(200, json={"access_token": "a", "refresh_token": "r", "expires_in": 90 * 24 * 3600})

    result = await oauth.exchange_figma_authorization_code(
        code="code-1", code_verifier="verifier-1", redirect_uri="https://example.org/cb",
        transport=httpx.MockTransport(handler),
    )

    assert result["refresh_token"] == "r"
    assert captured["url"] == oauth.FIGMA_TOKEN_URL
    expected = base64.b64encode(b"figma-client-id:figma-client-secret").decode()
    assert captured["auth"] == f"Basic {expected}"
    form = captured["form"]
    assert form["code_verifier"] == ["verifier-1"]
    assert form["grant_type"] == ["authorization_code"]
    assert form["redirect_uri"] == ["https://example.org/cb"]


# contract-test: supporting surface=rest_api assertions=design-figma.execution.token-lifecycle
@pytest.mark.anyio
async def test_figma_refresh_exchange_returns_access_token_and_expiry(monkeypatch) -> None:
    from backend.shared.providers.figma import oauth

    async def creds():
        return "figma-client-id", "figma-client-secret"

    monkeypatch.setattr(oauth, "get_figma_oauth_credentials", creds)

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == oauth.FIGMA_REFRESH_URL
        assert parse_qs(request.content.decode()) == {"refresh_token": ["r-1"]}
        return httpx.Response(200, json={"access_token": "new-access", "token_type": "bearer", "expires_in": 3600})

    result = await oauth.exchange_figma_refresh_token(
        "r-1", {"scopes": ["file_content:read"]}, transport=httpx.MockTransport(handler),
    )

    assert result == {"access_token": "new-access", "expires_in": 3600}


# contract-test: supporting surface=rest_api assertions=design-figma.execution.token-lifecycle
@pytest.mark.anyio
@pytest.mark.parametrize(
    ("status", "body", "reconnect"),
    [(400, {"error": "invalid_grant"}, True), (401, {"message": "Invalid token"}, True), (503, {}, False)],
)
async def test_figma_refresh_error_maps_reconnect_required(monkeypatch, caplog, status, body, reconnect) -> None:
    from backend.shared.providers.figma import oauth

    async def creds():
        return "figma-client-id", "figma-client-secret"

    monkeypatch.setattr(oauth, "get_figma_oauth_credentials", creds)
    transport = httpx.MockTransport(lambda request: httpx.Response(status, json=body))

    with caplog.at_level("WARNING"), pytest.raises(oauth.FigmaOAuthTokenExchangeError) as exc_info:
        await oauth.exchange_figma_refresh_token("secret-refresh-token", {}, transport=transport)

    assert exc_info.value.provider_id == "figma"
    assert exc_info.value.reconnect_required is reconnect
    assert "secret-refresh-token" not in str(exc_info.value)
    assert "secret-refresh-token" not in caplog.text


# contract-test: supporting surface=rest_api assertions=design-figma.connection.oauth
@pytest.mark.anyio
async def test_figma_credentials_missing_raises_not_configured() -> None:
    from backend.shared.providers.figma import oauth
    from backend.tests.test_google_calendar_oauth_adapter import FakeSecretsManager

    with pytest.raises(oauth.FigmaOAuthNotConfiguredError):
        await oauth.get_figma_oauth_credentials(FakeSecretsManager({}))

    manager = FakeSecretsManager(
        {
            ("kv/data/providers/figma", "oauth_client_id"): "id",
            ("kv/data/providers/figma", "oauth_client_secret"): "secret",
        }
    )
    assert await oauth.get_figma_oauth_credentials(manager) == ("id", "secret")


# contract-test: supporting surface=rest_api assertions=design-figma.execution.token-lifecycle
def test_figma_registry_entries() -> None:
    from backend.shared.providers.figma.oauth import exchange_figma_refresh_token
    from backend.shared.python_utils import connected_account_registry as registry

    config = registry.connected_account_skill_config("design", "get_design")
    assert (config.provider_id, config.action, config.scope_kind) == ("figma", "read", "provider_account")
    assert registry.exchange_refresh_token_for_provider("figma") is exchange_figma_refresh_token
    assert registry.normalize_connected_account_provider_id("figma") == "figma"
    assert registry.normalize_connected_account_app_id("design") == "design"
    assert registry.is_connected_account_action_allowed("design", "figma", "read")
    assert registry.action_scope_for_request({}, action="read", config=config) == {"provider": "figma"}
