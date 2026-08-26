"""Encrypted cold archive orchestration for complete chat graphs.

The service persists immutable, checksummed archive parts in every configured
region before removing hot child rows. Manifests retain only ciphertext and safe
routing metadata; every list, read, and promotion rechecks current authority.
Spec: docs/specs/regional-cold-storage-lifecycle/spec.yml.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from backend.core.api.app.services.s3.config import get_bucket_name
from backend.shared.python_utils.object_storage_regions import resolve_regional_bucket_name


COLD_ARCHIVE_BUCKET_KEY = "cold_archives"
DEFAULT_COLD_INACTIVITY_DAYS = 28
DEFAULT_ARCHIVE_PAGE_LIMIT = 20
MAX_ARCHIVE_PAGE_LIMIT = 100
MAX_ARCHIVE_PART_BYTES = 4 * 1024 * 1024
ARCHIVE_STREAM_CHUNK_BYTES = 1024 * 1024
COLD_ARCHIVE_SWEEP_LIMIT = 100
ARCHIVE_LEASE_SECONDS = 300
PROMOTION_LEASE_SECONDS = 300
ARCHIVE_COLLECTIONS_BY_CHAT_ID = (
    "messages",
    "drafts",
    "chat_compression_checkpoints",
    "code_run_outputs",
    "notebook_run_outputs",
    "message_highlights",
)
ARCHIVE_DELETE_ORDER = (
    "message_highlights",
    "notebook_run_outputs",
    "code_run_outputs",
    "chat_compression_checkpoints",
    "embed_keys",
    "embeds",
    "drafts",
    "messages",
    "chat_key_wrappers",
)
PUBLIC_MANIFEST_FIELDS = (
    "archive_id",
    "resource_type",
    "resource_id",
    "encrypted_listing_metadata",
    "active_generation",
    "archived_at",
)


class ColdArchiveError(RuntimeError):
    """Base error for visible cold archive failures."""


class ColdArchiveNotFoundError(ColdArchiveError):
    pass


class ColdArchiveAuthorizationError(ColdArchiveError):
    pass


class ColdArchiveConflictError(ColdArchiveError):
    pass


class ColdArchiveCursorError(ColdArchiveError):
    pass


def _hash_id(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def chat_is_archive_eligible(
    chat: dict[str, Any],
    *,
    now_timestamp: int,
    has_processing_task: bool,
    inactivity_days: int = DEFAULT_COLD_INACTIVITY_DAYS,
) -> bool:
    """Return whether one complete chat graph may move out of hot storage."""
    if (
        has_processing_task
        or chat.get("storage_state") not in {None, "hot"}
        or chat.get("cold_archive_id")
        or chat.get("pinned")
        or chat.get("is_shared")
        or chat.get("share_with_community")
    ):
        return False
    updated_at = int(chat.get("last_edited_overall_timestamp") or chat.get("updated_at") or 0)
    return updated_at <= now_timestamp - max(1, int(inactivity_days)) * 86_400


def encode_archive_cursor(*, sort_timestamp: int, archive_id: str, scope_hash: str) -> str:
    payload = json.dumps(
        {"timestamp": int(sort_timestamp), "archive_id": archive_id, "scope_hash": scope_hash},
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def decode_archive_cursor(cursor: str, *, expected_scope_hash: str) -> tuple[int, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode())
        timestamp = int(payload["timestamp"])
        archive_id = str(payload["archive_id"])
        scope_hash = str(payload["scope_hash"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ColdArchiveCursorError("INVALID_ARCHIVE_CURSOR") from exc
    if not archive_id or scope_hash != expected_scope_hash:
        raise ColdArchiveCursorError("INVALID_ARCHIVE_CURSOR")
    return timestamp, archive_id


def merge_archive_metadata_page(
    hot_items: list[dict[str, Any]],
    cold_items: list[dict[str, Any]],
    *,
    limit: int,
) -> dict[str, Any]:
    """Merge one bounded metadata window, preferring hot rows on duplicate IDs."""
    bounded_limit = max(1, min(int(limit), MAX_ARCHIVE_PAGE_LIMIT))
    by_resource: dict[str, dict[str, Any]] = {}
    for item in cold_items:
        resource_id = str(item.get("resource_id") or "")
        if resource_id:
            by_resource[resource_id] = item
    for item in hot_items:
        resource_id = str(item.get("resource_id") or item.get("id") or "")
        if resource_id:
            by_resource[resource_id] = {**item, "resource_id": resource_id}
    ordered = sorted(
        by_resource.values(),
        key=lambda item: (int(item.get("sort_timestamp") or 0), str(item.get("resource_id") or "")),
        reverse=True,
    )
    page = ordered[:bounded_limit]
    has_more = len(ordered) > bounded_limit
    next_cursor = None
    if has_more and page:
        last = page[-1]
        next_cursor = encode_archive_cursor(
            sort_timestamp=int(last.get("sort_timestamp") or 0),
            archive_id=str(last.get("archive_id") or last.get("resource_id")),
            scope_hash="",
        )
    return {"items": page, "next_cursor": next_cursor, "complete": not has_more}


async def dispatch_due_cold_chat_archives(
    *,
    directus_service: Any,
    cache_service: Any,
    dispatch: Any,
    now_timestamp: int | None = None,
) -> int:
    """Dispatch a bounded batch of inactive root chats for guarded archival."""
    now = int(now_timestamp or time.time())
    cutoff = now - DEFAULT_COLD_INACTIVITY_DAYS * 86_400
    rows = await directus_service.get_items(
        "chats",
        params={
            "filter": {
                "_and": [
                    {"is_sub_chat": {"_neq": True}},
                    {"pinned": {"_neq": True}},
                    {"is_shared": {"_neq": True}},
                    {"share_with_community": {"_neq": True}},
                    {"storage_state": {"_neq": "cold"}},
                    {
                        "_or": [
                            {"last_edited_overall_timestamp": {"_lte": cutoff}},
                            {"updated_at": {"_lte": cutoff}},
                        ]
                    },
                ]
            },
            "fields": "id,is_sub_chat,pinned,is_shared,share_with_community,storage_state,cold_archive_id,archive_started_at,last_edited_overall_timestamp,updated_at",
            "sort": "updated_at,id",
            "limit": COLD_ARCHIVE_SWEEP_LIMIT,
        },
        no_cache=True,
        admin_required=True,
    )
    dispatched = 0
    for chat in rows if isinstance(rows, list) else []:
        chat_id = str(chat.get("id") or "")
        if not chat_id or chat.get("is_sub_chat") or chat.get("parent_id"):
            continue
        has_processing_task = bool(await cache_service.get_active_ai_task(chat_id))
        if chat.get("storage_state") == "archiving":
            if not has_processing_task and int(chat.get("archive_started_at") or 0) <= now - ARCHIVE_LEASE_SECONDS:
                dispatch(chat_id)
                dispatched += 1
            continue
        if not chat_is_archive_eligible(chat, now_timestamp=now, has_processing_task=has_processing_task):
            continue
        dispatch(chat_id)
        dispatched += 1
    return dispatched


class ColdArchiveService:
    def __init__(self, *, directus_service: Any, s3_service: Any, archive_reader: Any | None = None):
        self.directus_service = directus_service
        self.s3_service = s3_service
        self.archive_reader = archive_reader

    async def archive_chat(
        self,
        chat_id: str,
        *,
        now_timestamp: int | None = None,
        has_processing_task: bool = False,
        processing_task_checker: Any | None = None,
    ) -> dict[str, Any]:
        now = int(now_timestamp or time.time())
        chat = await self._get_one("chats", {"id": {"_eq": chat_id}})
        if not chat:
            raise ColdArchiveNotFoundError("CHAT_NOT_FOUND")
        if chat.get("storage_state") == "archiving" and chat.get("cold_archive_id"):
            if int(chat.get("archive_started_at") or 0) > now - ARCHIVE_LEASE_SECONDS:
                raise ColdArchiveConflictError("CHAT_ARCHIVE_IN_PROGRESS")
            return await self._resume_chat_archive(chat, now=now)
        if not chat_is_archive_eligible(chat, now_timestamp=now, has_processing_task=has_processing_task):
            raise ColdArchiveConflictError("CHAT_NOT_ARCHIVE_ELIGIBLE")

        archive_id = str(uuid.uuid4())
        generation = 1
        archive_version = int(chat.get("archive_version") or 1)
        claimed = await self.directus_service.update_item_if_version(
            "chats",
            str(chat["id"]),
            {
                "storage_state": "archiving",
                "cold_archive_id": archive_id,
                "cold_generation": generation,
                "archive_started_at": now,
                "archive_version": archive_version + 1,
            },
            archive_version,
            version_field="archive_version",
            extra_filters={"storage_state": chat.get("storage_state") or "hot"},
            admin_required=True,
        )
        if not claimed:
            raise ColdArchiveConflictError("CHAT_ARCHIVE_CONFLICT")
        graph = await self._collect_chat_graph({**chat, **claimed})
        if processing_task_checker is not None:
            for graph_chat in graph["chats"]:
                if await processing_task_checker(str(graph_chat["id"])):
                    await self._release_archive_claim(claimed, archive_version=archive_version + 1)
                    raise ColdArchiveConflictError("CHAT_NOT_ARCHIVE_ELIGIBLE")
        parts = self._build_parts(archive_id, generation, graph)
        regions = sorted(self.s3_service.region_clients)
        if not regions:
            raise ColdArchiveError("NO_CONFIGURED_STORAGE_REGION")

        part_rows: list[dict[str, Any]] = []
        for part_number, content in enumerate(parts, start=1):
            object_key = (
                f"cold-archives/chat/{_hash_id(chat_id)}/{archive_id}/"
                f"g{generation}/part-{part_number:05d}.json.gz"
            )
            checksum = hashlib.sha256(content).hexdigest()
            part_row = {
                "archive_id": archive_id,
                "part_id": f"part-{part_number:05d}",
                "part_number": part_number,
                "generation": generation,
                "logical_bucket": COLD_ARCHIVE_BUCKET_KEY,
                "object_key": object_key,
                "checksum": checksum,
                "size_bytes": len(content),
                "regional_states": {region: "pending" for region in regions},
                "created_at": now,
            }
            success, persisted_part = await self.directus_service.create_item(
                "cold_archive_parts",
                part_row,
                admin_required=True,
            )
            if not success or not isinstance(persisted_part, dict):
                raise ColdArchiveError("ARCHIVE_PART_MANIFEST_PERSIST_FAILED")
            for region in regions:
                await self.s3_service.upload_file(
                    bucket_key=COLD_ARCHIVE_BUCKET_KEY,
                    file_key=object_key,
                    content=content,
                    content_type="application/gzip",
                    metadata={"archive-id": archive_id, "generation": str(generation), "part": str(part_number)},
                    region=region,
                )
                verified = await self.s3_service.verify_regional_object(
                    bucket_key=COLD_ARCHIVE_BUCKET_KEY,
                    object_key=object_key,
                    region=region,
                    checksum=checksum,
                )
                if not verified:
                    raise ColdArchiveError("ARCHIVE_REGION_CHECKSUM_MISMATCH")
            part_row["regional_states"] = {region: "verified" for region in regions}
            if not await self.directus_service.update_item(
                "cold_archive_parts",
                str(persisted_part["id"]),
                {"regional_states": part_row["regional_states"]},
                admin_required=True,
            ):
                raise ColdArchiveError("ARCHIVE_PART_MANIFEST_PERSIST_FAILED")
            part_rows.append(part_row)

        current_graph = await self._collect_chat_graph({**chat, **claimed})
        if self._graph_checksum(current_graph) != self._graph_checksum(graph):
            await self._cleanup_orphan_archive_parts(archive_id, now=now)
            await self._release_archive_claim(claimed, archive_version=archive_version + 1)
            raise ColdArchiveConflictError("CHAT_GRAPH_CHANGED_DURING_ARCHIVE")

        manifest_data = {
            "archive_id": archive_id,
            "resource_type": "chat",
            "resource_id": chat_id,
            "hashed_resource_id": _hash_id(chat_id),
            "hashed_user_id": chat.get("hashed_user_id"),
            "hashed_team_id": chat.get("hashed_team_id"),
            "encrypted_listing_metadata": self._encrypted_listing_metadata(chat),
            "active_generation": generation,
            "graph_checksum": self._graph_checksum(graph),
            "part_count": len(part_rows),
            "file_references": self._file_references(graph),
            "state": "preparing",
            "version": 1,
            "archived_at": now,
            "updated_at": now,
        }
        success, manifest = await self.directus_service.create_item(
            "cold_archive_manifests",
            manifest_data,
            admin_required=True,
        )
        if not success or not isinstance(manifest, dict):
            raise ColdArchiveError("ARCHIVE_MANIFEST_PERSIST_FAILED")

        committed = await self.directus_service.update_item_if_version(
            "cold_archive_manifests",
            str(manifest["id"]),
            {"state": "cold", "version": 2, "updated_at": now},
            1,
            admin_required=True,
        )
        if not committed:
            raise ColdArchiveError("ARCHIVE_MANIFEST_COMMIT_FAILED")

        await self._delete_hot_graph(graph)
        if not await self.directus_service.update_item_if_version(
            "chats",
            str(chat["id"]),
            {
                "storage_state": "cold",
                "archive_started_at": None,
                "archive_version": archive_version + 2,
            },
            archive_version + 1,
            version_field="archive_version",
            admin_required=True,
        ):
            raise ColdArchiveError("CHAT_COLD_INDEX_UPDATE_FAILED")
        return {**committed, "verified_regions": regions}

    async def _release_archive_claim(self, chat: dict[str, Any], *, archive_version: int) -> None:
        await self.directus_service.update_item_if_version(
            "chats",
            str(chat["id"]),
            {
                "storage_state": "hot",
                "cold_archive_id": None,
                "cold_generation": None,
                "archive_started_at": None,
                "archive_version": archive_version + 1,
            },
            archive_version,
            version_field="archive_version",
            extra_filters={"storage_state": "archiving"},
            admin_required=True,
        )

    async def _resume_chat_archive(self, chat: dict[str, Any], *, now: int) -> dict[str, Any]:
        archive_version = int(chat.get("archive_version") or 1)
        claimed = await self.directus_service.update_item_if_version(
            "chats",
            str(chat["id"]),
            {"archive_started_at": now, "archive_version": archive_version + 1},
            archive_version,
            version_field="archive_version",
            admin_required=True,
        )
        if not claimed:
            raise ColdArchiveConflictError("CHAT_ARCHIVE_CONFLICT")
        manifest = await self._get_one(
            "cold_archive_manifests",
            {"archive_id": {"_eq": chat["cold_archive_id"]}},
        )
        if not manifest:
            await self._cleanup_orphan_archive_parts(str(chat["cold_archive_id"]), now=now)
            await self.directus_service.update_item_if_version(
                "chats",
                str(chat["id"]),
                {
                    "storage_state": "hot",
                    "cold_archive_id": None,
                    "cold_generation": None,
                    "archive_started_at": None,
                    "archive_version": archive_version + 2,
                },
                archive_version + 1,
                version_field="archive_version",
                admin_required=True,
            )
            raise ColdArchiveError("ARCHIVE_MANIFEST_MISSING_RETRY_REQUIRED")
        if manifest.get("state") == "preparing":
            version = int(manifest.get("version") or 1)
            manifest = await self.directus_service.update_item_if_version(
                "cold_archive_manifests",
                str(manifest["id"]),
                {"state": "cold", "version": version + 1, "updated_at": now},
                version,
                admin_required=True,
            )
            if not manifest:
                raise ColdArchiveConflictError("CHAT_ARCHIVE_CONFLICT")
        graph = await self._load_archive_graph(manifest)
        await self._delete_hot_graph(graph)
        if not await self.directus_service.update_item_if_version(
            "chats",
            str(chat["id"]),
            {
                "storage_state": "cold",
                "archive_started_at": None,
                "archive_version": archive_version + 2,
            },
            archive_version + 1,
            version_field="archive_version",
            admin_required=True,
        ):
            raise ColdArchiveConflictError("CHAT_ARCHIVE_CONFLICT")
        return {**manifest, "verified_regions": sorted(self.s3_service.region_clients)}

    async def _cleanup_orphan_archive_parts(self, archive_id: str, *, now: int) -> None:
        parts = await self._get_all("cold_archive_parts", {"archive_id": {"_eq": archive_id}})
        if not parts:
            return
        from backend.core.api.app.services.storage_reference_service import (
            StorageReferenceInventory,
            persist_reference_safe_tombstones,
        )

        deleting = StorageReferenceInventory(
            references={
                (str(part["logical_bucket"]), str(part["object_key"]))
                for part in parts
            },
            ambiguous=[],
        )
        tombstones = await persist_reference_safe_tombstones(
            directus_service=self.directus_service,
            deleting=deleting,
            surviving=StorageReferenceInventory(references=set(), ambiguous=[]),
            regions=tuple(sorted(self.s3_service.region_clients)),
            now=datetime.fromtimestamp(now, tz=timezone.utc),
        )
        from backend.core.api.app.services.storage_reference_service import activate_storage_tombstones

        await activate_storage_tombstones(
            directus_service=self.directus_service,
            tombstones=tombstones,
            now=datetime.fromtimestamp(now, tz=timezone.utc),
        )
        for part in parts:
            if not await self.directus_service.delete_item(
                "cold_archive_parts",
                str(part["id"]),
                admin_required=True,
            ):
                raise ColdArchiveError("ORPHAN_ARCHIVE_PART_CLEANUP_FAILED")

    async def list_archives(
        self,
        *,
        user_id: str,
        resource_type: str,
        team_id: str | None = None,
        cursor: str | None = None,
        limit: int = DEFAULT_ARCHIVE_PAGE_LIMIT,
    ) -> dict[str, Any]:
        bounded_limit = max(1, min(int(limit), MAX_ARCHIVE_PAGE_LIMIT))
        if team_id:
            team_service = getattr(self.directus_service, "team", None)
            if team_service is None:
                raise ColdArchiveAuthorizationError("ARCHIVE_PERMISSION_DENIED")
            try:
                await team_service.require_team_role(team_id, user_id, {"owner", "admin", "member", "viewer"})
            except Exception as exc:
                raise ColdArchiveAuthorizationError("ARCHIVE_PERMISSION_DENIED") from exc
        scope_field = "hashed_team_id" if team_id else "hashed_user_id"
        scope_hash = _hash_id(team_id or user_id)
        filters: list[dict[str, Any]] = [
            {scope_field: {"_eq": scope_hash}},
            {"resource_type": {"_eq": resource_type}},
            {"state": {"_eq": "cold"}},
        ]
        if cursor:
            timestamp, archive_id = decode_archive_cursor(cursor, expected_scope_hash=scope_hash)
            filters.append(
                {
                    "_or": [
                        {"archived_at": {"_lt": timestamp}},
                        {"_and": [{"archived_at": {"_eq": timestamp}}, {"archive_id": {"_lt": archive_id}}]},
                    ]
                }
            )
        rows = await self.directus_service.get_items(
            "cold_archive_manifests",
            params={
                "filter": {"_and": filters},
                "fields": ",".join(PUBLIC_MANIFEST_FIELDS),
                "sort": "-archived_at,-archive_id",
                "limit": bounded_limit + 1,
            },
            no_cache=True,
            admin_required=True,
        )
        rows = rows if isinstance(rows, list) else []
        page_rows = rows[:bounded_limit]
        has_more = len(rows) > bounded_limit
        items = [self.public_manifest(row) for row in page_rows]
        next_cursor = None
        if has_more and page_rows:
            last = page_rows[-1]
            next_cursor = encode_archive_cursor(
                sort_timestamp=int(last.get("archived_at") or 0),
                archive_id=str(last.get("archive_id") or ""),
                scope_hash=scope_hash,
            )
        return {"items": items, "next_cursor": next_cursor, "complete": not has_more, "source": "cold"}

    async def authorize_manifest(
        self,
        manifest: dict[str, Any],
        *,
        user_id: str,
        team_id: str | None,
        mutation: bool,
    ) -> None:
        manifest_team_hash = manifest.get("hashed_team_id")
        if manifest_team_hash:
            if not team_id or _hash_id(team_id) != manifest_team_hash:
                raise ColdArchiveAuthorizationError("ARCHIVE_PERMISSION_DENIED")
            allowed = {"owner", "admin", "member"} if mutation else {"owner", "admin", "member", "viewer"}
            team_service = getattr(self.directus_service, "team", None)
            if team_service is None:
                raise ColdArchiveAuthorizationError("ARCHIVE_PERMISSION_DENIED")
            try:
                await team_service.require_team_role(team_id, user_id, allowed)
            except Exception as exc:
                raise ColdArchiveAuthorizationError("ARCHIVE_PERMISSION_DENIED") from exc
            return
        if team_id or manifest.get("hashed_user_id") != _hash_id(user_id):
            raise ColdArchiveAuthorizationError("ARCHIVE_PERMISSION_DENIED")

    def public_manifest(self, manifest: dict[str, Any]) -> dict[str, Any]:
        projected = {field: manifest.get(field) for field in PUBLIC_MANIFEST_FIELDS}
        projected["source"] = "cold"
        return projected

    async def get_manifest(self, archive_id: str) -> dict[str, Any]:
        manifest = await self._get_one("cold_archive_manifests", {"archive_id": {"_eq": archive_id}})
        if not manifest or manifest.get("state") == "deleted":
            raise ColdArchiveNotFoundError("ARCHIVE_NOT_FOUND")
        return manifest

    async def get_part(self, archive_id: str, part_id: str, generation: int) -> dict[str, Any]:
        part = await self._get_one(
            "cold_archive_parts",
            {
                "_and": [
                    {"archive_id": {"_eq": archive_id}},
                    {"part_id": {"_eq": part_id}},
                    {"generation": {"_eq": generation}},
                ]
            },
        )
        if not part:
            raise ColdArchiveNotFoundError("ARCHIVE_PART_NOT_FOUND")
        return part

    async def stream_archive_part(
        self,
        *,
        manifest: dict[str, Any],
        part: dict[str, Any],
    ) -> AsyncIterator[bytes]:
        if int(part.get("generation") or 0) != int(manifest.get("active_generation") or 0):
            raise ColdArchiveConflictError("ARCHIVE_GENERATION_MISMATCH")
        regional_states = part.get("regional_states") or {}
        verified_regions = tuple(
            sorted(region for region, state in regional_states.items() if state == "verified")
        )
        if hasattr(self.s3_service, "get_replicated_file_stream"):
            async for chunk in self.s3_service.get_replicated_file_stream(
                bucket_key=str(part["logical_bucket"]),
                object_key=str(part["object_key"]),
                regions=verified_regions,
                chunk_size=ARCHIVE_STREAM_CHUNK_BYTES,
            ):
                yield chunk
            return
        region = self.s3_service.region_name if hasattr(self.s3_service, "region_name") else "nbg1"
        legacy_bucket = get_bucket_name(str(part["logical_bucket"]), self.s3_service.environment)
        bucket_name = resolve_regional_bucket_name(legacy_bucket, region)
        async for chunk in self.s3_service.get_file_stream(
            bucket_name,
            str(part["object_key"]),
            chunk_size=ARCHIVE_STREAM_CHUNK_BYTES,
        ):
            yield chunk

    async def promote_archive(
        self,
        archive_id: str,
        *,
        user_id: str,
        team_id: str | None,
        expected_generation: int,
        mutation_intent: str,
    ) -> dict[str, Any]:
        manifest = await self.get_manifest(archive_id)
        await self.authorize_manifest(manifest, user_id=user_id, team_id=team_id, mutation=True)
        root_shell = await self._get_one("chats", {"id": {"_eq": manifest["resource_id"]}})
        if not root_shell or root_shell.get("storage_state") == "deleting":
            raise ColdArchiveConflictError("ARCHIVE_PROMOTION_CONFLICT")
        shell_archive_version = int(root_shell.get("archive_version") or 1)
        if int(manifest.get("active_generation") or 0) != int(expected_generation):
            raise ColdArchiveConflictError("ARCHIVE_GENERATION_MISMATCH")
        now = int(time.time())
        state = manifest.get("state")
        if state == "promoting":
            if (
                manifest.get("promotion_intent") != mutation_intent
                or int(manifest.get("updated_at") or 0) > now - PROMOTION_LEASE_SECONDS
            ):
                raise ColdArchiveConflictError("ARCHIVE_PROMOTION_CONFLICT")
        elif state != "cold":
            raise ColdArchiveConflictError("ARCHIVE_GENERATION_MISMATCH")
        expected_shell_state = "promoting" if state == "promoting" else "cold"
        if root_shell.get("storage_state") != expected_shell_state:
            raise ColdArchiveConflictError("ARCHIVE_PROMOTION_CONFLICT")
        shell_claim = await self.directus_service.update_item_if_version(
            "chats",
            str(root_shell["id"]),
            {
                "storage_state": "promoting",
                "archive_started_at": now,
                "archive_version": shell_archive_version + 1,
            },
            shell_archive_version,
            version_field="archive_version",
            extra_filters={"storage_state": expected_shell_state},
            admin_required=True,
        )
        if not shell_claim:
            raise ColdArchiveConflictError("ARCHIVE_PROMOTION_CONFLICT")
        version = int(manifest.get("version") or 1)
        claimed = await self.directus_service.update_item_if_version(
            "cold_archive_manifests",
            str(manifest["id"]),
            {
                "state": "promoting",
                "promotion_intent": mutation_intent,
                "version": version + 1,
                "updated_at": now,
            },
            version,
            admin_required=True,
        )
        if not claimed:
            await self.directus_service.update_item_if_version(
                "chats",
                str(root_shell["id"]),
                {
                    "storage_state": expected_shell_state,
                    "archive_started_at": None,
                    "archive_version": shell_archive_version + 2,
                },
                shell_archive_version + 1,
                version_field="archive_version",
                extra_filters={"storage_state": "promoting"},
                admin_required=True,
            )
            raise ColdArchiveConflictError("ARCHIVE_PROMOTION_CONFLICT")

        graph = await self._load_archive_graph(manifest)
        root_chat_id = str(manifest["resource_id"])
        for collection, rows in graph.items():
            if collection not in {"chats", *ARCHIVE_DELETE_ORDER}:
                continue
            for row in rows:
                if not isinstance(row, dict) or not row.get("id"):
                    raise ColdArchiveError("ARCHIVE_GRAPH_INVALID")
                if collection == "chats" and str(row["id"]) == root_chat_id:
                    continue
                if await self._get_one(collection, {"id": {"_eq": row["id"]}}):
                    continue
                success, _ = await self.directus_service.create_item(collection, row, admin_required=True)
                if not success:
                    if not await self._get_one(collection, {"id": {"_eq": row["id"]}}):
                        raise ColdArchiveError("ARCHIVE_GRAPH_RESTORE_FAILED")

        root_chat = next(
            (row for row in graph.get("chats", []) if str(row.get("id")) == root_chat_id),
            None,
        )
        if root_chat is None:
            raise ColdArchiveError("ARCHIVE_GRAPH_INVALID")
        shell_update = {
            **root_chat,
            "storage_state": "hot",
            "cold_archive_id": None,
            "cold_generation": None,
        }
        shell_update.pop("id", None)
        shell_update["archive_started_at"] = None
        shell_update["archive_version"] = shell_archive_version + 2
        if not await self.directus_service.update_item_if_version(
            "chats",
            root_chat_id,
            shell_update,
            shell_archive_version + 1,
            version_field="archive_version",
            extra_filters={"storage_state": "promoting"},
            admin_required=True,
        ):
            raise ColdArchiveError("ARCHIVE_ROOT_SHELL_RESTORE_FAILED")

        completed = await self.directus_service.update_item_if_version(
            "cold_archive_manifests",
            str(manifest["id"]),
            {"state": "hot", "version": version + 2, "promoted_at": now, "updated_at": now},
            version + 1,
            admin_required=True,
        )
        if not completed:
            raise ColdArchiveConflictError("ARCHIVE_PROMOTION_CONFLICT")
        return {"archive_id": archive_id, "state": "hot", "active_generation": expected_generation}

    async def _get_one(self, collection: str, filters: dict[str, Any]) -> dict[str, Any] | None:
        rows = await self.directus_service.get_items(
            collection,
            params={"filter": filters, "fields": "*", "limit": 1},
            no_cache=True,
            admin_required=True,
        )
        return rows[0] if isinstance(rows, list) and rows else None

    async def _collect_chat_graph(self, chat: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        chats = [chat]
        pending_ids = [str(chat["id"])]
        while pending_ids:
            children = await self._get_all("chats", {"parent_id": {"_eq": pending_ids.pop(0)}})
            known_ids = {str(row["id"]) for row in chats}
            for child in children:
                child_id = str(child["id"])
                if child_id not in known_ids:
                    chats.append(child)
                    pending_ids.append(child_id)

        chat_ids = [str(row["id"]) for row in chats]
        graph: dict[str, list[dict[str, Any]]] = {"chats": chats}
        for collection in ARCHIVE_COLLECTIONS_BY_CHAT_ID:
            graph[collection] = []
            for chat_id in chat_ids:
                graph[collection].extend(await self._get_all(collection, {"chat_id": {"_eq": chat_id}}))
        graph["embeds"] = []
        graph["chat_key_wrappers"] = []
        for chat_id in chat_ids:
            hashed_chat_id = _hash_id(chat_id)
            graph["embeds"].extend(await self._get_all("embeds", {"hashed_chat_id": {"_eq": hashed_chat_id}}))
            graph["chat_key_wrappers"].extend(
                await self._get_all("chat_key_wrappers", {"hashed_chat_id": {"_eq": hashed_chat_id}})
            )
        hashed_chat_ids = [_hash_id(chat_id) for chat_id in chat_ids]
        graph["embed_keys"] = await self._get_all(
            "embed_keys",
            {"hashed_chat_id": {"_in": hashed_chat_ids}},
        )
        return graph

    async def _get_all(self, collection: str, filters: dict[str, Any]) -> list[dict[str, Any]]:
        rows = await self.directus_service.get_items(
            collection,
            params={"filter": filters, "fields": "*", "sort": "id", "limit": -1},
            no_cache=True,
            admin_required=True,
        )
        return rows if isinstance(rows, list) else []

    def _build_parts(self, archive_id: str, generation: int, graph: dict[str, list[dict[str, Any]]]) -> list[bytes]:
        parts: list[bytes] = []
        current: dict[str, list[dict[str, Any]]] = {}
        for collection, rows in graph.items():
            for row in rows:
                candidate = {**current, collection: [*current.get(collection, []), row]}
                encoded = self._encode_part(archive_id, generation, candidate)
                if len(encoded) > MAX_ARCHIVE_PART_BYTES and current:
                    parts.append(self._encode_part(archive_id, generation, current))
                    current = {collection: [row]}
                    encoded = self._encode_part(archive_id, generation, current)
                    if len(encoded) > MAX_ARCHIVE_PART_BYTES:
                        raise ColdArchiveError("ARCHIVE_ROW_EXCEEDS_PART_LIMIT")
                    continue
                if len(encoded) > MAX_ARCHIVE_PART_BYTES:
                    raise ColdArchiveError("ARCHIVE_ROW_EXCEEDS_PART_LIMIT")
                current = candidate
        if current:
            parts.append(self._encode_part(archive_id, generation, current))
        if not parts:
            raise ColdArchiveError("ARCHIVE_GRAPH_EMPTY")
        return parts

    @staticmethod
    def _encode_part(archive_id: str, generation: int, records: dict[str, list[dict[str, Any]]]) -> bytes:
        payload = {"version": 1, "archive_id": archive_id, "generation": generation, "records": records}
        return gzip.compress(json.dumps(payload, separators=(",", ":"), sort_keys=True, default=str).encode())

    @staticmethod
    def _graph_checksum(graph: dict[str, list[dict[str, Any]]]) -> str:
        encoded = json.dumps(graph, separators=(",", ":"), sort_keys=True, default=str).encode()
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _encrypted_listing_metadata(chat: dict[str, Any]) -> dict[str, Any]:
        fields = (
            "encrypted_title",
            "encrypted_slug",
            "slug_lookup_hash",
            "encrypted_chat_summary",
            "encrypted_chat_key",
            "encrypted_icon",
            "encrypted_category",
            "last_edited_overall_timestamp",
            "updated_at",
        )
        return {field: chat.get(field) for field in fields if chat.get(field) is not None}

    @staticmethod
    def _file_references(graph: dict[str, list[dict[str, Any]]]) -> list[dict[str, str]]:
        references: dict[tuple[str, str], dict[str, str]] = {}
        for embed in graph.get("embeds", []):
            for item in embed.get("s3_file_keys") or []:
                if not isinstance(item, dict):
                    continue
                logical_bucket = item.get("logical_bucket") or item.get("bucket") or item.get("bucket_key")
                object_key = item.get("object_key") or item.get("key") or item.get("file_key")
                if isinstance(logical_bucket, str) and logical_bucket and isinstance(object_key, str) and object_key:
                    references[(logical_bucket, object_key)] = {
                        "logical_bucket": logical_bucket,
                        "object_key": object_key,
                    }
        return [references[key] for key in sorted(references)]

    async def _delete_hot_graph(self, graph: dict[str, list[dict[str, Any]]]) -> None:
        for collection in ARCHIVE_DELETE_ORDER:
            for row in graph.get(collection, []):
                row_id = row.get("id")
                if not row_id or not await self._get_one(collection, {"id": {"_eq": row_id}}):
                    continue
                if not await self.directus_service.delete_item(collection, row_id, admin_required=True):
                    raise ColdArchiveError("HOT_GRAPH_DELETE_FAILED")
        for child_chat in graph.get("chats", [])[1:]:
            if not await self._get_one("chats", {"id": {"_eq": child_chat["id"]}}):
                continue
            if not await self.directus_service.delete_item("chats", child_chat["id"], admin_required=True):
                raise ColdArchiveError("HOT_GRAPH_DELETE_FAILED")

    async def _load_archive_graph(self, manifest: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        if self.archive_reader is not None:
            return await self.archive_reader.load_graph(manifest)
        parts = await self.directus_service.get_items(
            "cold_archive_parts",
            params={
                "filter": {
                    "_and": [
                        {"archive_id": {"_eq": manifest["archive_id"]}},
                        {"generation": {"_eq": manifest["active_generation"]}},
                    ]
                },
                "fields": "*",
                "sort": "part_number",
                "limit": -1,
            },
            no_cache=True,
            admin_required=True,
        )
        graph: dict[str, list[dict[str, Any]]] = {}
        for part in parts if isinstance(parts, list) else []:
            compressed = b"".join([chunk async for chunk in self.stream_archive_part(manifest=manifest, part=part)])
            if hashlib.sha256(compressed).hexdigest() != part.get("checksum"):
                raise ColdArchiveError("ARCHIVE_PART_CHECKSUM_MISMATCH")
            payload = json.loads(gzip.decompress(compressed))
            for collection, rows in (payload.get("records") or {}).items():
                graph.setdefault(collection, []).extend(rows)
        if self._graph_checksum(graph) != manifest.get("graph_checksum"):
            raise ColdArchiveError("ARCHIVE_GRAPH_CHECKSUM_MISMATCH")
        return graph
