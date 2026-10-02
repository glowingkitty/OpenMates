"""Focused first-party refresh overlap and revocation regression coverage."""
import asyncio
import hashlib
from types import SimpleNamespace
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.utils import session_refresh as refresh
from backend.core.api.app.services import session_security_state as state
from fastapi import HTTPException


class FakeDirectus:
    """Persist ledger writes, including the retirement performed by rotation."""
    def __init__(self, refresh_token=None, tokens=("old-secret",), user="user-1"):
        self.refresh_token = refresh_token or AsyncMock()
        self.rows = {}
        self.pair_rows = {}
        self.admin = SimpleNamespace(repair_cached_admin_status=AsyncMock())
        for index, token in enumerate(tokens):
            digest = state.token_hash(token)
            self.rows[digest] = {
                "id": f"source-{index}", "token_hash": digest, "user_id": user,
                "logical_session_id": f"logical-{index}", "expires_at": 9999999999,
                "retired": False, "revoked": False, "risk_pending": False,
            }

    async def get_items(self, collection, *, params, **_kwargs):
        rows = self.rows if collection == state.COLLECTION else self.pair_rows
        filters = params["filter"]
        return [deepcopy({"token_hash": digest, **row}) for digest, row in rows.items()
                if all((digest if key == "token_hash" else row.get(key)) == condition["_eq"]
                       for key, condition in filters.items())]

    async def create_item(self, collection, payload, **_kwargs):
        rows = self.rows if collection == state.COLLECTION else self.pair_rows
        digest = payload["token_hash"]
        if digest in rows:
            return False, None
        row = {"id": f"row-{len(rows)}", **deepcopy(payload)}
        rows[digest] = row
        return True, deepcopy(row)

    async def _update_item(self, collection, item_id, changes, **_kwargs):
        rows = self.rows if collection == state.COLLECTION else self.pair_rows
        for row in rows.values():
            if row["id"] == item_id:
                row.update(deepcopy(changes))
                return deepcopy(row)
        return None


class FakeRedis:
    def __init__(self):
        self.locks = {}

    async def set(self, key, value, *, nx, ex):
        if key in self.locks:
            return False
        self.locks[key] = value
        return True

    async def eval(self, _script, _key_count, key, owner):
        if self.locks.get(key) == owner:
            del self.locks[key]
            return 1
        return 0


class FakeCache:
    SESSION_TTL = 86400

    def __init__(self):
        self.values = {}
        self.redis = FakeRedis()

    @property
    async def client(self):
        return self.redis

    async def get(self, key):
        return self.values.get(key)

    async def get_user_by_token(self, token):
        return self.values.get(session_key(token))

    async def set(self, key, value, ttl):
        self.values[key] = value
        return True

    async def delete(self, key):
        self.values.pop(key, None)
        return True


def session_key(token):
    return "session:" + hashlib.sha256(token.encode()).hexdigest()


async def publish(cache, old_token, new_token, user="user-1"):
    cache.values[session_key(new_token)] = {"user_id": user}
    await refresh.complete_refresh_rotation(
        cache, old_refresh_token=old_token, new_refresh_token=new_token, user_id=user,
    )


