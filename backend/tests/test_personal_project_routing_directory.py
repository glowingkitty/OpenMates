"""Session-only Personal Project routing directory contract."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

from backend.tests.runtime_import_stubs import install_code_route_import_stubs

install_code_route_import_stubs()

from backend.core.api.app.routes.auth_routes.auth_dependencies import get_current_user  # noqa: E402
from backend.core.api.app.routes.projects import (  # noqa: E402
    get_personal_project_routing_directory, router,
)
from backend.core.api.app.services.directus.project_methods import hash_id  # noqa: E402


class ProjectDirectus:
    def __init__(self, rows: list[dict], settings: dict | None = None) -> None:
        self.rows = rows
        self.get_items = AsyncMock(side_effect=self._get_items)
        self.project = SimpleNamespace(get_project_settings_for_projects=AsyncMock(return_value=settings or {}))

    async def _get_items(self, collection: str, *, params: dict, no_cache: bool, raise_on_error: bool):
        assert collection == "projects" and no_cache is True and raise_on_error is True
        assert params["filter[hashed_user_id][_eq]"] == hash_id("owner")
        assert params["filter[hashed_team_id][_null]"] is True
        assert params["filter[archived][_neq]"] is True
        assert params["limit"] == 40
        return self.rows


def project(project_id: str, **changes: object) -> dict:
    return {"project_id": project_id, "hashed_user_id": hash_id("owner"),
            "hashed_team_id": None, "archived": False,
            "encrypted_project_key": "key", "encrypted_name": "name",
            "encrypted_description": "description", **changes}


# contract-test: direct surface=rest_api assertions=auth.session.authoritative-enforcement,auth.session.isolation
def test_routing_directory_is_static_session_only_route() -> None:
    routes = [route for route in router.routes if isinstance(route, APIRoute)]
    route = next(route for route in routes if route.path == "/v1/projects/routing-directory")
    assert "GET" in route.methods
    assert routes.index(route) < next(index for index, other in enumerate(routes)
                                      if other.path == "/v1/projects/{project_id}")
    assert [dependency.call for dependency in route.dependant.dependencies].count(get_current_user) == 1
    assert "team_id" not in {param.name for param in route.dependant.query_params}
    with pytest.raises(HTTPException) as error:
        asyncio.run(get_current_user(refresh_token=None))
    assert error.value.status_code == 401


# contract-test: direct surface=rest_api assertions=auth.session.authoritative-enforcement,auth.session.isolation
def test_routing_directory_returns_only_fresh_enabled_personal_ciphertext() -> None:
    directus = ProjectDirectus([project("disabled"), project("enabled")], {
        "disabled": {"auto_selection": False},
        "enabled": {"auto_selection": True, "focus_activation_policy": "approval"},
    })
    result = asyncio.run(get_personal_project_routing_directory(
        request=SimpleNamespace(), current_user=SimpleNamespace(id="owner"), directus_service=directus,
    ))
    assert result == {"project_candidates": [{
        "project_id": "enabled", "encrypted_project_key": "key",
        "encrypted_name": "name", "encrypted_description": "description",
        "auto_selection": True, "focus_activation_policy": "approval",
    }]}
    directus.get_items.assert_awaited_once()
    directus.project.get_project_settings_for_projects.assert_awaited_once_with(
        ["disabled", "enabled"], "owner", team_id=None,
    )


# contract-test: direct surface=rest_api assertions=auth.session.isolation
@pytest.mark.parametrize("bad", [
    project("foreign", hashed_user_id="other"),
    project("team", hashed_team_id="team"),
])
def test_routing_directory_rejects_mismatched_scope_before_settings(bad: dict) -> None:
    directus = ProjectDirectus([bad])
    with pytest.raises(RuntimeError):
        asyncio.run(get_personal_project_routing_directory(
            request=SimpleNamespace(), current_user=SimpleNamespace(id="owner"), directus_service=directus,
        ))
    directus.project.get_project_settings_for_projects.assert_not_awaited()
