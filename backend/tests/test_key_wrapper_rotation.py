"""Rotation and replacement sequencing tests for key wrapper rows.

Object moves and key-context changes must add replacement wrapper rows before
deleting old access paths. If the owning object version cannot be advanced, the
new rows are removed and old wrappers are restored so decryptability remains.
"""

import hashlib

import pytest

from backend.core.api.app.services.directus.user_task_methods import UserTaskMethods


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def set(self, key: str, value: str, *, nx: bool, ex: int) -> bool:
        del ex
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def delete(self, key: str) -> None:
        self.values.pop(key, None)


class FakeCache:
    def __init__(self) -> None:
        self.redis = FakeRedis()

    @property
    def client(self):
        async def _client():
            return self.redis

        return _client()


class FakeDirectusService:
    def __init__(self, *, update_succeeds: bool = True) -> None:
        self.cache = FakeCache()
        self.update_succeeds = update_succeeds
        self.operations: list[tuple[str, str, dict | str | None]] = []
        self.task = {
            "id": "task-row-1",
            "task_id": "task-1",
            "hashed_user_id": _hash("user-1"),
            "version": 4,
            "linked_project_hashes": [],
        }
        self.wrappers = [
            {
                "id": "old-wrapper-1",
                "hashed_task_id": _hash("task-1"),
                "hashed_user_id": _hash("user-1"),
                "key_type": "master",
                "encrypted_task_key": "old-master-cipher",
                "wrapper_version": 1,
            }
        ]

    async def get_items(self, collection: str, params: dict, **_kwargs):
        if collection == "user_tasks":
            if params.get("filter[task_id][_eq]") == "task-1" and params.get("filter[hashed_user_id][_eq]") == _hash("user-1"):
                return [self.task]
            return []
        if collection == "user_task_key_wrappers":
            return list(self.wrappers)
        return []

    async def create_item(self, collection: str, record: dict, **_kwargs):
        created = {"id": f"new-wrapper-{len([op for op in self.operations if op[0] == 'create']) + 1}", **record}
        self.operations.append(("create", collection, created.copy()))
        self.wrappers.append(created)
        return True, created

    async def delete_item(self, collection: str, item_id: str, **_kwargs):
        self.operations.append(("delete", collection, item_id))
        self.wrappers = [wrapper for wrapper in self.wrappers if wrapper.get("id") != item_id]
        return True

    async def update_item_if_version(self, collection: str, item_id: str, patch: dict, expected_version: int, **_kwargs):
        self.operations.append(("update", collection, patch.copy()))
        if not self.update_succeeds or item_id != self.task["id"] or expected_version != self.task["version"]:
            return None
        self.task = {**self.task, **patch}
        return self.task


def _replacement_wrappers() -> list[dict]:
    return [
        {"key_type": "master", "encrypted_task_key": "new-master-cipher"},
        {
            "key_type": "team",
            "hashed_team_id": _hash("team-1"),
            "team_key_epoch": 2,
            "encrypted_task_key": "new-team-cipher",
        },
    ]


@pytest.mark.anyio
async def test_task_wrapper_replacement_adds_new_wrappers_before_deleting_old_ones():
    directus = FakeDirectusService()
    methods = UserTaskMethods(directus)

    created = await methods.replace_task_key_wrappers("user-1", "task-1", _replacement_wrappers(), expected_version=4)

    assert created is not None
    operation_names = [operation[0] for operation in directus.operations]
    assert operation_names[:3] == ["create", "create", "delete"]
    assert operation_names[-1] == "update"
    assert [wrapper["key_type"] for wrapper in created] == ["master", "team"]
    assert created[1]["team_key_epoch"] == 2
    assert all(wrapper.get("id") != "old-wrapper-1" for wrapper in directus.wrappers)
    assert directus.task["version"] == 5


@pytest.mark.anyio
async def test_task_wrapper_replacement_restores_old_wrappers_if_version_commit_fails():
    directus = FakeDirectusService(update_succeeds=False)
    methods = UserTaskMethods(directus)

    with pytest.raises(RuntimeError, match="Failed to advance task version"):
        await methods.replace_task_key_wrappers("user-1", "task-1", _replacement_wrappers(), expected_version=4)

    operation_names = [operation[0] for operation in directus.operations]
    assert operation_names[:4] == ["create", "create", "delete", "update"]
    assert operation_names[-1] == "create"
    assert any(wrapper.get("encrypted_task_key") == "old-master-cipher" for wrapper in directus.wrappers)
    assert all(wrapper.get("encrypted_task_key") not in {"new-master-cipher", "new-team-cipher"} for wrapper in directus.wrappers)
