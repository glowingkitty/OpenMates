"""Completed Task archival must preserve dependency graph targets."""

import pytest

from backend.core.api.app.services.user_task_archive_service import UserTaskArchiveService


class ArchiveDirectus:
    async def get_items(self, collection, **_kwargs):
        if collection == "user_tasks":
            return [{"id": "row-1", "task_id": "task-1", "hashed_user_id": "owner-1", "status": "done", "completed_at": 1}]
        if collection == "user_work_dependencies":
            return [{"source_ref": "plan:plan-1", "target_ref": "task:task-1"}]
        raise AssertionError(collection)


class CacheClient:
    def __init__(self):
        self.values = {}

    async def set(self, key, value, **_kwargs):
        if key in self.values:
            return False
        self.values[key] = value
        return True

    async def get(self, key):
        return self.values.get(key)

    async def delete(self, key):
        self.values.pop(key, None)

    async def eval(self, script, _keys, key, token, *_args):
        if "expire" in script:
            return 1 if self.values.get(key) == token else 0
        if self.values.get(key) != token:
            return 0
        self.values.pop(key, None)
        return 1


class CacheService:
    client = CacheClient()


# contract-test: direct surface=rest_api assertions=tasks.dependencies.done-only
@pytest.mark.asyncio
async def test_archive_skips_tasks_with_incoming_or_outgoing_dependencies():
    service = UserTaskArchiveService(directus_service=ArchiveDirectus(), s3_service=None, encryption_service=None, cache_service=CacheService())
    assert await service.archive_completed_tasks(retention_days=0) == {"checked": 1, "archived": 0, "archives": 0, "failed": 0, "skipped_dependencies": 1}
