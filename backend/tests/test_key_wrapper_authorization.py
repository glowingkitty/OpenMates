"""Authorization guard tests for unified key wrapper helpers.

Wrapper rows are cryptographic access material, not authorization. These tests
verify helper reads and replacement paths stay owner-scoped before returning or
mutating wrapper rows.
"""

import hashlib

import pytest

from backend.core.api.app.services.directus.chat_key_wrapper_methods import ChatKeyWrapperMethods
from backend.core.api.app.services.directus.project_methods import ProjectMethods
from backend.core.api.app.services.directus.user_plan_methods import UserPlanMethods
from backend.core.api.app.services.directus.user_task_methods import UserTaskMethods


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class FakeChatMethods:
    async def check_chat_ownership(self, chat_id: str, user_id: str) -> bool:
        return chat_id == "chat-1" and user_id == "user-1"


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
    def __init__(self) -> None:
        self.chat = FakeChatMethods()
        self.cache = FakeCache()
        self.created: list[tuple[str, dict, bool | None]] = []
        self.deleted: list[tuple[str, str, bool | None]] = []
        self.requests: list[tuple[str, dict, bool | None]] = []
        self.tasks = [
            {
                "id": "task-row-1",
                "task_id": "task-1",
                "hashed_user_id": _hash("user-1"),
                "version": 7,
                "linked_project_hashes": [],
            }
        ]
        self.task_wrappers = [
            {
                "id": "old-wrapper-1",
                "hashed_task_id": _hash("task-1"),
                "hashed_user_id": _hash("user-1"),
                "key_type": "master",
                "encrypted_task_key": "old-cipher",
            }
        ]

    async def get_items(self, collection: str, params: dict, admin_required: bool | None = None, **_kwargs):
        self.requests.append((collection, params, admin_required))
        if collection == "chat_key_wrappers":
            return [
                {
                    "id": "chat-wrapper-1",
                    "hashed_chat_id": _hash("chat-1"),
                    "hashed_user_id": _hash("user-1"),
                    "key_type": "master",
                    "encrypted_chat_key": "cipher",
                }
            ]
        if collection == "user_tasks":
            rows = self.tasks
            if "filter[task_id][_eq]" in params:
                rows = [row for row in rows if row["task_id"] == params["filter[task_id][_eq]"]]
            if "filter[hashed_user_id][_eq]" in params:
                rows = [row for row in rows if row["hashed_user_id"] == params["filter[hashed_user_id][_eq]"]]
            return rows[: params.get("limit", len(rows))]
        if collection == "user_task_key_wrappers":
            rows = self.task_wrappers
            if "filter[hashed_task_id][_eq]" in params:
                rows = [row for row in rows if row["hashed_task_id"] == params["filter[hashed_task_id][_eq]"]]
            if "filter[hashed_user_id][_eq]" in params:
                rows = [row for row in rows if row["hashed_user_id"] == params["filter[hashed_user_id][_eq]"]]
            return rows
        return []

    async def create_item(self, collection: str, record: dict, admin_required: bool | None = None):
        created = {"id": f"created-{len(self.created) + 1}", **record}
        self.created.append((collection, record.copy(), admin_required))
        return True, created

    async def delete_item(self, collection: str, item_id: str, admin_required: bool | None = None):
        self.deleted.append((collection, item_id, admin_required))
        return True

    async def update_item_if_version(self, *_args, **_kwargs):
        return {"id": "task-row-1", "version": 8}


@pytest.mark.anyio
async def test_chat_wrapper_read_denies_before_querying_wrapper_rows():
    directus = FakeDirectusService()
    methods = ChatKeyWrapperMethods(directus)

    denied = await methods.list_authorized_wrappers("chat-1", "user-2")

    assert denied == []
    assert all(collection != "chat_key_wrappers" for collection, _params, _admin in directus.requests)


@pytest.mark.anyio
async def test_task_wrapper_replacement_is_owner_scoped_before_mutation():
    directus = FakeDirectusService()
    methods = UserTaskMethods(directus)

    replaced = await methods.replace_task_key_wrappers(
        "user-2",
        "task-1",
        [{"key_type": "master", "encrypted_task_key": "new-cipher"}],
        expected_version=7,
    )

    assert replaced is None
    assert directus.created == []
    assert directus.deleted == []


@pytest.mark.anyio
async def test_wrapper_list_helpers_always_include_owner_hash_filters():
    directus = FakeDirectusService()

    await UserTaskMethods(directus).list_task_key_wrappers("user-1", "task-1")
    await UserPlanMethods(directus).list_plan_key_wrappers("user-1", "plan-1")
    await ProjectMethods(directus).list_project_key_wrappers("user-1", "project-1")

    wrapper_requests = [request for request in directus.requests if request[0].endswith("key_wrappers")]
    assert wrapper_requests
    assert all(params.get("filter[hashed_user_id][_eq]") == _hash("user-1") for _collection, params, _admin in wrapper_requests)


@pytest.mark.anyio
async def test_invalid_team_wrapper_scope_fails_closed_before_persistence():
    directus = FakeDirectusService()
    methods = UserTaskMethods(directus)

    created = await methods.create_task_key_wrapper(
        "user-1",
        "task-1",
        {
            "key_type": "team",
            "hashed_team_id": _hash("team-1"),
            "hashed_project_id": _hash("project-1"),
            "team_key_epoch": 1,
            "encrypted_task_key": "cipher-team",
        },
    )

    assert created is None
    assert directus.created == []
