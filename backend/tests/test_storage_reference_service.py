"""File-mapped storage reference service tests.

The reconciliation suite covers the full reference lifecycle. This file keeps
storage_reference_service.py visible to session deploy coverage while asserting
the account-export rows added to deletion cleanup remain fail-closed.
Contract: architecture.storage-lifecycle.
"""

from __future__ import annotations

import importlib
import hashlib

import pytest


def _module():
    return importlib.import_module("backend.core.api.app.services.storage_reference_service")


class _Directus:
    def __init__(self) -> None:
        self.rows = {
            "account_export_parts": [{"id": "part-1"}],
            "account_export_jobs": [{"id": "job-1"}],
            "upload_files": [{"id": "upload-1"}],
            "user_task_archives": [],
            "workspace_change_archives": [],
            "cold_archive_manifests": [{"id": "manifest-1", "archive_id": "archive-1"}],
            "cold_archive_parts": [{"id": "cold-part-1"}],
        }
        self.deleted: list[tuple[str, list[str]]] = []
        self.queries: list[tuple[str, dict]] = []

    async def get_items(self, collection: str, *, params: dict, **_kwargs: object) -> list[dict]:
        self.queries.append((collection, params))
        if collection == "cold_archive_parts":
            archive_ids = params["filter"]["archive_id"]["_in"]
            assert isinstance(archive_ids, list) and archive_ids
        offset = int(params.get("offset", 0))
        limit = int(params.get("limit", 500))
        return self.rows.get(collection, [])[offset:offset + limit]

    async def bulk_delete_items(self, collection: str, item_ids: list[str]) -> bool:
        self.deleted.append((collection, item_ids))
        self.rows[collection] = [row for row in self.rows.get(collection, []) if row.get("id") not in item_ids]
        return True


# contract-test: direct surface=rest_api assertions=storage.deletion.global-authoritative,storage.export.persisted-bounded-complete
@pytest.mark.anyio
async def test_account_deletion_removes_persisted_export_reference_rows_before_owner_removal() -> None:
    module = _module()
    directus = _Directus()

    deleted = await module.delete_account_storage_reference_rows(
        directus_service=directus,
        user_id="user-1",
        user_id_hash="hash-1",
    )

    assert deleted["account_export_parts"] == 1
    assert deleted["account_export_jobs"] == 1
    assert ("account_export_parts", ["part-1"]) in directus.deleted
    assert ("account_export_jobs", ["job-1"]) in directus.deleted
    assert ("cold_archive_parts", ["cold-part-1"]) in directus.deleted
    assert next(params for collection, params in directus.queries if collection == "cold_archive_parts")["filter"] == {
        "archive_id": {"_in": ["archive-1"]},
    }


