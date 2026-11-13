# backend/core/api/app/routes/handlers/websocket_handlers/draft_shell_deletion.py
# Server-side draft removal for deleting a draft-only chat (a chat with no
# persisted chat row). delete_chat queues no persistence worker for such chats,
# so this module removes the deleting user's encrypted draft itself instead of
# trusting every client to send a separate delete_draft first. Without it the
# Directus `drafts` row outlived the chat the user deleted.
# spec: specifications/architecture/drafts#drafts.draft-only.lifecycle

import hashlib
import logging

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.services.draft_deletion_record import record_draft_deletion

logger = logging.getLogger(__name__)


class DraftShellDeletionError(RuntimeError):
    """The draft of a draft-only chat could not be removed durably."""


async def delete_draft_shell_drafts(
    cache_service: CacheService,
    directus_service: DirectusService,
    user_id: str,
    chat_id: str,
) -> int:
    """Tombstone the user's cached draft and delete their Directus draft rows.

    Only rows owned by `user_id` are touched: a draft-only chat has no chat row
    to prove ownership, so the per-user hash is the ownership boundary.
    The cache tombstone atomically takes a new draft version so a stale async save cannot
    resurrect the deleted ciphertext. Returns the number of deleted rows.

    Raises DraftShellDeletionError when the tombstone or the Directus deletion
    fails, so the caller can fail closed instead of reporting a deletion that
    left encrypted content behind.
    """
    deleted_draft_v = await cache_service.increment_and_tombstone_user_draft(user_id, chat_id)
    if deleted_draft_v is None:
        raise DraftShellDeletionError("draft_cache_tombstone_failed")

    rows = await directus_service.get_items(
        "drafts",
        params={
            "filter[hashed_user_id][_eq]": hashlib.sha256(user_id.encode()).hexdigest(),
            "filter[chat_id][_eq]": chat_id,
            "fields": "id",
            "limit": -1,
        },
        no_cache=True,
        admin_required=True,
        raise_on_error=True,
    )
    if rows is None:
        raise DraftShellDeletionError("draft_rows_lookup_failed")
    draft_ids = [row["id"] for row in rows if row.get("id")]
    if len(draft_ids) != len(rows):
        raise DraftShellDeletionError("draft_row_without_id")
    if draft_ids and not await directus_service.bulk_delete_items(collection="drafts", item_ids=draft_ids):
        raise DraftShellDeletionError("draft_rows_delete_failed")
    # Positive delete evidence for the reconnect stale-draft probe; written only
    # after the Directus rows are gone so it never outlives a failed delete.
    await record_draft_deletion(cache_service, user_id, chat_id, deleted_draft_v)
    logger.info("Deleted %d persisted draft row(s) of draft-only chat %s.", len(draft_ids), chat_id)
    return len(draft_ids)
