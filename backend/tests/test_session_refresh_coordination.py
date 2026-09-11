"""Focused first-party refresh overlap and revocation regression coverage."""
import asyncio
import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.utils import session_refresh as refresh


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
    def __init__(self):
        self.values = {}
        self.redis = FakeRedis()

    @property
    async def client(self):
        return self.redis

    async def get(self, key):
        return self.values.get(key)

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

        directus = SimpleNamespace(refresh_token=AsyncMock(side_effect=rotate))
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
        directus = SimpleNamespace(refresh_token=AsyncMock(return_value=(True, auth, "OK")))
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
        directus = SimpleNamespace(refresh_token=AsyncMock(return_value=(False, None, "Invalid token")))
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
        directus = SimpleNamespace(refresh_token=AsyncMock(side_effect=refresh.SessionRefreshUnavailable()))
        with pytest.raises(refresh.SessionRefreshUnavailable) as error:
            await refresh.refresh_session_token(cache, directus, "old-secret")
        assert error.value.status_code == 503
        assert cache.values == {}
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
