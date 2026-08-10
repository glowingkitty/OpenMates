# backend/core/api/app/services/user_task_archive_service.py
#
# Archives completed Tasks V1 records out of Directus hot tables. The archive
# payload contains only already-encrypted task content/key wrappers, then the
# bundle is compressed and user-key encrypted before S3 upload.
# Spec: docs/specs/tasks-v1/spec.yml.

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from backend.core.api.app.services.directus.user_task_methods import USER_TASK_FIELDS, hash_id

logger = logging.getLogger(__name__)

TASK_ARCHIVE_BUCKET_KEY = "task_archives"
DEFAULT_TASK_ARCHIVE_RETENTION_DAYS = 30
DEFAULT_TASK_ARCHIVE_LIMIT = 500


class UserTaskArchiveService:
    def __init__(self, *, directus_service: Any, s3_service: Any, encryption_service: Any):
        self.directus_service = directus_service
        self.s3_service = s3_service
        self.encryption_service = encryption_service

    async def archive_completed_tasks(self, *, retention_days: int = DEFAULT_TASK_ARCHIVE_RETENTION_DAYS, limit: int = DEFAULT_TASK_ARCHIVE_LIMIT) -> dict[str, Any]:
        cutoff = int(time.time()) - int(retention_days) * 86_400
        tasks = await self.directus_service.get_items(
            "user_tasks",
            params={
                "filter": {
                    "_and": [
                        {"status": {"_eq": "done"}},
                        {"completed_at": {"_nnull": True}},
                        {"completed_at": {"_lt": cutoff}},
                    ]
                },
                "fields": USER_TASK_FIELDS,
                "sort": "completed_at",
                "limit": max(1, min(int(limit), 5000)),
            },
            no_cache=True,
            admin_required=True,
        )
        if not isinstance(tasks, list) or not tasks:
            return {"checked": 0, "archived": 0, "archives": 0, "failed": 0}

        by_owner: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for task in tasks:
            owner_hash = task.get("hashed_user_id")
            if isinstance(owner_hash, str) and owner_hash:
                by_owner[owner_hash].append(task)

        stats = {"checked": len(tasks), "archived": 0, "archives": 0, "failed": 0}
        for owner_hash, owner_tasks in by_owner.items():
            try:
                archived_count = await self._archive_owner_tasks(owner_hash, owner_tasks, cutoff=cutoff, retention_days=retention_days)
                stats["archived"] += archived_count
                if archived_count:
                    stats["archives"] += 1
            except Exception as exc:
                stats["failed"] += len(owner_tasks)
                logger.error("Task archive failed for owner hash %s: %s", owner_hash, exc, exc_info=True)
        return stats

    async def _archive_owner_tasks(self, owner_hash: str, tasks: list[dict[str, Any]], *, cutoff: int, retention_days: int) -> int:
        vault_key_id = await self._vault_key_id_for_owner_hash(owner_hash)
        if not vault_key_id:
            logger.warning("Skipping task archive for owner hash %s: vault key not found", owner_hash)
            return 0

        task_ids = [str(task["task_id"]) for task in tasks if task.get("task_id")]
        wrappers: list[dict[str, Any]] = []
        activities: list[dict[str, Any]] = []
        for task_id in task_ids:
            wrappers.extend(await self._task_key_wrappers(owner_hash, task_id))
            activities.extend(await self._task_activity(task_id))

        now = int(time.time())
        archive_payload = {
            "version": 1,
            "kind": "user_task_archive",
            "hashed_user_id": owner_hash,
            "archived_at": now,
            "completed_before": cutoff,
            "retention_days": retention_days,
            "tasks": tasks,
            "key_wrappers": wrappers,
            "activity": activities,
        }
        compressed = gzip.compress(json.dumps(archive_payload, ensure_ascii=False, default=str).encode("utf-8"))
        encrypted_text, _ = await self.encryption_service.encrypt_with_user_key(base64.b64encode(compressed).decode("utf-8"), vault_key_id)
        encrypted_bytes = encrypted_text.encode("utf-8")
        checksum = hashlib.sha256(encrypted_bytes).hexdigest()
        archive_key = f"task-archives/{owner_hash}/{datetime.now(timezone.utc):%Y/%m/%d}/tasks-{now}.json.gz"

        await self.s3_service.upload_file(
            bucket_key=TASK_ARCHIVE_BUCKET_KEY,
            file_key=archive_key,
            content=encrypted_bytes,
            content_type="application/gzip",
            metadata={"kind": "user-task-archive", "retention-days": str(retention_days)},
        )
        success, archive_row = await self.directus_service.create_item(
            "user_task_archives",
            {
                "hashed_user_id": owner_hash,
                "archive_s3_key": archive_key,
                "task_count": len(tasks),
                "archived_at": now,
                "completed_before": cutoff,
                "retention_days": retention_days,
                "content_checksum": checksum,
                "encrypted_manifest": None,
            },
            admin_required=True,
        )
        if not success:
            logger.error("Task archive row creation failed for owner hash %s: %s", owner_hash, archive_row)
            return 0

        await self._delete_hot_rows(tasks, wrappers, activities)
        return len(tasks)

    async def _vault_key_id_for_owner_hash(self, owner_hash: str) -> str | None:
        users = await self.directus_service.get_items(
            "directus_users",
            params={"fields": "id,vault_key_id", "limit": -1},
            no_cache=True,
            admin_required=True,
        )
        if not isinstance(users, list):
            return None
        for user in users:
            user_id = user.get("id")
            if isinstance(user_id, str) and hash_id(user_id) == owner_hash:
                vault_key_id = user.get("vault_key_id")
                return vault_key_id if isinstance(vault_key_id, str) and vault_key_id else None
        return None

    async def _task_key_wrappers(self, owner_hash: str, task_id: str) -> list[dict[str, Any]]:
        wrappers = await self.directus_service.get_items(
            "user_task_key_wrappers",
            params={
                "filter": {
                    "_and": [
                        {"hashed_user_id": {"_eq": owner_hash}},
                        {"hashed_task_id": {"_eq": hash_id(task_id)}},
                    ]
                },
                "fields": "*",
                "limit": 50,
            },
            no_cache=True,
            admin_required=True,
        )
        return wrappers if isinstance(wrappers, list) else []

    async def _task_activity(self, task_id: str) -> list[dict[str, Any]]:
        activity = await self.directus_service.get_items(
            "user_task_activity",
            params={"filter[task_id][_eq]": task_id, "fields": "*", "limit": -1},
            no_cache=True,
            admin_required=True,
        )
        return activity if isinstance(activity, list) else []

    async def _delete_hot_rows(self, tasks: list[dict[str, Any]], wrappers: list[dict[str, Any]], activities: list[dict[str, Any]]) -> None:
        for row in activities:
            row_id = row.get("id")
            if row_id:
                await self.directus_service.delete_item("user_task_activity", row_id, admin_required=True)
        for row in wrappers:
            row_id = row.get("id")
            if row_id:
                await self.directus_service.delete_item("user_task_key_wrappers", row_id, admin_required=True)
        for row in tasks:
            row_id = row.get("id")
            if row_id:
                await self.directus_service.delete_item("user_tasks", row_id, admin_required=True)
