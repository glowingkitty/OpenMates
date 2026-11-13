# backend/tests/test_project_test_snapshot.py
#
# Contract tests for the hosted-Project test snapshot: the pipeline fetches the
# Project files from the client (snapshot job), caches them briefly and injects
# them into a files-less code-run test_run call.

from __future__ import annotations

import hashlib
import importlib.util
import sys
import time
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from backend.apps.ai.processing import project_test_snapshot as pts
from backend.apps.code.skills import run_code_skill
from backend.apps.code.skills.run_code_skill import RunCodeRequest, RunCodeSkill
from backend.core.api.app.services.project_file_operation_service import (
    PROJECT_FILE_MUTATIONS, PROJECT_FILE_OPERATIONS, ProjectFileOperationError,
    ProjectFileOperationService,
)
from backend.tests.test_project_file_operations import MemoryCache, focus

TEST_RUN = {
    "kind": "browser", "target": "e2b",
    "test_command": {"argv": ["npx", "playwright", "test"], "cwd": "web-app"},
}
FILES = [
    {"path": "web-app/index.html", "code": "<h1>Hi</h1>", "revision": "rev-1"},
    {"path": "web-app/tests/app.spec.ts", "code": "test()", "revision": "rev-2"},
]


# contract-test: direct surface=rest_api assertions=code-run.tests.project-snapshot
def test_snapshot_operation_is_read_only_and_validates_arguments() -> None:
    assert "snapshot" in PROJECT_FILE_OPERATIONS
    assert "snapshot" not in PROJECT_FILE_MUTATIONS
    for arguments in ({}, {"prefix": "web-app"}, {"prefix": "a/b"}):
        ProjectFileOperationService._validate_arguments("snapshot", arguments)
    for arguments in (
        {"prefix": ""}, {"prefix": "/abs"}, {"prefix": "../x"}, {"prefix": "a/../b"},
        {"prefix": "x" * 513}, {"prefix": 3}, {"prefix": "a", "extra": 1}, {"path": "a"},
    ):
        with pytest.raises(ProjectFileOperationError, match="invalid_(snapshot_arguments|project_path)"):
            ProjectFileOperationService._validate_arguments("snapshot", arguments)


# contract-test: direct surface=rest_api assertions=code-run.tests.project-snapshot
def test_needs_snapshot_and_inject_shapes() -> None:
    assert pts.needs_snapshot({"test_run": TEST_RUN})
    assert not pts.needs_snapshot({"test_run": TEST_RUN, "files": [{"path": "a", "code": "b"}]})
    assert not pts.needs_snapshot({"test_run": {**TEST_RUN, "target": "remote_source"}})
    assert not pts.needs_snapshot({"entry_path": "a.py"})
    assert pts.snapshot_prefix({"test_run": TEST_RUN}) == "web-app"
    assert pts.snapshot_prefix({"test_run": {"test_command": {"cwd": "."}}}) is None
    injected = pts.inject_snapshot({"test_run": TEST_RUN}, {"files": FILES, "truncated": False})
    assert injected["files"] == [{"path": f["path"], "code": f["code"]} for f in FILES]
    assert injected["test_run"]["revisions"] == [
        {"path": "web-app/index.html", "revision": "rev-1"},
        {"path": "web-app/tests/app.spec.ts", "revision": "rev-2"},
    ]
    assert injected["test_run"]["kind"] == "browser"


# contract-test: direct surface=rest_api assertions=code-run.tests.project-snapshot
@pytest.mark.asyncio
async def test_snapshot_cache_is_scoped_short_lived_and_read_once() -> None:
    cache = MemoryCache()
    await pts.store_snapshot(cache, user_id="u", chat_id="c", project_id="p", files=FILES, truncated=False)
    key = f"project_test_snapshot:{hashlib.sha256(b'u').hexdigest()}:c:p"
    assert cache.ttls[key] == 900
    assert await pts.take_snapshot(cache, user_id="u", chat_id="c", project_id="other") is None
    taken = await pts.take_snapshot(cache, user_id="u", chat_id="c", project_id="p")
    assert taken["files"] == FILES
    assert await pts.take_snapshot(cache, user_id="u", chat_id="c", project_id="p") is None


