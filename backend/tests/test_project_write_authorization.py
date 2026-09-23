"""Focused Project focus, policy, and immutable approval authority tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from starlette.requests import Request

from backend.tests.runtime_import_stubs import install_code_route_import_stubs

install_code_route_import_stubs()

from backend.core.api.app.routes.projects import (  # noqa: E402
    ProjectCreateRequest,
    ProjectFocusActivateRequest,
    ProjectSettingsUpdateRequest,
    activate_project_focus,
    create_project,
    get_project_settings,
    update_project_settings,
)
from backend.core.api.app.services.directus.project_methods import ProjectMethods, hash_id  # noqa: E402
from backend.core.api.app.services.directus.team_methods import TeamPermissionError  # noqa: E402
from backend.core.api.app.services.project_write_authorization_service import (  # noqa: E402
    ProjectWriteAuthorizationError,
    ProjectWriteAuthorizationService,
    focus_id_hash,
)


FOCUS_ID = "9f56b770-3903-46bb-b9ea-5d01d6bc995b"
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


class MemoryCache:
    def __init__(self) -> None:
        self.data: dict[str, object] = {}

    async def get(self, key: str):
        return self.data.get(key)

    async def set(self, key: str, value, ttl=None) -> bool:
        self.data[key] = value
        return True

    async def delete(self, key: str) -> bool:
        return self.data.pop(key, None) is not None

    async def get_and_delete(self, key: str):
        return self.data.pop(key, None)


def project_settings(write_mode: str | None = "apply_and_show", **overrides):
    return {
        "write_mode": write_mode,
        "default_focus_id_hash": focus_id_hash(FOCUS_ID),
        "encrypted_settings": "cipher-settings-v1",
        "updated_at": 1,
        **overrides,
    }


def personal_directus(settings_ref: dict[str, object]):
    return SimpleNamespace(
        chat=SimpleNamespace(
            get_chat_metadata=AsyncMock(
                return_value={"id": "chat-a", "hashed_user_id": hash_id("user-1"), "hashed_team_id": None}
            )
        ),
        project=SimpleNamespace(
            get_project=AsyncMock(return_value={"id": "project-row", "project_id": "project-a"}),
            get_project_settings=AsyncMock(side_effect=lambda *_args, **_kwargs: settings_ref.get("value")),
        ),
    )


def make_request(cache: MemoryCache, method: str = "POST") -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": "/v1/projects/test",
            "headers": [],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "app": SimpleNamespace(state=SimpleNamespace(cache_service=cache)),
        }
    )


# contract-test: direct surface=rest_api assertions=projects.files.write-policy-setup,projects.focus.default-owned
def test_project_create_requires_explicit_policy_and_encrypted_default_focus() -> None:
    with pytest.raises(ValidationError):
        ProjectCreateRequest(
            project_id="project-a",
            encrypted_project_key="cipher-key",
            encrypted_name="cipher-name",
            created_at=10,
            updated_at=10,
            last_opened_at=10,
        )


async def activate(service: ProjectWriteAuthorizationService, *, chat_id: str = "chat-a", project_id: str = "project-a"):
    return await service.activate_focus(
        user_id="user-1",
        chat_id=chat_id,
        project_id=project_id,
        focus_id=FOCUS_ID,
        instruction="Stay inside the Project and follow its checked-in instructions.",
    )


# contract-test: supporting surface=rest_api assertions=projects.files.chat-focus-required,focus-modes.project-write-gate
@pytest.mark.anyio
async def test_write_gate_requires_same_chat_and_project_active_focus() -> None:
    settings_ref = {"value": project_settings()}
    service = ProjectWriteAuthorizationService(personal_directus(settings_ref), MemoryCache())

    with pytest.raises(ProjectWriteAuthorizationError, match="PROJECT_FOCUS_REQUIRED"):
        await service.require_write_authorization(
            requester_user_id="user-1",
            chat_id="chat-a",
            project_id="project-a",
            operation_id="operation-1",
            proposal_digest=DIGEST_A,
        )

    await activate(service)
    with pytest.raises(ProjectWriteAuthorizationError, match="PROJECT_FOCUS_REQUIRED"):
        await service.require_write_authorization(
            requester_user_id="user-1",
            chat_id="chat-b",
            project_id="project-a",
            operation_id="operation-1",
            proposal_digest=DIGEST_A,
        )
    with pytest.raises(ProjectWriteAuthorizationError, match="PROJECT_FOCUS_MISMATCH"):
        await service.require_write_authorization(
            requester_user_id="user-1",
            chat_id="chat-a",
            project_id="project-b",
            operation_id="operation-1",
            proposal_digest=DIGEST_A,
        )

    await service.deactivate_focus(user_id="user-1", chat_id="chat-a")
    with pytest.raises(ProjectWriteAuthorizationError, match="PROJECT_FOCUS_REQUIRED"):
        await service.require_write_authorization(
            requester_user_id="user-1",
            chat_id="chat-a",
            project_id="project-a",
            operation_id="operation-1",
            proposal_digest=DIGEST_A,
        )


# contract-test: supporting surface=rest_api assertions=projects.files.write-policy-enforcement,projects.files.recovery-authorization
@pytest.mark.anyio
async def test_current_policy_and_exact_approval_are_rechecked_at_commit() -> None:
    settings_ref = {"value": project_settings()}
    cache = MemoryCache()
    service = ProjectWriteAuthorizationService(personal_directus(settings_ref), cache)
    await activate(service)

    automatic = await service.require_write_authorization(
        requester_user_id="user-1",
        chat_id="chat-a",
        project_id="project-a",
        operation_id="operation-1",
        proposal_digest=DIGEST_A,
    )
    assert automatic["approval"] == "not_required"

    settings_ref["value"] = project_settings("always_ask", updated_at=2)
    with pytest.raises(ProjectWriteAuthorizationError, match="PROJECT_WRITE_APPROVAL_REQUIRED"):
        await service.require_write_authorization(
            requester_user_id="user-1",
            chat_id="chat-a",
            project_id="project-a",
            operation_id="operation-1",
            proposal_digest=DIGEST_A,
        )

    await service.approve_write(
        user_id="user-1",
        chat_id="chat-a",
        project_id="project-a",
        operation_id="operation-1",
        proposal_digest=DIGEST_A,
    )
    with pytest.raises(ProjectWriteAuthorizationError, match="PROJECT_WRITE_APPROVAL_MISMATCH"):
        await service.require_write_authorization(
            requester_user_id="user-1",
            chat_id="chat-a",
            project_id="project-a",
            operation_id="operation-1",
            proposal_digest=DIGEST_B,
        )

    preflight = await service.require_write_authorization(
        requester_user_id="user-1",
        chat_id="chat-a",
        project_id="project-a",
        operation_id="operation-1",
        proposal_digest=DIGEST_A,
    )
    assert preflight["approval"] == "approved"

    settings_ref["value"] = project_settings(
        "always_ask",
        encrypted_settings="cipher-settings-v2",
        updated_at=3,
    )
    with pytest.raises(ProjectWriteAuthorizationError, match="PROJECT_WRITE_APPROVAL_MISMATCH"):
        await service.require_write_authorization(
            requester_user_id="user-1",
            chat_id="chat-a",
            project_id="project-a",
            operation_id="operation-1",
            proposal_digest=DIGEST_A,
            consume_approval=True,
        )


# contract-test: supporting surface=rest_api assertions=projects.files.recovery-authorization,focus-modes.project-write-gate
@pytest.mark.anyio
async def test_consumed_approval_is_idempotent_only_for_same_operation_and_digest() -> None:
    settings_ref = {"value": project_settings("always_ask")}
    service = ProjectWriteAuthorizationService(personal_directus(settings_ref), MemoryCache())
    await activate(service)
    await service.approve_write(
        user_id="user-1",
        chat_id="chat-a",
        project_id="project-a",
        operation_id="operation-1",
        proposal_digest=DIGEST_A,
    )

    first = await service.require_write_authorization(
        requester_user_id="user-1",
        chat_id="chat-a",
        project_id="project-a",
        operation_id="operation-1",
        proposal_digest=DIGEST_A,
        consume_approval=True,
    )
    retry = await service.require_write_authorization(
        requester_user_id="user-1",
        chat_id="chat-a",
        project_id="project-a",
        operation_id="operation-1",
        proposal_digest=DIGEST_A,
        consume_approval=True,
    )
    assert first["idempotent_replay"] is False
    assert retry["idempotent_replay"] is True

    with pytest.raises(ProjectWriteAuthorizationError, match="PROJECT_WRITE_APPROVAL_REQUIRED"):
        await service.require_write_authorization(
            requester_user_id="user-1",
            chat_id="chat-a",
            project_id="project-a",
            operation_id="operation-2",
            proposal_digest=DIGEST_A,
            consume_approval=True,
        )


# contract-test: supporting surface=rest_api assertions=projects.files.chat-focus-required,projects.files.write-policy-enforcement
@pytest.mark.anyio
async def test_team_role_and_missing_policy_changes_fail_closed() -> None:
    settings_ref = {"value": project_settings()}
    membership = AsyncMock(return_value={"role": "member"})
    directus = SimpleNamespace(
        chat=SimpleNamespace(
            get_chat_metadata=AsyncMock(
                return_value={"id": "chat-a", "hashed_user_id": hash_id("owner"), "hashed_team_id": hash_id("team-1")}
            )
        ),
        team=SimpleNamespace(require_team_role=membership),
        project=SimpleNamespace(
            get_project=AsyncMock(return_value={"id": "project-row", "project_id": "project-a"}),
            get_project_settings=AsyncMock(side_effect=lambda *_args, **_kwargs: settings_ref.get("value")),
        ),
    )
    service = ProjectWriteAuthorizationService(directus, MemoryCache())
    await service.activate_focus(
        user_id="user-1",
        chat_id="chat-a",
        project_id="project-a",
        focus_id=FOCUS_ID,
        instruction="Team Project instructions",
        team_id="team-1",
    )

    membership.side_effect = TeamPermissionError("removed")
    with pytest.raises(ProjectWriteAuthorizationError, match="TEAM_PERMISSION_DENIED"):
        await service.require_write_authorization(
            requester_user_id="user-1",
            chat_id="chat-a",
            project_id="project-a",
            operation_id="operation-1",
            proposal_digest=DIGEST_A,
            team_id="team-1",
        )

    membership.side_effect = None
    membership.return_value = {"role": "member"}
    settings_ref["value"] = project_settings(None)
    with pytest.raises(ProjectWriteAuthorizationError, match="PROJECT_WRITE_MODE_REQUIRED"):
        await service.require_write_authorization(
            requester_user_id="user-1",
            chat_id="chat-a",
            project_id="project-a",
            operation_id="operation-1",
            proposal_digest=DIGEST_A,
            team_id="team-1",
        )


# contract-test: direct surface=rest_api assertions=projects.files.write-policy-setup,projects.files.write-policy-settings
@pytest.mark.anyio
async def test_settings_missing_state_and_explicit_setup_contract() -> None:
    cache = MemoryCache()
    project_api = SimpleNamespace(
        get_project=AsyncMock(return_value={"id": "project-row"}),
        get_project_settings=AsyncMock(return_value=None),
        upsert_project_settings=AsyncMock(),
    )
    directus = SimpleNamespace(project=project_api)

    missing = await get_project_settings(
        request=make_request(cache, "GET"),
        project_id="project-a",
        current_user=SimpleNamespace(id="user-1"),
        directus_service=directus,
    )
    assert missing["settings"] == {
        "write_mode": "apply_and_show",
        "selection_required": False,
        "default_focus_id_hash": None,
        "encrypted_settings": None,
        "updated_at": None,
    }

    with pytest.raises(HTTPException) as exc_info:
        await update_project_settings(
            request=make_request(cache, "PATCH"),
            project_id="project-a",
            body=ProjectSettingsUpdateRequest(write_mode="apply_and_show"),
            current_user=SimpleNamespace(id="user-1"),
            directus_service=directus,
        )
    assert exc_info.value.detail == "PROJECT_SETTINGS_SETUP_REQUIRED"
    project_api.upsert_project_settings.assert_not_awaited()


# contract-test: direct surface=rest_api assertions=projects.files.chat-focus-required,focus-modes.project-write-gate
@pytest.mark.anyio
async def test_focus_activation_route_returns_no_plaintext_instruction() -> None:
    settings_ref = {"value": project_settings()}
    directus = personal_directus(settings_ref)
    response = await activate_project_focus(
        request=make_request(MemoryCache()),
        project_id="project-a",
        body=ProjectFocusActivateRequest(
            chat_id="chat-a",
            focus_id=FOCUS_ID,
            instruction="private transient instructions",
        ),
        current_user=SimpleNamespace(id="user-1"),
        directus_service=directus,
    )
    assert response["focus"]["active"] is True
    assert response["focus"]["project_id"] == "project-a"
    assert "instruction" not in response["focus"]


# contract-test: supporting surface=rest_api assertions=projects.files.write-policy-setup,projects.files.write-policy-settings
@pytest.mark.anyio
async def test_directus_settings_hashes_focus_and_preserves_omitted_ciphertext() -> None:
    existing = {
        "id": "settings-row",
        **project_settings("always_ask"),
    }
    directus = SimpleNamespace(
        get_items=AsyncMock(return_value=[existing]),
        update_item=AsyncMock(return_value={**existing, "write_mode": "apply_and_show", "updated_at": 2}),
    )
    methods = ProjectMethods(directus)
    await methods.upsert_project_settings(
        "project-a",
        "user-1",
        {"write_mode": "apply_and_show", "updated_at": 2},
    )
    update = directus.update_item.await_args.args[2]
    assert update["encrypted_settings"] == "cipher-settings-v1"
    assert update["default_focus_id_hash"] == focus_id_hash(FOCUS_ID)

    directus.get_items.return_value = []
    directus.create_item = AsyncMock(return_value=(True, {"id": "new-settings"}))
    await methods.upsert_project_settings(
        "project-b",
        "user-1",
        {
            "write_mode": "always_ask",
            "default_focus_id": FOCUS_ID,
            "encrypted_settings": "cipher-new",
            "updated_at": 3,
        },
    )
    create = directus.create_item.await_args.args[1]
    assert create["default_focus_id_hash"] == focus_id_hash(FOCUS_ID)
    assert "default_focus_id" not in create


# contract-test: direct surface=rest_api assertions=projects.files.write-policy-setup,projects.files.write-policy-settings,projects.focus.default-owned
@pytest.mark.anyio
async def test_project_create_persists_required_settings_before_success(monkeypatch) -> None:
    created = {"id": "project-row", "project_id": "project-a", "encrypted_name": "cipher-name"}
    saved_settings = {
        "write_mode": "apply_and_show",
        "default_focus_id_hash": focus_id_hash(FOCUS_ID),
        "encrypted_settings": "cipher-settings",
        "updated_at": 10,
    }
    project_api = SimpleNamespace(
        create_project=AsyncMock(return_value=created),
        upsert_project_settings=AsyncMock(return_value=saved_settings),
        delete_project=AsyncMock(),
    )
    history = {"change_set": {"change_set_id": "change-1"}, "entries": []}
    monkeypatch.setattr(
        "backend.core.api.app.routes.projects._record_project_history",
        AsyncMock(return_value=history),
    )

    response = await create_project(
        request=make_request(MemoryCache()),
        body=ProjectCreateRequest(
            project_id="project-a",
            encrypted_project_key="cipher-key",
            encrypted_name="cipher-name",
            created_at=10,
            updated_at=10,
            last_opened_at=10,
            write_mode="apply_and_show",
            default_focus_id=FOCUS_ID,
            encrypted_settings="cipher-settings",
        ),
        current_user=SimpleNamespace(id="user-1"),
        directus_service=SimpleNamespace(project=project_api),
        history_service=AsyncMock(),
    )

    create_payload = project_api.create_project.await_args.args[1]
    assert "write_mode" not in create_payload
    assert "default_focus_id" not in create_payload
    assert "encrypted_settings" not in create_payload
    project_api.upsert_project_settings.assert_awaited_once_with(
        "project-a",
        "user-1",
        {
            "write_mode": "apply_and_show",
            "default_focus_id": FOCUS_ID,
            "encrypted_settings": "cipher-settings",
            "updated_at": 10,
        },
        team_id=None,
    )
    project_api.delete_project.assert_not_awaited()
    assert response["settings"]["selection_required"] is False


# contract-test: supporting surface=rest_api assertions=projects.files.write-policy-setup,projects.focus.default-owned
@pytest.mark.anyio
async def test_project_create_rolls_back_when_settings_cannot_be_persisted() -> None:
    project_api = SimpleNamespace(
        create_project=AsyncMock(return_value={"id": "project-row", "project_id": "project-a"}),
        upsert_project_settings=AsyncMock(return_value=None),
        delete_project=AsyncMock(return_value=True),
    )

    with pytest.raises(HTTPException) as exc_info:
        await create_project(
            request=make_request(MemoryCache()),
            body=ProjectCreateRequest(
                project_id="project-a",
                encrypted_project_key="cipher-key",
                encrypted_name="cipher-name",
                created_at=10,
                updated_at=10,
                last_opened_at=10,
                write_mode="always_ask",
                default_focus_id=FOCUS_ID,
                encrypted_settings="cipher-settings",
            ),
            current_user=SimpleNamespace(id="user-1"),
            directus_service=SimpleNamespace(project=project_api),
            history_service=AsyncMock(),
        )

    assert exc_info.value.detail == "Failed to create Project settings"
    project_api.delete_project.assert_awaited_once_with("project-a", "user-1", team_id=None)
