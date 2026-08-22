# backend/tests/test_cli_object_slugs.py
#
# Contract tests for CLI encrypted object slugs. These tests stay at the
# Directus helper/service boundary so they verify zero-knowledge storage and
# owner/team duplicate handling without needing a live CMS.
#
# Spec: docs/specs/cli-encrypted-slugs/spec.yml

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.services.directus.chat_methods import ChatMethods
from backend.core.api.app.services.directus.project_methods import ProjectMethods, hash_id as hash_project_id
from backend.core.api.app.services.directus.user_plan_methods import UserPlanMethods, hash_id as hash_plan_id
from backend.core.api.app.services.directus.user_task_methods import UserTaskMethods, hash_id as hash_task_id
from backend.core.api.app.services.team_workspace_service import TeamWorkspaceMoveError, move_workspace_record_to_team
from backend.core.api.app.services.workflow_service import DirectusWorkflowRepository
from backend.shared.python_utils.encrypted_slug_metadata import DuplicateObjectSlugError
from backend.tests.test_user_plans_api import plan_payload
from backend.tests.test_user_tasks_api import task_payload, with_lock_cache
from backend.tests.test_workflows_models import FakeDirectusClient, rain_graph
from backend.tests.workflow_test_utils import workflow_service


SCHEMA_ROOT = Path(__file__).resolve().parents[1] / "core" / "directus" / "schemas"
SLUG_HASH = "a" * 64
TEAM_SLUG_HASH = "b" * 64
ENCRYPTED_SLUG = "client:aes-gcm:encrypted-slug"


def _schema_text(name: str) -> str:
    return (SCHEMA_ROOT / name).read_text(encoding="utf-8")


# contract-test: direct surface=rest_api assertions=cli.slugs.encrypted-stable,cli.surface.semantic-parity
def test_slugged_object_schemas_define_encrypted_slug_metadata() -> None:
    for schema_name in ["workflows.yml", "projects.yml", "user_tasks.yml", "user_plans.yml", "chats.yml"]:
        schema_text = _schema_text(schema_name)
        assert "encrypted_slug:" in schema_text
        assert "slug_lookup_hash:" in schema_text


# contract-test: direct surface=rest_api assertions=cli.slugs.encrypted-stable,cli.surface.semantic-parity
def test_encrypted_slug_migration_is_wired_into_compose_setup() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    compose_text = (repo_root / "backend/core/docker-compose.yml").read_text(encoding="utf-8")
    selfhost_text = (repo_root / "backend/core/docker-compose.selfhost.yml").read_text(encoding="utf-8")
    selfhost_dockerfile_text = (
        repo_root / "backend/core/directus/Dockerfile.setup.selfhost"
    ).read_text(encoding="utf-8")

    assert "ENCRYPTED_SLUG_MIGRATION_PATH" in compose_text
    assert "migrate_encrypted_slug_indexes.sql:/usr/src/app/migrations/migrate_encrypted_slug_indexes.sql:ro" in compose_text
    assert "ENCRYPTED_SLUG_MIGRATION_PATH" in selfhost_text
    assert (
        "migrate_encrypted_slug_indexes.sql /usr/src/app/migrations/migrate_encrypted_slug_indexes.sql"
        in selfhost_dockerfile_text
    )


# contract-test: direct surface=rest_api assertions=cli.slugs.encrypted-stable,cli.surface.semantic-parity
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("methods_factory", "create_call", "hash_func"),
    [
        (
            lambda directus: ProjectMethods(directus),
            lambda methods: methods.create_project(
                "user-1",
                {
                    "project_id": "project-1",
                    "encrypted_project_key": "cipher-project-key",
                    "encrypted_name": "cipher-name",
                    "encrypted_slug": ENCRYPTED_SLUG,
                    "slug_lookup_hash": SLUG_HASH,
                    "created_at": 100,
                    "updated_at": 100,
                    "last_opened_at": 100,
                },
            ),
            hash_project_id,
        ),
        (
            lambda directus: UserTaskMethods(with_lock_cache(directus)),
            lambda methods: methods.create_task(
                "user-1",
                task_payload(encrypted_slug=ENCRYPTED_SLUG, slug_lookup_hash=SLUG_HASH),
            ),
            hash_task_id,
        ),
        (
            lambda directus: UserPlanMethods(directus),
            lambda methods: methods.create_plan(
                "user-1",
                plan_payload(encrypted_slug=ENCRYPTED_SLUG, slug_lookup_hash=SLUG_HASH),
            ),
            hash_plan_id,
        ),
    ],
)
# contract-test: direct surface=rest_api assertions=cli.slugs.encrypted-stable,cli.surface.semantic-parity
async def test_create_helpers_store_ciphertext_and_hash_without_plaintext_slug(methods_factory, create_call, hash_func) -> None:
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[])
    directus.create_item = AsyncMock(side_effect=lambda _collection, record, **_kwargs: (True, {"id": "row-1", **record}))
    directus.delete_item = AsyncMock(return_value=True)

    created = await create_call(methods_factory(directus))

    assert created is not None
    collection, record = directus.create_item.await_args_list[0].args[:2]
    assert collection in {"projects", "user_tasks", "user_plans"}
    assert record["encrypted_slug"] == ENCRYPTED_SLUG
    assert record["slug_lookup_hash"] == SLUG_HASH
    assert record["hashed_user_id"] == hash_func("user-1")
    assert "slug" not in record
    assert "plaintext_slug" not in record
    assert "daily-weather-reminder" not in json.dumps(record)


