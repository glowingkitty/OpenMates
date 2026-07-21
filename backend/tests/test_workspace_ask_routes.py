# backend/tests/test_workspace_ask_routes.py
#
# Route-level contracts for workspace ask/history handlers. The tests call the
# handlers directly with fake auth and service adapters so they stay fast while
# still protecting response shape, history writes, and restore routing.

from __future__ import annotations

import sys
import types
from types import SimpleNamespace

import pytest
from starlette.responses import Response

redis_stub = types.ModuleType("redis")
redis_asyncio_stub = types.ModuleType("redis.asyncio")
redis_exceptions_stub = types.SimpleNamespace(RedisError=Exception, ConnectionError=Exception, TimeoutError=TimeoutError)
redis_asyncio_stub.Redis = object
redis_stub.asyncio = redis_asyncio_stub
redis_stub.exceptions = redis_exceptions_stub
sys.modules.setdefault("redis", redis_stub)
sys.modules.setdefault("redis.asyncio", redis_asyncio_stub)


class _StubLimiter:
    def limit(self, _rule: str):
        def decorator(func):
            return func

        return decorator


auth_deps_stub = types.ModuleType("backend.core.api.app.routes.auth_routes.auth_dependencies")
auth_deps_stub.get_current_user = lambda: None
auth_deps_stub.get_current_user_or_api_key = lambda: None
directus_directus_stub = types.ModuleType("backend.core.api.app.services.directus.directus")
directus_directus_stub.DirectusService = object
cache_stub = types.ModuleType("backend.core.api.app.services.cache")
cache_stub.CacheService = object
limiter_stub = types.ModuleType("backend.core.api.app.services.limiter")
limiter_stub.limiter = _StubLimiter()
sys.modules.setdefault("backend.core.api.app.routes.auth_routes.auth_dependencies", auth_deps_stub)
sys.modules.setdefault("backend.core.api.app.services.directus.directus", directus_directus_stub)
sys.modules.setdefault("backend.core.api.app.services.cache", cache_stub)
sys.modules.setdefault("backend.core.api.app.services.limiter", limiter_stub)

from backend.core.api.app.routes import projects, user_plans, user_tasks, workflows  # noqa: E402


class FakeHistoryService:
    def __init__(self) -> None:
        self.recorded: list[dict] = []
        self.restores: list[dict] = []

    async def record_change_set(self, **kwargs):
        self.recorded.append(kwargs)
        entries = [
            {
                "entry_id": f"che-{index + 1}",
                "object_type": entry["object_type"],
                "object_id": entry["object_id"],
                "operation": entry["operation"],
            }
            for index, entry in enumerate(kwargs["entries"])
        ]
        return {"change_set": {"change_set_id": "chg-1"}, "entries": entries}

    async def restore_object_to_entry(self, **kwargs):
        self.restores.append(kwargs)
        return {
            "object": {"id": kwargs["object_id"], "restored": True},
            "history": {"change_set": {"change_set_id": "chg-restore"}},
            "change_set": {"change_set_id": "chg-restore"},
            "entries": [{"entry_id": kwargs["entry_id"], "object_type": kwargs["object_type"], "object_id": kwargs["object_id"], "operation": "restore"}],
            "undo_all_command": "openmates history undo chg-restore",
            "undo_entry_commands": [f"openmates {kwargs['object_type']}s restore {kwargs['object_id']} --entry {kwargs['entry_id']} --state before"],
        }


class FakeTaskService:
    async def create_task(self, user_id: str, payload: dict):
        assert user_id == "user-1"
        return {**payload, "id": "row-task"}


class FakeTaskReorderMethods:
    async def get_task(self, task_id: str, user_id: str):
        assert user_id == "user-1"
        if task_id == "task-1":
            return {"task_id": "task-1", "encrypted_title": "cipher-moved", "position": 10, "version": 1}
        if task_id == "task-anchor":
            return {"task_id": "task-anchor", "encrypted_title": "cipher-anchor", "position": 5, "version": 1}
        return None


class FakeTaskReorderService:
    task_methods = FakeTaskReorderMethods()

    async def update_task(self, task_id: str, user_id: str, patch: dict):
        assert task_id == "task-1"
        assert user_id == "user-1"
        return {"task_id": "task-1", "encrypted_title": "cipher-moved-updated", "position": patch["position"], "version": 2}


class FakePlanService:
    async def create_plan(self, user_id: str, payload: dict):
        assert user_id == "user-1"
        return {**payload, "id": "row-plan"}


class FakeProjectMethods:
    async def create_project(self, user_id: str, payload: dict):
        assert user_id == "user-1"
        return {**payload, "id": "row-project"}


class FakeWorkflow:
    id = "workflow-1"
    current_version_id = "version-1"

    def model_dump(self, **_kwargs):
        return {"id": self.id, "current_version_id": self.current_version_id, "title": "Inferred workflow"}


class FakeWorkflowService:
    def __init__(self) -> None:
        self.created: list[dict] = []

    def create_workflow(self, user_id: str, title: str, graph: dict, enabled: bool, *_args):
        self.created.append({"user_id": user_id, "title": title, "graph": graph, "enabled": enabled})
        return FakeWorkflow()


