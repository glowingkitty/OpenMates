# backend/tests/test_workspace_change_history.py
#
# Tests for the shared workspace history service. The fake Directus adapter keeps
# these contracts focused on privacy-safe metadata, history writes, retention,
# and undo semantics without depending on a live Directus instance.

from __future__ import annotations

import pytest

from backend.core.api.app.services.workspace_change_history_service import WorkspaceChangeHistoryService, s3_workspace_history_archive_io


class FakeDirectus:
    def __init__(self) -> None:
        self.collections: dict[str, list[dict]] = {
            "workspace_change_sets": [],
            "workspace_change_entries": [],
            "workspace_change_archives": [],
            "user_tasks": [],
            "user_plans": [],
            "projects": [],
        }
        self.user_task = self
        self.user_plan = self
        self.project = self

    async def create_item(self, collection: str, payload: dict, **_kwargs):
        row = {"id": f"{collection}-{len(self.collections.setdefault(collection, [])) + 1}", **payload}
        self.collections.setdefault(collection, []).append(row)
        return True, row

    async def get_items(self, collection: str, params: dict | None = None, **_kwargs):
        rows = list(self.collections.get(collection, []))
        params = params or {}
        for key, value in params.items():
            if key.startswith("filter[") and key.endswith("][_eq]"):
                field = key.removeprefix("filter[").split("]", 1)[0]
                rows = [row for row in rows if row.get(field) == value]
        filter_obj = params.get("filter")
        if isinstance(filter_obj, dict) and "_and" in filter_obj:
            for condition in filter_obj["_and"]:
                for field, matcher in condition.items():
                    if isinstance(matcher, dict) and "_eq" in matcher:
                        rows = [row for row in rows if row.get(field) == matcher["_eq"]]
                    if isinstance(matcher, dict) and "_null" in matcher:
                        rows = [row for row in rows if (row.get(field) is None) is bool(matcher["_null"])]
        sort = params.get("sort")
        if isinstance(sort, str):
            reverse = sort.startswith("-")
            field = sort[1:] if reverse else sort
            rows.sort(key=lambda row: row.get(field) or 0, reverse=reverse)
        limit = params.get("limit")
        if isinstance(limit, int) and limit >= 0:
            rows = rows[:limit]
        return rows

    async def update_item(self, collection: str, row_id: str, patch: dict, **_kwargs):
        for row in self.collections.get(collection, []):
            if row.get("id") == row_id:
                row.update(patch)
                return row
        return None

    async def delete_item(self, collection: str, row_id: str, **_kwargs):
        rows = self.collections.get(collection, [])
        for index, row in enumerate(rows):
            if row.get("id") == row_id:
                del rows[index]
                return True
        return False

    async def get_task(self, task_id: str, user_id: str):
        owner_hash = "0a041b9462caa4a31bac3567e0b6e6fd9100787d6a1b8822a98203a5caa1cf65"
        assert user_id == "user-1"
        return next((row for row in self.collections["user_tasks"] if row.get("task_id") == task_id and row.get("hashed_user_id") == owner_hash), None)

    async def create_task(self, user_id: str, payload: dict):
        assert user_id == "user-1"
        return (await self.create_item("user_tasks", {**payload, "hashed_user_id": "0a041b9462caa4a31bac3567e0b6e6fd9100787d6a1b8822a98203a5caa1cf65"}))[1]

    async def update_task_if_version(self, task_id: str, user_id: str, patch: dict, expected_version: int):
        task = await self.get_task(task_id, user_id)
        if not task or int(task.get("version") or 0) != expected_version:
            return None
        return await self.update_item("user_tasks", task["id"], {**patch, "version": expected_version + 1})

    async def delete_task(self, task_id: str, user_id: str, expected_version: int):
        task = await self.get_task(task_id, user_id)
        if not task or int(task.get("version") or 0) != expected_version:
            return False
        return await self.delete_item("user_tasks", task["id"])

    async def get_plan(self, plan_id: str, user_id: str):
        owner_hash = "0a041b9462caa4a31bac3567e0b6e6fd9100787d6a1b8822a98203a5caa1cf65"
        assert user_id == "user-1"
        return next((row for row in self.collections["user_plans"] if row.get("plan_id") == plan_id and row.get("hashed_user_id") == owner_hash), None)

    async def create_plan(self, user_id: str, payload: dict):
        assert user_id == "user-1"
        return (await self.create_item("user_plans", {**payload, "hashed_user_id": "0a041b9462caa4a31bac3567e0b6e6fd9100787d6a1b8822a98203a5caa1cf65"}))[1]

    async def update_plan(self, plan_id: str, user_id: str, patch: dict):
        plan = await self.get_plan(plan_id, user_id)
        if not plan:
            return None
        return await self.update_item("user_plans", plan["id"], patch)

    async def get_project(self, project_id: str, user_id: str):
        owner_hash = "0a041b9462caa4a31bac3567e0b6e6fd9100787d6a1b8822a98203a5caa1cf65"
        assert user_id == "user-1"
        return next((row for row in self.collections["projects"] if row.get("project_id") == project_id and row.get("hashed_user_id") == owner_hash), None)

    async def create_project(self, user_id: str, payload: dict):
        assert user_id == "user-1"
        return (await self.create_item("projects", {**payload, "hashed_user_id": "0a041b9462caa4a31bac3567e0b6e6fd9100787d6a1b8822a98203a5caa1cf65"}))[1]

    async def update_project(self, project_id: str, user_id: str, patch: dict):
        project = await self.get_project(project_id, user_id)
        if not project:
            return None
        version = int(project.get("version") or 1) + 1
        return await self.update_item("projects", project["id"], {**patch, "version": version})

    async def delete_project(self, project_id: str, user_id: str):
        project = await self.get_project(project_id, user_id)
        if not project:
            return False
        return await self.delete_item("projects", project["id"])


