"""
Tests for unified notification events and privacy-preserving push payloads.

These tests guard the notification contract: safe notification APIs and APNs
alert fields must not expose chat titles or assistant response content.
"""

import asyncio
import json
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from backend.core.api.app.services.notification_event_service import (
    NotificationEventService,
    NOTIFICATION_TYPE_CHAT_ASSISTANT_MESSAGE,
    SAFE_BODY_KEY_NEW_MESSAGE,
)
from backend.core.api.app.services.push_notification_service import (
    APNS_CHAT_CATEGORY,
    APNS_CHAT_MESSAGE_BODY,
    APNS_CHAT_MESSAGE_TITLE,
    APNS_ENCRYPTION_INFO,
    APNS_ENCRYPTION_VERSION,
    PushNotificationService,
    _decode_base64url,
    _encode_base64url,
)
from backend.core.api.app.services.push_subscription_targets import (
    merge_push_subscription_target,
    normalize_push_subscription_targets,
    remove_push_subscription_target,
)


class _FakeRedis:
    def __init__(self):
        self.lists = {}
        self.published = []
        self.ttls = {}

    async def lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, value)

    async def ltrim(self, key, start, end):
        self.lists[key] = self.lists.get(key, [])[start : end + 1]

    async def expire(self, key, ttl):
        self.ttls[key] = ttl

    async def lrange(self, key, start, end):
        return self.lists.get(key, [])[start : end + 1]


class _FakeCache:
    def __init__(self):
        self.redis = _FakeRedis()
        self.published = []

    @property
    async def client(self):
        return self.redis

    async def publish_event(self, channel, event_data):
        self.published.append((channel, event_data))
        return True


class _FakePushLock:
    def __init__(self):
        self.guard = asyncio.Lock()
        self.lease_owned = True

    async def acquire(self, **kwargs):
        await self.guard.acquire()
        return True

    async def extend(self, additional_time, replace_ttl):
        assert additional_time == 120
        assert replace_ttl is True
        return self.guard.locked() and self.lease_owned

    async def release(self):
        if not self.lease_owned:
            raise RuntimeError("This lease was replaced by another owner")
        self.guard.release()


class _FakePushCache:
    def __init__(self):
        self.push_lock = _FakePushLock()
        self.delete_user_cache = AsyncMock()
        self.close = AsyncMock()

    @property
    async def client(self):
        return self

    def lock(self, key, timeout):
        assert key == "push:subscription:user-1"
        assert timeout == 120
        return self.push_lock


