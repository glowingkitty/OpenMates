"""Owner assertions precede refresh rotation, cache writes and upload authentication.

Purpose: a mismatched X-OpenMates-Expected-Principal must change nothing on the
server (no Directus refresh, no cache/ledger/cookie effect), and the upload
service must forward the assertion to /internal/validate-token, which applies
the same closed refusal.
Run: python3 -m pytest backend/tests/test_session_owner_refresh_and_uploads.py -q
"""
import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from backend.tests.test_auth_common import _import_auth_common
from backend.tests.test_auth_dependencies import _stub_auth_dependency_imports

OWNER = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
MISMATCH = {"error": "session_principal_mismatch"}


def _request(expected=None, cookie=None):
    headers = [] if expected is None else [(b"x-openmates-expected-principal", expected.encode())]
    if cookie:
        headers.append((b"cookie", f"auth_refresh_token={cookie}".encode()))
    return Request({"type": "http", "headers": headers})


def _ledger(monkeypatch, owner):
    from backend.core.api.app.services import session_security_state
    reads = []

    async def get_session_state(_directus, digest, **_kwargs):
        reads.append(digest)
        return {"user_id": owner} if owner else None
    monkeypatch.setattr(session_security_state, "get_session_state", get_session_state)
    return reads


# contract-test: direct surface=rest_api assertions=owner-consistency.http.refuse-before-effect
@pytest.mark.asyncio
@pytest.mark.parametrize("ledger_owner", [OTHER, None])
async def test_cache_miss_mismatch_never_rotates_or_caches(monkeypatch, ledger_owner):
    _stub_auth_dependency_imports(monkeypatch)
    from backend.core.api.app.routes.auth_routes import auth_dependencies as auth

    async def resolved(_cache, _directus, token, **_kwargs):
        return token
    monkeypatch.setattr(auth, "resolve_session_credential", resolved)
    refresh = AsyncMock()
    monkeypatch.setattr(auth, "refresh_session_token", refresh)
    reads = _ledger(monkeypatch, ledger_owner)
    cache = SimpleNamespace(get_user_by_token=AsyncMock(return_value=None), set_user=AsyncMock())
    with pytest.raises(HTTPException) as error:
        await auth.get_current_user(SimpleNamespace(), cache, "cookie-b", SimpleNamespace(), _request(OWNER))
    assert error.value.status_code == 403 and error.value.detail == MISMATCH
    assert reads == [hashlib.sha256(b"cookie-b").hexdigest()]
    refresh.assert_not_awaited()
    cache.set_user.assert_not_awaited()


# contract-test: direct surface=rest_api assertions=owner-consistency.http.refuse-before-effect
@pytest.mark.asyncio
async def test_cache_miss_matching_owner_and_legacy_absence_proceed_to_refresh(monkeypatch):
    _stub_auth_dependency_imports(monkeypatch)
    from backend.core.api.app.routes.auth_routes import auth_dependencies as auth

    async def resolved(_cache, _directus, token, **_kwargs):
        return token
    monkeypatch.setattr(auth, "resolve_session_credential", resolved)
    refresh = AsyncMock(return_value=(False, None, "synthetic-expired"))
    monkeypatch.setattr(auth, "refresh_session_token", refresh)
    cache = SimpleNamespace(get_user_by_token=AsyncMock(return_value=None))
    for expected, owner in [(OWNER, OWNER), (None, None)]:
        reads = _ledger(monkeypatch, owner)
        refresh.reset_mock()
        with pytest.raises(HTTPException) as error:
            await auth.get_current_user(SimpleNamespace(), cache, "cookie-a", SimpleNamespace(), _request(expected))
        assert error.value.status_code == 401  # reached the unchanged refresh path
        refresh.assert_awaited_once()
        assert reads == ([hashlib.sha256(b"cookie-a").hexdigest()] if expected else [])


# contract-test: direct surface=rest_api assertions=owner-consistency.http.refuse-before-effect
@pytest.mark.asyncio
async def test_cache_hit_mismatch_precedes_admin_repair_ledger_and_cookie_effects(monkeypatch):
    _stub_auth_dependency_imports(monkeypatch)
    from backend.core.api.app.routes.auth_routes import auth_dependencies as auth

    async def resolved(_cache, _directus, _token, **_kwargs):
        return "rotated-b"
    monkeypatch.setattr(auth, "resolve_session_credential", resolved)
    legacy = AsyncMock()
    preserve = AsyncMock()
    publish = AsyncMock()
    monkeypatch.setattr(auth, "ensure_legacy_session_state", legacy)
    monkeypatch.setattr(auth, "preserve_rotated_session_metadata", preserve)
    monkeypatch.setattr(auth, "queue_rotated_session_cookie", publish)
    cache = SimpleNamespace(get_user_by_token=AsyncMock(return_value={
        "user_id": OTHER, "username": "synthetic", "vault_key_id": "synthetic"}))
    directus = SimpleNamespace(admin=SimpleNamespace(repair_cached_admin_status=AsyncMock()))
    with pytest.raises(HTTPException) as error:
        await auth.get_current_user(directus, cache, "cookie-b", SimpleNamespace(), _request(OWNER))
    assert error.value.detail == MISMATCH
    directus.admin.repair_cached_admin_status.assert_not_awaited()
    legacy.assert_not_awaited()
    preserve.assert_not_awaited()
    publish.assert_not_awaited()