# contract-test: direct surface=rest_api assertions=auth.session.lifecycle,auth.session.isolation
def test_overlapping_workers_share_rotation_and_wait_for_session_publication():
    async def run():
        cache = FakeCache()
        provider_started, provider_release = asyncio.Event(), asyncio.Event()
        auth = {"cookies": {"directus_refresh_token": "new-secret"}, "data": {"access_token": "access-secret"}}

        async def rotate(_token):
            provider_started.set()
            await provider_release.wait()
            return True, auth, "Token refreshed"

        directus = FakeDirectus(refresh_token=AsyncMock(side_effect=rotate))
        first = asyncio.create_task(refresh.refresh_session_token(cache, directus, "old-secret"))
        await provider_started.wait()
        second = asyncio.create_task(refresh.refresh_session_token(cache, directus, "old-secret"))
        await asyncio.sleep(0)
        provider_release.set()
        assert (await first)[1] == auth
        assert not second.done()
        # Session-linked state is published by the route only after validation.
        cache.values[session_key("old-secret")] = {"user_id": "user-1"}
        await publish(cache, "old-secret", "new-secret")
        assert (await second)[1] == auth
        assert directus.refresh_token.await_count == 1
        assert directus.rows[state.token_hash("old-secret")]["retired"] is True
        assert directus.rows[state.token_hash("new-secret")]["retired"] is False
        assert session_key("old-secret") not in cache.values
        encrypted_result = cache.values[refresh._keys("old-secret")[0]]
        assert "new-secret" not in encrypted_result
        assert "access-secret" not in encrypted_result
        # No credential substitution: knowing a cache digest cannot decrypt it.
        with pytest.raises(Exception):
            refresh._decode(hashlib.sha256(b"old-secret").hexdigest(), encrypted_result)

    asyncio.run(run())


# contract-test: direct surface=rest_api assertions=auth.session.lifecycle,auth.session.isolation
def test_short_overlap_does_not_restore_revoked_session_or_extend_grace(monkeypatch):
    async def run():
        cache = FakeCache()
        auth = {"cookies": {"directus_refresh_token": "new-secret"}}
        directus = FakeDirectus(refresh_token=AsyncMock(return_value=(True, auth, "OK")))
        clock = [100.0]
        monkeypatch.setattr(refresh.time, "time", lambda: clock[0])
        await refresh.refresh_session_token(cache, directus, "old-secret")
        await publish(cache, "old-secret", "new-secret")
        result_key = refresh._keys("old-secret")[0]
        original_deadline = refresh._decode("old-secret", cache.values[result_key])["expires_at"]

        clock[0] += 5
        assert (await refresh.refresh_session_token(cache, directus, "old-secret"))[0]
        await publish(cache, "old-secret", "new-secret")
        assert refresh._decode("old-secret", cache.values[result_key])["expires_at"] == original_deadline
        await cache.delete(session_key("new-secret"))
        assert (await refresh.refresh_session_token(cache, directus, "old-secret"))[0] is False
        assert directus.refresh_token.await_count == 1

        cache.values[session_key("new-secret")] = {"user_id": "user-1"}
        clock[0] = original_deadline + 1
        assert (await refresh.refresh_session_token(cache, directus, "old-secret"))[0] is False

    asyncio.run(run())


# contract-test: direct surface=rest_api assertions=auth.session.lifecycle,auth.session.isolation
def test_sibling_sessions_rotate_independently_and_invalid_credentials_stay_invalid():
    async def run():
        cache = FakeCache()
        directus = FakeDirectus(refresh_token=AsyncMock(return_value=(False, None, "Invalid token")), tokens=("browser-token", "cli-token"))
        results = await asyncio.gather(
            refresh.refresh_session_token(cache, directus, "browser-token"),
            refresh.refresh_session_token(cache, directus, "cli-token"),
        )
        assert all(result[0] is False for result in results)
        assert directus.refresh_token.await_count == 2
        assert (await refresh.refresh_session_token(cache, directus, "browser-token"))[0] is False
        assert directus.refresh_token.await_count == 2

    asyncio.run(run())


# contract-test: direct surface=rest_api assertions=auth.session.lifecycle
def test_transient_refresh_failure_is_503_and_does_not_poison_next_attempt():
    async def run():
        cache = FakeCache()
        directus = FakeDirectus(refresh_token=AsyncMock(side_effect=refresh.SessionRefreshUnavailable()))
        with pytest.raises(refresh.SessionRefreshUnavailable) as error:
            await refresh.refresh_session_token(cache, directus, "old-secret")
        assert error.value.status_code == 503
        assert refresh._keys("old-secret")[0] not in cache.values
        assert directus.rows[state.token_hash("old-secret")]["retired"] is False
        assert cache.redis.locks == {}
        directus.refresh_token.side_effect = None
        directus.refresh_token.return_value = (True, {"cookies": {"refresh_token": "new-secret"}}, "OK")
        assert (await refresh.refresh_session_token(cache, directus, "old-secret"))[0]

    asyncio.run(run())


