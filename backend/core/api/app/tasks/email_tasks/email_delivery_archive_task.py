"""
Purpose: Archives old email delivery details to S3 while keeping Directus tombstones for idempotency.
Architecture: Daily Celery task uploads full rows, then marks rows archived and clears bulky fields.
"""

from __future__ import annotations

import asyncio
import gzip
import json
import logging
from datetime import datetime, timedelta, timezone

from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.core.api.app.tasks.celery_config import app

logger = logging.getLogger(__name__)

COLLECTION = "email_deliveries"
ARCHIVE_BUCKET_KEY = "email_delivery_archives"
DEFAULT_RETENTION_DAYS = 7
DEFAULT_BATCH_SIZE = 1000


@app.task(
    name="app.tasks.email_tasks.email_delivery_archive_task.archive_old_email_deliveries",
    base=BaseServiceTask,
    bind=True,
)
def archive_old_email_deliveries(self: BaseServiceTask, retention_days: int = DEFAULT_RETENTION_DAYS, limit: int = DEFAULT_BATCH_SIZE) -> dict:
    """Archive old email delivery rows to S3 and keep idempotency tombstones."""
    return asyncio.run(_async_archive_old_email_deliveries(self, retention_days=retention_days, limit=limit))


async def _async_archive_old_email_deliveries(
    task: BaseServiceTask,
    *,
    retention_days: int,
    limit: int,
) -> dict:
    stats = {"checked": 0, "archived": 0, "failed_updates": 0, "archive_key": None}
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

    try:
        await task.initialize_services()
        rows = await task.directus_service.get_items(
            COLLECTION,
            params={
                "fields": "*",
                "filter": {
                    "_and": [
                        {"status": {"_in": ["sent", "failed"]}},
                        {"archived_at": {"_null": True}},
                        {
                            "_or": [
                                {"sent_at": {"_lt": cutoff.isoformat()}},
                                {"failed_at": {"_lt": cutoff.isoformat()}},
                            ]
                        },
                    ]
                },
                "sort": "sent_at",
                "limit": limit,
            },
            admin_required=True,
        )
        stats["checked"] = len(rows)
        if not rows:
            return stats

        now = datetime.now(timezone.utc)
        archive_key = f"email-deliveries/{now:%Y/%m/%d}/email-deliveries-{now:%Y%m%dT%H%M%SZ}.json.gz"
        archive_payload = {
            "archived_at": now.isoformat(),
            "retention_days": retention_days,
            "count": len(rows),
            "rows": rows,
        }
        compressed = gzip.compress(json.dumps(archive_payload, ensure_ascii=False, default=str).encode("utf-8"))
        await task.s3_service.upload_file(
            bucket_key=ARCHIVE_BUCKET_KEY,
            file_key=archive_key,
            content=compressed,
            content_type="application/gzip",
            metadata={"kind": "email-deliveries", "retention-days": str(retention_days)},
        )
        stats["archive_key"] = archive_key

        archived_at = now.isoformat()
        for row in rows:
            row_id = row.get("id")
            if not row_id:
                continue
            updated = await task.directus_service.update_item(
                COLLECTION,
                row_id,
                {
                    "status": "archived",
                    "archived_at": archived_at,
                    "archive_key": archive_key,
                    "metadata": None,
                    "error": None,
                },
                admin_required=True,
            )
            if updated:
                stats["archived"] += 1
            else:
                stats["failed_updates"] += 1

        logger.info("Email delivery archive completed: %s", stats)
        return stats
    except Exception as exc:
        logger.error("Email delivery archive failed: %s", exc, exc_info=True)
        stats["error"] = str(exc)
        return stats
    finally:
        await task.cleanup_services()
