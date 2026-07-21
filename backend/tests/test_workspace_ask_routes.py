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

from backend.core.api.app.routes import projects, user_plans, user_tasks, workflows, workspace_history  # noqa: E402


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


class FakeTaskMethods:
    async def get_task(self, task_id: str, user_id: str):
        assert user_id == "user-1"
        return {"task_id": task_id, "encrypted_title": "cipher-before", "status": "todo", "version": 1}

    async def delete_task(self, task_id: str, user_id: str, version: int):
        assert user_id == "user-1"
        assert version == 1
        return bool(task_id)


class FakeTaskService:
    task_methods = FakeTaskMethods()

    async def create_task(self, user_id: str, payload: dict):
        assert user_id == "user-1"
        return {**payload, "id": "row-task"}

    async def update_task(self, task_id: str, user_id: str, patch: dict):
        assert user_id == "user-1"
        return {"task_id": task_id, "encrypted_title": "cipher-after", **patch, "version": 2}


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


class FakePlanMethods:
    async def get_plan(self, plan_id: str, user_id: str):
        assert user_id == "user-1"
        return {"plan_id": plan_id, "encrypted_title": "cipher-before", "status": "draft", "version": 1}


class FakePlanService:
    plan_methods = FakePlanMethods()

    async def create_plan(self, user_id: str, payload: dict):
        assert user_id == "user-1"
        return {**payload, "id": "row-plan"}

    async def update_plan(self, plan_id: str, user_id: str, patch: dict):
        assert user_id == "user-1"
        return {"plan_id": plan_id, "encrypted_title": "cipher-after", **patch, "version": 2}


class FakeProjectMethods:
    async def get_project(self, project_id: str, user_id: str):
        assert user_id == "user-1"
        return {"project_id": project_id, "encrypted_name": "cipher-before", "archived": False, "version": 1}

    async def create_project(self, user_id: str, payload: dict):
        assert user_id == "user-1"
        return {**payload, "id": "row-project"}

    async def update_project(self, project_id: str, user_id: str, patch: dict):
        assert user_id == "user-1"
        return {"project_id": project_id, "encrypted_name": "cipher-after", **patch, "version": 2}

    async def delete_project(self, project_id: str, user_id: str):
        assert user_id == "user-1"
        return bool(project_id)


class FakeWorkflow:
    def __init__(self, workflow_id: str = "workflow-1", version_id: str = "version-1", enabled: bool = True) -> None:
        self.id = workflow_id
        self.current_version_id = version_id
        self.enabled = enabled
        self.status = "active" if enabled else "disabled"

    def model_dump(self, **_kwargs):
        return {"id": self.id, "current_version_id": self.current_version_id, "title": "Inferred workflow", "enabled": self.enabled, "status": self.status}


class FakeWorkflowService:
    def __init__(self) -> None:
        self.created: list[dict] = []

    def create_workflow(self, user_id: str, title: str, graph: dict, enabled: bool, *_args):
        self.created.append({"user_id": user_id, "title": title, "graph": graph, "enabled": enabled})
        return FakeWorkflow(enabled=enabled)

    def get_workflow(self, workflow_id: str, user_id: str, _vault_key_id: str):
        assert user_id == "user-1"
        return FakeWorkflow(workflow_id=workflow_id, version_id="version-before", enabled=True)

    def update_workflow(self, workflow_id: str, user_id: str, **kwargs):
        assert user_id == "user-1"
        return FakeWorkflow(workflow_id=workflow_id, version_id="version-after", enabled=bool(kwargs.get("enabled", False)))

    def delete_workflow(self, workflow_id: str, user_id: str):
        assert workflow_id
        assert user_id == "user-1"


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

    assert result["outcome"] == "applied"
    assert result["applied"] is True
    assert result["fallback_to_chat"] is False
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
async def test_task_ask_without_exact_payload_falls_back_without_history(monkeypatch) -> None:
    async def fake_current_user(_request, _response):
        return _user()

    monkeypatch.setattr(user_tasks, "_current_user", fake_current_user)
    history = FakeHistoryService()
    body = user_tasks.UserTaskAskRequest(instruction="mark my 3d printing tasks done")

    result = await user_tasks.ask_user_tasks(SimpleNamespace(), Response(), body, service=FakeTaskService(), history_service=history)

    assert result["outcome"] == "fallback_to_chat"
    assert result["fallback_to_chat"] is True
    assert result["change_set_id"] is None
    assert history.recorded == []


