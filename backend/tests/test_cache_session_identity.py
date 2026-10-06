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


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=auth.session.lifecycle
async def test_stale_session_write_preserves_new_profile_image_url():
    cache = SessionExpiryCache()
    image_url = "/v1/users/alice/profile-image"
    await cache.set_user({"user_id": "alice", "profile_image_url": image_url})
    await cache.set_user({"user_id": "alice", "profile_image_url": None}, refresh_token="older-session")

    assert (await cache.get_user_by_token("older-session"))["profile_image_url"] == image_url


@pytest.mark.anyio
@pytest.mark.parametrize("case,expected", [
    ("credential_absent", "credential_absent"),
    ("link_absent", "link_absent"),
    ("link_invalid", "link_invalid"),
    ("profile_unavailable", "profile_unavailable"),
    ("profile_identity_rejected", "profile_identity_rejected"),
    ("lookup_failure", "lookup_failure"),
    ("healthy", None),
])
# contract-test: supporting surface=rest_api assertions=auth.session.lifecycle,auth.session.authoritative-enforcement
async def test_session_cache_miss_diagnostic_keeps_existing_decisions_and_omits_private_values(case, expected, caplog):
    import logging
    credential = "private-credential-canary"
    identity = "private-user-canary"

    class LookupCache(UserCacheMixin):
        SESSION_KEY_PREFIX = "session:"

        async def get(self, key):
            if case == "lookup_failure":
                raise RuntimeError("private-exception-canary")
            if case == "link_absent":
                return None
            if case == "link_invalid":
                return {"id": identity}
            return {"user_id": identity, "token_expiry": 123}

        async def get_user_by_id(self, user_id):
            assert user_id == identity
            if case == "profile_unavailable":
                return None
            if case == "profile_identity_rejected":
                return {"id": "other-private-user", "user_id": "other-private-user"}
            return {"id": identity, "user_id": identity, "private": "private-profile-canary"}

    with caplog.at_level(logging.WARNING):
        result = await LookupCache().get_user_by_token("" if case == "credential_absent" else credential)
    events = [r for r in caplog.records if getattr(r, "event_type", None) == "session_cache_lookup_miss"]
    assert len(events) == (0 if expected is None else 1)
    if expected is None:
        assert result["user_id"] == identity
        assert result["token_expiry"] == 123
    else:
        assert result is None
        event = events[0]
        assert event.miss_reason == expected
        message = event.getMessage()
        assert credential not in message and identity not in message
        assert "private-profile-canary" not in message
        assert "private-exception-canary" not in message


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=auth.session.authoritative-enforcement
async def test_session_cache_miss_logging_failure_preserves_link_rejection(monkeypatch):
    from backend.core.api.app.services import cache_user_mixin

    class MissingCache(UserCacheMixin):
        SESSION_KEY_PREFIX = "session:"

        async def get(self, key):
            return None

    def fail(*args, **kwargs):
        raise RuntimeError("diagnostic sink unavailable")

    monkeypatch.setattr(cache_user_mixin.logger, "warning", fail)
    assert await MissingCache().get_user_by_token("credential") is None
