"""Regional Account Export storage contract tests.

Purpose: prove TASK-7 persistent, bounded, hot/cold Account Export behavior.
Architecture: docs/specs/regional-cold-storage-lifecycle/spec.yml.
Security: Team exports must recheck current membership before status or parts.
Privacy: persisted job state and part manifests must not contain raw secrets.
Run: python3 -m pytest backend/tests/test_account_export_streaming_storage.py
"""

from __future__ import annotations

from collections import defaultdict
import hashlib
from typing import Any

import pytest

from backend.core.api.app.services.account_export_service import (
    AccountExportAuthorizationError,
    AccountExportError,
    AccountExportNotFoundError,
    AccountExportService,
)


class TeamService:
    def __init__(self) -> None:
        self.roles: dict[tuple[str, str], str | None] = {}
        self.calls: list[tuple[str, str, tuple[str, ...]]] = []

    async def require_team_role(self, team_id: str, user_id: str, allowed_roles: set[str]) -> None:
        self.calls.append((team_id, user_id, tuple(sorted(allowed_roles))))
        if self.roles.get((team_id, user_id)) not in allowed_roles:
            raise RuntimeError("TEAM_PERMISSION_DENIED")


class PersistentDirectus:
    def __init__(self, *, forbid_unbounded_reads: bool = False) -> None:
        self.collections: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
        self.forbid_unbounded_reads = forbid_unbounded_reads
        self.team = TeamService()
        self.updated_users: list[tuple[str, dict[str, Any]]] = []

    async def get_items(self, collection: str, params: dict[str, Any] | None = None, **_kwargs: Any) -> list[dict[str, Any]]:
        params = params or {}
        if self.forbid_unbounded_reads and params.get("limit") == -1:
            raise AssertionError(f"{collection} used unbounded Directus export read")
        rows = [dict(row) for row in self.collections.get(collection, [])]
        item_filter = params.get("filter") or {}
        rows = [row for row in rows if _matches_filter(row, item_filter)]
        sort = params.get("sort")
        if sort:
            rows = _sort_rows(rows, str(sort))
        offset = int(params.get("offset") or 0)
        limit = int(params.get("limit") if params.get("limit") is not None else len(rows))
        if limit >= 0:
            rows = rows[offset : offset + limit]
        fields = params.get("fields")
        if fields and fields != "*":
            selected = [field.strip() for field in str(fields).split(",") if field.strip()]
            rows = [{field: row.get(field) for field in selected} for row in rows]
        return rows

    async def create_item(self, collection: str, payload: dict[str, Any], **_kwargs: Any) -> tuple[bool, dict[str, Any]]:
        row = dict(payload)
        row.setdefault("id", f"{collection}-{len(self.collections[collection]) + 1}")
        self.collections[collection].append(row)
        return True, dict(row)

    async def update_item(self, collection: str, item_id: str, payload: dict[str, Any], **_kwargs: Any) -> dict[str, Any] | None:
        for row in self.collections.get(collection, []):
            if str(row.get("id")) == str(item_id):
                row.update(payload)
                return dict(row)
        return None

    async def delete_items(self, collection: str, filter_dict: dict[str, Any], **_kwargs: Any) -> int:
        before = len(self.collections.get(collection, []))
        self.collections[collection] = [row for row in self.collections.get(collection, []) if not _matches_filter(row, filter_dict)]
        return before - len(self.collections[collection])

    async def get_user(self, user_id: str) -> dict[str, Any]:
        return {"id": user_id, "email": "person@example.invalid", "last_export_at": None}

    async def update_user(self, user_id: str, payload: dict[str, Any]) -> None:
        self.updated_users.append((user_id, payload))


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _matches_filter(row: dict[str, Any], item_filter: dict[str, Any]) -> bool:
    for field, condition in item_filter.items():
        if field == "_and":
            return all(_matches_filter(row, child) for child in condition)
        if field == "_or":
            return any(_matches_filter(row, child) for child in condition)
        if isinstance(condition, dict) and "_eq" in condition and row.get(field) != condition["_eq"]:
            return False
        if isinstance(condition, dict) and "_in" in condition and row.get(field) not in condition["_in"]:
            return False
        if isinstance(condition, dict) and "_lte" in condition and str(row.get(field) or "") > str(condition["_lte"]):
            return False
        if isinstance(condition, dict) and "_gte" in condition and str(row.get(field) or "") < str(condition["_gte"]):
            return False
        if isinstance(condition, dict) and condition.get("_null") is True and row.get(field) is not None:
            return False
    return True


