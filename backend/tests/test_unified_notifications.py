"""
Tests for unified notification events and privacy-preserving push payloads.

These tests guard the notification contract: safe notification APIs and APNs
alert fields must not expose chat titles or assistant response content.
"""

import json

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