@pytest.mark.asyncio
async def test_task_ask_exact_status_update_records_history(monkeypatch) -> None:
    async def fake_current_user(_request, _response):
        return _user()

    monkeypatch.setattr(user_tasks, "_current_user", fake_current_user)
    history = FakeHistoryService()
    body = user_tasks.UserTaskAskRequest(
        instruction="mark @task:task-1 done",
        encrypted_update={"task_id": "task-1", "patch": {"status": "done", "version": 1, "updated_at": 2}},
    )

    result = await user_tasks.ask_user_tasks(SimpleNamespace(), Response(), body, service=FakeTaskService(), history_service=history)

    assert result["outcome"] == "applied"
    assert result["tasks"][0]["status"] == "done"
    assert history.recorded[0]["action_type"] == "ask_update"
    assert history.recorded[0]["entries"][0]["operation"] == "status"


@pytest.mark.asyncio
async def test_task_ask_plan_route_uses_inference_planner(monkeypatch) -> None:
    async def fake_current_user(_request, _response):
        return _user()

    async def fake_pipeline(instruction, secrets_manager):
        assert instruction == "split release work into tasks"
        assert secrets_manager is not None
        return SimpleNamespace(
            proposal=[SimpleNamespace(model_dump=lambda: {"title": "Verify release", "status": "todo", "assignee_type": "user"})],
            processing={},
        )

    monkeypatch.setattr(user_tasks, "_current_user", fake_current_user)
    monkeypatch.setattr(user_tasks, "run_task_ask_pipeline", fake_pipeline)

    result = await user_tasks.plan_user_task_ask(
        _request_with_secrets(),
        Response(),
        user_tasks.UserTaskAskPlanRequest(instruction="split release work into tasks"),
    )

    assert result == {"proposed_tasks": [{"title": "Verify release", "status": "todo", "assignee_type": "user"}], "inference_used": True, "processing": {}}


@pytest.mark.asyncio
async def test_task_ask_plan_route_exposes_pipeline_processing(monkeypatch) -> None:
    async def fake_current_user(_request, _response):
        return _user()

    async def fake_pipeline(instruction, secrets_manager):
        assert instruction == "split release work into tasks"
        assert secrets_manager is not None
        return SimpleNamespace(
            proposal=[SimpleNamespace(model_dump=lambda: {"title": "Verify release", "status": "todo", "assignee_type": "user"})],
            processing={"intent_frame": {"namespace": "tasks"}, "model_selection": {"primary_model_id": "google/gemini-3-flash-preview"}},
        )

    monkeypatch.setattr(user_tasks, "_current_user", fake_current_user)
    monkeypatch.setattr(user_tasks, "run_task_ask_pipeline", fake_pipeline)

    result = await user_tasks.plan_user_task_ask(
        _request_with_secrets(),
        Response(),
        user_tasks.UserTaskAskPlanRequest(instruction="split release work into tasks"),
    )

    assert result["proposed_tasks"] == [{"title": "Verify release", "status": "todo", "assignee_type": "user"}]
    assert result["processing"]["model_selection"]["primary_model_id"] == "google/gemini-3-flash-preview"


@pytest.mark.asyncio
async def test_plan_ask_without_exact_payload_falls_back_without_history(monkeypatch) -> None:
    async def fake_current_user(_request, _response):
        return _user()

    monkeypatch.setattr(user_plans, "_current_user", fake_current_user)
    history = FakeHistoryService()
    body = user_plans.UserPlanAskRequest(instruction="archive the launch plan")

    result = await user_plans.ask_user_plans(SimpleNamespace(), Response(), body, service=FakePlanService(), history_service=history)

    assert result["outcome"] == "fallback_to_chat"
    assert result["applied"] is False
    assert result["changed_entries"] == []
    assert history.recorded == []


@pytest.mark.asyncio
async def test_plan_ask_exact_status_update_records_history(monkeypatch) -> None:
    async def fake_current_user(_request, _response):
        return _user()

    monkeypatch.setattr(user_plans, "_current_user", fake_current_user)
    history = FakeHistoryService()
    body = user_plans.UserPlanAskRequest(
        instruction="archive @plan:plan-1",
        encrypted_update={"plan_id": "plan-1", "patch": {"status": "archived", "version": 1, "updated_at": 2}},
    )

    result = await user_plans.ask_user_plans(SimpleNamespace(), Response(), body, service=FakePlanService(), history_service=history)

    assert result["outcome"] == "applied"
    assert result["plans"][0]["status"] == "archived"
    assert history.recorded[0]["entries"][0]["operation"] == "status"


