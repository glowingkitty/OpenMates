"""Presence leases distinguish human foreground activity from transport activity."""
# contract-test-file: infrastructure

import asyncio
import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

from backend.core.api.app.services.notification_presence import (
    LEASE_SECONDS, classify_lifecycle_client, clear_presence, has_active_human,
    is_message_viewed, mark_message_viewed, refresh_legacy_apple_presence_on_message, report_presence,
)
from backend.core.api.app.routes.handlers.websocket_handlers.notification_read_receipt_handler import handle_notification_read_receipt


class Pipeline:
    def __init__(self, client):
        self.client = client

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass

    def set(self, key, value, ex=None):
        self.client.values[key] = value

    def zadd(self, key, mapping):
        self.client.scores.setdefault(key, {}).update(mapping)

    def expire(self, key, seconds):
        pass

    async def execute(self):
        pass


class Cache:
    def __init__(self):
        self.values = {}
        self.scores = {}
        self.client = self

    def pipeline(self, transaction=True):
        return Pipeline(self)

    async def set(self, key, value, ex=None):
        self.values[key] = value

    async def delete(self, key):
        self.values.pop(key, None)

    async def zrem(self, index, key):
        self.scores.get(index, {}).pop(key, None)

    async def zremrangebyscore(self, index, minimum, maximum):
        for key, score in list(self.scores.get(index, {}).items()):
            if score <= maximum:
                del self.scores[index][key]

    async def zrangebyscore(self, index, minimum, maximum):
        cutoff = float(minimum.lstrip("("))
        return [key for key, score in self.scores.get(index, {}).items() if score > cutoff]

    async def mget(self, keys):
        return [self.values.get(key) for key in keys]

    async def exists(self, key):
        return key in self.values


class CacheService:
    def __init__(self):
        self._client = Cache()

    @property
    async def client(self):
        return self._client


# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled
def test_lifecycle_client_requires_explicit_type_or_established_apple_headers(monkeypatch):
    apple_headers = {
        "user-agent": "OpenMates-Apple/1.2.3",
        "x-openmates-client": "ios",
        "x-openmates-bundle-id": "org.openmates.app",
    }
    assert classify_lifecycle_client({}, apple_headers) == ("apple", True)
    for device in ("macos", "watchos"):
        assert classify_lifecycle_client({}, {**apple_headers, "x-openmates-client": device}) == ("apple", True)
    for explicit in ("web", "apple", "cli"):
        assert classify_lifecycle_client({"client_type": explicit}, {}) == (explicit, False)
    assert classify_lifecycle_client({"client_type": "web"}, apple_headers) == ("web", False)
    for malformed in ("unknown", None, [], ""):
        assert classify_lifecycle_client({"client_type": malformed}, apple_headers) == ("automation", False)
    assert classify_lifecycle_client({}, {}) == ("automation", False)
    assert classify_lifecycle_client({}, {"origin": "https://openmates.org"}) == ("automation", False)
    assert classify_lifecycle_client({}, {**apple_headers, "user-agent": "OpenMates-Apple"}) == ("automation", False)
    assert classify_lifecycle_client({}, {**apple_headers, "x-openmates-client": "sdk"}) == ("automation", False)
    assert classify_lifecycle_client({}, {**apple_headers, "x-openmates-bundle-id": ""}) == ("automation", False)
    monkeypatch.setenv("OPENMATES_IOS_BUNDLE_ID", "org.openmates.app")
    assert classify_lifecycle_client({}, {**apple_headers, "x-openmates-bundle-id": "other.app"}) == ("automation", False)


# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled
def test_legacy_apple_application_message_renews_only_declared_foreground_lease():
    async def scenario():
        cache = CacheService()
        await report_presence(cache, "u", "legacy-apple", "apple", True, now=100)
        assert await has_active_human(cache, "u", "chat", now=100 + LEASE_SECONDS - 1)
        assert not await has_active_human(cache, "u", "chat", now=100 + LEASE_SECONDS)

        await report_presence(cache, "u", "legacy-apple", "apple", True, now=200)
        await refresh_legacy_apple_presence_on_message(cache, "u", "legacy-apple", True, now=250)
        assert await has_active_human(cache, "u", "chat", now=200 + LEASE_SECONDS + 1)
        assert not await has_active_human(cache, "u", "chat", now=250 + LEASE_SECONDS)

        await report_presence(cache, "u", "legacy-apple", "apple", False, now=400)
        await refresh_legacy_apple_presence_on_message(cache, "u", "legacy-apple", False, now=420)
        assert not await has_active_human(cache, "u", "chat", now=421)

    asyncio.run(scenario())


# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled
def test_human_presence_is_fresh_and_scoped():
    async def scenario():
        cache = CacheService()
        await report_presence(cache, "u", "web", "web", True, now=100)
        assert await has_active_human(cache, "u", "any-chat", now=101)
        await report_presence(cache, "u", "web", "web", False, now=102)
        assert not await has_active_human(cache, "u", "any-chat", now=103)

        await report_presence(cache, "u", "cli", "cli", True, interactive=True, chat_id="chat-a", now=100)
        assert await has_active_human(cache, "u", "chat-a", now=101)
        assert not await has_active_human(cache, "u", "chat-b", now=101)
        assert not await has_active_human(cache, "u", "chat-a", now=100 + LEASE_SECONDS)

        await report_presence(cache, "u", "automation", "cli", True, interactive=False, chat_id="chat-a", now=200)
        assert not await has_active_human(cache, "u", "chat-a", now=201)
        await report_presence(cache, "u", "apple", "apple", True, now=200)
        assert await has_active_human(cache, "u", "chat-b", now=201)
        await clear_presence(cache, "u", "apple")
        assert not await has_active_human(cache, "u", "chat-b", now=201)

        # One expired connection must not erase a newer device's live lease.
        await report_presence(cache, "u", "old-web", "web", True, now=300)
        await report_presence(cache, "u", "new-apple", "apple", True, now=350)
        assert await has_active_human(cache, "u", "chat-b", now=300 + LEASE_SECONDS)
        await clear_presence(cache, "u", "new-apple")
        assert not await has_active_human(cache, "u", "chat-b", now=300 + LEASE_SECONDS)

    asyncio.run(scenario())


# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled
def test_view_receipt_is_message_specific():
    async def scenario():
        cache = CacheService()
        await mark_message_viewed(cache, "u", "chat-a", "message-1")
        assert await is_message_viewed(cache, "u", "chat-a", "message-1")
        assert not await is_message_viewed(cache, "u", "chat-a", "message-2")
        assert not await is_message_viewed(cache, "u", "chat-b", "message-1")
        assert not await is_message_viewed(cache, "other-user", "chat-a", "message-1")

    asyncio.run(scenario())


# contract-test: supporting surface=rest_api assertions=notifications.delivery.email-enabled
def test_view_receipt_succeeds_only_with_access_and_a_written_cache_marker():
    async def scenario():
        cache = CacheService()
        directus = SimpleNamespace(chat=SimpleNamespace(get_chat_metadata=AsyncMock(return_value={
            "hashed_user_id": hashlib.sha256(b"u").hexdigest(),
        })))
        arguments = dict(directus_service=directus, cache_service=cache, user_id="u",
                         payload={"chat_id": "chat-a", "message_id": "message-1"})
        assert await handle_notification_read_receipt(**arguments)
        assert await is_message_viewed(cache, "u", "chat-a", "message-1")
        directus.chat.get_chat_metadata.return_value = {"hashed_user_id": "different-owner"}
        assert not await handle_notification_read_receipt(**arguments)
        directus.chat.get_chat_metadata.return_value = {"hashed_user_id": hashlib.sha256(b"u").hexdigest()}
        cache._client = None
        assert not await handle_notification_read_receipt(**arguments)

    asyncio.run(scenario())
