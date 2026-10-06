"""Watch topic routing, generic payloads, and paired installation preservation."""
import json

import pytest

from backend.core.api.app.services.push_notification_service import (
    APNS_CHAT_CATEGORY,
    APNS_CHAT_MESSAGE_BODY,
    APNS_CHAT_MESSAGE_TITLE,
    PushNotificationService,
    apns_topic_for_platform,
)
from backend.core.api.app.services.push_subscription_targets import (
    merge_push_subscription_target,
    normalize_push_subscription_targets,
    remove_push_subscription_target,
)


# contract-test: supporting surface=gui.apple assertions=apple-notifications.registration.lifecycle
def test_native_topic_is_server_selected_and_allowlisted(monkeypatch):
    monkeypatch.delenv("APNS_BUNDLE_ID", raising=False)
    assert apns_topic_for_platform("watchos") == "org.openmates.app.watch"
    for platform in ("apns", "ios", "macos"):
        assert apns_topic_for_platform(platform) == "org.openmates.app"
    with pytest.raises(ValueError):
        apns_topic_for_platform("untrusted")
    monkeypatch.setenv("APNS_BUNDLE_ID", "arbitrary.client.topic")
    with pytest.raises(ValueError):
        apns_topic_for_platform("ios")
    assert apns_topic_for_platform("watchos") == "org.openmates.app.watch"


# contract-test: supporting surface=gui.apple assertions=apple-notifications.registration.lifecycle
def test_watch_token_rotation_and_logout_preserve_phone_mac_and_browser():
    targets = [
        {"type": "web", "endpoint": "https://push.example/browser"},
        {"type": "apns", "platform": "ios", "token": "phone-token", "device_id": "phone-installation"},
        {"type": "apns", "platform": "macos", "token": "mac-token", "device_id": "mac-installation"},
        {"type": "apns", "platform": "watchos", "token": "watch-old", "device_id": "watch-installation"},
    ]
    stored = None
    for target in targets:
        stored = merge_push_subscription_target(stored, target)
    rotated = {**targets[-1], "token": "watch-rotated"}
    stored = merge_push_subscription_target(stored, rotated)
    assert normalize_push_subscription_targets(stored) == targets[:-1] + [rotated]
    stored, enabled = remove_push_subscription_target(stored, rotated)
    assert enabled is True
    assert normalize_push_subscription_targets(stored) == targets[:-1]


# contract-test: supporting surface=gui.apple assertions=apple-notifications.payload.privacy-safe,apple-notifications.delivery.idempotent-visible
def test_paired_dispatch_keeps_safe_routing_and_watch_topic(monkeypatch):
    calls = []

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, json, headers):
            calls.append((url, json, headers))
            return type("Response", (), {"status_code": 200, "text": "ok"})()

    monkeypatch.setenv("APNS_TEAM_ID", "fixture-team")
    monkeypatch.setenv("APNS_KEY_ID", "fixture-key")
    monkeypatch.setenv("APNS_PRIVATE_KEY", "fixture-private")
    monkeypatch.delenv("APNS_BUNDLE_ID", raising=False)
    monkeypatch.setattr("httpx.Client", Client)
    service = PushNotificationService()
    monkeypatch.setattr(service, "_build_apns_jwt", lambda **kwargs: "fixture-jwt")
    encrypted = []

    def encrypt(target, body):
        encrypted.append(target["platform"])
        return {"ciphertext": "fixture-ciphertext"}

    monkeypatch.setattr(service, "_build_encrypted_apns_payload", encrypt)
    targets = [
        {"type": "apns", "token": "fixture-phone", "platform": "ios", "environment": "sandbox",
         "topic": "client-untrusted-topic"},
        {"type": "apns", "token": "fixture-watch", "platform": "watchos", "environment": "sandbox",
         "topic": "client-untrusted-topic", "notification_public_key": "ignored-watch-key"},
    ]
    assert service.send_push_notification(json.dumps({"type": "multi", "targets": targets}),
        title="Private title", body="Private assistant response", chat_id="exact-chat",
        category=APNS_CHAT_CATEGORY, tag="ai-response-exact-chat")
    assert len(calls) == 2
    assert encrypted == ["ios"]
    assert [call[2]["apns-topic"] for call in calls] == ["org.openmates.app", "org.openmates.app.watch"]
    for url, payload, headers in calls:
        assert url.startswith("https://api.sandbox.push.apple.com/")
        assert payload["aps"]["alert"] == {"title": APNS_CHAT_MESSAGE_TITLE, "body": APNS_CHAT_MESSAGE_BODY}
        assert payload["aps"]["category"] == APNS_CHAT_CATEGORY
        assert payload["aps"]["thread-id"] == "exact-chat"
        assert payload["chat_id"] == "exact-chat"
        assert headers["apns-collapse-id"] == "ai-response-exact-chat"
        assert "Private" not in json.dumps(payload)
    watch = calls[-1][1]
    assert "mutable-content" not in watch["aps"]
    assert "encrypted_notification" not in watch


