"""Regional Account Export storage contract tests.

Purpose: prove TASK-7 persistent, bounded, hot/cold Account Export behavior.
Architecture: docs/specs/regional-cold-storage-lifecycle/spec.yml.
Security: Team exports must recheck current membership before status or parts.
Privacy: persisted job state and part manifests must not contain raw secrets.
Run: python3 -m pytest backend/tests/test_account_export_streaming_storage.py
"""

from __future__ import annotations

from collections import defaultdict
import base64
import gzip
import hashlib
import json
from typing import Any

import pytest

from backend.core.api.app.services.account_export_service import (
    AccountExportAuthorizationError,
    AccountExportError,
    AccountExportNotFoundError,
    AccountExportService,
)
from backend.core.api.app.services.team_data_portability_service import TeamDataPortabilityError, TeamDataPortabilityService


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
        for key, value in params.items():
            if key.startswith("filter[") and key.endswith("][_eq]"):
                field = key.removeprefix("filter[").split("]", 1)[0]
                rows = [row for row in rows if row.get(field) == value]
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


class ArchiveBytes:
    environment = "development"
    region_clients = {"nbg1": object()}

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def get_replicated_file_stream(self, *, object_key: str, **_kwargs: Any):
        if object_key in self.objects:
            yield self.objects[object_key]

    async def get_file(self, _bucket: str, key: str, *, max_bytes: int | None = None) -> bytes | None:
        content = self.objects.get(key)
        if content is not None and max_bytes is not None and len(content) > max_bytes:
            return None
        return content


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


