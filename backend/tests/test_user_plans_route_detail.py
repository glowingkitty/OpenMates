"""Tests for the user Plans detail route.

These tests exercise the FastAPI handler without full application startup.
The route returns encrypted Plan records only, with ownership enforced by the
service layer and team access gated before team-scoped lookup.
"""

import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import Response


class _FakeLimiter:
    def limit(self, _rate: str):
        def decorator(func):
            return func

        return decorator


auth_deps_stub = types.ModuleType("backend.core.api.app.routes.auth_routes.auth_dependencies")
auth_deps_stub.get_current_user = lambda: None
auth_deps_stub.get_current_user_or_api_key = lambda: None
limiter_stub = types.ModuleType("backend.core.api.app.services.limiter")
limiter_stub.limiter = _FakeLimiter()
workspace_planner_stub = types.ModuleType("backend.apps.ai.processing.workspace_ask_planner")
workspace_planner_stub.WorkspaceAskPlanningError = RuntimeError
workspace_planner_stub.run_plan_ask_pipeline = AsyncMock()
team_workspace_stub = types.ModuleType("backend.core.api.app.services.team_workspace_service")
team_workspace_stub.move_workspace_record_to_team = AsyncMock()
workspace_history_stub = types.ModuleType("backend.core.api.app.services.workspace_change_history_service")
workspace_history_stub.WorkspaceChangeHistoryService = object
workspace_history_stub.build_history_commands = lambda *args, **kwargs: {}
workspace_history_stub.s3_workspace_history_archive_io = lambda *args, **kwargs: None
sys.modules.setdefault("backend.core.api.app.routes.auth_routes.auth_dependencies", auth_deps_stub)
sys.modules.setdefault("backend.core.api.app.services.limiter", limiter_stub)
sys.modules.setdefault("backend.apps.ai.processing.workspace_ask_planner", workspace_planner_stub)
sys.modules.setdefault("backend.core.api.app.services.team_workspace_service", team_workspace_stub)
sys.modules.setdefault("backend.core.api.app.services.workspace_change_history_service", workspace_history_stub)

from backend.core.api.app.routes import user_plans  # noqa: E402
from backend.core.api.app.services.user_plan_service import UserPlanNotFoundError, UserPlanService  # noqa: E402


get_user_plan = getattr(user_plans.get_user_plan, "__wrapped__", user_plans.get_user_plan)


async def _current_user(_request: object, _response: Response) -> SimpleNamespace:
    return SimpleNamespace(id="user-1")


# contract-test: direct surface=rest_api assertions=plans.lifecycle.visible,plans.content.client-encrypted,plans.surface.semantic-parity
@pytest.mark.asyncio
async def test_get_user_plan_returns_owner_scoped_encrypted_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(user_plans, "_current_user", _current_user)
    plan = {"plan_id": "plan-1", "encrypted_title": "cipher-title", "status": "draft"}
    service = SimpleNamespace(get_plan=AsyncMock(return_value=plan))

    result = await get_user_plan(
        request=SimpleNamespace(),
        response=Response(),
        plan_id="plan-1",
        service=service,
    )

    assert result == {"plan": plan}
    service.get_plan.assert_awaited_once_with("plan-1", "user-1", team_id=None)


# contract-test: direct surface=rest_api assertions=plans.lifecycle.visible,plans.key-wrappers.contextual,plans.surface.semantic-parity
@pytest.mark.asyncio
async def test_get_user_plan_checks_team_permission_before_team_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(user_plans, "_current_user", _current_user)
    team = SimpleNamespace(require_team_role=AsyncMock())
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(directus_service=SimpleNamespace(team=team))))
    plan = {"plan_id": "plan-1", "hashed_team_id": "team-hash", "encrypted_title": "cipher-title"}
    service = SimpleNamespace(get_plan=AsyncMock(return_value=plan))

    result = await get_user_plan(
        request=request,
        response=Response(),
        plan_id="plan-1",
        team_id="team-1",
        service=service,
    )

    assert result == {"plan": plan}
    team.require_team_role.assert_awaited_once_with("team-1", "user-1", {"owner", "admin", "member", "viewer"})
    service.get_plan.assert_awaited_once_with("plan-1", "user-1", team_id="team-1")


# contract-test: direct surface=rest_api assertions=plans.active-context.vault-boundary,plans.surface.semantic-parity
def test_active_context_route_stays_before_plan_detail_route() -> None:
    get_paths = [route.path for route in user_plans.router.routes if "GET" in getattr(route, "methods", set())]

    assert get_paths.index("/v1/user-plans/active-context") < get_paths.index("/v1/user-plans/{plan_id}")


# contract-test: direct surface=rest_api assertions=plans.lifecycle.visible,plans.surface.semantic-parity
@pytest.mark.asyncio
async def test_user_plan_service_get_plan_hides_missing_or_cross_owner_plan() -> None:
    plan_methods = SimpleNamespace(get_plan=AsyncMock(return_value=None))
    service = UserPlanService(plan_methods)

    with pytest.raises(UserPlanNotFoundError):
        await service.get_plan("plan-1", "user-2")

    plan_methods.get_plan.assert_awaited_once_with("plan-1", "user-2", team_id=None)
