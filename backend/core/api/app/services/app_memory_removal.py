"""Idempotent active-storage cleanup for removed app-memory owners.

The Directus setup migration performs the primary SQL purge. API startup repeats
the exact app-id cleanup through Directus so dev restarts and partially upgraded
self-host installations cannot retain or recreate obsolete AI-memory rows.
"""

import logging

from backend.shared.python_utils.app_memory_policy import REMOVED_APP_MEMORY_APP_IDS


logger = logging.getLogger(__name__)
MEMORY_COLLECTION = "user_app_settings_and_memories"
PURGE_BATCH_SIZE = 500


async def purge_removed_app_memory_rows(directus_service) -> int:
    """Delete and verify rows for removed app owners without reading payloads."""
    deleted_count = 0
    for app_id in REMOVED_APP_MEMORY_APP_IDS:
        while True:
            rows = await directus_service.get_items(
                MEMORY_COLLECTION,
                params={
                    "filter": {"app_id": {"_eq": app_id}},
                    "fields": ["id"],
                    "limit": PURGE_BATCH_SIZE,
                },
            )
            row_ids = [str(row["id"]) for row in rows or [] if row.get("id")]
            if not row_ids:
                break
            if not await directus_service.bulk_delete_items(
                MEMORY_COLLECTION, row_ids
            ):
                raise RuntimeError("Failed to delete removed app-memory rows")
            deleted_count += len(row_ids)

        remaining = await directus_service.get_items(
            MEMORY_COLLECTION,
            params={
                "filter": {"app_id": {"_eq": app_id}},
                "fields": ["id"],
                "limit": 1,
            },
        )
        if remaining:
            raise RuntimeError("Removed app-memory rows remain after purge")

    logger.info("Purged %s removed app-memory row(s) from active storage", deleted_count)
    return deleted_count
