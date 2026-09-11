"""Regression coverage for canonical cached session identity.

Cookie-authenticated REST and WebSocket requests must resolve the same user ID.
The session link is canonical even when a legacy or partial cache write left
conflicting identity fields in the cached profile.
"""

import pytest

from backend.core.api.app.services.cache_user_mixin import UserCacheMixin, canonical_session_user_id


class FakeCache(UserCacheMixin):
    SESSION_KEY_PREFIX = "session:"

    def __init__(self, session_data=None):
        self.session_data = session_data if session_data is not None else {"user_id": "canonical-user"}

    async def get(self, key):
        if key.startswith("session:"):
            return self.session_data
        if key == "user:canonical-user":
            return {
                "user_id": "stale-user",
                "id": "stale-user",
                "username": "cached-profile",
            }
        raise AssertionError(f"Unexpected cache key: {key}")

    async def get_user_by_id(self, user_id):
        return await self.get(f"user:{user_id}")


# contract-test: supporting surface=rest_api assertions=auth.session.lifecycle
def test_websocket_session_identity_ignores_profile_fields_and_supports_legacy_links():
    assert canonical_session_user_id({"user_id": "canonical-user", "profile_user_id": "stale-user"}) == "canonical-user"
    assert canonical_session_user_id("legacy-canonical-user") == "legacy-canonical-user"
    assert canonical_session_user_id({"user_id": ""}) is None
    assert canonical_session_user_id({"id": "untrusted-profile-id"}) is None
    assert canonical_session_user_id(None) is None


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=auth.session.lifecycle
async def test_session_link_identity_rejects_stale_cached_profile_identity():
    cached_user = await FakeCache().get_user_by_token("refresh-token")

    assert cached_user is None


@pytest.mark.anyio
@pytest.mark.parametrize("session_data", [{"user_id": 123}, {"id": "profile-only"}, [], ""])
# contract-test: supporting surface=rest_api assertions=auth.session.lifecycle
async def test_cache_lookup_rejects_malformed_session_identity(session_data):
    assert await FakeCache(session_data).get_user_by_token("refresh-token") is None


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=auth.session.lifecycle
async def test_cache_write_uses_explicit_canonical_identity():
    class WriteCache(UserCacheMixin):
        USER_KEY_PREFIX = "user:"
        SESSION_KEY_PREFIX = "session:"
        USER_TTL = 3600
        SESSION_TTL = 3600

        def __init__(self):
            self.saved = {}

        async def get(self, _key):
            return None

        async def set(self, key, value, ttl=None):
            self.saved[key] = value
            return True

    cache = WriteCache()
    await cache.set_user(
        {"user_id": "stale-user", "id": "stale-user", "username": "cached-profile"},
        user_id="canonical-user",
        refresh_token="refresh-token",
    )

    assert cache.saved["user:canonical-user"]["user_id"] == "canonical-user"
    assert cache.saved["user:canonical-user"]["id"] == "canonical-user"
    assert cache.saved[next(key for key in cache.saved if key.startswith("session:"))] == {
        "user_id": "canonical-user"
    }


class SessionExpiryCache(UserCacheMixin):
    USER_KEY_PREFIX = "user:"
    SESSION_KEY_PREFIX = "session:"
    USER_TTL = SESSION_TTL = 3600

    def __init__(self):
        self.saved = {}

    async def get(self, key):
        import copy
        return copy.deepcopy(self.saved.get(key))

    async def set(self, key, value, ttl=None):
        import copy
        self.saved[key] = copy.deepcopy(value)
        return True

    async def get_user_by_id(self, user_id):
        return await self.get(f"user:{user_id}")


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=auth.session.lifecycle
async def test_refresh_expiry_is_isolated_between_same_account_sessions():
    cache = SessionExpiryCache()
    await cache.set_user({"user_id": "alice", "token_expiry": 100}, refresh_token="old-profile")
    await cache.set_user({"user_id": "alice", "token_expiry": 200}, refresh_token="new-profile")
    assert (await cache.get_user_by_token("old-profile"))["token_expiry"] == 100
    assert (await cache.get_user_by_token("new-profile"))["token_expiry"] == 200
    await cache.set_user({"user_id": "alice", "username": "alice"}, refresh_token="old-profile")
    assert (await cache.get_user_by_token("old-profile"))["token_expiry"] == 100


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=auth.session.lifecycle
async def test_legacy_session_cannot_borrow_another_sessions_refresh_expiry():
    import hashlib
    cache = SessionExpiryCache()
    cache.saved["user:alice"] = {"user_id": "alice", "id": "alice", "token_expiry": 9999999999}
    cache.saved["session:" + hashlib.sha256(b"legacy").hexdigest()] = {"user_id": "alice"}
    assert (await cache.get_user_by_token("legacy"))["token_expiry"] == 0