# contract-test: direct surface=rest_api assertions=storage.deletion.global-authoritative
@pytest.mark.anyio
async def test_account_deletion_fences_and_removes_only_personal_chat_archive_rows() -> None:
    module = _module()

    class ScopedDirectus(_Directus):
        def __init__(self) -> None:
            super().__init__()
            self.rows.update({
                "chats": [
                    {"id": "personal", "hashed_user_id": "owner", "hashed_team_id": None,
                     "storage_state": "hot", "archive_version": 1},
                    {"id": "team", "hashed_user_id": "owner", "hashed_team_id": "team-owner",
                     "storage_state": "hot", "archive_version": 1},
                ],
                "chat_message_archive_pages": [
                    {"id": "personal-page", "hashed_user_id": "owner", "hashed_team_id": None},
                    {"id": "team-page", "hashed_user_id": "owner", "hashed_team_id": "team-owner"},
                ],
                "chat_message_archive_segments": [
                    {"id": "personal-segment", "hashed_user_id": "owner", "hashed_team_id": None,
                     "state": "pruned", "lease_until": 0},
                    {"id": "team-segment", "hashed_user_id": "owner", "hashed_team_id": "team-owner",
                     "state": "pruned", "lease_until": 0},
                ],
                "embed_diffs": [], "chat_recovery_outputs": [],
            })

        async def get_items(self, collection: str, *, params: dict, **_kwargs: object) -> list[dict]:
            filters = params.get("filter", {})
            def matched(row: dict) -> bool:
                return all(
                    (row.get(field) == condition["_eq"] if "_eq" in condition else
                     row.get(field) is None if condition.get("_null") else False)
                    for field, condition in filters.items()
                )
            rows = [row for row in self.rows.get(collection, []) if matched(row)]
            return rows[:int(params.get("limit", 500))]

        async def update_item_if_version(self, collection: str, row_id: str, patch: dict,
                                         version: int, **_kwargs: object) -> bool:
            row = next(row for row in self.rows[collection] if row["id"] == row_id)
            if row["archive_version"] != version:
                return False
            row.update(patch)
            return True

    directus = ScopedDirectus()
    assert await module.fence_account_chats_for_deletion(
        directus_service=directus, user_id_hash="owner",
    ) == 1
    assert directus.rows["chats"][0]["storage_state"] == "deleting"
    assert directus.rows["chats"][1]["storage_state"] == "hot"
    deleted = await module.delete_account_storage_reference_rows(
        directus_service=directus, user_id="user", user_id_hash="owner",
    )
    assert deleted["chat_message_archive_pages"] == 1
    assert deleted["chat_message_archive_segments"] == 1
    assert [row["id"] for row in directus.rows["chat_message_archive_pages"]] == ["team-page"]
    assert [row["id"] for row in directus.rows["chat_message_archive_segments"]] == ["team-segment"]


class _OwnershipDirectus(_Directus):
    def __init__(self) -> None:
        super().__init__()
        self.rows.update({
            "chats": [], "embeds": [], "embed_keys": [], "embed_diffs": [],
            "project_items": [], "chat_message_archive_pages": [],
            "chat_message_archive_segments": [], "chat_recovery_outputs": [],
        })

    async def get_items(self, collection: str, *, params: dict, **_kwargs: object) -> list[dict]:
        filters = params.get("filter", {})
        if collection == "embed_diffs":
            from pathlib import Path
            import yaml
            schema = yaml.safe_load((Path(__file__).resolve().parents[1]
                / "core/directus/schemas/embed_diffs.yml").read_text())["embed_diffs"]["fields"]
            assert set(filters) <= set(schema), "Version query uses fields absent from Directus schema"
        def matched(row: dict) -> bool:
            return all(
                (row.get(field) == condition["_eq"] if "_eq" in condition else
                 row.get(field) in condition["_in"] if "_in" in condition else
                 row.get(field) is None if condition.get("_null") else False)
                for field, condition in filters.items()
            )
        return [row for row in self.rows.get(collection, []) if matched(row)][:int(params.get("limit", 500))]


