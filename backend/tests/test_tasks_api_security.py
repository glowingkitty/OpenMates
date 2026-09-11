# backend/tests/test_tasks_api_security.py
#
# Focused owner-binding tests for public async task polling.
# A valid authenticated user or API key must not receive another user's terminal
# task result by guessing a Celery task id.

# ruff: noqa: E402

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.tests.runtime_import_stubs import install_code_route_import_stubs

install_code_route_import_stubs()

from backend.core.api.app.routes import tasks_api


@pytest.fixture(autouse=True)
def no_owner_store(monkeypatch):
    monkeypatch.setattr(tasks_api, "read_task_owner", lambda *args: None)
    monkeypatch.setattr(tasks_api, "celery_app", SimpleNamespace(conf=SimpleNamespace(broker_url="redis://localhost/0")))


class FakeAsyncResult:
    def __init__(self, task_id: str, app=None):
        del app
        fixtures = {
            "owned": ("SUCCESS", {"user_id": "user-1", "payload": {"ok": True}}),
            "owned-nested": ("SUCCESS", {"result": {"metadata": {"user_id": "user-1"}}, "payload": {"ok": True}}),
            "other": ("SUCCESS", {"user_id": "user-2", "payload": {"secret": True}}),
            "unverified": ("SUCCESS", {"payload": {"secret": True}}),
            "pending": ("PENDING", None),
            "owned-music": ("SUCCESS", {"embed_id": "music-1", "files": {"original": {"format": "wav"}}}),
            "failed-owned": ("FAILURE", RuntimeError("private provider diagnostic")),
        }
        self.status, self.result = fixtures[task_id]


async def _get_task_status(task_id: str):
    handler = getattr(tasks_api.get_task_status, "__wrapped__", tasks_api.get_task_status)
    return await handler(task_id=task_id, request=SimpleNamespace(), user_info={"user_id": "user-1"})


# contract-test: infrastructure
@pytest.mark.anyio
async def test_owned_task_result_is_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tasks_api, "AsyncResult", FakeAsyncResult)

    response = await _get_task_status("owned")

    assert response.status == "completed"
    assert response.result == {"user_id": "user-1", "payload": {"ok": True}}

    nested_response = await _get_task_status("owned-nested")
    assert nested_response.result["payload"] == {"ok": True}


# contract-test: infrastructure
@pytest.mark.anyio
async def test_other_users_task_result_is_not_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tasks_api, "AsyncResult", FakeAsyncResult)

    with pytest.raises(HTTPException) as exc:
        await _get_task_status("other")

    assert exc.value.status_code == 404
    assert exc.value.detail == "Task not found"


# contract-test: infrastructure
@pytest.mark.anyio
async def test_unverified_terminal_task_result_is_not_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tasks_api, "AsyncResult", FakeAsyncResult)

    with pytest.raises(HTTPException) as exc:
        await _get_task_status("unverified")

    assert exc.value.status_code == 403
    assert exc.value.detail == {"error": "task_owner_unverified"}


# contract-test: infrastructure
@pytest.mark.anyio
async def test_pending_task_status_does_not_return_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tasks_api, "AsyncResult", FakeAsyncResult)

    response = await _get_task_status("pending")


    assert response.status == "pending"
    assert response.result is None


# contract-test: supporting surface=rest_api assertions=app-skills.execution.async-owner-bound
@pytest.mark.anyio
async def test_dispatch_owner_authorizes_results_without_worker_owner_fields(monkeypatch):
    monkeypatch.setattr(tasks_api, "AsyncResult", FakeAsyncResult)
    monkeypatch.setattr(tasks_api, "read_task_owner", lambda *args: tasks_api._hash_id("user-1"), raising=False)
    response = await _get_task_status("owned-music")
    assert response.status == "completed"
    assert response.result["embed_id"] == "music-1"
    response = await _get_task_status("failed-owned")
    assert response.status == "failed"
    assert "private provider diagnostic" not in response.error


# contract-test: supporting surface=rest_api assertions=app-skills.execution.async-owner-bound
@pytest.mark.anyio
async def test_dispatch_owner_wins_over_result_metadata(monkeypatch):
    monkeypatch.setattr(tasks_api, "AsyncResult", FakeAsyncResult)
    monkeypatch.setattr(tasks_api, "read_task_owner", lambda *args: tasks_api._hash_id("user-2"), raising=False)
    with pytest.raises(HTTPException) as exc:
        await _get_task_status("owned")
    assert exc.value.status_code == 404


# contract-test: supporting surface=rest_api assertions=app-skills.execution.async-owner-bound
@pytest.mark.anyio
async def test_owner_is_recorded_before_dispatch(monkeypatch):
    from backend.apps.ai.processing import celery_helpers
    calls = []
    monkeypatch.setattr(celery_helpers, "record_task_owner", lambda *args: calls.append(("owner", args)), raising=False)
    class Producer:
        conf = SimpleNamespace(broker_url="redis://localhost/0")
        def send_task(self, **kwargs):
            calls.append(("dispatch", kwargs))
            return SimpleNamespace(id=kwargs["task_id"])
    task_id = await celery_helpers.execute_skill_via_celery("music", "generate", {"user_id": "user-1"}, Producer())
    assert calls[0][0] == "owner"
    assert calls[0][1][:2] == (task_id, "user-1")
    assert calls[1][1]["task_id"] == task_id