# contract-test: supporting surface=gui.apple assertions=apple-notifications.registration.lifecycle
def test_unsupported_platform_never_reaches_provider(monkeypatch):
    service = PushNotificationService()
    monkeypatch.setattr("httpx.Client", lambda **kwargs: pytest.fail("Unexpected provider request"))
    assert service._send_apns_notification({"type": "apns", "token": "fixture", "platform": "arbitrary"},
        title="OpenMates", body="New message", chat_id="chat", category=APNS_CHAT_CATEGORY, tag="tag") is False


# contract-test: supporting surface=gui.apple assertions=apple-notifications.registration.lifecycle
def test_legacy_processing_tokens_retire_without_losing_completion_targets():
    phone = {"type": "apns", "platform": "ios", "token": "fixture-completion-token",
             "device_id": "fixture-phone", "environment": "production",
             "notification_public_key": "fixture-preview-key", "encryption_version": "v1"}
    old_phone = {**phone, "activity_start_token": "obsolete-token",
                 "activity_owner": "obsolete-owner", "activity_input_push_token": True}
    browser = {"type": "web", "endpoint": "https://push.example.invalid/fixture"}
    legacy = json.dumps({"type": "multi", "targets": [old_phone, browser]})
    assert normalize_push_subscription_targets(legacy) == [phone, browser]
    assert normalize_push_subscription_targets(json.dumps(old_phone)) == [phone]
    refreshed = merge_push_subscription_target(legacy, {**old_phone, "token": "rotated-completion-token"})
    assert normalize_push_subscription_targets(refreshed) == [browser, {**phone, "token": "rotated-completion-token"}]
    assert "obsolete" not in refreshed
    remaining, enabled = remove_push_subscription_target(refreshed, phone)
    assert enabled and normalize_push_subscription_targets(remaining) == [browser]


# contract-test: supporting surface=rest assertions=auth.session.lifecycle,auth.session.isolation
# contract-test: supporting surface=gui.apple assertions=apple-notifications.registration.lifecycle
@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["native_register", "native_unregister", "browser_subscribe", "browser_unsubscribe"])
async def test_push_changes_preserve_live_auth_sessions_and_profile(monkeypatch, operation):
    from contextlib import asynccontextmanager
    from copy import deepcopy
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from backend.core.api.app.routes import push
    from backend.core.api.app.services.cache_user_mixin import UserCacheMixin

    user_id = "fixture-account"
    old_targets = json.dumps({"type": "multi", "targets": [
        {"type": "apns", "token": "fixture-native", "platform": "macos", "device_id": "fixture-installation"},
        {"type": "web", "endpoint": "https://push.example/fixture", "keys": {"p256dh": "fixture", "auth": "fixture"}},
    ]})

    class Cache(UserCacheMixin):
        USER_KEY_PREFIX = "user_profile:"
        USER_TTL = 86400

        def __init__(self):
            self.values = {
                "user_profile:" + user_id: {"id": user_id, "user_id": user_id,
                    "vault_key_id": "fixture-vault", "username": "fixture-name",
                    "push_notification_enabled": True, "push_notification_subscription": old_targets},
                "session:active-native": {"user_id": user_id, "token_expiry": 9999999999},
                "session:active-cli": {"user_id": user_id, "token_expiry": 9999999999},
                "chat:fixture": {"version": 7},
            }
            self.ttls = {key: 7200 for key in self.values}

        async def get(self, key):
            return deepcopy(self.values.get(key))

        async def get_key_ttl(self, key):
            return self.ttls.get(key, -2)

        async def set(self, key, value, ttl=None):
            self.values[key] = deepcopy(value)
            self.ttls[key] = ttl
            return True

        async def delete_user_cache(self, user_id):
            pytest.fail("Push updates must not delete authenticated sessions or chat caches")

    cache = Cache()
    before = deepcopy(cache.values)
    directus = SimpleNamespace(update_user=AsyncMock(return_value=True))

    @asynccontextmanager
    async def lock(*args):
        yield object()

    monkeypatch.setattr(push, "push_subscription_write_lock", lock)
    monkeypatch.setattr(push, "require_push_subscription_lock", AsyncMock())
    monkeypatch.delenv("APNS_BUNDLE_ID", raising=False)
    current_user = SimpleNamespace(id=user_id)
    kwargs = dict(current_user=current_user, directus_service=directus, cache_service=cache)
    if operation == "native_register":
        result = await push.register_native_device(push.NativeDeviceRegisterRequest(
            token="fixture-rotated", platform="macos", device_id="fixture-installation"), **kwargs)
    elif operation == "native_unregister":
        result = await push.unregister_native_device(push.NativeDeviceUnregisterRequest(
            token="fixture-native", device_id="fixture-installation"), **kwargs)
    elif operation == "browser_subscribe":
        result = await push.subscribe_push(None, push.PushSubscribeRequest(
            endpoint="https://push.example/new", keys={"p256dh": "fixture", "auth": "fixture"}), **kwargs)
    else:
        result = await push.unsubscribe_push(**kwargs)

    assert result.success is True
    changed_fields = directus.update_user.await_args.args[1]
    profile_key = "user_profile:" + user_id
    assert cache.values[profile_key] == {**before[profile_key], **changed_fields}
    assert cache.ttls[profile_key] == 7200
    for key in ("session:active-native", "session:active-cli", "chat:fixture"):
        assert cache.values[key] == before[key]
        assert cache.ttls[key] == 7200