def _sort_rows(rows: list[dict[str, Any]], sort: str) -> list[dict[str, Any]]:
    for field in reversed([part.strip() for part in sort.split(",") if part.strip()]):
        reverse = field.startswith("-")
        key = field[1:] if reverse else field
        rows = sorted(rows, key=lambda row: row.get(key) or 0, reverse=reverse)
    return rows


def _seed_personal_chats(directus: PersistentDirectus, *, count: int) -> None:
    for index in range(count):
        chat_id = f"chat-{index}"
        directus.collections["chats"].append(
            {"id": chat_id, "hashed_user_id": _hash("user-1"), "hashed_team_id": None, "updated_at": index}
        )
        directus.collections["messages"].append(
            {"id": f"message-{index}", "chat_id": chat_id, "client_message_id": f"msg-{index}"}
        )


class NonListReadDirectus(PersistentDirectus):
    async def get_items(self, collection: str, params: dict[str, Any] | None = None, **kwargs: Any) -> list[dict[str, Any]]:
        if collection == "chats":
            return {"errors": ["permission denied"]}  # type: ignore[return-value]
        return await super().get_items(collection, params, **kwargs)


class FailingPartWriteDirectus(PersistentDirectus):
    async def create_item(self, collection: str, payload: dict[str, Any], **kwargs: Any) -> tuple[bool, dict[str, Any]]:
        if collection == "account_export_parts":
            return False, {}
        return await super().create_item(collection, payload, **kwargs)


class FailingDeleteDirectus(PersistentDirectus):
    async def delete_items(self, collection: str, filter_dict: dict[str, Any], **kwargs: Any) -> int:
        if collection == "account_export_parts":
            return 0
        return await super().delete_items(collection, filter_dict, **kwargs)


def _seed_cold_archive(
    directus: PersistentDirectus,
    *,
    resource_type: str,
    owner_id: str | None = "user-1",
    team_id: str | None = None,
    part_count: int = 1,
    persisted_parts: int | None = None,
    archive_id: str | None = None,
    resource_id: str | None = None,
    archived_at: str | int = 100,
) -> None:
    archive_id = archive_id or f"cold-{resource_type}-{team_id or owner_id}"
    directus.collections["cold_archive_manifests"].append(
        {
            "id": f"manifest-{archive_id}",
            "archive_id": archive_id,
            "resource_type": resource_type,
            "resource_id": resource_id or f"{resource_type}-old",
            "hashed_user_id": _hash(owner_id) if owner_id else None,
            "hashed_team_id": _hash(team_id) if team_id else None,
            "encrypted_listing_metadata": {"ciphertext": "listing"},
            "active_generation": 4,
            "part_count": part_count,
            "state": "cold",
            "archived_at": archived_at,
        }
    )
    for index in range(persisted_parts if persisted_parts is not None else part_count):
        directus.collections["cold_archive_parts"].append(
            {
                "id": f"part-{archive_id}-{index}",
                "archive_id": archive_id,
                "part_id": f"part-{index + 1:05d}",
                "part_number": index + 1,
                "generation": 4,
                "logical_bucket": "cold_archives",
                "object_key": f"private/{archive_id}/part-{index + 1:05d}.json.gz",
                "checksum": f"checksum-{index}",
                "size_bytes": 128,
                "regional_states": {"nbg1": "verified"},
                "created_at": 100,
            }
        )