def _seed_new_archive_data(
    directus: PersistentDirectus, storage: ArchiveBytes, *, team_id: str | None = None,
) -> None:
    owner = _hash("user-1")
    team_hash = _hash(team_id) if team_id else None
    directus.collections["chats"].append({
        "id": "chat-archived", "hashed_user_id": owner, "hashed_team_id": team_hash,
        "archived_message_count": 1, "encrypted_title": "cipher-title", "encrypted_chat_key": "secret-key-wrapper",
    })
    record = {"id": "message-archived", "chat_id": "chat-archived", "client_message_id": "m-archived",
              "created_at": 1, "encrypted_content": "cipher-archived"}
    page_content = gzip.compress(json.dumps({"format_version": 2, "chat_id": "chat-archived", "records": [record]}).encode())
    storage.objects["message-pages/page.json.gz"] = page_content
    directus.collections["chat_message_archive_pages"].append({
        "id": "page-1", "chat_id": "chat-archived", "page_number": 1,
        "hashed_user_id": owner, "published": True, "read_enabled": True, "pruned": True,
        "object_key": "message-pages/page.json.gz", "checksum": hashlib.sha256(page_content).hexdigest(),
        "size_bytes": len(page_content), "verified_regions": ["nbg1"], "message_count": 1,
        "message_ids": ["m-archived"], "first_timestamp": 1, "first_message_id": "m-archived",
    })
    directus.collections["embeds"].append({
        "id": "embed-row-1", "embed_id": "embed-1", "hashed_chat_id": _hash("chat-archived"),
        "hashed_user_id": owner,
    })
    envelope = {"version_number": 1, "encrypted_snapshot": "cipher-version", "encrypted_patch": None}
    version_content = json.dumps(envelope).encode()
    storage.objects["embed-versions/version.json"] = version_content
    directus.collections["embed_diffs"].append({
        "id": "diff-1", "embed_id": "embed-1", "hashed_user_id": owner, "version_number": 1,
        "encrypted_snapshot": None, "encrypted_patch": None, "archive_object_key": "embed-versions/version.json",
        "archive_checksum": hashlib.sha256(version_content).hexdigest(), "archive_regions": ["nbg1"],
    })
    if not team_id:
        sealed = b"cipher-sealed-output"
        storage.objects["chat-recovery/output.json"] = sealed
        directus.collections["chat_recovery_outputs"].append({
            "id": "output-1", "hashed_user_id": owner, "target_chat_id": "chat-archived",
            "state": "PENDING", "deleted_at": None, "payload_storage": "s3",
            "payload_s3_key": "chat-recovery/output.json", "payload_size_bytes": len(sealed),
            "sealed_payload_digest": hashlib.sha256(sealed).hexdigest(), "payload_verified_regions": ["nbg1"],
        })


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
    storage: ArchiveBytes | None = None,
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
        object_key = f"private/{archive_id}/part-{index + 1:05d}.json.gz"
        content = gzip.compress(json.dumps({"records": {"messages": [{"encrypted_content": f"cipher-cold-{index}"}]}}).encode())
        if storage is not None:
            storage.objects[object_key] = content
        directus.collections["cold_archive_parts"].append(
            {
                "id": f"part-{archive_id}-{index}",
                "archive_id": archive_id,
                "part_id": f"part-{index + 1:05d}",
                "part_number": index + 1,
                "generation": 4,
                "logical_bucket": "cold_archives",
                "object_key": object_key,
                "checksum": hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content),
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
    storage = ArchiveBytes()
    _seed_personal_chats(directus, count=1)
    _seed_cold_archive(directus, resource_type="chat", part_count=2, storage=storage)

    service = AccountExportService(directus_service=directus, s3_service=storage, part_item_limit=10)
    job = await service.start_export(user_id="user-1", domains=["chats"])
    manifest = await service.get_manifest(user_id="user-1", export_id=job["export_id"])
    chunks = await service.list_chunks(user_id="user-1", export_id=job["export_id"])
    serialized_chunks = repr(chunks)

    assert manifest["domains"]["chats"]["count"] == 2
    assert any(chunk["payload"].get("cold_archives") for chunk in chunks)
    archived_chunks = [chunk for chunk in chunks if chunk["payload"].get("cold_archives")]
    assert len(archived_chunks) == 2
    assert [chunk["payload"]["cold_archives"][0]["parts"][0]["part_number"] for chunk in archived_chunks] == [1, 2]
    for chunk in archived_chunks:
        parts = chunk["payload"]["cold_archives"][0]["parts"]
        assert len(parts) == 1
        decoded = gzip.decompress(base64.b64decode(parts[0]["ciphertext"]))
        assert "cipher-cold" in decoded.decode()
    assert job["failures"] == []
    assert "private/" not in serialized_chunks
    assert "object_key" not in serialized_chunks


# contract-test: direct surface=rest_api assertions=storage.export.persisted-bounded-complete,storage.privacy.ciphertext-boundary
@pytest.mark.asyncio
async def test_export_filters_apply_to_task_archives_and_cold_archive_refs() -> None:
    directus = PersistentDirectus()
    storage = ArchiveBytes()
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
        storage=storage,
        resource_id="cold-task-old",
        archived_at="2025-12-31T00:00:00Z",
    )
    _seed_cold_archive(
        directus,
        resource_type="task",
        archive_id="cold-new",
        storage=storage,
        resource_id="cold-task-new",
        archived_at="2026-02-01T00:00:00Z",
    )

    service = AccountExportService(directus_service=directus, s3_service=storage)
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
    storage = ArchiveBytes()
    _seed_cold_archive(directus, resource_type="chat", part_count=2, persisted_parts=1, storage=storage)

    service = AccountExportService(directus_service=directus, s3_service=storage)
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
    storage = ArchiveBytes()
    directus.team.roles[("team-1", "user-1")] = "member"
    directus.collections["projects"].append(
        {"id": "project-hot", "project_id": "project-hot", "hashed_team_id": _hash("team-1")}
    )
    _seed_cold_archive(directus, resource_type="project", owner_id=None, team_id="team-1", storage=storage)

    service = AccountExportService(directus_service=directus, s3_service=storage)
    job = await service.start_export(user_id="user-1", team_id="team-1", domains=["projects"])
    chunks = await service.list_chunks(user_id="user-1", team_id="team-1", export_id=job["export_id"])

    assert chunks
    assert job["failures"] == []
    assert any(chunk["payload"].get("cold_archives") for chunk in chunks)
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