# contract-test: direct surface=rest_api assertions=storage.deletion.global-authoritative,storage.files.reference-safe-single-copy
@pytest.mark.anyio
async def test_account_embed_snapshot_excludes_team_project_and_unresolved_survivors() -> None:
    module = _module()
    directus = _OwnershipDirectus()
    def digest(value):
        return hashlib.sha256(value.encode()).hexdigest()
    directus.rows["chats"] = [
        {"id": "personal", "hashed_user_id": "owner", "hashed_team_id": None},
        {"id": "team", "hashed_user_id": "owner", "hashed_team_id": "team-owner"},
    ]
    directus.rows["embeds"] = [
        {"id": "e1", "embed_id": "personal-embed", "hashed_embed_id": digest("personal-embed"),
         "hashed_user_id": "owner", "hashed_chat_id": digest("personal")},
        {"id": "e2", "embed_id": "team-embed", "hashed_embed_id": digest("team-embed"),
         "hashed_user_id": "owner", "hashed_chat_id": digest("team")},
        {"id": "e3", "embed_id": "orphan-embed", "hashed_embed_id": digest("orphan-embed"),
         "hashed_user_id": "owner", "hashed_chat_id": None},
        {"id": "e4", "embed_id": "shared-embed", "hashed_embed_id": digest("shared-embed"),
         "hashed_user_id": "owner", "hashed_chat_id": digest("personal")},
    ]
    directus.rows["embed_keys"] = [
        {"id": "key-personal", "hashed_embed_id": digest("personal-embed"), "key_type": "chat",
         "hashed_chat_id": digest("personal"), "hashed_user_id": "owner"},
        {"id": "key-shared", "hashed_embed_id": digest("shared-embed"), "key_type": "project",
         "hashed_project_id": digest("team-project"), "hashed_user_id": "owner"},
    ]
    directus.rows["project_items"] = [
        {"id": "project-ref", "item_type": "embed", "target_id_hash": digest("shared-embed"),
         "hashed_user_id": None, "hashed_team_id": "team-owner"},
    ]
    directus.rows["embed_diffs"] = [
        {"id": "v1", "embed_id": "personal-embed", "hashed_user_id": "owner"},
        {"id": "v2", "embed_id": "team-embed", "hashed_user_id": "owner",
         "archive_pending_object_key": "team/live.json", "archive_copy_lease_until": 4102444800},
        {"id": "v3", "embed_id": "orphan-embed", "hashed_user_id": "owner"},
        {"id": "v4", "embed_id": "shared-embed", "hashed_user_id": "owner"},
    ]
    snapshot = await module.load_account_deletable_embed_rows(
        directus_service=directus, user_id_hash="owner",
    )
    assert {row["id"] for row in snapshot.embeds} == {"e1", "e3"}
    assert {row["id"] for row in snapshot.versions} == {"v1", "v3"}
    directus.rows["embed_diffs"][0].update({
        "archive_pending_object_key": "personal/live.json", "archive_copy_lease_until": 4102444800,
    })
    with pytest.raises(RuntimeError, match="Embed version writer lease is active"):
        await module.load_account_deletable_embed_rows(directus_service=directus, user_id_hash="owner")
    directus.rows["embed_diffs"][0].pop("archive_pending_object_key")
    directus.rows["chats"] = []
    directus.rows["embeds"] = []
    deleted = await module.delete_account_storage_reference_rows(
        directus_service=directus, user_id="user", user_id_hash="owner",
        eligible_embed_rows=snapshot,
    )
    assert deleted["embed_diffs"] == 2
    assert {row["id"] for row in directus.rows["embed_diffs"]} == {"v2", "v4"}


# contract-test: direct surface=rest_api assertions=storage.deletion.global-authoritative
@pytest.mark.anyio
async def test_surviving_team_project_chat_or_upload_reference_stops_account_deletion() -> None:
    module = _module()
    directus = _OwnershipDirectus()
    directus.rows["chats"] = [{"id": "personal", "hashed_user_id": "owner", "hashed_team_id": None}]
    directus.rows["project_items"] = [{
        "id": "team-chat-link", "item_type": "chat",
        "target_id_hash": hashlib.sha256(b"personal").hexdigest(),
        "hashed_user_id": None, "hashed_team_id": "team-owner",
    }]
    with pytest.raises(RuntimeError, match="surviving Project"):
        await module.assert_no_surviving_account_project_references(
            directus_service=directus, user_id="user", user_id_hash="owner",
        )
    directus.rows["project_items"] = [{
        "id": "team-upload-link", "item_type": "upload",
        "target_id_hash": hashlib.sha256(b"upload-1").hexdigest(),
        "hashed_user_id": None, "hashed_team_id": "team-owner",
    }]
    directus.rows["upload_files"] = [{"id": "upload-1", "user_id": "user"}]
    with pytest.raises(RuntimeError, match="surviving Project"):
        await module.assert_no_surviving_account_project_references(
            directus_service=directus, user_id="user", user_id_hash="owner",
        )


