"""Run-detail completion targets stay within the Personal Workflow context."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.core.api.app.services import workflow_completion_notification_service as completion
from backend.core.api.app.services.workflow_models import WorkflowRunDetail, WorkflowRunStatus


_ROUTE_SOURCE = Path(__file__).resolve().parents[2] / "backend/core/api/app/routes/workflows.py"


@pytest.mark.anyio
@pytest.mark.parametrize("personal_context", [None, ""])
# contract-test: supporting surface=rest_api assertions=notifications.workflow-run.chat-target,workflows.access.boundaries
async def test_run_detail_projects_completion_only_for_authorized_personal_context(
    monkeypatch: pytest.MonkeyPatch, personal_context: str | None,
) -> None:
    route = next(node for node in ast.parse(_ROUTE_SOURCE.read_text()).body
                 if isinstance(node, ast.AsyncFunctionDef) and node.name == "get_workflow_run")
    route.decorator_list = []
    route.args.defaults = []
    for arg in route.args.args:
        arg.annotation = None
    route.returns = None

    calls: list[tuple] = []
    directus = object()

    async def inline(function, *args):
        return function(*args)

    async def require_team_role(value, team_id, user):
        assert value is directus and team_id == "team-1" and user.id == "owner"
        calls.append(("role", team_id))

    async def project(value, run, user_id):
        assert value is directus and run.id == "run-1" and user_id == "owner"
        calls.append(("projection", user_id))
        return {"chat_id": "personal-chat", "message_id": "personal-message", "delivery_id": "delivery-1"}

    monkeypatch.setattr(completion, "owner_run_completion_projection", project)
    namespace = {
        "run_in_threadpool": inline,
        "get_directus_service": lambda request: request.app.state.directus_service,
        "_require_team_read_role": require_team_role,
        "_handle_workflow_error": lambda exc: (_ for _ in ()).throw(exc),
    }
    exec(compile(ast.fix_missing_locations(ast.Module(body=[route], type_ignores=[])), str(_ROUTE_SOURCE), "exec"), namespace)

    class Service:
        def get_workflow(self, workflow_id, user_id, vault_key_id):
            calls.append(("workflow", workflow_id, user_id, vault_key_id))
            return object()

        def get_run(self, workflow_id, run_id, user_id, vault_key_id, team_id):
            calls.append(("run", workflow_id, run_id, user_id, vault_key_id, team_id))
            return WorkflowRunDetail(
                id=run_id, workflow_id=workflow_id, version_id="version-1",
                trigger_type="schedule", status=WorkflowRunStatus.COMPLETED,
            )

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(directus_service=directus)))
    user = SimpleNamespace(id="owner", vault_key_id="vault")
    team = await namespace["get_workflow_run"]("workflow-1", "run-1", request, user, Service(), "team-1")
    assert team["run"]["completion_notification"] is None
    assert calls == [
        ("role", "team-1"),
        ("run", "workflow-1", "run-1", "owner", "vault", "team-1"),
    ]

    calls.clear()
    personal = await namespace["get_workflow_run"]("workflow-1", "run-1", request, user, Service(), personal_context)
    assert personal["run"]["completion_notification"]["chat_id"] == "personal-chat"
    assert calls == [
        ("workflow", "workflow-1", "owner", "vault"),
        ("run", "workflow-1", "run-1", "owner", "vault", None),
        ("projection", "owner"),
    ]