@pytest.mark.asyncio
async def test_plan_ask_plan_route_uses_inference_planner(monkeypatch) -> None:
    async def fake_current_user(_request, _response):
        return _user()

    async def fake_pipeline(instruction, secrets_manager):
        assert instruction == "make a release validation plan"
        assert secrets_manager is not None
        return SimpleNamespace(
            proposal=SimpleNamespace(model_dump=lambda: {"title": "Release validation", "summary": "Check release", "goal": "Ship safely"}),
            processing={},
        )

    monkeypatch.setattr(user_plans, "_current_user", fake_current_user)
    monkeypatch.setattr(user_plans, "run_plan_ask_pipeline", fake_pipeline)

    result = await user_plans.plan_user_plan_ask(
        _request_with_secrets(),
        Response(),
        user_plans.UserPlanAskPlanRequest(instruction="make a release validation plan"),
    )

    assert result == {"proposed_plan": {"title": "Release validation", "summary": "Check release", "goal": "Ship safely"}, "inference_used": True, "processing": {}}


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

    assert result["outcome"] == "applied"
    assert result["applied"] is True
    assert result["undo_entry_commands"] == ["openmates projects restore project-1 --entry che-1 --state before"]
    assert history.recorded[0]["source"] == "ai_ask"
    assert "Launch workspace" not in str(history.recorded)


@pytest.mark.asyncio
async def test_project_ask_exact_archive_records_history() -> None:
    history = FakeHistoryService()
    body = projects.ProjectAskRequest(
        instruction="archive @project:project-1",
        encrypted_update={"project_id": "project-1", "patch": {"archived": True, "version": 1, "updated_at": 2}},
    )

    result = await projects.ask_projects(
        SimpleNamespace(),
        body,
        current_user=_user(),
        directus_service=SimpleNamespace(project=FakeProjectMethods()),
        history_service=history,
    )

    assert result["outcome"] == "applied"
    assert result["projects"][0]["archived"] is True
    assert history.recorded[0]["entries"][0]["operation"] == "archive"


@pytest.mark.asyncio
async def test_project_ask_plan_route_uses_inference_planner(monkeypatch) -> None:
    async def fake_pipeline(instruction, secrets_manager):
        assert instruction == "make a release project"
        assert secrets_manager is not None
        return SimpleNamespace(
            proposal=SimpleNamespace(model_dump=lambda: {"name": "Release", "description": "Ship", "icon": "rocket", "color": "blue"}),
            processing={},
        )

    monkeypatch.setattr(projects, "run_project_ask_pipeline", fake_pipeline)

    result = await projects.plan_project_ask_route(
        _request_with_secrets(),
        projects.ProjectAskPlanRequest(instruction="make a release project"),
        current_user=_user(),
    )

    assert result == {"proposed_project": {"name": "Release", "description": "Ship", "icon": "rocket", "color": "blue"}, "inference_used": True, "processing": {}}


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
async def test_workflow_ask_selected_edit_without_exact_payload_falls_back() -> None:
    history = FakeHistoryService()
    body = workflows.WorkflowAskRequest(instruction="add a Discord notification", selected_object_id="workflow-1")

    result = await workflows.ask_workflows(SimpleNamespace(), body, current_user=_user(), service=FakeWorkflowService(), history_service=history)

    assert result["outcome"] == "fallback_to_chat"
    assert result["applied"] is False
    assert result["changed_entries"] == []
    assert history.recorded == []


@pytest.mark.asyncio
async def test_workflow_ask_broad_edit_without_exact_payload_falls_back(monkeypatch) -> None:
    async def fail_pipeline(_instruction, _secrets_manager):
        raise AssertionError("broad workflow edits must fall back before inference")

    monkeypatch.setattr(workflows, "run_workflow_ask_pipeline", fail_pipeline)
    history = FakeHistoryService()
    service = FakeWorkflowService()
    body = workflows.WorkflowAskRequest(instruction="add a Discord notification to all my workflows once they are done")

    result = await workflows.ask_workflows(_request_with_secrets(), body, current_user=_user(), service=service, history_service=history)

    assert result["outcome"] == "fallback_to_chat"
    assert result["applied"] is False
    assert result["changed_entries"] == []
    assert service.created == []
    assert history.recorded == []