# contract-test: direct surface=rest_api assertions=storage.deletion.global-authoritative
@pytest.mark.anyio
async def test_upload_embed_identity_project_reference_blocks_preflight_and_tombstones() -> None:
    module = _module()
    directus = _OwnershipDirectus()
    directus.rows["upload_files"] = [{"id": "upload-row", "embed_id": "public-upload", "user_id": "user"}]
    directus.rows["project_items"] = [{
        "id": "team-upload", "item_type": "upload",
        "target_id_hash": hashlib.sha256(b"public-upload").hexdigest(),
        "hashed_user_id": None, "hashed_team_id": "team-owner",
        "deleted_target_state": None,
    }]
    with pytest.raises(RuntimeError, match="surviving Project"):
        await module.assert_no_surviving_account_project_references(
            directus_service=directus, user_id="user", user_id_hash="owner",
        )
    # A deleted target marker no longer makes this Project item an active reference.
    directus.rows["project_items"][0]["deleted_target_state"] = "deleted"
    await module.assert_no_surviving_account_project_references(
        directus_service=directus, user_id="user", user_id_hash="owner",
    )


# contract-test: direct surface=rest_api assertions=storage.deletion.global-authoritative
@pytest.mark.anyio
async def test_unresolved_embed_chat_hash_blocks_account_deletion_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module()
    directus = _OwnershipDirectus()
    from backend.core.api.app.services.chat_message_archive_service import ChatMessageArchiveService

    async def unresolved(_self: ChatMessageArchiveService, operation: str, data: dict) -> dict:
        assert operation == "resolve_chat_hashes"
        assert data["hashes"] == [hashlib.sha256(b"missing-chat").hexdigest()]
        return {"chats": []}

    monkeypatch.setattr(ChatMessageArchiveService, "transaction", unresolved)
    directus.rows["embeds"] = [{
        "id": "orphan", "embed_id": "orphan-embed", "hashed_user_id": "owner",
        "hashed_embed_id": hashlib.sha256(b"orphan-embed").hexdigest(),
        "hashed_chat_id": hashlib.sha256(b"missing-chat").hexdigest(),
    }]
    with pytest.raises(RuntimeError, match="owner is unresolved"):
        await module.load_account_deletable_embed_rows(
            directus_service=directus, user_id_hash="owner",
        )


# contract-test: direct surface=rest_api assertions=storage.deletion.global-authoritative
@pytest.mark.anyio
async def test_resolved_moved_team_embed_survives_creator_account_deletion(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module()
    directus = _OwnershipDirectus()
    from backend.core.api.app.services.chat_message_archive_service import ChatMessageArchiveService

    moved_chat_hash = hashlib.sha256(b"moved-team-chat").hexdigest()
    directus.rows["embeds"] = [{
        "id": "team-embed", "embed_id": "embed-1", "hashed_user_id": "owner",
        "hashed_embed_id": hashlib.sha256(b"embed-1").hexdigest(),
        "hashed_chat_id": moved_chat_hash,
    }]

    async def resolved(_self: ChatMessageArchiveService, operation: str, data: dict) -> dict:
        assert operation == "resolve_chat_hashes"
        assert data["hashes"] == [moved_chat_hash]
        return {"chats": [{"hashed_chat_id": moved_chat_hash,
                           "hashed_user_id": None, "hashed_team_id": "team-owner"}]}

    monkeypatch.setattr(ChatMessageArchiveService, "transaction", resolved)
    snapshot = await module.load_account_deletable_embed_rows(
        directus_service=directus, user_id_hash="owner",
    )
    assert snapshot.embeds == ()
    assert snapshot.versions == ()


# contract-test: direct surface=rest_api assertions=storage.deletion.global-authoritative
@pytest.mark.anyio
async def test_account_deletion_without_cold_archives_skips_empty_parts_filter() -> None:
    directus = _Directus()
    directus.rows["cold_archive_manifests"] = []
    directus.rows["cold_archive_parts"] = []
    deleted = await _module().delete_account_storage_reference_rows(
        directus_service=directus, user_id="user-1", user_id_hash="hash-1",
    )
    assert deleted["cold_archive_parts"] == 0
    assert not any(collection == "cold_archive_parts" for collection, _ in directus.queries)
    assert deleted["account_export_parts"] == 1
    assert deleted["upload_files"] == 1
