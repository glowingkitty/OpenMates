"""Red contract tests for encrypted Task Activity persistence and API routes.

TASK-1 defines a first-party-only Activity transport with no plaintext storage.
These tests intentionally name the pending schema, persistence, and route APIs.
They cover personal and Team scope, source attribution, and deletion tombstones.
"""

import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError


class _FakeLimiter:
    def limit(self, _rate: str):
        def decorator(func):
            return func

        return decorator


limiter_stub = types.ModuleType("backend.core.api.app.services.limiter")
limiter_stub.limiter = _FakeLimiter()
sys.modules.setdefault("backend.core.api.app.services.limiter", limiter_stub)

from backend.core.api.app.routes import user_tasks  # noqa: E402
from backend.core.api.app.services.directus.team_methods import TeamPermissionError  # noqa: E402
from backend.core.api.app.services.directus.user_task_methods import UserTaskMethods, hash_id  # noqa: E402


def activity_payload(**overrides: object) -> dict[str, object]:
    payload = {
        "entry_id": "activity-1",
        "encrypted_entry_key": "cipher-entry-key",
        "encrypted_message": "cipher-message",
        "encrypted_embed_key_material": "cipher-embed-key",
        "embed_refs": ["embed-1"],
        "created_at": 100,
    }
    payload.update(overrides)
    return payload


def activity_request(**overrides: object):
    return user_tasks.UserTaskActivityCreateRequest(**activity_payload(**overrides))


def route_request(*, role: str = "member", client_surface: str = "web") -> SimpleNamespace:
    async def require_team_role(_team_id: str, _user_id: str, allowed_roles: set[str]):
        if role not in allowed_roles:
            raise TeamPermissionError("Team permission denied")
        return {"role": role}

    return SimpleNamespace(
        headers={"x-openmates-client": client_surface},
        app=SimpleNamespace(
            state=SimpleNamespace(
                directus_service=SimpleNamespace(
                    team=SimpleNamespace(require_team_role=AsyncMock(side_effect=require_team_role))
                )
            )
        ),
    )


# contract-test: direct surface=rest_api assertions=tasks.content.client-encrypted,tasks.activity.client-encrypted
def test_activity_create_request_rejects_plaintext_and_unknown_private_extras() -> None:
    with pytest.raises(ValidationError):
        activity_request(plaintext_message="do not persist me")

    with pytest.raises(ValidationError):
        activity_request(raw_entry_key="do not persist me")

    request = activity_request()
    assert request.model_dump() == activity_payload()
    assert "plaintext_message" not in request.model_dump()
    assert "raw_entry_key" not in request.model_dump()


# contract-test: direct surface=rest_api assertions=tasks.activity.context-attribution
@pytest.mark.parametrize(
    ("client_surface", "expected_surface"),
    [("web", "web"), ("cli", "cli"), ("npm", "sdk_npm"), ("pip", "sdk_pip")],
)
def test_activity_source_surface_is_derived_only_from_allowlisted_authenticated_client_identity(
    client_surface: str,
    expected_surface: str,
) -> None:
    request = route_request(client_surface=client_surface)

    assert user_tasks.derive_task_activity_source_surface(request) == expected_surface

    request.headers["x-openmates-client"] = "spoofed-client"
    with pytest.raises(HTTPException) as exc_info:
        user_tasks.derive_task_activity_source_surface(request)

    assert exc_info.value.status_code == 400


# contract-test: direct surface=rest_api assertions=tasks.activity.client-encrypted,tasks.activity.task-scoped-authorization
@pytest.mark.asyncio
@pytest.mark.parametrize("team_id", [None, "team-1"])
async def test_create_activity_persists_only_ciphertext_with_personal_or_team_task_scope(team_id: str | None) -> None:
    directus = SimpleNamespace(
        get_items=AsyncMock(return_value=[]),
        create_item=AsyncMock(return_value=(True, {"id": "row-1", **activity_payload()})),
    )
    methods = UserTaskMethods(directus)

    created = await methods.create_task_activity(
        "user-1",
        "task-1",
        activity_payload(),
        team_id=team_id,
        source_surface="web",
    )

    assert created is not None
    collection, record = directus.create_item.await_args.args
    assert collection == "user_task_activity"
    assert record["hashed_task_id"] == hash_id("task-1")
    assert record["hashed_user_id"] == hash_id("user-1")
    assert record["hashed_team_id"] == (hash_id(team_id) if team_id else None)
    assert record["encrypted_entry_key"] == "cipher-entry-key"
    assert record["encrypted_message"] == "cipher-message"
    assert record["encrypted_embed_key_material"] == "cipher-embed-key"
    assert record["embed_refs"] == ["embed-1"]
    assert record["source_surface"] == "web"
    assert "plaintext_message" not in record
    assert "raw_entry_key" not in record
    assert "raw_embed_key" not in record


# contract-test: direct surface=rest_api assertions=tasks.activity.client-encrypted,tasks.activity.single-final-section
@pytest.mark.asyncio
async def test_activity_create_is_idempotent_and_list_order_is_created_at_then_entry_id() -> None:
    existing = {"id": "row-1", **activity_payload()}
    directus = SimpleNamespace(
        get_items=AsyncMock(return_value=[existing]),
        create_item=AsyncMock(),
    )
    methods = UserTaskMethods(directus)

    retried = await methods.create_task_activity("user-1", "task-1", activity_payload(), source_surface="web")
    entries = await methods.list_task_activity("user-1", "task-1")

    assert retried == existing
    directus.create_item.assert_not_awaited()
    assert entries == [existing]
    params = directus.get_items.await_args_list[-1].kwargs["params"]
    assert params["sort"] == "created_at,entry_id"