# contract-test: direct surface=rest_api assertions=cli.slugs.encrypted-stable,cli.surface.semantic-parity
@pytest.mark.asyncio
async def test_duplicate_task_slug_lookup_hash_is_rejected_in_personal_scope() -> None:
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[{"id": "existing-task"}])
    directus.create_item = AsyncMock(return_value=(True, {"id": "row-1"}))

    methods = UserTaskMethods(with_lock_cache(directus))

    with pytest.raises(DuplicateObjectSlugError):
        await methods.create_task("user-1", task_payload(encrypted_slug=ENCRYPTED_SLUG, slug_lookup_hash=SLUG_HASH))
    directus.create_item.assert_not_awaited()
    params = directus.get_items.await_args.kwargs["params"]
    filter_terms = params["filter"]["_and"]
    assert {"slug_lookup_hash": {"_eq": SLUG_HASH}} in filter_terms
    assert {"hashed_user_id": {"_eq": hash_task_id("user-1")}} in filter_terms
    assert {"hashed_team_id": {"_null": True}} in filter_terms


# contract-test: direct surface=rest_api assertions=cli.slugs.encrypted-stable,cli.surface.semantic-parity
@pytest.mark.asyncio
async def test_duplicate_project_slug_lookup_hash_is_rejected_in_team_scope() -> None:
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[{"id": "existing-project"}])
    directus.create_item = AsyncMock(return_value=(True, {"id": "row-1"}))

    methods = ProjectMethods(directus)

    with pytest.raises(DuplicateObjectSlugError):
        await methods.create_project(
            "user-1",
            {
                "project_id": "project-1",
                "encrypted_project_key": "cipher-project-key",
                "encrypted_name": "cipher-name",
                "encrypted_slug": ENCRYPTED_SLUG,
                "slug_lookup_hash": TEAM_SLUG_HASH,
                "created_at": 100,
                "updated_at": 100,
                "last_opened_at": 100,
            },
            team_id="team-1",
        )
    directus.create_item.assert_not_awaited()
    params = directus.get_items.await_args.kwargs["params"]
    filter_terms = params["filter"]["_and"]
    assert {"slug_lookup_hash": {"_eq": TEAM_SLUG_HASH}} in filter_terms
    assert {"hashed_team_id": {"_eq": hash_project_id("team-1")}} in filter_terms
    assert {"hashed_user_id": {"_null": True}} in filter_terms