def _user():
    return SimpleNamespace(id="user-1", vault_key_id="vault-1")


def _request_with_secrets():
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(secrets_manager=object())))


@pytest.mark.asyncio
async def test_task_ask_auto_apply_requires_encrypted_create_and_records_history(monkeypatch) -> None:
    async def fake_current_user(_request, _response):
        return _user()

    monkeypatch.setattr(user_tasks, "_current_user", fake_current_user)
    history = FakeHistoryService()
    body = user_tasks.UserTaskAskRequest(
        instruction="Prepare launch copy",
        encrypted_create={
            "task_id": "task-1",
            "encrypted_task_key": "key",
            "encrypted_title": "cipher-title",
            "status": "todo",
            "assignee_type": "user",
            "version": 1,
            "created_at": 1,
            "updated_at": 1,
        },
    )

    result = await user_tasks.ask_user_tasks(SimpleNamespace(), Response(), body, service=FakeTaskService(), history_service=history)

    assert result["applied"] is True
    assert result["change_set_id"] == "chg-1"
    assert result["undo_entry_commands"] == ["openmates tasks restore task-1 --entry che-1 --state before"]
    assert history.recorded[0]["source"] == "ai_ask"
    assert "Prepare launch copy" not in str(history.recorded)


@pytest.mark.asyncio
async def test_task_ask_bulk_create_records_one_change_set(monkeypatch) -> None:
    async def fake_current_user(_request, _response):
        return _user()

    monkeypatch.setattr(user_tasks, "_current_user", fake_current_user)
    history = FakeHistoryService()
    encrypted_create = {
        "encrypted_task_key": "key",
        "encrypted_title": "cipher-title",
        "status": "todo",
        "assignee_type": "user",
        "version": 1,
        "created_at": 1,
        "updated_at": 1,
    }
    body = user_tasks.UserTaskAskRequest(
        instruction="Prepare launch: write copy, test signup",
        encrypted_creates=[
            {**encrypted_create, "task_id": "task-1"},
            {**encrypted_create, "task_id": "task-2"},
        ],
    )

    result = await user_tasks.ask_user_tasks(SimpleNamespace(), Response(), body, service=FakeTaskService(), history_service=history)

    assert result["applied"] is True
    assert result["summary"] == "Created 2 task(s)."
    assert [task["task_id"] for task in result["tasks"]] == ["task-1", "task-2"]
    assert len(history.recorded) == 1
    assert [entry["object_id"] for entry in history.recorded[0]["entries"]] == ["task-1", "task-2"]


@pytest.mark.asyncio
async def test_task_ask_plan_route_uses_inference_planner(monkeypatch) -> None:
    async def fake_current_user(_request, _response):
        return _user()

    async def fake_plan(instruction, secrets_manager):
        assert instruction == "split release work into tasks"
        assert secrets_manager is not None
        return [SimpleNamespace(model_dump=lambda: {"title": "Verify release", "status": "todo", "assignee_type": "user"})]

    monkeypatch.setattr(user_tasks, "_current_user", fake_current_user)
    monkeypatch.setattr(user_tasks, "plan_task_ask", fake_plan)

    result = await user_tasks.plan_user_task_ask(
        _request_with_secrets(),
        Response(),
        user_tasks.UserTaskAskPlanRequest(instruction="split release work into tasks"),
    )

    assert result == {"proposed_tasks": [{"title": "Verify release", "status": "todo", "assignee_type": "user"}], "inference_used": True}


@pytest.mark.asyncio
async def test_plan_ask_confirm_first_does_not_record_history(monkeypatch) -> None:
    async def fake_current_user(_request, _response):
        return _user()

    monkeypatch.setattr(user_plans, "_current_user", fake_current_user)
    history = FakeHistoryService()
    body = user_plans.UserPlanAskRequest(instruction="Prepare launch plan", apply_mode="confirm_first")

    result = await user_plans.ask_user_plans(SimpleNamespace(), Response(), body, service=FakePlanService(), history_service=history)

    assert result["applied"] is False
    assert result["changed_entries"] == []
    assert history.recorded == []


@pytest.mark.asyncio
async def test_plan_ask_plan_route_uses_inference_planner(monkeypatch) -> None:
    async def fake_current_user(_request, _response):
        return _user()

    async def fake_plan(instruction, secrets_manager):
        assert instruction == "make a release validation plan"
        assert secrets_manager is not None
        return SimpleNamespace(model_dump=lambda: {"title": "Release validation", "summary": "Check release", "goal": "Ship safely"})

    monkeypatch.setattr(user_plans, "_current_user", fake_current_user)
    monkeypatch.setattr(user_plans, "plan_plan_ask", fake_plan)

    result = await user_plans.plan_user_plan_ask(
        _request_with_secrets(),
        Response(),
        user_plans.UserPlanAskPlanRequest(instruction="make a release validation plan"),
    )

    assert result == {"proposed_plan": {"title": "Release validation", "summary": "Check release", "goal": "Ship safely"}, "inference_used": True}


