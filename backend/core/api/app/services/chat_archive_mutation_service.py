"""Promote one verified ciphertext page before an individual message mutation.

The indexed page is removed atomically with its bounded PostgreSQL restore.
Prepared regional tombstones precede that transaction, so a crash after index
removal leaves their existing reconciliation worker able to finish the purge.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from typing import Any

from backend.core.api.app.services.bounded_archive_io import ArchiveIntegrityError
from backend.core.api.app.services.chat_message_archive_service import (
    ChatMessageArchiveService, encode_record,
)
from backend.core.api.app.services.storage_reference_service import (
    _inventory_for_reference_row,
    activate_storage_tombstones,
    find_surviving_storage_references,
    persist_reference_safe_tombstones,
)

MAX_PROMOTION_BYTES = 2 * 1024 * 1024 + 8192


class ChatArchiveMutationService:
    def __init__(self, *, directus_service: Any, s3_service: Any | None) -> None:
        self.directus = directus_service
        self.s3 = s3_service

    async def promote_for_message(
        self, *, user_id: str, chat_id: str, client_message_id: str,
    ) -> dict[str, Any]:
        """Restore at most one page; the caller may then edit/delete its hot row."""
        actor_hash = hashlib.sha256(user_id.encode()).hexdigest()
        chats = await self.directus.get_items(
            "chats", params={
                "filter": {"id": {"_eq": chat_id}},
                "fields": "id,hashed_user_id,hashed_team_id,storage_state", "limit": 1,
            }, no_cache=True, admin_required=True, raise_on_error=True,
        )
        if not isinstance(chats, list):
            raise RuntimeError("Chat mutation authority lookup failed")
        if not chats:
            return {"promoted": False, "reason": "chat_not_persisted"}
        chat = chats[0]
        team_hash = chat.get("hashed_team_id")
        owner_hash = team_hash or chat.get("hashed_user_id")
        if chat.get("storage_state") == "deleting" or not owner_hash:
            raise PermissionError("Chat mutation authority changed")
        if team_hash:
            members = await self.directus.get_items(
                "team_memberships", params={
                    "filter": {"hashed_team_id": {"_eq": team_hash},
                               "hashed_user_id": {"_eq": actor_hash}, "status": {"_eq": "active"},
                               "role": {"_in": ["owner", "admin", "member"]}},
                    "fields": "id", "limit": 1,
                }, no_cache=True, admin_required=True, raise_on_error=True,
            )
            teams = await self.directus.get_items(
                "teams", params={"filter": {"hashed_team_id": {"_eq": team_hash},
                                            "status": {"_eq": "active"}},
                                 "fields": "id", "limit": 1},
                no_cache=True, admin_required=True, raise_on_error=True,
            )
            if not isinstance(members, list) or not members or not isinstance(teams, list) or not teams:
                raise PermissionError("Team chat mutation permission changed")
        elif owner_hash != actor_hash:
            raise PermissionError("Chat mutation authority changed")
        archive = ChatMessageArchiveService(directus_service=self.directus, s3_service=self.s3)
        lookup = await archive.transaction("lookup_mutation_page", {
            "chat_id": chat_id, "message_id": client_message_id,
            "expected_owner_hash": owner_hash,
            "expected_actor_user_hash": actor_hash,
        })
        page = lookup.get("page")
        if page is None:
            return {"promoted": False, "reason": "not_archived"}
        if (not isinstance(page, dict) or page.get("chat_id") != chat_id
                or (page.get("hashed_team_id") or page.get("hashed_user_id")) != owner_hash):
            raise ArchiveIntegrityError("ARCHIVE_MUTATION_SCOPE_CHANGED")
        if self.s3 is None or not getattr(self.s3, "region_clients", None):
            raise ArchiveIntegrityError("ARCHIVE_MUTATION_REGIONAL_STORAGE_REQUIRED")
        now = datetime.now(timezone.utc)
        if not page.get("published"):
            segment = lookup.get("segment")
            if not isinstance(segment, dict) or segment.get("state") != "copying":
                raise ArchiveIntegrityError("ARCHIVE_MUTATION_UNPUBLISHED_AUTHORITY_INVALID")
            if now.timestamp() < int(segment["lease_until"]) + 90:
                raise ArchiveIntegrityError("ARCHIVE_MUTATION_WRITER_MAY_STILL_UPLOAD")
            restored: list[dict[str, Any]] | None = None
        else:
            segment = lookup.get("segment")
            if not isinstance(segment, dict) or segment.get("state") not in {"verified", "reader_active", "pruned"}:
                raise ArchiveIntegrityError("ARCHIVE_MUTATION_WRITER_MAY_STILL_UPLOAD")
            large_objects = page.get("large_objects")
            if not isinstance(large_objects, list) or not all(
                isinstance(ref, dict) and isinstance(ref.get("size_bytes"), int)
                and ref["size_bytes"] > 0 for ref in large_objects
            ):
                raise ArchiveIntegrityError("ARCHIVE_MUTATION_LARGE_OBJECT_METADATA_INVALID")
            if sum(ref["size_bytes"] for ref in large_objects) + int(page.get("raw_size_bytes") or 0) > MAX_PROMOTION_BYTES:
                raise ArchiveIntegrityError("ARCHIVE_MUTATION_BUDGET_EXCEEDED")
            records = await archive.read_page(page)
            restored = []
            for record in records:
                restored.extend(await archive.hydrate_records([record]))
            if len(restored) != int(page["message_count"]) or not any(
                row.get("client_message_id") == client_message_id for row in restored
            ):
                raise ArchiveIntegrityError("ARCHIVE_MUTATION_IDENTITIES_CHANGED")
            source = encode_record(restored)
            if len(source) > MAX_PROMOTION_BYTES or hashlib.sha256(source).hexdigest() != page.get("source_checksum"):
                raise ArchiveIntegrityError("ARCHIVE_MUTATION_SOURCE_CHANGED_OR_UNBOUNDED")

        deleting = _inventory_for_reference_row("chat_message_archive_pages", page)
        if deleting.ambiguous:
            raise ArchiveIntegrityError("ARCHIVE_MUTATION_OBJECT_REFERENCES_AMBIGUOUS")
        surviving = await find_surviving_storage_references(
            directus_service=self.directus, candidates=deleting.references,
            excluded_ids={"chat_message_archive_pages": {str(page["id"])}},
        )
        tombstones = await persist_reference_safe_tombstones(
            directus_service=self.directus, deleting=deleting, surviving=surviving,
            regions=tuple(sorted(self.s3.region_clients)), now=now,
        )
        if restored is None:
            result = await archive.transaction("abort_unpublished_page", {
                "chat_id": chat_id, "page_id": str(page["id"]),
                "expected_owner_hash": owner_hash,
                "expected_actor_user_hash": actor_hash,
                "expected_page_checksum": page["checksum"],
                "expected_object_key": page["object_key"],
                "expected_large_objects": page["large_objects"],
                "now": int(datetime.now(timezone.utc).timestamp()),
            })
        else:
            result = await archive.transaction("restore_and_retire_page", {
                "chat_id": chat_id, "page_id": str(page["id"]), "message_id": client_message_id,
                "expected_owner_hash": owner_hash,
                "expected_actor_user_hash": actor_hash,
                "expected_page_checksum": page["checksum"],
                "expected_source_checksum": page["source_checksum"],
                "expected_object_key": page["object_key"],
                "expected_large_objects": page["large_objects"],
                "source_rows": restored,
            })
        await activate_storage_tombstones(
            directus_service=self.directus, tombstones=tombstones,
            now=datetime.now(timezone.utc),
        )
        return result
