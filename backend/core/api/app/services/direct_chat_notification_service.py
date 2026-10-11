"""Recipient-only, content-free notifications for a newly created Team DM.

Publish a projected chat event so the recipient can hydrate before a message.
Store a safe in-app event with routing IDs only, then use existing email and
push dispatchers with the recipient's current notification preferences.
No title, message plaintext, private key or peer key envelope enters alerts.
"""

import json
import logging
from typing import Any
from urllib.parse import quote

from backend.core.api.app.services.notification_event_service import NotificationEvent, NotificationEventService
from backend.core.api.app.services.directus.team_methods import hash_id

logger = logging.getLogger(__name__)


def _preference_map(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


async def notify_new_direct_chat(app: Any, *, recipient_id: str, team_id: str, chat_id: str,
                                 recipient_chat: dict[str, Any]) -> None:
    """Route identifiers only; never include peer identity, title or key material."""
    cache = app.state.cache_service
    directus = app.state.directus_service
    from backend.core.api.app.services.team_realtime_service import broadcast_team_event
    try:
        await broadcast_team_event(
            manager=None, active_member_user_ids=(), event_name="team_chat_created",
            payload={"team_id": team_id, "chat": recipient_chat}, cache_service=cache,
            active_member_hashes=(hash_id(recipient_id),),
        )
    except Exception as exc:
        logger.warning("New direct chat WebSocket event failed (%s)", type(exc).__name__)
    event = NotificationEvent(
        user_id=recipient_id, type="team.direct_chat_created",
        safe_title_key="notifications.team_direct_chat.title",
        safe_body_key="notifications.team_direct_chat.body",
        routing={"team_id": team_id, "chat_id": chat_id},
    )
    try:
        await NotificationEventService(cache).store_and_publish(event)
    except Exception as exc:
        logger.warning("New direct chat in-app event failed (%s)", type(exc).__name__)

    # The existing chat email dispatcher checks durable opt-ins, active Team
    # access, online presence and verified address again at send time.
    from backend.core.api.app.services.chat_email_notification_service import enqueue_chat_email
    try:
        await enqueue_chat_email(
            cache_service=cache, directus_service=directus,
            encryption_service=app.state.encryption_service,
            user_id=recipient_id, chat_id=chat_id,
            message_id=f"new-dm:{chat_id}", sender_name="A team member",
            source="team", team_id=team_id,
        )
    except Exception as exc:
        logger.warning("New direct chat email enqueue failed (%s)", type(exc).__name__)

    recipient = await cache.get_user_by_id(recipient_id)
    if not isinstance(recipient, dict):
        recipient = await directus.get_user_fields_direct(
            recipient_id,
            ["push_notification_enabled", "push_notification_subscription", "push_notification_preferences"],
            no_cache=True,
        )
    if not isinstance(recipient, dict) or recipient.get("push_notification_enabled") is not True:
        return
    subscription = recipient.get("push_notification_subscription")
    if not isinstance(subscription, str) or not subscription:
        return
    if _preference_map(recipient.get("push_notification_preferences")).get("aiResponses", True) is False:
        return
    from backend.core.api.app.tasks.celery_config import app as celery_app
    try:
        celery_app.send_task(
            name="app.tasks.push_notification_task.send_push_notification",
            kwargs={"subscription_json": subscription, "title": "OpenMates",
                    "body": "You have a new direct chat.",
                    "url": f"/#chat-id={quote(chat_id, safe='')}&team-id={quote(team_id, safe='')}",
                    "tag": f"team-direct-chat-{chat_id}", "chat_id": chat_id,
                    "category": "OPENMATES_CHAT_MESSAGE", "user_id": recipient_id},
            queue="push",
        )
    except Exception as exc:
        logger.warning("New direct chat push enqueue failed (%s)", type(exc).__name__)
