# backend/tests/test_tasks_api_security.py
#
# Focused owner-binding tests for public async task polling.
# A valid authenticated user or API key must not receive another user's terminal
# task result by guessing a Celery task id.

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.core.api.app.routes import tasks_api


class FakeAsyncResult:
    def __init__(self, task_id: str, app=None):
        del app
        fixtures = {
            "owned": ("SUCCESS", {"user_id": "user-1", "payload": {"ok": True}}),
            "owned-nested": ("SUCCESS", {"result": {"metadata": {"user_id": "user-1"}}, "payload": {"ok": True}}),
            "other": ("SUCCESS", {"user_id": "user-2", "payload": {"secret": True}}),
            "unverified": ("SUCCESS", {"payload": {"secret": True}}),
            "pending": ("PENDING", None),
        }
        self.status, self.result = fixtures[task_id]


async def _get_task_status(task_id: str):
    handler = getattr(tasks_api.get_task_status, "__wrapped__", tasks_api.get_task_status)
    return await handler(task_id=task_id, request=SimpleNamespace(), user_info={"user_id": "user-1"})


@pytest.mark.anyio
async def test_owned_task_result_is_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tasks_api, "AsyncResult", FakeAsyncResult)

    response = await _get_task_status("owned")

    assert response.status == "completed"
    assert response.result == {"user_id": "user-1", "payload": {"ok": True}}

    nested_response = await _get_task_status("owned-nested")
    assert nested_response.result["payload"] == {"ok": True}


@pytest.mark.anyio
async def test_other_users_task_result_is_not_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tasks_api, "AsyncResult", FakeAsyncResult)

    with pytest.raises(HTTPException) as exc:
        await _get_task_status("other")

    assert exc.value.status_code == 404
    assert exc.value.detail == "Task not found"


@pytest.mark.anyio
async def test_unverified_terminal_task_result_is_not_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tasks_api, "AsyncResult", FakeAsyncResult)

    with pytest.raises(HTTPException) as exc:
        await _get_task_status("unverified")

    assert exc.value.status_code == 403
    assert exc.value.detail == {"error": "task_owner_unverified"}


@pytest.mark.anyio
async def test_pending_task_status_does_not_return_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tasks_api, "AsyncResult", FakeAsyncResult)

    response = await _get_task_status("pending")


    assert response.status == "pending"
    assert response.result is None