class FakeS3Service:
    environment = "development"

    def __init__(self) -> None:
        self.uploads: dict[str, bytes] = {}

    async def upload_file(self, *, bucket_key: str, file_key: str, content: bytes, content_type: str):
        assert bucket_key == "workspace_history_archives"
        assert content_type == "application/json"
        self.uploads[file_key] = content
        return {"s3_key": file_key}

    async def get_file(self, *, bucket_name: str, object_key: str):
        assert bucket_name == "dev-openmates-workspace-history-archives"
        return self.uploads.get(object_key)


@pytest.mark.asyncio
async def test_record_change_set_creates_metadata_and_entries_without_plaintext_title() -> None:
    directus = FakeDirectus()
    service = WorkspaceChangeHistoryService(directus)

    result = await service.record_change_set(
        user_id="user-1",
        source="cli",
        namespace="tasks",
        action_type="create",
        entries=[
            {
                "object_type": "task",
                "object_id": "task-1",
                "operation": "create",
                "after": {"task_id": "task-1", "encrypted_title": "ciphertext-title", "version": 1},
            }
        ],
        redacted_summary="Created 1 task",
    )

    assert result["change_set"]["change_set_id"].startswith("chg_")
    assert result["entries"][0]["entry_id"].startswith("che_")
    assert result["entries"][0]["encrypted_after_ref"]
    assert "Prepare launch" not in str(result)
    assert directus.collections["workspace_change_sets"][0]["namespace"] == "tasks"


@pytest.mark.asyncio
async def test_s3_archive_io_uses_workspace_history_bucket_and_checksummed_payload() -> None:
    s3 = FakeS3Service()
    writer, reader = s3_workspace_history_archive_io(s3)
    payload = b'{"entries":[]}'

    checksum = await writer("workspace-history/hash/task/task-1/archive.json.enc", payload)
    restored = await reader("workspace-history/hash/task/task-1/archive.json.enc")

    assert checksum
    assert restored == payload


@pytest.mark.asyncio
async def test_archive_due_keeps_latest_10_and_marks_oldest_10_archived() -> None:
    directus = FakeDirectus()
    uploaded: list[tuple[str, bytes]] = []

    async def writer(key: str, payload: bytes) -> str:
        uploaded.append((key, payload))
        return "checksum-from-writer"

    service = WorkspaceChangeHistoryService(directus, archive_writer=writer)
    for index in range(20):
        await service.record_change_set(
            user_id="user-1",
            source="cli",
            namespace="tasks",
            action_type="update",
            entries=[{"object_type": "task", "object_id": "task-1", "operation": "update", "before": {"version": index}, "after": {"version": index + 1}}],
        )

    archived = await service.archive_due_entries(user_id="user-1", object_type="task", object_id="task-1")

    assert archived["archived_count"] == 10
    assert len(uploaded) == 1
    assert len(directus.collections["workspace_change_archives"]) == 1
    hot = [row for row in directus.collections["workspace_change_entries"] if row.get("archived_at") is None]
    assert len(hot) == 10