# contract-test: direct surface=rest_api assertions=cli.slugs.encrypted-stable,cli.surface.semantic-parity
@pytest.mark.asyncio
async def test_slugged_workspace_move_requires_team_scoped_slug_metadata() -> None:
    source_row = {
        "id": "row-1",
        "hashed_user_id": hash_task_id("user-1"),
        "hashed_team_id": None,
        "encrypted_slug": ENCRYPTED_SLUG,
        "slug_lookup_hash": SLUG_HASH,
    }
    directus = SimpleNamespace()
    directus.team = SimpleNamespace(require_team_role=AsyncMock(return_value=True))
    directus.get_items = AsyncMock(side_effect=[[source_row], [source_row], [{"id": "team-duplicate"}], [source_row], []])
    directus.update_item = AsyncMock(return_value={"id": "row-1"})

    with pytest.raises(TeamWorkspaceMoveError, match="team-scoped encrypted slug metadata"):
        await move_workspace_record_to_team(
            directus_service=directus,
            actor_user_id="user-1",
            team_id="team-1",
            workspace_type="task",
            object_id="task-1",
            confirmed=True,
    )
    directus.update_item.assert_not_awaited()

    with pytest.raises(DuplicateObjectSlugError):
        await move_workspace_record_to_team(
            directus_service=directus,
            actor_user_id="user-1",
            team_id="team-1",
            workspace_type="task",
            object_id="task-1",
            confirmed=True,
            encrypted_slug="client:aes-gcm:team-encrypted-slug",
            slug_lookup_hash=TEAM_SLUG_HASH,
        )
    directus.update_item.assert_not_awaited()

    moved = await move_workspace_record_to_team(
        directus_service=directus,
        actor_user_id="user-1",
        team_id="team-1",
        workspace_type="task",
        object_id="task-1",
        confirmed=True,
        encrypted_slug="client:aes-gcm:team-encrypted-slug",
        slug_lookup_hash=TEAM_SLUG_HASH,
    )

    assert moved == {"id": "row-1"}
    patch = directus.update_item.await_args.args[2]
    assert patch["encrypted_slug"] == "client:aes-gcm:team-encrypted-slug"
    assert patch["slug_lookup_hash"] == TEAM_SLUG_HASH
    assert patch["hashed_team_id"] == hash_task_id("team-1")


# contract-test: direct surface=rest_api assertions=cli.slugs.encrypted-stable,cli.surface.semantic-parity
@pytest.mark.asyncio
async def test_plaintext_slug_fields_are_rejected_before_directus_write() -> None:
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[])
    directus.create_item = AsyncMock(return_value=(True, {"id": "row-1"}))

    methods = UserPlanMethods(directus)

    with pytest.raises(ValueError, match="plaintext slug"):
        await methods.create_plan("user-1", plan_payload(slug="daily-weather-reminder"))
    directus.create_item.assert_not_awaited()


# contract-test: direct surface=rest_api assertions=cli.slugs.encrypted-stable,workflows.surface.semantic-parity
def test_workflow_service_persists_and_returns_encrypted_slug_metadata() -> None:
    repository = DirectusWorkflowRepository(base_url="http://directus.test", token="test-token")
    directus = FakeDirectusClient()
    setattr(repository, "_client", directus)
    service = workflow_service(repository=repository)

    workflow = service.create_workflow(
        "alice",
        "Daily rain alert",
        rain_graph(),
        encrypted_slug=ENCRYPTED_SLUG,
        slug_lookup_hash=SLUG_HASH,
    )

    stored = next(iter(directus.collections["workflows"].values()))
    assert workflow.encrypted_slug == ENCRYPTED_SLUG
    assert workflow.slug_lookup_hash == SLUG_HASH
    assert stored["encrypted_slug"] == ENCRYPTED_SLUG
    assert stored["slug_lookup_hash"] == SLUG_HASH
    assert "daily-rain-alert" not in json.dumps(stored)


# contract-test: direct surface=rest_api assertions=cli.slugs.encrypted-stable,cli.surface.semantic-parity
@pytest.mark.asyncio
async def test_chat_creation_persists_encrypted_slug_metadata_without_plaintext() -> None:
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[])
    directus.create_item = AsyncMock(return_value=(True, {"id": "chat-1", "encrypted_slug": ENCRYPTED_SLUG, "slug_lookup_hash": SLUG_HASH}))
    directus.cache = SimpleNamespace(delete=AsyncMock(), increment_stat=AsyncMock())
    chat_key_wrapper = SimpleNamespace(ensure_default_wrapper_for_chat=AsyncMock(return_value=None))
    directus.chat_key_wrapper = chat_key_wrapper
    methods = ChatMethods(directus)

    created, existed = await methods.create_chat_in_directus(
        {
            "id": "chat-1",
            "hashed_user_id": hash_task_id("user-1"),
            "encrypted_title": "cipher-title",
            "encrypted_slug": ENCRYPTED_SLUG,
            "slug_lookup_hash": SLUG_HASH,
            "created_at": 100,
            "updated_at": 100,
        }
    )

    assert existed is False
    assert created is not None
    record = directus.create_item.await_args.args[1]
    assert record["encrypted_slug"] == ENCRYPTED_SLUG
    assert record["slug_lookup_hash"] == SLUG_HASH
    assert "slug" not in record
    assert "daily-weather-reminder" not in json.dumps(record)