# contract-test: direct surface=rest_api assertions=auth.session.lifecycle
@pytest.mark.parametrize("status_code", [401, 429, 503])
def test_directus_refresh_distinguishes_invalid_credentials_from_unavailability(monkeypatch, status_code):
    # Load the targeted service file without importing unrelated user deletion
    # dependencies (aiohttp is not installed in the lightweight unit runtime).
    import importlib.util
    import sys
    from pathlib import Path
    lookup_name = "backend.core.api.app.services.directus.user.user_lookup"
    monkeypatch.setitem(sys.modules, lookup_name, SimpleNamespace(hash_username=lambda value: value))
    source = Path(__file__).parents[1] / "core/api/app/services/directus/user/user_authentication.py"
    spec = importlib.util.spec_from_file_location("refresh_authentication_under_test", source)
    user_authentication = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(user_authentication)

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def post(self, *_args, **_kwargs):
            return SimpleNamespace(status_code=status_code)

    monkeypatch.setattr(user_authentication.httpx, "AsyncClient", lambda **_kwargs: Client())

    async def run():
        service = SimpleNamespace(base_url="https://invalid.example")
        if status_code == 401:
            result = await user_authentication.refresh_token(service, "old-secret")
            assert result[0] is False
        else:
            with pytest.raises(refresh.SessionRefreshUnavailable) as error:
                await user_authentication.refresh_token(service, "old-secret")
            assert error.value.status_code == 503

    asyncio.run(run())


# contract-test: direct surface=rest_api assertions=auth.session.lifecycle,auth.session.authoritative-enforcement,auth.session.isolation
@pytest.mark.parametrize("invalid", [
    "source_revoked", "source_expired", "successor_revoked", "successor_expired",
    "successor_retired", "foreign_owner", "foreign_logical_session", "extended_deadline",
    "missing_source", "missing_successor", "missing_link", "foreign_link",
    "expired_grace", "unpublished", "failed_result", "source_risk", "successor_risk",
])
def test_published_grace_cannot_bypass_durable_authority(monkeypatch, invalid):
    async def run():
        monkeypatch.setattr(refresh.time, "time", lambda: 1000)
        cache = FakeCache()
        auth = {"cookies": {"directus_refresh_token": "new-secret"}}
        directus = FakeDirectus(refresh_token=AsyncMock(return_value=(True, auth, "OK")))
        await refresh.refresh_session_token(cache, directus, "old-secret")
        await publish(cache, "old-secret", "new-secret")
        source = directus.rows[state.token_hash("old-secret")]
        successor = directus.rows[state.token_hash("new-secret")]
        result_key = refresh._keys("old-secret")[0]
        result = refresh._decode("old-secret", cache.values[result_key])
        if invalid == "source_revoked":
            source["revoked"] = True
        if invalid == "source_expired":
            source["expires_at"] = 1000
        if invalid == "successor_revoked":
            successor["revoked"] = True
        if invalid == "successor_expired":
            successor["expires_at"] = 1000
        if invalid == "successor_retired":
            successor["retired"] = True
        if invalid == "foreign_owner":
            successor["user_id"] = "other-user"
        if invalid == "foreign_logical_session":
            successor["logical_session_id"] = "sibling-session"
        if invalid == "extended_deadline":
            successor["expires_at"] += 1
        if invalid == "missing_source":
            del directus.rows[state.token_hash("old-secret")]
        if invalid == "missing_successor":
            del directus.rows[state.token_hash("new-secret")]
        if invalid == "missing_link":
            del cache.values[session_key("new-secret")]
        if invalid == "foreign_link":
            cache.values[session_key("new-secret")]["user_id"] = "other-user"
        if invalid == "expired_grace":
            result["expires_at"] = 1000
        if invalid == "unpublished":
            result["published"] = False
        if invalid == "failed_result":
            result["success"] = False
        if invalid == "source_risk":
            source["risk_pending"] = True
        if invalid == "successor_risk":
            successor["risk_pending"] = True
        cache.values[result_key] = refresh._encode("old-secret", result)
        # Exercise the result check directly too: a missing ledger source must
        # never inherit the permissive legacy-absence path.
        with pytest.raises(HTTPException) as denied:
            await refresh._published_successor(cache, directus, "old-secret", result, allow_risk=False)
        assert denied.value.status_code == (503 if invalid == "unpublished" else 401)
        with pytest.raises(HTTPException) as denied:
            await refresh.resolve_session_credential(cache, directus, "old-secret", allow_risk=False)
        assert denied.value.status_code == (503 if invalid == "unpublished" else 401)
        assert directus.refresh_token.await_count == 1
    asyncio.run(run())