# contract-test: direct surface=rest_api assertions=code-run.tests.project-snapshot
@pytest.mark.asyncio
async def test_settled_snapshot_is_cached_and_continuation_gets_compact_result(monkeypatch) -> None:
    from backend.core.api.app.services.project_write_authorization_service import ProjectWriteAuthorizationService

    dispatched = AsyncMock()
    tasks_package = ModuleType("backend.apps.ai.tasks")
    tasks_package.__path__ = []
    continuation_module = ModuleType("backend.apps.ai.tasks.async_skill_continuation")
    continuation_module.dispatch_async_skill_continuation = dispatched
    monkeypatch.setitem(sys.modules, tasks_package.__name__, tasks_package)
    monkeypatch.setitem(sys.modules, continuation_module.__name__, continuation_module)
    handler_path = (
        Path(__file__).parents[1] / "core/api/app/routes/handlers/websocket_handlers"
        / "project_file_operation_handlers.py"
    )
    spec = importlib.util.spec_from_file_location("_snapshot_handlers_test", handler_path)
    assert spec and spec.loader
    handlers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(handlers)

    cache = MemoryCache()
    service = ProjectFileOperationService(cache)
    summary = await service.create_operation(
        user_id="user-1", chat_id="chat-1", project_focus=focus(),
        operation="snapshot", arguments={"prefix": "web-app"},
        continuation_task_id="continuation-1", now=int(time.time()),
    )
    claim = await service.claim(
        user_id="user-1", device_fingerprint_hash="device-a",
        operation_id=summary["operation_id"], chat_id="chat-1", project_id="project-1",
    )
    monkeypatch.setattr(
        ProjectWriteAuthorizationService, "get_active_focus", AsyncMock(return_value=focus()),
    )
    await handlers.handle_project_file_operation_result(
        websocket=SimpleNamespace(send_json=AsyncMock()),
        manager=SimpleNamespace(can_execute_project_file_job=lambda *_args: True),
        cache_service=cache, directus_service=SimpleNamespace(),
        user_id="user-1", device_fingerprint_hash="device-a",
        payload={
            "protocol_version": 1, "operation_id": summary["operation_id"],
            "chat_id": "chat-1", "project_id": "project-1",
            "lease_token": claim["lease_token"], "lease_generation": claim["lease_generation"],
            "status": "completed",
            "result": {"files": FILES, "truncated": False, "source_id": None},
        },
    )
    result = dispatched.await_args.kwargs["completed_results"][0]
    assert result["file_count"] == 2 and result["truncated"] is False
    assert result["operation"] == "snapshot" and result["status"] == "completed"
    assert "files" not in result and "<h1>" not in str(result)
    stored = await pts.take_snapshot(cache, user_id="user-1", chat_id="chat-1", project_id="project-1")
    assert stored["files"] == FILES


# contract-test: direct surface=rest_api assertions=code-run.tests.project-snapshot
@pytest.mark.asyncio
async def test_injected_snapshot_passes_the_files_required_check(monkeypatch) -> None:
    injected = pts.inject_snapshot({"test_run": TEST_RUN}, {"files": FILES, "truncated": False})
    request = RunCodeRequest(**injected)

    async def fake_resolve(spec: Any, **_kwargs: Any):
        return "e2b", None, None

    class FakeAuth:
        def __init__(self, *_a: Any, **_k: Any) -> None: ...
        async def get_active_focus(self, **_k: Any):
            return None

    monkeypatch.setattr(run_code_skill, "create_directus_service", lambda **_k: object())
    monkeypatch.setattr(run_code_skill, "resolve_test_run_target", fake_resolve)
    monkeypatch.setattr(
        "backend.core.api.app.services.project_write_authorization_service.ProjectWriteAuthorizationService",
        FakeAuth,
    )
    skill = RunCodeSkill(app=SimpleNamespace(), app_id="code", skill_id="run", skill_name="r", skill_description="r")
    prepared, error = await skill._prepare_test_run(
        request, chat_id="c", user_id="u", cache_service=MemoryCache(), encryption_service=object(),
    )
    assert error is None
    assert [f.path for f in prepared.files] == ["web-app/index.html", "web-app/tests/app.spec.ts"]
    empty, error = await skill._prepare_test_run(
        RunCodeRequest(test_run=TEST_RUN), chat_id="c", user_id="u",
        cache_service=MemoryCache(), encryption_service=object(),
    )
    assert error is not None and "Project snapshot" in error.error