@pytest.mark.asyncio
async def test_cold_restore_loads_archived_entry_when_hot_snapshot_refs_are_missing() -> None:
    directus = FakeDirectus()
    archive_blobs: dict[str, bytes] = {}

    async def writer(key: str, payload: bytes) -> str:
        archive_blobs[key] = payload
        return ""

    async def reader(key: str) -> bytes | None:
        return archive_blobs.get(key)

    service = WorkspaceChangeHistoryService(directus, archive_writer=writer, archive_reader=reader)
    await directus.create_task(
        "user-1",
        {"task_id": "task-1", "encrypted_title": "cipher-current", "encrypted_task_key": "key", "version": 1, "created_at": 1, "updated_at": 1},
    )
    target_entry_id = None
    for index in range(20):
        change = await service.record_change_set(
            user_id="user-1",
            source="cli",
            namespace="tasks",
            action_type="update",
            entries=[{
                "object_type": "task",
                "object_id": "task-1",
                "operation": "update",
                "before": {"task_id": "task-1", "encrypted_title": f"cipher-before-{index}", "version": index + 1},
                "after": {"task_id": "task-1", "encrypted_title": f"cipher-after-{index}", "version": index + 2},
            }],
        )
        if index == 0:
            target_entry_id = change["entries"][0]["entry_id"]

    await service.archive_due_entries(user_id="user-1", object_type="task", object_id="task-1")
    first_entry = directus.collections["workspace_change_entries"][0]
    first_entry["encrypted_before_ref"] = None
    first_entry["encrypted_after_ref"] = None

    restored = await service.restore_object_to_entry(
        user_id="user-1",
        object_type="task",
        object_id="task-1",
        entry_id=str(target_entry_id),
        state="after",
    )

    assert restored["object"]["encrypted_title"] == "cipher-after-0"
    assert restored["object"]["version"] == 2


@pytest.mark.asyncio
async def test_undo_marks_original_entries_and_creates_compensating_change_set() -> None:
    directus = FakeDirectus()
    service = WorkspaceChangeHistoryService(directus)
    await directus.create_task(
        "user-1",
        {"task_id": "task-1", "encrypted_title": "cipher-created", "encrypted_task_key": "key", "version": 1, "created_at": 1, "updated_at": 1},
    )
    created = await service.record_change_set(
        user_id="user-1",
        source="cli",
        namespace="tasks",
        action_type="create",
        entries=[{"object_type": "task", "object_id": "task-1", "operation": "create", "after": {"task_id": "task-1", "version": 1}}],
    )

    undone = await service.undo_change_set(user_id="user-1", change_set_id=created["change_set"]["change_set_id"])

    assert undone["change_set"]["action_type"] == "undo"
    assert undone["entries"][0]["operation"] == "delete"
    assert directus.collections["workspace_change_entries"][0]["undone_at"] is not None
    assert await directus.get_task("task-1", "user-1") is None


@pytest.mark.asyncio
async def test_restore_task_entry_applies_opaque_snapshot_as_new_version() -> None:
    directus = FakeDirectus()
    service = WorkspaceChangeHistoryService(directus)
    created = await directus.create_task(
        "user-1",
        {"task_id": "task-1", "encrypted_title": "cipher-current", "encrypted_task_key": "key", "version": 1, "created_at": 1, "updated_at": 1},
    )
    change = await service.record_change_set(
        user_id="user-1",
        source="cli",
        namespace="tasks",
        action_type="update",
        entries=[{
            "object_type": "task",
            "object_id": "task-1",
            "operation": "update",
            "before": {**created, "encrypted_title": "cipher-before", "version": 1},
            "after": {**created, "encrypted_title": "cipher-after", "version": 2},
        }],
    )

    restored = await service.restore_object_to_entry(
        user_id="user-1",
        object_type="task",
        object_id="task-1",
        entry_id=change["entries"][0]["entry_id"],
        state="before",
    )

    assert restored["object"]["encrypted_title"] == "cipher-before"
    assert restored["object"]["version"] == 2
    assert restored["entries"][0]["restored_from_entry_id"] == change["entries"][0]["entry_id"]
    assert restored["rollback_entry_commands"][0].startswith("openmates tasks restore task-1 --entry")


@pytest.mark.asyncio
async def test_restore_plan_entry_applies_opaque_snapshot() -> None:
    directus = FakeDirectus()
    service = WorkspaceChangeHistoryService(directus)
    created = await directus.create_plan(
        "user-1",
        {"plan_id": "plan-1", "encrypted_title": "cipher-current", "encrypted_plan_key": "key", "version": 1, "created_at": 1, "updated_at": 1},
    )
    change = await service.record_change_set(
        user_id="user-1",
        source="cli",
        namespace="plans",
        action_type="update",
        entries=[{
            "object_type": "plan",
            "object_id": "plan-1",
            "operation": "update",
            "before": {**created, "encrypted_title": "cipher-before", "version": 1},
            "after": {**created, "encrypted_title": "cipher-after", "version": 2},
        }],
    )

    restored = await service.restore_object_to_entry(
        user_id="user-1",
        object_type="plan",
        object_id="plan-1",
        entry_id=change["entries"][0]["entry_id"],
        state="before",
    )

    assert restored["object"]["encrypted_title"] == "cipher-before"
    assert restored["object"]["version"] == 2
    assert restored["rollback_entry_commands"][0].startswith("openmates plans restore plan-1 --entry")


