"""
Server-authoritative unread counter for chats.

A chat is unread while at least one finished assistant reply has not been seen
to its last line. The server increments the counter when an assistant reply is
persisted; clients reset it to 0 via ``chat_read_status_update`` once the reply's
last line has been visible in their viewport, or when the user sends a follow-up
(a follow-up implies the previous reply was read).

The increment broadcast carries the triggering ``message_id`` so clients that
also optimistically count background completions locally do not count the same
reply twice.
"""
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


async def _current_unread_count(cache_service: Any, directus_service: Any, user_id: str, chat_id: str) -> int:
    cached = await cache_service.get_chat_list_item_data(user_id, chat_id, refresh_ttl=False)
    if cached is not None and cached.unread_count is not None:
        return int(cached.unread_count)
    metadata = await directus_service.chat.get_chat_metadata(chat_id)
    if not metadata:
        return 0
    return int(metadata.get("unread_count") or 0)


async def increment_unread_for_assistant_reply(
    cache_service: Any,
    directus_service: Any,
    user_id: str,
    chat_id: str,
) -> Optional[int]:
    """Increment and persist the unread count; return the new count, or None if persisting failed."""
    previous_count = await _current_unread_count(cache_service, directus_service, user_id, chat_id)
    new_count = previous_count + 1
    logger.info(f"Unread counter: chat {chat_id} unread_count {previous_count} -> {new_count}")
    cache_ok = await cache_service.update_chat_read_status(user_id=user_id, chat_id=chat_id, unread_count=new_count)
    db_ok = await directus_service.chat.update_chat_read_status(chat_id=chat_id, unread_count=new_count)
    if not cache_ok or not db_ok:
        logger.error(
            f"Unread counter: failed to persist unread_count={new_count} for chat {chat_id} "
            f"(cache_ok={cache_ok}, db_ok={db_ok})"
        )
        return None
    return new_count



# Unread-only event on the ``ai_message_persisted::<hash>`` channel. The API's
# persisted listener forwards it as ``chat_read_status_updated``. Fixture replay
# uses it because it publishes the final chunk without running the stream
# consumer's ``_update_chat_metadata``, which carries the count on the
# ``ai_message_persisted`` event instead.
UNREAD_COUNT_UPDATED_EVENT = "chat_unread_count_updated"


async def increment_and_publish_unread(
    cache_service: Any,
    directus_service: Any,
    *,
    user_id: str,
    user_id_hash: str,
    chat_id: str,
    message_id: str,
) -> Optional[int]:
    """Increment the unread count for a finished reply and publish it to the user's devices."""
    unread_count = await increment_unread_for_assistant_reply(cache_service, directus_service, user_id, chat_id)
    if unread_count is None:
        return None
    await cache_service.publish_event(f"ai_message_persisted::{user_id_hash}", {
        "type": UNREAD_COUNT_UPDATED_EVENT,
        "user_id_uuid": user_id,
        "chat_id": chat_id,
        "unread_count": unread_count,
        "message_id": message_id,
    })
    return unread_count