# contract-test: direct surface=rest_api assertions=auth.session.lifecycle,auth.session.authoritative-enforcement,auth.pair-login.expiry,auth.pair-login.session-grant
@pytest.mark.parametrize("invalid", [None, "source_pending", "source_unacknowledged", "successor_pending", "successor_unacknowledged", "foreign_pair_owner", "extended_pair_deadline", "missing_pair_successor", "expired_pair"])
def test_published_grace_preserves_pair_deadline_and_ack(monkeypatch, invalid):
    async def run():
        monkeypatch.setattr(refresh.time, "time", lambda: 1000)
        cache = FakeCache()
        auth = {"cookies": {"directus_refresh_token": "new-secret"}}
        directus = FakeDirectus(refresh_token=AsyncMock(return_value=(True, auth, "OK")))
        directus.pair_rows[state.token_hash("old-secret")] = {
            "id": "pair-old", "user_id": "user-1", "expires_at": 2000,
            "pending_ack": False, "relay_acknowledged": True, "retired": False,
        }
        await refresh.refresh_session_token(cache, directus, "old-secret")
        await publish(cache, "old-secret", "new-secret")
        source = directus.pair_rows[state.token_hash("old-secret")]
        successor = directus.pair_rows[state.token_hash("new-secret")]
        if invalid == "source_pending":
            source["pending_ack"] = True
        if invalid == "source_unacknowledged":
            source["relay_acknowledged"] = False
        if invalid == "successor_pending":
            successor["pending_ack"] = True
        if invalid == "successor_unacknowledged":
            successor["relay_acknowledged"] = False
        if invalid == "foreign_pair_owner":
            successor["user_id"] = "other-user"
        if invalid == "extended_pair_deadline":
            successor["expires_at"] += 1
        if invalid == "missing_pair_successor":
            del directus.pair_rows[state.token_hash("new-secret")]
        if invalid == "expired_pair":
            source["expires_at"] = successor["expires_at"] = 1000
        if invalid:
            with pytest.raises(HTTPException) as denied:
                await refresh.resolve_session_credential(cache, directus, "old-secret")
            assert denied.value.status_code == 401
        else:
            assert await refresh.resolve_session_credential(cache, directus, "old-secret") == "new-secret"
            assert source["retired"] is True
            assert successor["expires_at"] == 2000
        assert directus.refresh_token.await_count == 1
    asyncio.run(run())


def _load_auth_guards(monkeypatch):
    import sys
    from pathlib import Path
    from importlib.util import spec_from_file_location, module_from_spec

    # Load these two real guards without pulling in the full server. Only cookie
    # domain configuration is isolated; all rotation and durable reads are real.
    root = Path(__file__).parents[1] / "core/api/app"
    common_spec = spec_from_file_location("rotation_common_under_test", root / "routes/auth_routes/auth_common.py")
    common = module_from_spec(common_spec)
    common_spec.loader.exec_module(common)
    monkeypatch.setitem(sys.modules, "backend.core.api.app.routes.auth_routes.auth_common", common)
    monkeypatch.setitem(sys.modules, "backend.core.api.app.routes.auth_routes.auth_utils", SimpleNamespace(get_cookie_domain=lambda _request: None))
    # Infrastructure tests elsewhere intentionally stub User; use its real model
    # for this regression so the required profile fields are still validated.
    user_spec = spec_from_file_location("rotation_user_under_test", root / "models/user.py")
    user_module = module_from_spec(user_spec)
    user_spec.loader.exec_module(user_module)
    monkeypatch.setitem(sys.modules, "backend.core.api.app.models.user", user_module)
    dependency_spec = spec_from_file_location("rotation_dependency_under_test", root / "routes/auth_routes/auth_dependencies.py")
    dependencies = module_from_spec(dependency_spec)
    dependency_spec.loader.exec_module(dependencies)

    return common, dependencies


