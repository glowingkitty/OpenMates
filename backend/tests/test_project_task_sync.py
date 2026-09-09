"""Scoped Task sync delivery without product/network dependencies.

Tests prove auth, complete batching, cursor advancement and revocation cleanup.
The real PostgreSQL journal/commit boundary is tested in isolated GitHub CI.
No model, shared-dev browser or background daemon is launched here.
See docs/plans/codex-tasks-orchestration/plan.yml.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.services.project_task_sync_service import (
    ProjectTaskSyncService,
    scope_key,
)


class Socket:
    def __init__(self):
        self.frames = []

    async def send_json(self, value):
        self.frames.append(value)


def service():
    directus = SimpleNamespace(
        project=SimpleNamespace(
            get_project=AsyncMock(return_value={"id": "project"}),
            get_source=AsyncMock(return_value={"status": "connected"}),
        ),
        team=SimpleNamespace(require_team_role=AsyncMock()),
    )
    instance = ProjectTaskSyncService(directus, SimpleNamespace())
    instance._read = AsyncMock(
        return_value={
            "reset": True,
            "cursor": "epoch:1",
            "tasks": [{"task_id": str(i)} for i in range(45)],
            "removed_task_ids": [],
        }
    )
    return instance


@pytest.mark.asyncio
async def test_authorized_subscription_sends_all_records_and_commits_cursor():
    instance = service()
    websocket = Socket()
    await instance.subscribe(
        websocket,
        "user",
        {"bindings": [{"project_id": "project", "source_id": "source"}]},
    )
    subscription = instance.subscriptions[websocket]["project"]
    await subscription.delivery
    assert sum(len(frame["payload"]["tasks"]) for frame in websocket.frames) == 45
    assert [frame["payload"]["part"] for frame in websocket.frames] == [0, 1, 2]
    assert [frame["payload"]["final"] for frame in websocket.frames] == [
        False,
        False,
        True,
    ]
    assert subscription.cursor == "epoch:1"
    instance.reconcile(websocket)
    assert instance._read.await_count == 1
    instance.disconnect(websocket)
    assert websocket not in instance.subscriptions


@pytest.mark.asyncio
async def test_revoked_source_never_returns_records():
    instance = service()
    instance.directus.project.get_source.return_value = {"status": "revoked"}
    websocket = Socket()
    with pytest.raises(PermissionError):
        await instance.subscribe(
            websocket,
            "user",
            {"bindings": [{"project_id": "project", "source_id": "source"}]},
        )
    instance._read.assert_not_awaited()
    assert websocket.frames == []


@pytest.mark.asyncio
async def test_access_is_checked_again_before_push():
    instance = service()
    websocket = Socket()
    await instance.subscribe(
        websocket,
        "user",
        {"bindings": [{"project_id": "project", "source_id": "source"}]},
    )
    subscription = instance.subscriptions[websocket]["project"]
    instance.directus.project.get_source.return_value = {"status": "revoked"}
    await subscription.delivery
    assert websocket.frames[-1]["payload"]["code"] == "access_revoked"
    assert "project" not in instance.subscriptions[websocket]
    instance._read.assert_not_awaited()


def test_personal_and_team_scope_do_not_collide():
    assert scope_key("same", None) != scope_key("user", "same")
    assert scope_key("user-a", "team") == scope_key("user-b", "team")


@pytest.mark.asyncio
async def test_committed_hint_only_reads_the_affected_workspace():
    instance = service()
    first, other = Socket(), Socket()
    bindings = {"bindings": [{"project_id": "project", "source_id": "source"}]}
    await instance.subscribe(first, "user-one", bindings)
    await instance.subscribe(other, "user-two", bindings)
    await asyncio.gather(
        instance.subscriptions[first]["project"].delivery,
        instance.subscriptions[other]["project"].delivery,
    )
    instance._read.reset_mock()
    instance.notify_scope(scope_key("user-one", None))
    await instance.subscriptions[first]["project"].delivery
    assert instance._read.await_count == 1
    assert instance._read.await_args.args[0].user_id == "user-one"
    instance.disconnect(first)
    assert scope_key("user-one", None) not in instance.scope_sockets
    instance.disconnect(other)
