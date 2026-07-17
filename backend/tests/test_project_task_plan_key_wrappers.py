"""Backend contract tests for project/plan/task wrapper canonicalization.

Projects, plans, and tasks are not shipped production surfaces yet, so they can
move to wrapper-row key material before launch. These tests verify the backend
accepts plan/team wrapper contexts, records team key epochs, and rejects scoped
team wrappers without a valid epoch.
"""

import hashlib

import pytest

from backend.core.api.app.services.directus.project_methods import ProjectMethods
from backend.core.api.app.services.directus.user_plan_methods import UserPlanMethods
from backend.core.api.app.services.directus.user_task_methods import UserTaskMethods


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class FakeDirectusService:
    def __init__(self) -> None:
        self.created: list[tuple[str, dict, bool | None]] = []

    async def create_item(self, collection: str, record: dict, admin_required: bool | None = None):
        created = {"id": f"{collection}-{len(self.created) + 1}", **record}
        self.created.append((collection, record.copy(), admin_required))
        return True, created

    async def delete_item(self, _collection: str, _item_id: str, **_kwargs):
        return True

    async def get_items(self, _collection: str, params: dict, **_kwargs):
        return []


@pytest.mark.anyio
async def test_task_plan_and_team_wrappers_are_persisted_with_epoch():
    directus = FakeDirectusService()
    methods = UserTaskMethods(directus)
    created = await methods.create_task(
        "user-1",
        {
            "task_id": "task-1",
            "version": 1,
            "created_at": 1,
            "updated_at": 1,
            "encrypted_title": "cipher-title",
            "encrypted_task_key": None,
            "plan_id": "plan-1",
            "key_wrappers": [
                {"key_type": "master", "encrypted_task_key": "cipher-master", "created_at": 1},
                {"key_type": "plan", "hashed_plan_id": _hash("plan-1"), "encrypted_task_key": "cipher-plan", "created_at": 1},
                {"key_type": "team", "hashed_team_id": _hash("team-1"), "team_key_epoch": 3, "encrypted_task_key": "cipher-team", "created_at": 1},
            ],
        },
    )

    assert created is not None
    wrapper_records = [record for collection, record, _admin in directus.created if collection == "user_task_key_wrappers"]
    assert [record["key_type"] for record in wrapper_records] == ["master", "plan", "team"]
    assert wrapper_records[1]["hashed_plan_id"] == _hash("plan-1")
    assert wrapper_records[2]["hashed_team_id"] == _hash("team-1")
    assert wrapper_records[2]["team_key_epoch"] == 3
    assert all(record["wrapper_version"] == 1 for record in wrapper_records)


@pytest.mark.anyio
async def test_task_team_wrapper_requires_epoch():
    directus = FakeDirectusService()
    methods = UserTaskMethods(directus)

    created = await methods.create_task(
        "user-1",
        {
            "task_id": "task-1",
            "version": 1,
            "created_at": 1,
            "updated_at": 1,
            "encrypted_title": "cipher-title",
            "plan_id": "plan-1",
            "key_wrappers": [
                {"key_type": "master", "encrypted_task_key": "cipher-master", "created_at": 1},
                {"key_type": "plan", "hashed_plan_id": _hash("plan-1"), "encrypted_task_key": "cipher-plan", "created_at": 1},
                {"key_type": "team", "hashed_team_id": _hash("team-1"), "encrypted_task_key": "cipher-team", "created_at": 1},
            ],
        },
    )

    assert created is None
    assert directus.created == []


@pytest.mark.anyio
async def test_plan_team_wrapper_is_persisted_with_epoch():
    directus = FakeDirectusService()
    methods = UserPlanMethods(directus)
    created = await methods.create_plan(
        "user-1",
        {
            "plan_id": "plan-1",
            "created_at": 1,
            "updated_at": 1,
            "encrypted_title": "cipher-title",
            "key_wrappers": [
                {"key_type": "master", "encrypted_plan_key": "cipher-master", "created_at": 1},
                {"key_type": "team", "hashed_team_id": _hash("team-1"), "team_key_epoch": 5, "encrypted_plan_key": "cipher-team", "created_at": 1},
            ],
        },
    )

    assert created is not None
    wrapper_records = [record for collection, record, _admin in directus.created if collection == "user_plan_key_wrappers"]
    assert wrapper_records[1]["hashed_team_id"] == _hash("team-1")
    assert wrapper_records[1]["team_key_epoch"] == 5


@pytest.mark.anyio
async def test_project_key_wrappers_are_created_separately_from_row_key():
    directus = FakeDirectusService()
    methods = ProjectMethods(directus)
    created = await methods.create_project(
        "user-1",
        {
            "project_id": "project-1",
            "created_at": 1,
            "updated_at": 1,
            "encrypted_name": "cipher-name",
            "encrypted_project_key": None,
            "key_wrappers": [
                {"key_type": "master", "encrypted_project_key": "cipher-master", "created_at": 1},
                {"key_type": "team", "hashed_team_id": _hash("team-1"), "team_key_epoch": 2, "encrypted_project_key": "cipher-team", "created_at": 1},
            ],
        },
    )

    assert created is not None
    project_record = next(record for collection, record, _admin in directus.created if collection == "projects")
    assert project_record["encrypted_project_key"] is None
    wrapper_records = [record for collection, record, _admin in directus.created if collection == "project_key_wrappers"]
    assert [record["key_type"] for record in wrapper_records] == ["master", "team"]
    assert wrapper_records[1]["team_key_epoch"] == 2
