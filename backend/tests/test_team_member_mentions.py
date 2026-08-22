"""Teams V1 member-mention notification contract tests.

Mention recipients are resolved and authorized without exposing message text.
In-app and default-on email notifications carry safe routing metadata only, and
member mentions do not independently invoke AI processing.
"""

import pytest
from pathlib import Path

from backend.core.api.app.services.team_member_mention_service import notify_team_member_mentions


class RecordingNotifications:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []
        self.emails: list[tuple[str, dict]] = []

    async def create_in_app(self, user_id: str, payload: dict) -> None:
        self.events.append((user_id, payload))

    async def enqueue_email(self, user_id: str, payload: dict) -> None:
        self.emails.append((user_id, payload))


# contract-test: supporting surface=rest_api assertions=teams.chat.member-mentions-notify,teams.chat.encrypted-until-invoked
@pytest.mark.anyio
async def test_member_mention_notifies_only_active_member_without_plaintext_or_ai_dispatch() -> None:
    notifications = RecordingNotifications()

    result = await notify_team_member_mentions(
        notification_sink=notifications,
        team_id="team-1",
        chat_id="chat-1",
        message_id="message-1",
        sender_user_id="alice",
        mentioned_user_ids=["bob", "removed-user", "alice"],
        active_member_user_ids={"alice", "bob"},
    )

    expected_payload = {
        "team_id": "team-1",
        "chat_id": "chat-1",
        "message_id": "message-1",
        "safe_title_key": "notifications.team_member_mention.title",
        "safe_body_key": "notifications.team_member_mention.body",
    }
    assert notifications.events == [("bob", expected_payload)]
    assert notifications.emails == [("bob", expected_payload)]
    assert result.notified_user_ids == ("bob",)
    assert result.should_trigger_ai is False
    assert "content" not in repr(notifications.events)


# contract-test: supporting surface=rest_api assertions=teams.chat.member-mentions-notify
def test_websocket_handler_dispatches_authorized_team_mentions() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "core/api/app/routes/handlers/websocket_handlers/message_received_handler.py"
    ).read_text(encoding="utf-8")

    assert "await notify_team_member_mentions(" in source
    assert "if hash_id(mentioned_user_id) in active_member_hashes" in source


# contract-test: supporting surface=rest_api assertions=teams.chat.member-mentions-notify
def test_member_mention_email_template_and_task_exclude_message_content() -> None:
    backend_root = Path(__file__).resolve().parents[1]
    template = (backend_root / "core/api/templates/email/team-member-mention-notification.mjml").read_text(encoding="utf-8")
    task_source = (backend_root / "core/api/app/tasks/email_tasks/team_member_mention_email_task.py").read_text(encoding="utf-8")

    assert "team_member_mention_notification.description" in template
    assert "message_content" not in template
    assert "message_content" not in task_source
    assert "response_preview" not in task_source