# contract-test: direct surface=rest_api assertions=storage.export.persisted-bounded-complete,storage.privacy.ciphertext-boundary
@pytest.mark.asyncio
async def test_export_job_and_bounded_parts_persist_across_service_restart() -> None:
    directus = PersistentDirectus(forbid_unbounded_reads=True)
    _seed_personal_chats(directus, count=5)

    first_service = AccountExportService(directus_service=directus, part_item_limit=2)
    job = await first_service.start_export(user_id="user-1", domains=["chats"])

    assert directus.collections["account_export_jobs"][0]["export_id"] == job["export_id"]
    assert len(directus.collections["account_export_parts"]) >= 3

    restarted_service = AccountExportService(directus_service=directus, part_item_limit=2)
    resumed = await restarted_service.get_job(user_id="user-1", export_id=job["export_id"])
    chunks = await restarted_service.list_chunks(user_id="user-1", export_id=job["export_id"])

    assert resumed["export_id"] == job["export_id"]
    assert resumed["progress"]["total_parts"] == len(chunks)
    assert all(len(chunk["payload"].get("items", [])) <= 2 for chunk in chunks)
    assert "private/" not in repr(directus.collections["account_export_jobs"])


# contract-test: direct surface=rest_api assertions=storage.export.persisted-bounded-complete
@pytest.mark.asyncio
async def test_export_filters_are_applied_to_persisted_parts_and_manifest() -> None:
    directus = PersistentDirectus()
    for chat_id, updated_at in (
        ("old-chat", "2025-12-31T23:59:59Z"),
        ("matching-chat", "2026-02-15T12:00:00Z"),
        ("future-chat", "2026-04-01T00:00:00Z"),
    ):
        directus.collections["chats"].append(
            {"id": chat_id, "hashed_user_id": _hash("user-1"), "hashed_team_id": None, "updated_at": updated_at}
        )
        directus.collections["messages"].append({"id": f"message-{chat_id}", "chat_id": chat_id, "client_message_id": chat_id})

    service = AccountExportService(directus_service=directus)
    job = await service.start_export(
        user_id="user-1",
        domains=["chats"],
        filters={"chats": {"from": "2026-01-01T00:00:00Z", "to": "2026-03-31T23:59:59Z"}},
    )
    manifest = await service.get_manifest(user_id="user-1", export_id=job["export_id"])
    chunks = await service.list_chunks(user_id="user-1", export_id=job["export_id"])

    exported_chat_ids = [item["id"] for chunk in chunks for item in chunk["payload"].get("items", [])]
    exported_message_ids = [
        message["client_message_id"]
        for chunk in chunks
        for item in chunk["payload"].get("items", [])
        for message in item.get("messages", [])
    ]

    assert manifest["filters"] == {"chats": {"from": "2026-01-01T00:00:00Z", "to": "2026-03-31T23:59:59Z"}}
    assert manifest["domains"]["chats"]["count"] == 1
    assert exported_chat_ids == ["matching-chat"]
    assert exported_message_ids == ["matching-chat"]


# contract-test: direct surface=rest_api assertions=storage.export.persisted-bounded-complete
@pytest.mark.asyncio
async def test_directus_read_failures_do_not_become_empty_complete_exports() -> None:
    service = AccountExportService(directus_service=NonListReadDirectus())

    with pytest.raises(AccountExportError, match="Directus export read failed for chats"):
        await service.start_export(user_id="user-1", domains=["chats"])


# contract-test: direct surface=rest_api assertions=storage.export.persisted-bounded-complete
@pytest.mark.asyncio
async def test_part_write_failure_marks_persisted_job_failed_before_raising() -> None:
    directus = FailingPartWriteDirectus()
    _seed_personal_chats(directus, count=1)
    service = AccountExportService(directus_service=directus)

    with pytest.raises(AccountExportError, match="Failed to persist export part"):
        await service.start_export(user_id="user-1", domains=["chats"])

    persisted_job = directus.collections["account_export_jobs"][0]
    assert persisted_job["status"] == "failed"
    assert persisted_job["failures"] == [
        {"domain": "export", "item_id": persisted_job["export_id"], "reason": "persist_part_failed"}
    ]


