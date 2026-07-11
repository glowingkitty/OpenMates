"""Red contracts for unified detail-page metadata writes.

These tests keep metadata persistence in each owning domain while requiring one
shared security property: writes are owner-scoped and accepted updates receive
server-authoritative monotonic versions. Client-encrypted domains must persist
only ciphertext; Workflow metadata remains inside its Automation Vault boundary.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.services.directus.project_methods import ProjectMethods, hash_id
from backend.core.api.app.services.user_plan_service import UserPlanNotFoundError, UserPlanService
from backend.core.api.app.services.user_task_service import UserTaskNotFoundError, UserTaskService
from backend.core.api.app.services.workflow_service import WorkflowNotFoundError
from backend.tests.workflow_test_utils import workflow_service


class OwnerScopedMetadataMethods:
    """Minimal task/plan repository double that never invents server versions."""

    def __init__(self, item_id_field: str, item_id: str) -> None:
        self.item_id_field = item_id_field
        self.item_id = item_id
        self.record = {
            "id": "row-1",
            item_id_field: item_id,
            "version": 4,
            "updated_at": 900,
            "encrypted_title": "cipher-title-v4",
        }
        self.patches: list[dict[str, object]] = []

    async def _get(self, item_id: str, user_id: str) -> dict[str, object] | None:
        if item_id != self.item_id or user_id != "owner-1":
            return None
        return dict(self.record)

    async def get_task(self, task_id: str, user_id: str) -> dict[str, object] | None:
        return await self._get(task_id, user_id)

    async def get_plan(self, plan_id: str, user_id: str) -> dict[str, object] | None:
        return await self._get(plan_id, user_id)

    async def _update(self, item_id: str, user_id: str, patch: dict[str, object]) -> dict[str, object] | None:
        if item_id != self.item_id or user_id != "owner-1":
            return None
        self.patches.append(dict(patch))
        self.record.update(patch)
        return dict(self.record)

    async def update_task(self, task_id: str, user_id: str, patch: dict[str, object]) -> dict[str, object] | None:
        return await self._update(task_id, user_id, patch)

    async def update_plan(self, plan_id: str, user_id: str, patch: dict[str, object]) -> dict[str, object] | None:
        return await self._update(plan_id, user_id, patch)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("service_type", "methods_id_field", "item_id", "update_name", "not_found_error", "encrypted_description_field"),
    [
        (UserTaskService, "task_id", "task-1", "update_task", UserTaskNotFoundError, "encrypted_description"),
        (UserPlanService, "plan_id", "plan-1", "update_plan", UserPlanNotFoundError, "encrypted_summary"),
    ],
)
async def test_task_and_plan_metadata_versions_are_owner_scoped_and_server_monotonic(
    service_type,
    methods_id_field: str,
    item_id: str,
    update_name: str,
    not_found_error,
    encrypted_description_field: str,
) -> None:
    methods = OwnerScopedMetadataMethods(methods_id_field, item_id)
    service = service_type(methods)
    update = getattr(service, update_name)

    with pytest.raises(not_found_error):
        await update(item_id, "read-only-user", {"version": 4, "encrypted_title": "forged-ciphertext"})

    first = await update(
        item_id,
        "owner-1",
        {
            "version": 4,
            "updated_at": 100,
            "encrypted_title": "cipher-title-v5",
            encrypted_description_field: "cipher-description-v5",
        },
    )
    second = await update(
        item_id,
        "owner-1",
        {
            "version": 5,
            "updated_at": 50,
            "encrypted_title": "cipher-title-v6",
        },
    )

    assert first["version"] == 5
    assert second["version"] == 6
    assert methods.patches[0]["version"] == 5
    assert methods.patches[1]["version"] == 6
    assert methods.record["encrypted_title"] == "cipher-title-v6"
    assert "title" not in methods.record
    assert "description" not in methods.record
    assert "summary" not in methods.record


@pytest.mark.asyncio
async def test_project_metadata_version_is_owner_scoped_and_ignores_client_clock_ordering() -> None:
    owner_hash = hash_id("owner-1")
    record = {
        "id": "row-1",
        "project_id": "project-1",
        "hashed_user_id": owner_hash,
        "version": 4,
        "updated_at": 900,
        "encrypted_name": "cipher-name-v4",
    }

    async def get_items(_collection, *, params, **_kwargs):
        if params.get("filter[hashed_user_id][_eq]") != owner_hash:
            return []
        return [dict(record)]

    async def update_item(_collection, _row_id, patch):
        record.update(patch)
        return dict(record)

    directus = SimpleNamespace(
        get_items=AsyncMock(side_effect=get_items),
        update_item=AsyncMock(side_effect=update_item),
    )
    methods = ProjectMethods(directus)

    assert await methods.update_project("project-1", "read-only-user", {"encrypted_name": "forged"}) is None
    updated = await methods.update_project(
        "project-1",
        "owner-1",
        {
            "version": 4,
            "updated_at": 100,
            "encrypted_name": "cipher-name-v5",
            "encrypted_description": "cipher-description-v5",
        },
    )

    assert updated is not None
    assert updated["version"] == 5
    persisted_patch = directus.update_item.await_args.args[2]
    assert persisted_patch["version"] == 5
    assert persisted_patch["encrypted_name"] == "cipher-name-v5"
    assert "name" not in persisted_patch
    assert "description" not in persisted_patch


def test_workflow_metadata_version_is_owner_scoped_and_vault_backed() -> None:
    service = workflow_service()
    workflow = service.create_workflow(
        "owner-1",
        "Workflow title v1",
        {
            "version": 1,
            "trigger_node_id": "manual",
            "nodes": [{"id": "manual", "type": "manual_trigger", "title": "Manual", "config": {}}],
            "edges": [],
        },
        description="Workflow description v1",
    )

    with pytest.raises(WorkflowNotFoundError):
        service.update_workflow(workflow.id, "read-only-user", title="Forged title")

    updated = service.update_workflow(
        workflow.id,
        "owner-1",
        title="Workflow title v2",
        description="Workflow description v2",
    )
    record = service.repository.get_workflow(workflow.id, "owner-1")

    assert updated.version == 2
    assert record["version"] == 2
    assert "title" not in record
    assert "description" not in record
    assert record["encrypted_title_ref"]
    assert record["encrypted_description_ref"]