# contract-test: direct surface=rest_api assertions=tasks.activity.deletion-tombstone,tasks.activity.task-scoped-authorization
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("deleter_id", "allow_task_mutation"),
    [("author-1", False), ("deleter-1", True)],
)
async def test_activity_delete_allows_author_or_mutation_role_and_tombstones_ciphertext(
    deleter_id: str,
    allow_task_mutation: bool,
) -> None:
    entry = {"id": "row-1", **activity_payload(), "actor_hash": hash_id("author-1")}
    directus = SimpleNamespace(
        get_items=AsyncMock(return_value=[entry]),
        update_item=AsyncMock(return_value={"id": "row-1", "entry_id": "activity-1", "deleted_at": 200}),
    )
    methods = UserTaskMethods(directus)

    tombstone = await methods.delete_task_activity(
        deleter_id,
        "task-1",
        "activity-1",
        deleted_at=200,
        allow_task_mutation=allow_task_mutation,
    )

    assert tombstone["entry_id"] == "activity-1"
    assert tombstone["author_hash"] == hash_id("author-1")
    assert tombstone["deleted_by_hash"] == hash_id(deleter_id)
    _collection, _row_id, patch = directus.update_item.await_args.args
    assert patch["deleted_at"] == 200
    assert patch["deleted_by_hash"] == hash_id(deleter_id)
    assert patch["encrypted_message"] is None
    assert patch["encrypted_entry_key"] is None
    assert patch["encrypted_embed_key_material"] is None
    assert patch["embed_refs"] == []


# contract-test: direct surface=rest_api assertions=tasks.activity.task-scoped-authorization
@pytest.mark.asyncio
async def test_create_activity_route_rejects_team_viewer_before_persistence(monkeypatch) -> None:
    async def current_user(_request, _response):
        return SimpleNamespace(id="viewer-1")

    monkeypatch.setattr(user_tasks, "_current_user", current_user)
    service = SimpleNamespace(create_task_activity=AsyncMock())

    with pytest.raises(HTTPException) as exc_info:
        await user_tasks.create_user_task_activity(
            route_request(role="viewer"),
            SimpleNamespace(),
            "task-1",
            activity_request(),
            team_id="team-1",
            service=service,
        )

    assert exc_info.value.status_code == 403
    service.create_task_activity.assert_not_awaited()


# contract-test: direct surface=rest_api assertions=tasks.activity.context-attribution,tasks.activity.task-scoped-authorization
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("client_surface", "expected_surface"),
    [("web", "web"), ("cli", "cli"), ("npm", "sdk_npm"), ("pip", "sdk_pip")],
)
async def test_create_activity_route_derives_source_and_never_accepts_body_attribution(
    monkeypatch,
    client_surface: str,
    expected_surface: str,
) -> None:
    async def current_user(_request, _response):
        return SimpleNamespace(id="user-1")

    monkeypatch.setattr(user_tasks, "_current_user", current_user)
    created = {"entry_id": "activity-1", "source_surface": expected_surface}
    service = SimpleNamespace(create_task_activity=AsyncMock(return_value=created))

    result = await user_tasks.create_user_task_activity(
        route_request(client_surface=client_surface),
        SimpleNamespace(),
        "task-1",
        activity_request(),
        team_id=None,
        service=service,
    )

    assert result == {"entry": created}
    assert service.create_task_activity.await_args.kwargs["source_surface"] == expected_surface
    assert "actor_hash" not in service.create_task_activity.await_args.kwargs["payload"]


# contract-test: direct surface=rest_api assertions=tasks.activity.client-encrypted,tasks.activity.deletion-tombstone
def test_activity_response_hides_storage_scope_and_derives_tombstone_author() -> None:
    projected = user_tasks._task_activity_response(
        {
            "id": 42,
            "entry_id": "activity-1",
            "task_id": "task-1",
            "hashed_user_id": hash_id("user-1"),
            "hashed_team_id": None,
            "kind": "tombstone",
            "actor_hash": hash_id("author-1"),
            "deleted_by_hash": hash_id("deleter-1"),
            "encrypted_entry_key": None,
            "encrypted_message": None,
            "encrypted_embed_key_material": None,
            "embed_refs": [],
        }
    )

    assert projected["author_hash"] == hash_id("author-1")
    assert "id" not in projected
    assert "hashed_user_id" not in projected
    assert "hashed_team_id" not in projected


# contract-test: direct surface=rest_api assertions=tasks.activity.deletion-tombstone,tasks.activity.task-scoped-authorization
@pytest.mark.asyncio
async def test_delete_activity_route_allows_author_or_team_mutation_role_and_denies_cross_scope(monkeypatch) -> None:
    async def current_user(_request, _response):
        return SimpleNamespace(id="deleter-1")

    monkeypatch.setattr(user_tasks, "_current_user", current_user)
    service = SimpleNamespace(
        delete_task_activity=AsyncMock(return_value={"entry_id": "activity-1", "deleted_by_hash": hash_id("deleter-1")})
    )

    result = await user_tasks.delete_user_task_activity(
        route_request(role="admin"),
        SimpleNamespace(),
        "task-1",
        "activity-1",
        team_id="team-1",
        service=service,
    )

    assert result["entry"]["deleted_by_hash"] == hash_id("deleter-1")
    assert service.delete_task_activity.await_args.kwargs["allow_task_mutation"] is True

    service.delete_task_activity.reset_mock()
    service.delete_task_activity.side_effect = TeamPermissionError("cross-task or cross-team entry")
    with pytest.raises(HTTPException) as exc_info:
        await user_tasks.delete_user_task_activity(
            route_request(role="member"),
            SimpleNamespace(),
            "other-task",
            "activity-1",
            team_id="other-team",
            service=service,
        )

    assert exc_info.value.status_code == 403
