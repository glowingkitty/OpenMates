"""Privacy-safe Team member mention notifications.

Recipients are already resolved client-side and are intersected with the active
membership set. Notification payloads contain only routing IDs and translation
keys, so message plaintext never enters notification storage or email queues.
"""

from dataclasses import dataclass
from typing import Any, Iterable

from backend.core.api.app.services.notification_event_service import NotificationEventService


TEAM_MEMBER_MENTION_EMAIL_TASK = "app.tasks.email_tasks.team_member_mention_email_task.send_team_member_mention_email"


@dataclass(frozen=True)
class TeamMemberMentionResult:
    notified_user_ids: tuple[str, ...]
    should_trigger_ai: bool = False


class TeamMemberMentionNotificationSink:
    """Bridge safe mentions to the existing in-app store and email worker."""

    def __init__(self, cache_service: Any) -> None:
        self.events = NotificationEventService(cache_service)

    async def create_in_app(self, user_id: str, payload: dict[str, str]) -> None:
        await self.events.create_team_member_mention_event(
            user_id=user_id,
            team_id=payload["team_id"],
            chat_id=payload["chat_id"],
            message_id=payload["message_id"],
        )

    async def enqueue_email(self, user_id: str, payload: dict[str, str]) -> None:
        from backend.core.api.app.tasks.celery_config import app as celery_app

        celery_app.send_task(
            TEAM_MEMBER_MENTION_EMAIL_TASK,
            kwargs={"user_id": user_id, "team_id": payload["team_id"], "chat_id": payload["chat_id"]},
            queue="email",
        )


async def notify_team_member_mentions(
    *,
    notification_sink: Any,
    team_id: str,
    chat_id: str,
    message_id: str,
    sender_user_id: str,
    mentioned_user_ids: Iterable[str],
    active_member_user_ids: set[str],
) -> TeamMemberMentionResult:
    """Notify active mentioned members once, excluding the sender."""
    recipients = tuple(
        user_id
        for user_id in dict.fromkeys(mentioned_user_ids)
        if isinstance(user_id, str) and user_id != sender_user_id and user_id in active_member_user_ids
    )
    payload = {
        "team_id": team_id,
        "chat_id": chat_id,
        "message_id": message_id,
        "safe_title_key": "notifications.team_member_mention.title",
        "safe_body_key": "notifications.team_member_mention.body",
    }
    for user_id in recipients:
        await notification_sink.create_in_app(user_id, payload)
        await notification_sink.enqueue_email(user_id, payload)
    return TeamMemberMentionResult(notified_user_ids=recipients)
