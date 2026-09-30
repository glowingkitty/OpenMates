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