# contract-test: direct surface=rest_api assertions=storage.export.persisted-bounded-complete,storage.privacy.ciphertext-boundary
@pytest.mark.asyncio
async def test_export_includes_verified_message_version_and_pending_sealed_ciphertext() -> None:
    directus = PersistentDirectus(forbid_unbounded_reads=True)
    storage = ArchiveBytes()
    _seed_new_archive_data(directus, storage)
    service = AccountExportService(directus_service=directus, s3_service=storage)

    job = await service.start_export(user_id="user-1", domains=["chats", "embeds"])
    chunks = await service.list_chunks(user_id="user-1", export_id=job["export_id"])
    by_source = {chunk["payload"]["source"]: chunk["payload"] for chunk in chunks}

    assert by_source["chat_message_archive_pages"]["items"][0]["messages"][0]["encrypted_content"] == "cipher-archived"
    assert by_source["chats+messages+embeds"]["items"][0]["encrypted_title"] == "cipher-title"
    assert "encrypted_chat_key" not in repr(by_source["chats+messages+embeds"])
    assert by_source["embed_diffs"]["items"][0]["encrypted_snapshot"] == "cipher-version"
    assert by_source["chat_recovery_outputs"]["items"][0]["sealed_payload"] == "cipher-sealed-output"
    assert "object_key" not in repr(by_source["chat_message_archive_pages"])
    assert "payload_s3_key" not in repr(by_source["chat_recovery_outputs"])
    assert job["failures"] == []


# contract-test: direct surface=rest_api assertions=storage.export.persisted-bounded-complete,storage.integrity.observable-reconcilable
@pytest.mark.asyncio
async def test_corrupt_or_unpublished_pruned_page_marks_export_partial() -> None:
    directus = PersistentDirectus()
    storage = ArchiveBytes()
    _seed_new_archive_data(directus, storage)
    page = directus.collections["chat_message_archive_pages"][0]
    page["checksum"] = "0" * 64
    service = AccountExportService(directus_service=directus, s3_service=storage)

    job = await service.start_export(user_id="user-1", domains=["chats"])

    assert job["status"] == "partial"
    assert any(failure["reason"] == "archive_page_integrity_failed" for failure in job["failures"])
    page["published"] = False
    second = await service.start_export(user_id="user-1", domains=["chats"])
    assert any(failure["reason"] == "pruned_archive_page_unreadable" for failure in second["failures"])


# contract-test: direct surface=rest_api assertions=storage.export.persisted-bounded-complete,storage.background.saved-output-retention
@pytest.mark.asyncio
async def test_missing_version_and_sealed_output_cannot_complete_export() -> None:
    directus = PersistentDirectus()
    storage = ArchiveBytes()
    _seed_new_archive_data(directus, storage)
    storage.objects.pop("embed-versions/version.json")
    storage.objects.pop("chat-recovery/output.json")
    service = AccountExportService(directus_service=directus, s3_service=storage)

    job = await service.start_export(user_id="user-1", domains=["chats", "embeds"])
    completed = await service.mark_complete(user_id="user-1", export_id=job["export_id"])

    assert completed["status"] == "partial"
    assert {failure["reason"] for failure in completed["failures"]} == {
        "version_archive_integrity_failed", "sealed_recovery_integrity_failed",
    }
    assert directus.updated_users == []