@pytest.mark.asyncio
async def test_project_ask_auto_apply_records_history_without_plaintext() -> None:
    history = FakeHistoryService()
    body = projects.ProjectAskRequest(
        instruction="Launch workspace",
        encrypted_create={
            "project_id": "project-1",
            "encrypted_project_key": "key",
            "encrypted_name": "cipher-name",
            "created_at": 1,
            "updated_at": 1,
            "last_opened_at": 1,
        },
    )

    result = await projects.ask_projects(
        SimpleNamespace(),
        body,
        current_user=_user(),
        directus_service=SimpleNamespace(project=FakeProjectMethods()),
        history_service=history,
    )

    assert result["applied"] is True
    assert result["undo_entry_commands"] == ["openmates projects restore project-1 --entry che-1 --state before"]
    assert history.recorded[0]["source"] == "ai_ask"
    assert "Launch workspace" not in str(history.recorded)


@pytest.mark.asyncio
async def test_project_ask_plan_route_uses_inference_planner(monkeypatch) -> None:
    async def fake_plan(instruction, secrets_manager):
        assert instruction == "make a release project"
        assert secrets_manager is not None
        return SimpleNamespace(model_dump=lambda: {"name": "Release", "description": "Ship", "icon": "rocket", "color": "blue"})

    monkeypatch.setattr(projects, "plan_project_ask", fake_plan)

    result = await projects.plan_project_ask_route(
        _request_with_secrets(),
        projects.ProjectAskPlanRequest(instruction="make a release project"),
        current_user=_user(),
    )

    assert result == {"proposed_project": {"name": "Release", "description": "Ship", "icon": "rocket", "color": "blue"}, "inference_used": True}


@pytest.mark.asyncio
async def test_namespace_restore_routes_delegate_object_type(monkeypatch) -> None:
    async def fake_current_user(_request, _response):
        return _user()

    monkeypatch.setattr(user_tasks, "_current_user", fake_current_user)
    history = FakeHistoryService()
    body = user_tasks.UserTaskRestoreRequest(entry_id="che-1", state="before")

    result = await user_tasks.restore_user_task_from_history(SimpleNamespace(), Response(), "task-1", body, history_service=history)

    assert result["task"] == {"id": "task-1", "restored": True}
    assert history.restores == [
        {"user_id": "user-1", "object_type": "task", "object_id": "task-1", "entry_id": "che-1", "state": "before", "source": "cli"}
    ]


@pytest.mark.asyncio
async def test_task_reorder_history_uses_moved_task_before_snapshot(monkeypatch) -> None:
    async def fake_current_user(_request, _response):
        return _user()

    monkeypatch.setattr(user_tasks, "_current_user", fake_current_user)
    history = FakeHistoryService()
    body = user_tasks.UserTaskReorderRequest(moves=[{"task_id": "task-1", "before_task_id": "task-anchor", "version": 1}])

    result = await user_tasks.reorder_user_tasks(SimpleNamespace(), Response(), body, service=FakeTaskReorderService(), history_service=history)

    assert result["tasks"][0]["position"] == 4
    recorded_entry = history.recorded[0]["entries"][0]
    assert recorded_entry["before"]["task_id"] == "task-1"
    assert recorded_entry["before"]["encrypted_title"] == "cipher-moved"


@pytest.mark.asyncio
async def test_workflow_ask_confirm_first_does_not_record_history() -> None:
    history = FakeHistoryService()
    body = workflows.WorkflowAskRequest(instruction="Alert me if it rains", apply_mode="confirm_first")

    result = await workflows.ask_workflows(SimpleNamespace(), body, current_user=_user(), service=object(), history_service=history)

    assert result["applied"] is False
    assert result["changed_entries"] == []
    assert history.recorded == []


@pytest.mark.asyncio
async def test_workflow_ask_without_create_uses_inference_planner(monkeypatch) -> None:
    async def fake_plan(instruction, secrets_manager):
        assert instruction == "make a release workflow"
        assert secrets_manager is not None
        return {
            "title": "Inferred workflow",
            "description": "From LLM",
            "enabled": True,
            "graph": {
                "version": 1,
                "trigger_node_id": "manual-trigger",
                "nodes": [
                    {"id": "manual-trigger", "type": "manual_trigger", "title": "Manual trigger"},
                    {"id": "end", "type": "end", "title": "End"},
                ],
                "edges": [{"from": "manual-trigger", "to": "end"}],
            },
        }

    monkeypatch.setattr(workflows, "plan_workflow_ask", fake_plan)
    history = FakeHistoryService()
    service = FakeWorkflowService()

    result = await workflows.ask_workflows(
        _request_with_secrets(),
        workflows.WorkflowAskRequest(instruction="make a release workflow"),
        current_user=_user(),
        service=service,
        history_service=history,
    )

    assert result["applied"] is True
    assert service.created[0]["title"] == "Inferred workflow"
    assert service.created[0]["enabled"] is True
    assert history.recorded[0]["entries"][0]["workflow_version_after_id"] == "version-1"