# contract-test: direct surface=rest_api assertions=owner-consistency.http.refuse-before-effect
@pytest.mark.asyncio
async def test_session_common_fallback_mismatch_never_rotates(monkeypatch):
    auth = _import_auth_common(monkeypatch)
    refresh = AsyncMock()
    monkeypatch.setattr(auth, "refresh_session_token", refresh)
    reads = _ledger(monkeypatch, OTHER)
    cache = SimpleNamespace(get_user_by_token=AsyncMock(return_value=None), set_user=AsyncMock())
    request = _request(OWNER, cookie="cookie-b")
    request.state.auth_refresh_token = None
    with pytest.raises(HTTPException) as error:
        await auth.verify_authenticated_user(request, cache, SimpleNamespace(), require_known_device=False)
    assert error.value.detail == MISMATCH
    assert reads == [hashlib.sha256(b"cookie-b").hexdigest()]
    refresh.assert_not_awaited()
    cache.set_user.assert_not_awaited()


# contract-test: direct surface=rest_api assertions=owner-consistency.uploads.forwarded
@pytest.mark.asyncio
@pytest.mark.parametrize("expected,allowed", [(None, True), (OWNER, True), (OTHER, False)])
async def test_internal_validate_token_applies_forwarded_owner_assertion(expected, allowed):
    from backend.core.api.app.routes import internal_api
    headers = [(b"x-refresh-token", b"cookie-a")]
    if expected:
        headers.append((b"x-openmates-expected-principal", expected.encode()))
    request = Request({"type": "http", "headers": headers})
    cache = SimpleNamespace(get_user_by_token=AsyncMock(return_value={
        "user_id": OWNER, "vault_key_id": "synthetic-key", "username": "synthetic"}))
    if allowed:
        result = await internal_api.validate_token_route(request, cache, SimpleNamespace())
        assert result.user_id == OWNER
    else:
        with pytest.raises(HTTPException) as error:
            await internal_api.validate_token_route(request, cache, SimpleNamespace())
        assert error.value.status_code == 403 and error.value.detail == MISMATCH


class _FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body
        self.text = "synthetic"

    def json(self):
        if self._body is None:
            raise ValueError("not json")
        return self._body


def _fake_client(monkeypatch, route, response, sent):
    class Client:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def get(self, url, headers):
            sent.append((url, list(headers)))
            return response
    monkeypatch.setattr(route.httpx, "AsyncClient", Client)
    monkeypatch.setattr(route, "_get_core_api_credentials", lambda _request: ("http://core.invalid", "internal-synthetic"))


# contract-test: direct surface=rest_api assertions=owner-consistency.uploads.forwarded
@pytest.mark.asyncio
@pytest.mark.parametrize("values", [[], [OWNER], [OWNER, OTHER]])
async def test_upload_service_forwards_every_assertion_value_unchanged(monkeypatch, values):
    from backend.upload.routes import upload_route as route
    sent = []
    _fake_client(monkeypatch, route, _FakeResponse(200, {"user_id": OWNER}), sent)
    request = Request({"type": "http", "headers": [(b"x-openmates-expected-principal", v.encode()) for v in values]})
    assert await route.get_authenticated_user(request, "cookie-a") == {"user_id": OWNER}
    forwarded = [v for k, v in sent[0][1] if k == route.EXPECTED_PRINCIPAL_HEADER]
    assert forwarded == values
    assert ("X-Refresh-Token", "cookie-a") in sent[0][1]


# contract-test: direct surface=rest_api assertions=owner-consistency.uploads.forwarded
@pytest.mark.asyncio
@pytest.mark.parametrize("response,status", [
    (_FakeResponse(403, {"detail": MISMATCH}), 403),
    (_FakeResponse(403, {"detail": "Forbidden"}), 502),
    (_FakeResponse(403, None), 502),
])
async def test_upload_service_relays_only_the_closed_mismatch_refusal(monkeypatch, response, status):
    from backend.upload.routes import upload_route as route
    _fake_client(monkeypatch, route, response, [])
    request = Request({"type": "http", "headers": [(b"x-openmates-expected-principal", OWNER.encode())]})
    with pytest.raises(HTTPException) as error:
        await route.get_authenticated_user(request, "cookie-b")
    assert error.value.status_code == status
    if status == 403:
        assert error.value.detail == MISMATCH


# contract-test: direct surface=rest_api assertions=owner-consistency.uploads.forwarded
@pytest.mark.asyncio
async def test_upload_service_refuses_non_ascii_assertion_without_core_call(monkeypatch):
    from backend.upload.routes import upload_route as route
    sent = []
    _fake_client(monkeypatch, route, _FakeResponse(200, {"user_id": OWNER}), sent)
    request = Request({"type": "http", "headers": [(b"x-openmates-expected-principal", "\u00e9".encode("latin-1"))]})
    with pytest.raises(HTTPException) as error:
        await route.get_authenticated_user(request, "cookie-a")
    assert error.value.status_code == 403 and error.value.detail == MISMATCH
    assert sent == []