@pytest.fixture
def push_task_module(monkeypatch):
    """Load the push task alone, without starting Celery's broad worker bootstrap."""
    class _FakeApp:
        def task(self, **kwargs):
            return lambda function: SimpleNamespace(
                run=lambda *args, **kwargs: function(None, *args, **kwargs)
            )

    monkeypatch.setitem(
        sys.modules,
        "backend.core.api.app.tasks.celery_config",
        SimpleNamespace(app=_FakeApp()),
    )
    task_path = Path(__file__).resolve().parents[1] / "core/api/app/tasks/push_notification_task.py"
    spec = importlib.util.spec_from_file_location("push_notification_task_under_test", task_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# contract-test: direct surface=gui.apple assertions=apple-notifications.payload.privacy-safe
@pytest.mark.asyncio
async def test_notification_event_service_serializes_safe_chat_event_only():
    cache = _FakeCache()
    service = NotificationEventService(cache)

    event = await service.create_chat_assistant_message_event(
        user_id="user-1",
        chat_id="chat-1",
        has_encrypted_preview=True,
    )

    public_event = event.public_dict()
    serialized = json.dumps(public_event)

    assert event.type == NOTIFICATION_TYPE_CHAT_ASSISTANT_MESSAGE
    assert public_event["safe_body_key"] == SAFE_BODY_KEY_NEW_MESSAGE
    assert public_event["routing"] == {"chat_id": "chat-1"}
    assert public_event["metadata"] == {"has_encrypted_preview": True}
    assert "user_id" not in public_event
    assert "assistant response" not in serialized
    assert "Private chat title" not in serialized
    assert cache.published[0][1] == public_event

    recent = await service.get_recent("user-1")
    assert recent == [public_event]


# contract-test: direct surface=gui.apple assertions=apple-notifications.payload.privacy-safe,apple-notifications.delivery.idempotent-visible
def test_apns_chat_payload_uses_safe_alert_and_encrypted_preview(monkeypatch):
    device_private_key = x25519.X25519PrivateKey.generate()
    device_public_key = device_private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    captured = {}

    class _FakeResponse:
        status_code = 200
        text = "ok"

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def post(self, url, json, headers):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return _FakeResponse()

    monkeypatch.setenv("APNS_TEAM_ID", "TEAMID")
    monkeypatch.setenv("APNS_KEY_ID", "KEYID")
    monkeypatch.setenv("APNS_PRIVATE_KEY", "dummy")
    monkeypatch.setattr("httpx.Client", _FakeClient)

    service = PushNotificationService()
    monkeypatch.setattr(service, "_build_apns_jwt", lambda **kwargs: "jwt-token")

    assert service._send_apns_notification(
        subscription_info={
            "type": "apns",
            "token": "abc123",
            "environment": "sandbox",
            "notification_public_key": _encode_base64url(device_public_key),
            "encryption_version": APNS_ENCRYPTION_VERSION,
        },
        title="Private chat title",
        body="secret assistant response first line",
        chat_id="chat-1",
        category=APNS_CHAT_CATEGORY,
        tag="ai-response-chat-1",
    )

    payload = captured["json"]
    payload_text = json.dumps(payload)

    assert captured["url"] == "https://api.sandbox.push.apple.com/3/device/abc123"
    assert payload["aps"]["alert"]["title"] == APNS_CHAT_MESSAGE_TITLE
    assert payload["aps"]["alert"]["body"] == APNS_CHAT_MESSAGE_BODY
    assert payload["aps"]["mutable-content"] == 1
    assert payload["encrypted_notification"]["version"] == APNS_ENCRYPTION_VERSION
    assert "secret assistant response" not in payload_text
    assert "Private chat title" not in payload_text

    encrypted = payload["encrypted_notification"]
    ephemeral_public_key = x25519.X25519PublicKey.from_public_bytes(
        _decode_base64url(encrypted["ephemeral_public_key"])
    )
    shared_secret = device_private_key.exchange(ephemeral_public_key)
    key = HKDF(
        algorithm=SHA256(),
        length=32,
        salt=None,
        info=APNS_ENCRYPTION_INFO,
    ).derive(shared_secret)
    plaintext = AESGCM(key).decrypt(
        _decode_base64url(encrypted["nonce"]),
        _decode_base64url(encrypted["ciphertext"]),
        None,
    )

    assert json.loads(plaintext) == {"preview": "secret assistant response first line"}


# contract-test: supporting surface=rest_api assertions=apple-notifications.registration.lifecycle
def test_push_subscription_targets_preserve_browser_and_native_devices():
    browser_target = {
        "type": "web",
        "endpoint": "https://push.example/browser-1",
        "keys": {"p256dh": "pub", "auth": "auth"},
        "expirationTime": None,
    }
    native_target = {
        "type": "apns",
        "token": "token-1",
        "platform": "apns",
        "environment": "sandbox",
    }

    stored = merge_push_subscription_target(None, browser_target)
    stored = merge_push_subscription_target(stored, native_target)
    targets = normalize_push_subscription_targets(stored)

    assert [target["type"] for target in targets] == ["web", "apns"]
    assert targets[0]["endpoint"] == browser_target["endpoint"]
    assert targets[1]["token"] == native_target["token"]


# contract-test: direct surface=rest_api assertions=apple-notifications.registration.lifecycle
def test_native_rotation_and_unregister_use_stable_installation_identity():
    first = {"type": "apns", "token": "token-1", "device_id": "installation-1"}
    rotated = {"type": "apns", "token": "token-2", "device_id": "installation-1"}
    other = {"type": "apns", "token": "token-3", "device_id": "installation-2"}

    stored = merge_push_subscription_target(None, first)
    stored = merge_push_subscription_target(stored, other)
    stored = merge_push_subscription_target(stored, rotated)
    targets = normalize_push_subscription_targets(stored)

    assert [target["token"] for target in targets] == ["token-3", "token-2"]
    stored, enabled = remove_push_subscription_target(stored, rotated)
    assert enabled is True
    assert [target["token"] for target in normalize_push_subscription_targets(stored)] == ["token-3"]


# contract-test: supporting surface=rest_api assertions=apple-notifications.delivery.idempotent-visible
def test_multi_target_push_dispatches_to_web_and_apns(monkeypatch):
    calls = []

    def fake_webpush(**kwargs):
        calls.append(("web", kwargs["subscription_info"]["endpoint"]))

    service = PushNotificationService()
    service._initialized = True
    service._vapid_private_key = "private"
    service._vapid_public_key = "public"
    monkeypatch.setitem(sys.modules, "pywebpush", SimpleNamespace(webpush=fake_webpush))
    monkeypatch.setattr(
        service,
        "_send_apns_notification",
        lambda subscription_info, **kwargs: calls.append(("apns", subscription_info["token"])) or True,
    )

    subscription_json = json.dumps(
        {
            "type": "multi",
            "targets": [
                {
                    "type": "web",
                    "endpoint": "https://push.example/browser-1",
                    "keys": {"p256dh": "pub", "auth": "auth"},
                },
                {"type": "apns", "token": "token-1", "platform": "apns"},
            ],
        }
    )

    assert service.send_push_notification(
        subscription_json=subscription_json,
        title="OpenMates",
        body="New message received",
        chat_id="chat-1",
    )

    assert calls == [("web", "https://push.example/browser-1"), ("apns", "token-1")]


# contract-test: supporting surface=gui.apple assertions=apple-notifications.delivery.idempotent-visible
@pytest.mark.parametrize("status_code,expected_expiry", [(410, True), (503, False)])
def test_browser_delivery_marks_only_permanent_expiry(monkeypatch, caplog, status_code, expected_expiry):
    class _WebPushError(Exception):
        response = SimpleNamespace(status_code=status_code)

    def failed_webpush(**kwargs):
        raise _WebPushError("push provider rejected request")

    service = PushNotificationService()
    service._initialized = True
    service._vapid_private_key = "private"
    service._vapid_public_key = "public"
    monkeypatch.setitem(sys.modules, "pywebpush", SimpleNamespace(webpush=failed_webpush))
    expiries = []

    assert service.send_push_notification(
        subscription_json=json.dumps({"endpoint": "https://push.example/browser-1", "keys": {}}),
        title="OpenMates",
        body="New message",
        on_expired_web_target=lambda: expiries.append(True),
    ) is False
    assert expiries == ([True] if expected_expiry else [])
    assert "https://push.example/browser-1" not in caplog.text


# contract-test: direct surface=gui.apple assertions=apple-notifications.delivery.idempotent-visible
@pytest.mark.parametrize("targets", [
    [{"type": "apns", "token": "native-1"}],
    [{"type": "web", "endpoint": "https://push.example/browser-1"},
     {"type": "apns", "token": "native-1"}],
])
def test_failed_multi_target_push_keeps_other_devices_and_setting(monkeypatch, push_task_module, targets):
    task_module = push_task_module
    clear_subscription = AsyncMock()
    monkeypatch.setattr(task_module, "_clear_stale_subscription", clear_subscription)
    monkeypatch.setattr(task_module.push_notification_service, "is_ready", lambda: True)

    def failed_send(**kwargs):
        # Even a known-expired browser target cannot clear an unrelated device.
        kwargs["on_expired_web_target"]()
        return False

    monkeypatch.setattr(task_module.push_notification_service, "send_push_notification", failed_send)
    stored = json.dumps({"type": "multi", "targets": targets})

    assert task_module.send_push_notification.run(stored, "OpenMates", "New message", user_id="user-1") is False
    clear_subscription.assert_not_awaited()
    assert task_module._should_clear_failed_subscription(stored) is False


# contract-test: supporting surface=gui.apple assertions=apple-notifications.delivery.idempotent-visible
@pytest.mark.parametrize("expired,expected_clear", [(False, False), (True, True)])
@pytest.mark.parametrize("storage_format", ["legacy", "multi"])
def test_browser_only_cleanup_requires_permanent_failure(monkeypatch, push_task_module, expired, expected_clear, storage_format):
    task_module = push_task_module
    clear_subscription = AsyncMock()
    monkeypatch.setattr(task_module, "_clear_stale_subscription", clear_subscription)
    monkeypatch.setattr(task_module.push_notification_service, "is_ready", lambda: True)

    def failed_send(**kwargs):
        if expired:
            kwargs["on_expired_web_target"]()
        return False

    monkeypatch.setattr(task_module.push_notification_service, "send_push_notification", failed_send)
    browser = {"endpoint": "https://push.example/browser-1", "keys": {}}
    stored = json.dumps(browser) if storage_format == "legacy" else merge_push_subscription_target(None, browser)

    assert task_module.send_push_notification.run(stored, "OpenMates", "New message", user_id="user-1") is False
    assert clear_subscription.await_count == int(expected_clear)
    if expected_clear:
        clear_subscription.assert_awaited_once_with("user-1", stored)


# contract-test: supporting surface=gui.apple assertions=apple-notifications.registration.lifecycle
@pytest.mark.asyncio
async def test_expired_browser_cannot_clear_new_native_registration(monkeypatch, push_task_module):
    old_browser = json.dumps({"endpoint": "https://push.example/old", "keys": {}})
    current = json.dumps({"type": "multi", "targets": [
        {"type": "web", "endpoint": "https://push.example/new"},
        {"type": "apns", "token": "native-1"},
    ]})
    directus = SimpleNamespace(
        get_user_fields_direct=AsyncMock(return_value={"push_notification_subscription": current}),
        update_user=AsyncMock(return_value=True),
    )
    cache = _FakePushCache()
    secrets = SimpleNamespace(initialize=AsyncMock(), aclose=AsyncMock())
    monkeypatch.setitem(sys.modules, "backend.core.api.app.utils.secrets_manager",
                        SimpleNamespace(SecretsManager=lambda: secrets))
    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.directus",
                        SimpleNamespace(DirectusService=lambda **kwargs: directus))
    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.cache",
                        SimpleNamespace(CacheService=lambda: cache))

    await push_task_module._clear_stale_subscription("user-1", old_browser)

    directus.update_user.assert_not_awaited()
    cache.delete_user_cache.assert_not_awaited()
    secrets.aclose.assert_awaited_once_with()


