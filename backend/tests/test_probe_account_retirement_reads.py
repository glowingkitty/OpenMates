"""The database probe must never run against shared dev or production."""

import asyncio
import base64
import hashlib
from pathlib import Path
from uuid import uuid4, UUID
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.scripts.probe_account_retirement_reads import main, project_fixture_records, require_account_project_fence


# contract-test-file: tooling
@pytest.mark.parametrize("missing", ["CI", "OPENMATES_CI_ISOLATED", "OPENMATES_CI_MAIL_CAPTURE", "CMS_URL", "SERVER_ENVIRONMENT"])
def test_probe_requires_disposable_ci_before_importing_or_opening_database(monkeypatch, missing):
    for key, value in {
        "CI": "true", "OPENMATES_CI_ISOLATED": "1", "OPENMATES_CI_MAIL_CAPTURE": "1",
        "CMS_URL": "http://cms:8055", "SERVER_ENVIRONMENT": "development",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv(missing)
    with pytest.raises(RuntimeError, match="isolated CI"):
        asyncio.run(main())


def test_project_fixture_satisfies_real_schema_actor_parent_and_ciphertext_contracts():
    import yaml

    project_ids, item_ids, target_ids = [[str(uuid4()) for _ in range(2)] for _ in range(3)]
    owner_hashes = [hashlib.sha256(value.encode()).hexdigest() for value in ("synthetic-owner", "synthetic-foreign")]
    timestamp = 1791980000
    fixture = project_fixture_records(
        project_ids=project_ids, item_ids=item_ids, target_ids=target_ids,
        owner_hashes=owner_hashes, timestamp=timestamp,
    )
    root = Path(__file__).resolve().parents[2]
    schema_dir = root / "backend/core/directus/schemas"
    project_schema = yaml.safe_load((schema_dir / "projects.yml").read_text())
    item_schema = yaml.safe_load((schema_dir / "project_items.yml").read_text())
    migration = (root / "backend/core/directus/setup/migrate_project_owner_context.sql").read_text()
    assert "ALTER TABLE public.projects ALTER COLUMN created_by_user_hash SET NOT NULL" in migration
    assert "ALTER TABLE public.project_items ALTER COLUMN attached_by_user_hash SET NOT NULL" in migration
    assert list(fixture) == ["projects", "project_key_wrappers", "project_items"]
    for index, (project, wrapper, item) in enumerate(zip(*fixture.values())):
        assert set(project) <= set(project_schema["projects"]["fields"])
        assert set(wrapper) <= set(project_schema["project_key_wrappers"]["fields"])
        assert set(item) <= set(item_schema["project_items"]["fields"])
        assert UUID(project["id"]).version == UUID(wrapper["id"]).version == UUID(item["id"]).version == 4
        assert project["project_id"] == project_ids[index]
        assert project["created_by_user_hash"] == item["attached_by_user_hash"] == owner_hashes[index]
        assert project["hashed_user_id"] == wrapper["hashed_user_id"] == item["hashed_user_id"] == owner_hashes[index]
        assert project["hashed_team_id"] is wrapper["hashed_team_id"] is item["hashed_team_id"] is None
        assert wrapper["hashed_project_id"] == item["hashed_project_id"] == hashlib.sha256(project_ids[index].encode()).hexdigest()
        assert item["target_id_hash"] == hashlib.sha256(target_ids[index].encode()).hexdigest()
        assert item["item_type"] == "chat" and item["deleted_target_state"] is None
        assert project["created_at"] == item["created_at"] == item["updated_at"] == timestamp
        assert wrapper["key_type"] == "master" and wrapper["wrapper_version"] == 1
        for ciphertext in (project["encrypted_name"], wrapper["encrypted_project_key"], item["target_id_encrypted"]):
            assert base64.b64decode(ciphertext, validate=True).startswith(b"OM\x01")
    assert fixture["projects"][0]["hashed_user_id"] != fixture["projects"][1]["hashed_user_id"]


def test_project_fixture_rejects_incomplete_owner_target_context():
    with pytest.raises(ValueError, match="two complete"):
        project_fixture_records(project_ids=[], item_ids=[], target_ids=[], owner_hashes=[], timestamp=1)


@pytest.mark.asyncio
async def test_full_account_preflight_blocks_foreign_project_link_to_owners_own_chat():
    owner_id = str(uuid4())
    owner = hashlib.sha256(owner_id.encode()).hexdigest()
    foreign = hashlib.sha256(str(uuid4()).encode()).hexdigest()
    targets = [str(uuid4()), str(uuid4())]
    fixture = project_fixture_records(
        project_ids=[str(uuid4()), str(uuid4())], item_ids=[str(uuid4()), str(uuid4())],
        target_ids=targets, owner_hashes=[owner, foreign], timestamp=1,
    )
    collections = []

    async def read(collection, *, params, **options):
        collections.append(collection)
        assert options["admin_required"] and options["raise_on_error"]
        if collection == "chats":
            assert params["filter"] == {"hashed_user_id": {"_eq": owner}, "hashed_team_id": {"_null": True}}
            return [{"id": target} for target in targets]
        if collection == "upload_files":
            assert UUID(params["filter"]["user_id"]["_eq"]) == UUID(owner_id)
            return []
        assert collection == "project_items"
        assert set(params["filter"]["target_id_hash"]["_in"]) == {
            hashlib.sha256(target.encode()).hexdigest() for target in targets
        }
        return fixture["project_items"]

    await require_account_project_fence(SimpleNamespace(get_items=read), owner_id=owner_id, owner_hash=owner)
    assert collections == ["chats", "upload_files", "project_items"]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, RuntimeError("Database read failed")])
async def test_full_account_fence_cannot_pass_when_absent_or_database_fails(monkeypatch, failure):
    checker = AsyncMock(side_effect=failure)
    monkeypatch.setattr(
        "backend.core.api.app.services.storage_reference_service.assert_no_surviving_account_project_references", checker,
    )
    with pytest.raises((AssertionError, RuntimeError)):
        await require_account_project_fence(object(), owner_id=str(uuid4()), owner_hash="synthetic-owner")