# contract-test: direct surface=rest_api assertions=auth.session.lifecycle,auth.session.authoritative-enforcement,auth.session.isolation
@pytest.mark.parametrize("entry", ["session", "protected"])
@pytest.mark.parametrize("status", ["published", "revoked", "unpublished"])
def test_retired_cookie_resolves_through_authentication_entry_guards(monkeypatch, entry, status):
    from fastapi import Request, Response
    common, dependencies = _load_auth_guards(monkeypatch)

    async def run():
        cache = FakeCache()
        auth = {"cookies": {"directus_refresh_token": "new-secret"}}
        directus = FakeDirectus(refresh_token=AsyncMock(return_value=(True, auth, "OK")))
        await refresh.refresh_session_token(cache, directus, "old-secret")
        await publish(cache, "old-secret", "new-secret")
        cache.values[session_key("new-secret")].update(
            username="example", vault_key_id="test-vault-key", stay_logged_in=True,
        )
        successor = directus.rows[state.token_hash("new-secret")]
        if status == "revoked":
            successor["revoked"] = True
        if status == "unpublished":
            key = refresh._keys("old-secret")[0]
            result = refresh._decode("old-secret", cache.values[key])
            result["published"] = False
            cache.values[key] = refresh._encode("old-secret", result)
        request = Request({
            "type": "http", "method": "GET", "path": "/v1/auth/sessions",
            "headers": [(b"cookie", b"auth_refresh_token=old-secret")],
        })
        response = Response()
        async def invoke():
            if entry == "session":
                return await common.verify_authenticated_user(request, cache, directus, require_known_device=False)
            return await dependencies.get_current_user(
                directus_service=directus, cache_service=cache,
                refresh_token="old-secret", response=response, request=request,
            )
        if status != "published":
            with pytest.raises(HTTPException) as denied:
                await invoke()
            assert denied.value.status_code == (401 if status == "revoked" else 503)
            assert not response.headers.get("set-cookie")
        else:
            result = await invoke()
            if entry == "session":
                assert result[0] is True and result[2] == "new-secret"
            else:
                assert result.id == "user-1"
                cookie = response.headers["set-cookie"]
                assert "auth_refresh_token=new-secret" in cookie
                assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=lax" in cookie
                assert "Max-Age=2592000" in cookie
        assert directus.refresh_token.await_count == 1
        assert successor["expires_at"] == 9999999999
    asyncio.run(run())


