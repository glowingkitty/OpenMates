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

from backend.core.api.app.routes.projects import (
    ProjectSourceCreateRequest,
    ProjectSettingsUpdateRequest,
    create_project_source,
    get_project_settings,
    list_project_sources,
    update_project_settings,
)
from backend.core.api.app.services.directus.project_methods import ProjectMethods, hash_id
from backend.shared.python_utils.project_file_risk import classify_project_file_risk


def make_request(method: str = "POST") -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": "/v1/projects/test",
            "headers": [],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
        }
    )


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


def test_project_file_risk_user_patterns_add_restrictions() -> None:
    result = classify_project_file_risk(
        "src/components/BillingCard.svelte",
        user_protected_patterns=["src/components/**"],
    )

    assert result.is_high_risk
    assert "user_protected_pattern" in result.reasons


@pytest.mark.anyio
async def test_upsert_project_settings_creates_hashed_owned_row() -> None:
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[])
    directus.create_item = AsyncMock(
        return_value=(
            True,
            {
                "id": "settings-row-1",
                "hashed_project_id": hash_id("project-1"),
                "hashed_user_id": hash_id("user-1"),
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
            "write_mode": "always_ask",
            "encrypted_settings": "encrypted-settings",
            "updated_at": 123,
        },
    )


def test_project_settings_request_rejects_auto_decide() -> None:
    with pytest.raises(ValidationError):
        ProjectSettingsUpdateRequest(write_mode="auto_decide", updated_at=123)


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

    assert response == {"sources": [{"source_id": "source-1"}]}


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
            "write_mode": "always_ask",
            "encrypted_settings": None,
            "updated_at": None,
        }
    }


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


@pytest.mark.anyio
async def test_update_project_settings_returns_sanitized_row() -> None:
    directus = SimpleNamespace()
    directus.project = SimpleNamespace(
        get_project=AsyncMock(return_value={"id": "project-row-1"}),
        upsert_project_settings=AsyncMock(
            return_value={
                "id": "settings-row-1",
                "hashed_project_id": hash_id("project-1"),
                "hashed_user_id": hash_id("user-1"),
                "write_mode": "auto_approve_safe_writes",
                "encrypted_settings": "encrypted-settings",
                "updated_at": 123,
            }
        ),
    )

    response = await update_project_settings(
        request=make_request("PATCH"),
        project_id="project-1",
        body=ProjectSettingsUpdateRequest(
            write_mode="auto_approve_safe_writes",
            encrypted_settings="encrypted-settings",
            updated_at=123,
        ),
        current_user=SimpleNamespace(id="user-1"),
        directus_service=directus,
    )

    assert response == {
        "settings": {
            "write_mode": "auto_approve_safe_writes",
            "encrypted_settings": "encrypted-settings",
            "updated_at": 123,
        }
    }


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


def test_remote_diff_proposals_are_not_project_database_rows() -> None:
    methods = ProjectMethods(SimpleNamespace())

    assert not hasattr(methods, "create_remote_diff_proposal")