# contract-test: supporting surface=gui.apple assertions=apple-notifications.registration.lifecycle
@pytest.mark.asyncio
async def test_registration_waits_for_expired_browser_cleanup(monkeypatch, push_task_module):
    from backend.core.api.app.services.push_subscription_lock import push_subscription_write_lock

    old_browser = merge_push_subscription_target(None, {
        "type": "web", "endpoint": "https://push.example/old", "keys": {},
    })
    state = {"subscription": old_browser, "enabled": True}
    get_started = asyncio.Event()
    finish_get = asyncio.Event()
    cache = _FakePushCache()
    secrets = SimpleNamespace(initialize=AsyncMock(), aclose=AsyncMock())

    async def get_user_fields_direct(*args):
        get_started.set()
        await finish_get.wait()
        return {"push_notification_subscription": state["subscription"]}

    async def update_user(user_id, fields):
        state["subscription"] = fields["push_notification_subscription"]
        state["enabled"] = fields["push_notification_enabled"]
        return True

    directus = SimpleNamespace(
        get_user_fields_direct=get_user_fields_direct,
        update_user=AsyncMock(side_effect=update_user),
    )
    monkeypatch.setitem(sys.modules, "backend.core.api.app.utils.secrets_manager",
                        SimpleNamespace(SecretsManager=lambda: secrets))
    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.directus",
                        SimpleNamespace(DirectusService=lambda **kwargs: directus))
    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.cache",
                        SimpleNamespace(CacheService=lambda: cache))

    cleanup = asyncio.create_task(push_task_module._clear_stale_subscription("user-1", old_browser))
    await get_started.wait()

    async def register_native():
        async with push_subscription_write_lock(cache, "user-1"):
            state["subscription"] = merge_push_subscription_target(state["subscription"], {
                "type": "apns", "token": "native-1", "device_id": "installation-1",
            })
            state["enabled"] = True

    registration = asyncio.create_task(register_native())
    await asyncio.sleep(0)
    assert registration.done() is False
    finish_get.set()
    await asyncio.gather(cleanup, registration)

    assert state["enabled"] is True
    assert [target["type"] for target in normalize_push_subscription_targets(state["subscription"])] == ["apns"]
    directus.update_user.assert_awaited_once()