@pytest.mark.asyncio
async def test_workflow_ask_exact_disable_records_history() -> None:
    history = FakeHistoryService()
    service = FakeWorkflowService()
    body = workflows.WorkflowAskRequest(instruction="turn off @workflow:workflow-1", exact_action={"workflow_id": "workflow-1", "action": "disable"})

    result = await workflows.ask_workflows(SimpleNamespace(), body, current_user=_user(), service=service, history_service=history)

    assert result["outcome"] == "applied"
    assert result["workflow"]["enabled"] is False
    assert history.recorded[0]["action_type"] == "ask_disable"
    entry = history.recorded[0]["entries"][0]
    assert entry["operation"] == "status"
    assert entry["before"]["enabled"] is True
    assert entry["after"]["enabled"] is False


@pytest.mark.asyncio
async def test_workspace_history_undo_workflow_status_uses_snapshot_not_version_restore(monkeypatch) -> None:
    async def fake_current_user(_request, _response):
        return _user()

    class FakeWorkflowUndoHistory:
        def snapshot_for_entry_state(self, entry: dict, state: str):
            assert entry["operation"] == "status"
            assert state == "before"
            return {"workflow_version_id": "version-before", "enabled": True, "status": "active"}

        async def undo_change_set(self, **kwargs):
            result = await kwargs["workflow_undo_handler"]({
                "object_type": "workflow",
                "object_id": "workflow-1",
                "operation": "status",
                "workflow_version_before_id": "version-before",
                "workflow_version_after_id": "version-before",
            })
            return {"handler_result": result}

    class FakeWorkflowUndoService:
        def __init__(self) -> None:
            self.updated_enabled: list[bool] = []

        def get_workflow(self, workflow_id: str, user_id: str, vault_key_id: str):
            assert workflow_id == "workflow-1"
            assert user_id == "user-1"
            assert vault_key_id == "vault-1"
            return FakeWorkflow(workflow_id="workflow-1", version_id="version-before", enabled=False)

        def update_workflow(self, workflow_id: str, user_id: str, **kwargs):
            assert workflow_id == "workflow-1"
            assert user_id == "user-1"
            self.updated_enabled.append(kwargs["enabled"])
            return FakeWorkflow(workflow_id="workflow-1", version_id="version-before", enabled=kwargs["enabled"])

        def restore_workflow_version_from_history(self, *_args):
            raise AssertionError("status undo must not restore the already-current workflow version")

    monkeypatch.setattr(workspace_history, "_current_user", fake_current_user)
    workflow_service = FakeWorkflowUndoService()

    result = await workspace_history.undo_workspace_history(
        SimpleNamespace(),
        Response(),
        "chg-1",
        service=FakeWorkflowUndoHistory(),
        workflow_service=workflow_service,
    )

    assert workflow_service.updated_enabled == [True]
    assert result["handler_result"]["after"]["enabled"] is True


@pytest.mark.asyncio
async def test_workflow_ask_without_create_uses_inference_planner(monkeypatch) -> None:
    async def fake_pipeline(instruction, secrets_manager):
        assert instruction == "create a workflow that prepares release validation and sends a notification"
        assert secrets_manager is not None
        return SimpleNamespace(
            proposal={
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
            },
            processing={"intent_frame": {"namespace": "workflows"}},
        )

    monkeypatch.setattr(workflows, "run_workflow_ask_pipeline", fake_pipeline)
    history = FakeHistoryService()
    service = FakeWorkflowService()

    result = await workflows.ask_workflows(
        _request_with_secrets(),
        workflows.WorkflowAskRequest(instruction="create a workflow that prepares release validation and sends a notification"),
        current_user=_user(),
        service=service,
        history_service=history,
    )

    assert result["applied"] is True
    assert service.created[0]["title"] == "Inferred workflow"
    assert service.created[0]["enabled"] is True
    assert result["processing"] == {"intent_frame": {"namespace": "workflows"}}
    assert history.recorded[0]["entries"][0]["workflow_version_after_id"] == "version-1"


@pytest.mark.asyncio
async def test_workflow_ask_short_input_creates_deterministically_without_inference(monkeypatch) -> None:
    async def fail_pipeline(_instruction, _secrets_manager):
        raise AssertionError("short workflow asks must not use inference")

    monkeypatch.setattr(workflows, "run_workflow_ask_pipeline", fail_pipeline)
    history = FakeHistoryService()
    service = FakeWorkflowService()

    result = await workflows.ask_workflows(
        SimpleNamespace(),
        workflows.WorkflowAskRequest(instruction="Nightly report"),
        current_user=_user(),
        service=service,
        history_service=history,
    )

    assert result["outcome"] == "applied"
    assert service.created[0]["title"] == "Nightly report"
    assert service.created[0]["enabled"] is False
    assert result["processing"] == {"inference_used": False, "deterministic_short_create": True}