# contract-test: direct surface=rest_api assertions=storage.export.persisted-bounded-complete,storage.privacy.ciphertext-boundary
@pytest.mark.asyncio
async def test_expired_export_purges_persisted_job_and_parts_before_download() -> None:
    directus = PersistentDirectus()
    _seed_personal_chats(directus, count=1)
    service = AccountExportService(directus_service=directus)
    job = await service.start_export(user_id="user-1", domains=["chats"])
    export_id = job["export_id"]
    directus.collections["account_export_jobs"][0]["expires_at"] = "2020-01-01T00:00:00+00:00"

    restarted_service = AccountExportService(directus_service=directus)

    with pytest.raises(AccountExportNotFoundError, match="Export job expired"):
        await restarted_service.get_chunk(user_id="user-1", export_id=export_id, chunk_id="chats-0001")

    assert directus.collections["account_export_jobs"] == []
    assert directus.collections["account_export_parts"] == []


# contract-test: supporting surface=rest_api assertions=storage.export.persisted-bounded-complete,storage.privacy.ciphertext-boundary
@pytest.mark.asyncio
async def test_idle_expired_export_cleanup_purges_persisted_job_and_parts() -> None:
    directus = PersistentDirectus()
    _seed_personal_chats(directus, count=1)
    await AccountExportService(directus_service=directus).start_export(user_id="user-1", domains=["chats"])
    directus.collections["account_export_jobs"][0]["expires_at"] = "2020-01-01T00:00:00+00:00"

    cleanup = await AccountExportService(directus_service=directus).purge_expired_exports()

    assert cleanup == {"expired_jobs": 1}
    assert directus.collections["account_export_jobs"] == []
    assert directus.collections["account_export_parts"] == []


# contract-test: direct surface=rest_api assertions=storage.export.persisted-bounded-complete
@pytest.mark.asyncio
async def test_expired_export_purge_failure_remains_visible_and_retryable() -> None:
    directus = FailingDeleteDirectus()
    _seed_personal_chats(directus, count=1)
    job = await AccountExportService(directus_service=directus).start_export(user_id="user-1", domains=["chats"])
    directus.collections["account_export_jobs"][0]["expires_at"] = "2020-01-01T00:00:00+00:00"

    with pytest.raises(AccountExportError, match="Failed to purge expired export rows"):
        await AccountExportService(directus_service=directus).purge_expired_exports()

    assert directus.collections["account_export_jobs"][0]["export_id"] == job["export_id"]
    assert directus.collections["account_export_parts"]


# contract-test: direct surface=rest_api assertions=storage.export.persisted-bounded-complete,storage.cold.atomic-eligible-graphs,storage.privacy.ciphertext-boundary
@pytest.mark.asyncio
async def test_export_merges_hot_and_cold_sources_without_exposing_object_keys() -> None:
    directus = PersistentDirectus()
    _seed_personal_chats(directus, count=1)
    _seed_cold_archive(directus, resource_type="chat", part_count=2)

    service = AccountExportService(directus_service=directus, part_item_limit=10)
    job = await service.start_export(user_id="user-1", domains=["chats"])
    manifest = await service.get_manifest(user_id="user-1", export_id=job["export_id"])
    chunks = await service.list_chunks(user_id="user-1", export_id=job["export_id"])
    serialized_chunks = repr(chunks)

    assert manifest["domains"]["chats"]["count"] == 2
    assert any(chunk["payload"].get("cold_archives") for chunk in chunks)
    assert "private/" not in serialized_chunks
    assert "object_key" not in serialized_chunks