# contract-test: direct surface=rest_api assertions=storage.export.persisted-bounded-complete,storage.cold.shared-team-authorized
@pytest.mark.asyncio
async def test_team_portability_exports_only_its_verified_archive_ciphertext() -> None:
    directus = PersistentDirectus(forbid_unbounded_reads=True)
    directus.team.roles[("team-1", "user-1")] = "owner"
    storage = ArchiveBytes()
    _seed_new_archive_data(directus, storage, team_id="team-1")
    directus.collections["chats"].append({
        "id": "other-team-chat", "hashed_team_id": _hash("team-2"), "hashed_user_id": _hash("user-2"),
    })

    artifact = (await TeamDataPortabilityService(directus, s3_service=storage).export_team_data(
        "team-1", "user-1",
    ))["artifact"]

    assert [row["id"] for row in artifact["collections"]["chats"]] == ["chat-archived"]
    assert artifact["collections"]["embeds"][0]["embed_id"] == "embed-1"
    assert artifact["collections"]["chat_message_archive_pages"][0]["messages"][0]["encrypted_content"] == "cipher-archived"
    assert artifact["collections"]["embed_diffs"][0]["encrypted_snapshot"] == "cipher-version"
    personal = await AccountExportService(directus_service=directus, s3_service=storage).start_export(
        user_id="user-1", domains=["embeds"],
    )
    personal_chunks = await AccountExportService(directus_service=directus, s3_service=storage).list_chunks(
        user_id="user-1", export_id=personal["export_id"],
    )
    assert all(not chunk["payload"].get("items") for chunk in personal_chunks)
    storage.objects.pop("message-pages/page.json.gz")
    with pytest.raises(TeamDataPortabilityError, match="archive is incomplete"):
        await TeamDataPortabilityService(directus, s3_service=storage).export_team_data("team-1", "user-1")


# contract-test: direct surface=rest_api assertions=storage.export.persisted-bounded-complete,storage.cold.shared-team-authorized
@pytest.mark.asyncio
async def test_personal_cold_export_excludes_team_archive_retaining_creator_hash() -> None:
    directus = PersistentDirectus(forbid_unbounded_reads=True)
    storage = ArchiveBytes()
    _seed_cold_archive(directus, resource_type="chat", storage=storage, archive_id="personal-cold")
    _seed_cold_archive(directus, resource_type="chat", storage=storage, team_id="team-1", archive_id="team-cold")
    service = AccountExportService(directus_service=directus, s3_service=storage)
    job = await service.start_export(user_id="user-1", domains=["chats"])
    chunks = await service.list_chunks(user_id="user-1", export_id=job["export_id"])
    archives = [archive for chunk in chunks for archive in chunk["payload"].get("cold_archives", [])]
    assert [archive["archive_id"] for archive in archives] == ["personal-cold"]
    assert job["failures"] == []


# contract-test: direct surface=rest_api assertions=storage.export.persisted-bounded-complete,storage.integrity.observable-reconcilable
@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["missing_storage", "checksum", "oversized", "truncated", "no_verified_region"])
async def test_personal_cold_export_blocks_completion_for_unreadable_ciphertext(failure) -> None:
    directus = PersistentDirectus(forbid_unbounded_reads=True)
    storage = ArchiveBytes()
    _seed_cold_archive(directus, resource_type="chat", storage=storage)
    part = directus.collections["cold_archive_parts"][0]
    if failure == "checksum":
        part["checksum"] = "0" * 64
    elif failure == "oversized":
        part["size_bytes"] = 4 * 1024 * 1024 + 1
    elif failure == "truncated":
        storage.objects[part["object_key"]] = b"truncated"
    elif failure == "no_verified_region":
        part["regional_states"] = {"nbg1": "pending"}
    service = AccountExportService(directus_service=directus, s3_service=None if failure == "missing_storage" else storage)
    job = await service.start_export(user_id="user-1", domains=["chats"])
    completed = await service.mark_complete(user_id="user-1", export_id=job["export_id"])
    assert completed["status"] == "partial"
    assert completed["failures"] == [{"domain": "chats", "item_id": "cold-chat-user-1", "reason": "cold_archive_integrity_failed"}]
    assert directus.updated_users == []