# contract-test: direct surface=rest_api assertions=auth.session.lifecycle,auth.session.authoritative-enforcement
def test_provisional_result_fences_retirement_until_publication(monkeypatch):
    async def run():
        cache = FakeCache()
        auth = {"cookies": {"directus_refresh_token": "new-secret"}}
        directus = FakeDirectus(refresh_token=AsyncMock(return_value=(True, auth, "OK")))
        provisional, resume_retirement = asyncio.Event(), asyncio.Event()
        retired, resume_transfer = asyncio.Event(), asyncio.Event()
        original_transfer = refresh.transfer_session_state

        async def pause_after_retirement(*args):
            # The result must already be encrypted and fenced before retirement.
            encoded = await cache.get(refresh._keys("old-secret")[0])
            assert encoded and refresh._decode("old-secret", encoded)["published"] is False
            provisional.set()
            await resume_retirement.wait()
            result = await original_transfer(*args)
            retired.set()
            await resume_transfer.wait()
            return result

        monkeypatch.setattr(refresh, "transfer_session_state", pause_after_retirement)
        owner = asyncio.create_task(refresh.refresh_session_token(cache, directus, "old-secret"))
        await provisional.wait()
        assert directus.rows[state.token_hash("old-secret")]["retired"] is False
        with pytest.raises(HTTPException) as unavailable:
            await refresh.resolve_session_credential(cache, directus, "old-secret")
        assert unavailable.value.status_code == 503
        resume_retirement.set()
        await retired.wait()
        overlap = asyncio.create_task(refresh.refresh_session_token(cache, directus, "old-secret"))
        with pytest.raises(HTTPException) as unavailable:
            await refresh.resolve_session_credential(cache, directus, "old-secret")
        assert unavailable.value.status_code == 503
        assert directus.refresh_token.await_count == 1
        assert not overlap.done()
        resume_transfer.set()
        assert (await owner)[0] is True
        # The route has not published the session even though transfer completed.
        with pytest.raises(HTTPException) as unavailable:
            await refresh.resolve_session_credential(cache, directus, "old-secret")
        assert unavailable.value.status_code == 503
        await publish(cache, "old-secret", "new-secret")
        assert (await overlap)[1] == auth
        assert await refresh.resolve_session_credential(cache, directus, "old-secret") == "new-secret"
        assert directus.refresh_token.await_count == 1
    asyncio.run(run())


def _load_session_management(monkeypatch):
    """Isolate heavyweight service imports; route bodies and guards stay real."""
    import sys
    from pathlib import Path
    from importlib.util import spec_from_file_location, module_from_spec
    from pydantic import BaseModel
    from backend.tests.test_auth_session_revocation import _stub_auth_session_imports, FakeCompliance
    _stub_auth_session_imports(monkeypatch)
    dependencies = sys.modules["backend.core.api.app.routes.auth_routes.auth_dependencies"]
    dependencies.get_encryption_service = lambda: None
    monkeypatch.setitem(sys.modules, "backend.core.api.app.utils.encryption", SimpleNamespace(EncryptionService=object))
    monkeypatch.setitem(sys.modules, "backend.core.api.app.tasks.celery_config", SimpleNamespace(app=SimpleNamespace()))
    monkeypatch.setitem(sys.modules, "backend.core.api.app.routes.auth_routes.auth_utils", SimpleNamespace(verify_allowed_origin=lambda: None, get_cookie_domain=lambda _request: None))
    class LogoutResponse(BaseModel):
        success: bool
        message: str
    monkeypatch.setitem(sys.modules, "backend.core.api.app.schemas.auth", SimpleNamespace(LogoutResponse=LogoutResponse))
    monkeypatch.setattr(sys.modules["backend.core.api.app.services.compliance"], "ComplianceService", FakeCompliance)
    root = Path(__file__).parents[1] / "core/api/app/routes/auth_routes"
    modules = []
    for filename in ("auth_sessions", "auth_logout"):
        spec = spec_from_file_location(f"rotation_{filename}_under_test", root / f"{filename}.py")
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        modules.append(module)
    monkeypatch.setattr(modules[1], "generate_device_fingerprint_hash", lambda *_args, **_kwargs: ("test-device", None, None, None, None, None, None, None))
    return (*modules, FakeCompliance)