@pytest.mark.asyncio
async def test_restore_project_entry_can_delete_created_project() -> None:
    directus = FakeDirectus()
    service = WorkspaceChangeHistoryService(directus)
    created = await directus.create_project(
        "user-1",
        {"project_id": "project-1", "encrypted_name": "cipher-current", "encrypted_project_key": "key", "version": 1, "created_at": 1, "updated_at": 1},
    )
    change = await service.record_change_set(
        user_id="user-1",
        source="cli",
        namespace="projects",
        action_type="create",
        entries=[{"object_type": "project", "object_id": "project-1", "operation": "create", "after": created}],
    )

    restored = await service.restore_object_to_entry(
        user_id="user-1",
        object_type="project",
        object_id="project-1",
        entry_id=change["entries"][0]["entry_id"],
        state="before",
    )

    assert restored["object"] is None
    assert await directus.get_project("project-1", "user-1") is None
    assert restored["rollback_entry_commands"][0].startswith("openmates projects restore project-1 --entry")


@pytest.mark.asyncio
async def test_undo_workflow_change_set_fails_visibly_instead_of_noop() -> None:
    directus = FakeDirectus()
    service = WorkspaceChangeHistoryService(directus)
    change = await service.record_change_set(
        user_id="user-1",
        source="cli",
        namespace="workflows",
        action_type="create",
        entries=[{"object_type": "workflow", "object_id": "wf-1", "operation": "create", "workflow_version_after_id": "wv-1"}],
    )

    with pytest.raises(ValueError, match="Workflow change-set undo"):
        await service.undo_change_set(user_id="user-1", change_set_id=change["change_set"]["change_set_id"])

    assert directus.collections["workspace_change_entries"][0]["undone_at"] is None


@pytest.mark.asyncio
async def test_undo_workflow_change_set_uses_injected_workflow_handler() -> None:
    directus = FakeDirectus()
    service = WorkspaceChangeHistoryService(directus)
    change = await service.record_change_set(
        user_id="user-1",
        source="cli",
        namespace="workflows",
        action_type="update",
        entries=[{
            "object_type": "workflow",
            "object_id": "wf-1",
            "operation": "workflow_version",
            "workflow_version_before_id": "wv-before",
            "workflow_version_after_id": "wv-after",
        }],
    )
    handled: list[dict] = []

    async def workflow_handler(entry: dict) -> dict:
        handled.append(entry)
        return {"workflow_version_before_id": entry["workflow_version_after_id"], "workflow_version_after_id": "wv-restored"}

    undone = await service.undo_change_set(
        user_id="user-1",
        change_set_id=change["change_set"]["change_set_id"],
        workflow_undo_handler=workflow_handler,
    )

    assert handled[0]["object_id"] == "wf-1"
    assert undone["entries"][0]["workflow_version_before_id"] == "wv-after"
    assert undone["entries"][0]["workflow_version_after_id"] == "wv-restored"
    assert directus.collections["workspace_change_entries"][0]["undone_at"] is not None


@pytest.mark.asyncio
async def test_workflow_status_history_keeps_opaque_status_snapshot_for_undo() -> None:
    directus = FakeDirectus()
    service = WorkspaceChangeHistoryService(directus)
    change = await service.record_change_set(
        user_id="user-1",
        source="cli",
        namespace="workflows",
        action_type="disable",
        entries=[{
            "object_type": "workflow",
            "object_id": "wf-1",
            "operation": "status",
            "before": {"workflow_version_id": "wv-1", "enabled": True, "status": "active"},
            "after": {"workflow_version_id": "wv-1", "enabled": False, "status": "disabled"},
            "workflow_version_before_id": "wv-1",
            "workflow_version_after_id": "wv-1",
        }],
    )
    entry = change["entries"][0]

    before_snapshot = service.snapshot_for_entry_state(entry, "before")
    after_snapshot = service.snapshot_for_entry_state(entry, "after")

    assert before_snapshot == {"workflow_version_id": "wv-1", "enabled": True, "status": "active"}
    assert after_snapshot == {"workflow_version_id": "wv-1", "enabled": False, "status": "disabled"}

    async def workflow_handler(entry: dict) -> dict:
        target = service.snapshot_for_entry_state(entry, "before")
        return {
            "before": {"workflow_version_id": "wv-1", "enabled": False, "status": "disabled"},
            "after": target,
            "workflow_version_before_id": entry["workflow_version_after_id"],
            "workflow_version_after_id": entry["workflow_version_before_id"],
        }

    undone = await service.undo_change_set(
        user_id="user-1",
        change_set_id=change["change_set"]["change_set_id"],
        workflow_undo_handler=workflow_handler,
    )

    undo_snapshot = service.snapshot_for_entry_state(undone["entries"][0], "after")
    assert undone["entries"][0]["operation"] == "status"
    assert undo_snapshot == {"workflow_version_id": "wv-1", "enabled": True, "status": "active"}
