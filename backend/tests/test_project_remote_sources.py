"""Tests for Projects remote-source permission foundations.

This suite covers the first Projects remote-source slice: deterministic file-risk
classification and encrypted Project permission settings. Remote diff proposals
are message-local virtual artifacts, not Project database rows. Remote writes and
command execution remain out of scope.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from starlette.requests import Request

from backend.tests.runtime_import_stubs import install_code_route_import_stubs

install_code_route_import_stubs()

from backend.core.api.app.routes.projects import (  # noqa: E402 - optional dependency stubs precede route imports.
    ProjectSourceCreateRequest,
    ProjectSourceCapabilitiesUpdateRequest,
    ProjectSettingsUpdateRequest,
    create_project_source,
    get_project_settings,
    list_project_sources,
    update_project_settings,
    update_project_source_capabilities,
)
from backend.core.api.app.services.directus.project_methods import ProjectMethods, hash_id  # noqa: E402
from backend.core.api.app.services.project_write_authorization_service import focus_id_hash  # noqa: E402
from backend.shared.python_utils.project_file_risk import classify_project_file_risk  # noqa: E402


def make_request(method: str = "POST") -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": "/v1/projects/test",
            "headers": [],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "app": SimpleNamespace(
                state=SimpleNamespace(
                    cache_service=SimpleNamespace(get=AsyncMock(return_value=None))
                )
            ),
        }
    )


# contract-test: supporting surface=rest_api assertions=projects.files.write-policy-enforcement
def test_project_file_risk_marks_only_narrow_high_risk_defaults() -> None:
    risky_paths = [
        ".env",
        ".env.example",
        ".gitignore",
        "Caddyfile",
        "package.json",
        "backend/core/directus/schemas/projects.yml",
        "backend/core/security/auth.py",
        "infra/main.tf",
        ".github/workflows/deploy.yml",
    ]
    safe_paths = [
        "src/App.svelte",
        "backend/apps/weather/skills/search_skill.py",
        "docs/architecture/platforms/cli-package.md",
    ]

    for path in risky_paths:
        result = classify_project_file_risk(path)
        assert result.is_high_risk, path
        assert result.reasons

    for path in safe_paths:
        result = classify_project_file_risk(path)
        assert not result.is_high_risk, path
        assert result.reasons == []


# contract-test: supporting surface=rest_api assertions=projects.files.write-policy-enforcement
def test_project_file_risk_user_patterns_add_restrictions() -> None:
    result = classify_project_file_risk(
        "src/components/BillingCard.svelte",
        user_protected_patterns=["src/components/**"],
    )

    assert result.is_high_risk
    assert "user_protected_pattern" in result.reasons


# contract-test: supporting surface=rest_api assertions=projects.files.write-policy-settings,projects.focus.default-owned
@pytest.mark.anyio
async def test_upsert_project_settings_creates_hashed_owned_row() -> None:
    focus_id = "9f56b770-3903-46bb-b9ea-5d01d6bc995b"
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[])
    directus.create_item = AsyncMock(
        return_value=(
            True,
            {
                "id": "settings-row-1",
                "hashed_project_id": hash_id("project-1"),
                "hashed_user_id": hash_id("user-1"),
                "hashed_team_id": None,
                "updated_by_user_hash": hash_id("user-1"),
                "write_mode": "always_ask",
            },
        )
    )

    methods = ProjectMethods(directus)
    settings = await methods.upsert_project_settings(
        "project-1",
        "user-1",
        {
            "write_mode": "always_ask",
            "default_focus_id": focus_id,
            "encrypted_settings": "encrypted-settings",
            "updated_at": 123,
        },
    )

    assert settings["write_mode"] == "always_ask"
    directus.create_item.assert_awaited_once_with(
        "project_settings",
        {
            "hashed_project_id": hash_id("project-1"),
            "hashed_user_id": hash_id("user-1"),
            "hashed_team_id": None,
            "updated_by_user_hash": hash_id("user-1"),
            "write_mode": "always_ask",
            "default_focus_id_hash": focus_id_hash(focus_id),
            "encrypted_settings": "encrypted-settings",
            "updated_at": 123,
        },
    )


# contract-test: supporting surface=rest_api assertions=projects.files.write-policy-setup,projects.files.write-policy-settings
def test_project_settings_request_rejects_auto_decide() -> None:
    with pytest.raises(ValidationError):
        ProjectSettingsUpdateRequest(write_mode="auto_decide", updated_at=123)


# contract-test: supporting surface=rest_api assertions=projects.access.explicit-context
def test_project_source_request_rejects_mutating_v1_capabilities() -> None:
    with pytest.raises(ValidationError):
        ProjectSourceCreateRequest(
            source_id="source-1",
            source_type="remote_git_repository",
            encrypted_display_name="encrypted-name",
            encrypted_metadata="encrypted-metadata",
            capabilities=["read", "apply_patch"],
            created_at=123,
            updated_at=123,
        )

    with pytest.raises(ValidationError):
        ProjectSourceCapabilitiesUpdateRequest(
            capabilities=["read", "run_command", "run_command"],
            updated_at=123,
        )


# contract-test: supporting surface=rest_api assertions=projects.access.explicit-context,code-run.remote.confinement
@pytest.mark.anyio
async def test_update_project_source_capabilities_preserves_encrypted_identity() -> None:
    source = {
        "id": "source-row-1",
        "source_id": "source-1",
        "encrypted_display_name": "encrypted-name",
        "encrypted_metadata": "encrypted-metadata",
        "status": "connected",
        "capabilities": ["read"],
        "updated_at": 100,
    }
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[source])
    directus.update_item = AsyncMock(return_value=True)
    updated = await ProjectMethods(directus).update_source_capabilities(
        "project-1",
        "user-1",
        "source-1",
        capabilities=["read", "search", "write_request", "run_command"],
        updated_at=123,
    )
    assert updated["encrypted_display_name"] == "encrypted-name"
    assert updated["encrypted_metadata"] == "encrypted-metadata"
    assert updated["source_id"] == "source-1"
    directus.update_item.assert_awaited_once_with(
        "project_sources",
        "source-row-1",
        {
            "capabilities": ["read", "search", "write_request", "run_command"],
            "updated_at": 123,
        },
    )


# contract-test: supporting surface=rest_api assertions=projects.access.explicit-context,code-run.remote.confinement
@pytest.mark.anyio
async def test_update_project_source_capabilities_route_requires_owner_or_team_source_authority() -> None:
    source = {
        "id": "source-row-1",
        "source_id": "source-1",
        "attached_by_user_hash": hash_id("another-member"),
        "status": "connected",
    }
    directus = SimpleNamespace(
        team=SimpleNamespace(
            require_team_role=AsyncMock(return_value={"role": "member"})
        ),
        project=SimpleNamespace(
            get_project=AsyncMock(return_value={"id": "project-row-1"}),
            get_source=AsyncMock(return_value=source),
            update_source_capabilities=AsyncMock(),
        ),
    )
    with pytest.raises(HTTPException) as exc_info:
        await update_project_source_capabilities(
            request=make_request("PATCH"),
            project_id="project-1",
            source_id="source-1",
            body=ProjectSourceCapabilitiesUpdateRequest(
                capabilities=["read", "run_command"], updated_at=123
            ),
            team_id="team-1",
            current_user=SimpleNamespace(id="user-1"),
            directus_service=directus,
        )
    assert exc_info.value.status_code == 403
    directus.project.update_source_capabilities.assert_not_called()


# contract-test: supporting surface=rest_api assertions=projects.lifecycle.encrypted-crud,projects.keys.client-wrapped
@pytest.mark.anyio
async def test_create_project_source_stores_hashed_owned_encrypted_row() -> None:
    directus = SimpleNamespace()
    directus.create_item = AsyncMock(
        return_value=(
            True,
            {
                "id": "source-row-1",
                "source_id": "source-1",
                "source_type": "remote_git_repository",
                "status": "connected",
            },
        )
    )

    methods = ProjectMethods(directus)
    source = await methods.create_source(
        "project-1",
        "user-1",
        {
            "source_id": "source-1",
            "source_type": "remote_git_repository",
            "encrypted_display_name": "encrypted-name",
            "encrypted_metadata": "encrypted-metadata",
            "capabilities": ["read", "search"],
            "status": "connected",
            "created_at": 123,
            "updated_at": 123,
            "last_indexed_at": 122,
        },
    )

    assert source["source_id"] == "source-1"
    directus.create_item.assert_awaited_once_with(
        "project_sources",
        {
            "source_id": "source-1",
            "hashed_project_id": hash_id("project-1"),
            "hashed_user_id": hash_id("user-1"),
            "hashed_team_id": None,
            "attached_by_user_hash": hash_id("user-1"),
            "source_type": "remote_git_repository",
            "encrypted_display_name": "encrypted-name",
            "encrypted_metadata": "encrypted-metadata",
            "capabilities": ["read", "search"],
            "status": "connected",
            "created_at": 123,
            "updated_at": 123,
            "last_indexed_at": 122,
        },
    )


# contract-test: supporting surface=rest_api assertions=projects.access.explicit-context
@pytest.mark.anyio
async def test_list_project_sources_filters_by_project_and_user() -> None:
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[{"source_id": "source-1"}])

    methods = ProjectMethods(directus)
    sources = await methods.list_sources("project-1", "user-1")

    assert sources == [{"source_id": "source-1"}]
    directus.get_items.assert_awaited_once()
    params = directus.get_items.await_args.kwargs["params"]
    assert params["filter[hashed_project_id][_eq]"] == hash_id("project-1")
    assert params["filter[hashed_user_id][_eq]"] == hash_id("user-1")


# contract-test: supporting surface=rest_api assertions=projects.access.explicit-context
@pytest.mark.anyio
async def test_create_project_source_route_requires_project_access() -> None:
    directus = SimpleNamespace()
    directus.project = SimpleNamespace(
        get_project=AsyncMock(return_value=None),
        create_source=AsyncMock(),
    )

    with pytest.raises(HTTPException) as exc_info:
        await create_project_source(
            request=make_request(),
            project_id="project-1",
            body=ProjectSourceCreateRequest(
                source_id="source-1",
                source_type="remote_git_repository",
                encrypted_display_name="encrypted-name",
                encrypted_metadata="encrypted-metadata",
                capabilities=["read", "search"],
                created_at=123,
                updated_at=123,
            ),
            current_user=SimpleNamespace(id="user-1"),
            directus_service=directus,
        )

    assert exc_info.value.status_code == 404
    directus.project.create_source.assert_not_called()


# contract-test: supporting surface=rest_api assertions=projects.access.explicit-context
@pytest.mark.anyio
async def test_list_project_sources_route_returns_owned_sources() -> None:
    directus = SimpleNamespace()
    directus.project = SimpleNamespace(
        get_project=AsyncMock(return_value={"id": "project-row-1"}),
        list_sources=AsyncMock(return_value=[{"source_id": "source-1"}]),
    )

    response = await list_project_sources(
        request=make_request("GET"),
        project_id="project-1",
        current_user=SimpleNamespace(id="user-1"),
        directus_service=directus,
    )

    assert response == {
        "sources": [
            {
                "source_id": "source-1",
                "status": "offline",
                "source_session_id": None,
                "key_epoch": None,
            }
        ]
    }


# contract-test: supporting surface=rest_api assertions=projects.files.write-policy-setup,projects.files.write-policy-settings
@pytest.mark.anyio
async def test_get_project_settings_returns_default_without_row() -> None:
    directus = SimpleNamespace()
    directus.project = SimpleNamespace(
        get_project=AsyncMock(return_value={"id": "project-row-1"}),
        get_project_settings=AsyncMock(return_value=None),
    )

    response = await get_project_settings(
        request=make_request("GET"),
        project_id="project-1",
        current_user=SimpleNamespace(id="user-1"),
        directus_service=directus,
    )

    assert response == {
        "settings": {
            "write_mode": None,
            "selection_required": True,
            "default_focus_id_hash": None,
            "encrypted_settings": None,
            "updated_at": None,
        }
    }


# contract-test: supporting surface=rest_api assertions=projects.access.explicit-context,projects.files.write-policy-settings
@pytest.mark.anyio
async def test_get_project_settings_requires_project_access() -> None:
    directus = SimpleNamespace()
    directus.project = SimpleNamespace(
        get_project=AsyncMock(return_value=None),
        get_project_settings=AsyncMock(),
    )

    with pytest.raises(HTTPException) as exc_info:
        await get_project_settings(
            request=make_request("GET"),
            project_id="project-1",
            current_user=SimpleNamespace(id="user-1"),
            directus_service=directus,
        )

    assert exc_info.value.status_code == 404
    directus.project.get_project_settings.assert_not_called()


# contract-test: supporting surface=rest_api assertions=projects.files.write-policy-settings
@pytest.mark.anyio
async def test_update_project_settings_returns_sanitized_row() -> None:
    directus = SimpleNamespace()
    directus.project = SimpleNamespace(
        get_project=AsyncMock(return_value={"id": "project-row-1"}),
        get_project_settings=AsyncMock(
            return_value={
                "write_mode": "always_ask",
                "default_focus_id_hash": "f" * 64,
                "encrypted_settings": "old-encrypted-settings",
                "updated_at": 122,
            }
        ),
        upsert_project_settings=AsyncMock(
            return_value={
                "id": "settings-row-1",
                "hashed_project_id": hash_id("project-1"),
                "hashed_user_id": hash_id("user-1"),
                "write_mode": "apply_and_show",
                "default_focus_id_hash": "f" * 64,
                "encrypted_settings": "encrypted-settings",
                "updated_at": 123,
            }
        ),
    )

    response = await update_project_settings(
        request=make_request("PATCH"),
        project_id="project-1",
        body=ProjectSettingsUpdateRequest(
            write_mode="apply_and_show",
            encrypted_settings="encrypted-settings",
            updated_at=123,
        ),
        current_user=SimpleNamespace(id="user-1"),
        directus_service=directus,
    )

    assert response == {
        "settings": {
            "write_mode": "apply_and_show",
            "selection_required": False,
            "default_focus_id_hash": "f" * 64,
            "encrypted_settings": "encrypted-settings",
            "updated_at": 123,
        }
    }


# contract-test: supporting surface=rest_api assertions=projects.access.explicit-context,projects.files.write-policy-settings
@pytest.mark.anyio
async def test_update_project_settings_requires_project_access() -> None:
    directus = SimpleNamespace()
    directus.project = SimpleNamespace(
        get_project=AsyncMock(return_value=None),
        upsert_project_settings=AsyncMock(),
    )

    with pytest.raises(HTTPException) as exc_info:
        await update_project_settings(
            request=make_request("PATCH"),
            project_id="project-1",
            body=ProjectSettingsUpdateRequest(write_mode="always_ask", updated_at=123),
            current_user=SimpleNamespace(id="user-1"),
            directus_service=directus,
        )

    assert exc_info.value.status_code == 404
    directus.project.upsert_project_settings.assert_not_called()


# contract-test: supporting surface=rest_api assertions=projects.files.no-server-decryption-authority
def test_remote_diff_proposals_are_not_project_database_rows() -> None:
    methods = ProjectMethods(SimpleNamespace())

    assert not hasattr(methods, "create_remote_diff_proposal")