# contract-test: direct surface=rest_api assertions=auth.session.lifecycle,auth.session.authoritative-enforcement,auth.session.isolation
@pytest.mark.parametrize("operation", ["list", "register", "revoke_current", "logout_others", "logout"])
def test_rotated_cookie_management_uses_guard_verified_successor(monkeypatch, operation):
    from fastapi import Request, Response
    _, dependencies = _load_auth_guards(monkeypatch)
    sessions, logout, FakeCompliance = _load_session_management(monkeypatch)
    async def run():
        cache = FakeCache()
        cache.publish_event = AsyncMock()
        cache.get_chat_ids_versions = AsyncMock(return_value=[])
        cache.has_pending_orders = AsyncMock(return_value=True)
        auth = {"cookies": {"directus_refresh_token": "new-secret"}}
        directus = FakeDirectus(refresh_token=AsyncMock(return_value=(True, auth, "OK")), tokens=("old-secret", "sibling-secret"))
        directus.logout_user = AsyncMock(return_value=(True, "OK"))
        await refresh.refresh_session_token(cache, directus, "old-secret")
        await publish(cache, "old-secret", "new-secret")
        new_hash, old_hash, sibling_hash = (state.token_hash(token) for token in ("new-secret", "old-secret", "sibling-secret"))
        cache.values[session_key("new-secret")].update(username="example", vault_key_id="test-vault-key")
        cache.values[session_key("sibling-secret")] = {"user_id": "user-1"}
        cache.values["user_tokens:user-1"] = {
            new_hash: {"created_at": 1000, "connection_hash": "current-connection"},
            sibling_hash: {"created_at": 900, "connection_hash": "sibling-connection"},
        }
        request = Request({
            "type": "http", "method": "POST", "path": "/v1/auth/sessions",
            "headers": [(b"cookie", b"auth_refresh_token=old-secret")],
            "app": SimpleNamespace(state=SimpleNamespace(directus_service=directus)),
        })
        response = Response()
        user = await dependencies.get_current_user(
            directus_service=directus, cache_service=cache, refresh_token="old-secret", request=request, response=response,
        )
        assert request.state.auth_refresh_token == "new-secret"
        if operation == "list":
            result = await sessions.list_sessions(request, current_user=user, cache_service=cache, refresh_token="old-secret")
            assert [(item.session_id, item.is_current) for item in result.sessions] == [(new_hash[:12], True), (sibling_hash[:12], False)]
        elif operation == "register":
            result = await sessions.register_session_meta(request, sessions.RegisterMetaRequest(encrypted_meta="opaque-test-blob"), current_user=user, cache_service=cache, refresh_token="old-secret")
            assert result.success is True
            assert cache.values["user_tokens:user-1"][new_hash]["encrypted_meta"] == "opaque-test-blob"
        elif operation == "revoke_current":
            with pytest.raises(HTTPException) as denied:
                await sessions.revoke_session(request, new_hash[:12], current_user=user, cache_service=cache, compliance_service=FakeCompliance(), refresh_token="old-secret")
            assert denied.value.status_code == 400
            assert directus.rows[new_hash]["revoked"] is False
        elif operation == "logout_others":
            result = await sessions.logout_all_others(request, response, current_user=user, cache_service=cache, directus_service=directus, compliance_service=FakeCompliance(), refresh_token="old-secret")
            assert result.success is True
            assert directus.rows[new_hash]["revoked"] is False
            assert directus.rows[sibling_hash]["revoked"] is True
            assert set(cache.values["user_tokens:user-1"]) == {new_hash}
            event = cache.publish_event.await_args.kwargs["event_data"]
            assert event["exclude_connection_hash"] == "current-connection"
            assert await refresh.resolve_session_credential(cache, directus, "old-secret") == "new-secret"
        else:
            # Logout has no get_current_user dependency; it must independently
            # resolve the old credential before revoking and issuer logout.
            result = await logout.logout(request, Response(), directus_service=directus, cache_service=cache, encryption_service=None, refresh_token="old-secret", directus_refresh_token=None)
            assert result.success is True
            directus.logout_user.assert_awaited_once_with("new-secret")
            assert directus.rows[new_hash]["revoked"] is True
            assert directus.rows[old_hash]["revoked"] is True
            assert directus.rows[sibling_hash]["revoked"] is False
            assert set(cache.values["user_tokens:user-1"]) == {sibling_hash}
            for token in ("old-secret", "new-secret"):
                with pytest.raises(HTTPException) as denied:
                    await refresh.resolve_session_credential(cache, directus, token)
                assert denied.value.status_code == 401
        assert directus.refresh_token.await_count == 1
    asyncio.run(run())