# contract-test: direct surface=rest_api assertions=storage.export.persisted-bounded-complete,storage.privacy.ciphertext-boundary
@pytest.mark.asyncio
async def test_export_filters_apply_to_task_archives_and_cold_archive_refs() -> None:
    directus = PersistentDirectus()
    directus.collections["user_tasks"].append(
        {
            "id": "task-hot",
            "task_id": "task-hot",
            "hashed_user_id": _hash("user-1"),
            "hashed_team_id": None,
            "updated_at": "2026-02-01T00:00:00Z",
        }
    )
    directus.collections["user_task_archives"].extend(
        [
            {
                "id": "archive-old",
                "hashed_user_id": _hash("user-1"),
                "archive_s3_key": "task-archives/old.gz",
                "task_count": 1,
                "archived_at": "2025-12-31T00:00:00Z",
            },
            {
                "id": "archive-new",
                "hashed_user_id": _hash("user-1"),
                "archive_s3_key": "task-archives/new.gz",
                "task_count": 1,
                "archived_at": "2026-02-01T00:00:00Z",
            },
        ]
    )
    _seed_cold_archive(
        directus,
        resource_type="task",
        archive_id="cold-old",
        resource_id="cold-task-old",
        archived_at="2025-12-31T00:00:00Z",
    )
    _seed_cold_archive(
        directus,
        resource_type="task",
        archive_id="cold-new",
        resource_id="cold-task-new",
        archived_at="2026-02-01T00:00:00Z",
    )

    service = AccountExportService(directus_service=directus)
    job = await service.start_export(
        user_id="user-1",
        domains=["tasks"],
        filters={"tasks": {"from": "2026-01-01T00:00:00Z"}},
    )
    chunks = await service.list_chunks(user_id="user-1", export_id=job["export_id"])

    archive_keys = [archive["archive_s3_key"] for chunk in chunks for archive in chunk["payload"].get("archives", [])]
    cold_archive_ids = [archive["archive_id"] for chunk in chunks for archive in chunk["payload"].get("cold_archives", [])]

    assert archive_keys == ["task-archives/new.gz"]
    assert cold_archive_ids == ["cold-new"]


# contract-test: direct surface=rest_api assertions=storage.export.persisted-bounded-complete
@pytest.mark.asyncio
async def test_missing_required_cold_part_marks_export_partial_until_accepted() -> None:
    directus = PersistentDirectus()
    _seed_cold_archive(directus, resource_type="chat", part_count=2, persisted_parts=1)

    service = AccountExportService(directus_service=directus)
    job = await service.start_export(user_id="user-1", domains=["chats"])
    completed = await service.mark_complete(user_id="user-1", export_id=job["export_id"])

    assert job["status"] == "partial"
    assert completed["status"] == "partial"
    assert completed["failures"] == [
        {"domain": "chats", "item_id": "cold-chat-user-1", "reason": "missing_cold_archive_part"}
    ]
    assert directus.updated_users == []


# contract-test: direct surface=rest_api assertions=storage.export.persisted-bounded-complete,storage.cold.shared-team-authorized
@pytest.mark.asyncio
async def test_team_export_rechecks_authorization_on_resume_and_part_download() -> None:
    directus = PersistentDirectus()
    directus.team.roles[("team-1", "user-1")] = "member"
    directus.collections["projects"].append(
        {"id": "project-hot", "project_id": "project-hot", "hashed_team_id": _hash("team-1")}
    )
    _seed_cold_archive(directus, resource_type="project", owner_id=None, team_id="team-1")

    service = AccountExportService(directus_service=directus)
    job = await service.start_export(user_id="user-1", team_id="team-1", domains=["projects"])
    chunks = await service.list_chunks(user_id="user-1", team_id="team-1", export_id=job["export_id"])

    assert chunks
    assert len(directus.team.calls) >= 2

    directus.team.roles[("team-1", "user-1")] = None
    restarted_service = AccountExportService(directus_service=directus)

    with pytest.raises(AccountExportAuthorizationError):
        await restarted_service.get_job(user_id="user-1", team_id="team-1", export_id=job["export_id"])
    with pytest.raises(AccountExportAuthorizationError):
        await restarted_service.get_chunk(
            user_id="user-1",
            team_id="team-1",
            export_id=job["export_id"],
            chunk_id=chunks[0]["chunk_id"],
        )
