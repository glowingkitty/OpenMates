"""
Tests for safe notification API serialization helpers.

Route authentication is covered by shared auth dependencies; these tests focus on
the SSE wire format used by `/v1/notifications/stream`.
"""

from backend.core.api.app.services.notification_sse import sse_event


def test_sse_event_serializes_safe_notification_payload():
    payload = {
        "id": "notif_1",
        "type": "chat.assistant_message_received",
        "safe_title_key": "apps.openmates",
        "safe_body_key": "notifications.chat_message.new_message_received",
        "routing": {"chat_id": "chat-1"},
        "metadata": {"has_encrypted_preview": False},
    }

    event = sse_event("notification", payload, event_id=payload["id"])

    assert event.startswith("id: notif_1\nevent: notification\ndata: ")
    assert "secret assistant response" not in event
    assert "Private chat title" not in event
    assert event.endswith("\n\n")