# contract-test: supporting surface=gui.apple assertions=apple-notifications.registration.lifecycle
@pytest.mark.asyncio
async def test_expired_lock_prevents_stale_browser_patch(monkeypatch, push_task_module):
    old_browser = merge_push_subscription_target(None, {
        "type": "web", "endpoint": "https://push.example/old", "keys": {},
    })
    cache = _FakePushCache()
    directus = SimpleNamespace(
        get_user_fields_direct=AsyncMock(return_value={"push_notification_subscription": old_browser}),
        update_user=AsyncMock(return_value=True),
    )
    secrets = SimpleNamespace(initialize=AsyncMock(), aclose=AsyncMock())
    monkeypatch.setitem(sys.modules, "backend.core.api.app.utils.secrets_manager",
                        SimpleNamespace(SecretsManager=lambda: secrets))
    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.directus",
                        SimpleNamespace(DirectusService=lambda **kwargs: directus))
    monkeypatch.setitem(sys.modules, "backend.core.api.app.services.cache",
                        SimpleNamespace(CacheService=lambda: cache))
    cache.push_lock.lease_owned = False

    await push_task_module._clear_stale_subscription("user-1", old_browser)

    directus.update_user.assert_not_awaited()


# contract-test: supporting surface=gui.apple assertions=apple-notifications.delivery.idempotent-visible
def test_apns_dispatch_does_not_need_vapid(monkeypatch, push_task_module):
    task_module = push_task_module
    monkeypatch.setattr(task_module.push_notification_service, "is_ready", lambda: False)
    monkeypatch.setattr(task_module.push_notification_service, "is_apns_ready", lambda: True)
    calls = []
    monkeypatch.setattr(
        task_module.push_notification_service,
        "send_push_notification",
        lambda **kwargs: calls.append(kwargs["subscription_json"]) or True,
    )
    stored = json.dumps({"type": "multi", "targets": [{"type": "apns", "token": "native-1"}]})

    assert task_module.send_push_notification.run(stored, "OpenMates", "New message") is True
    assert calls == [stored]
