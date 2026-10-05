"""Incremental, independently readable client-encrypted message segments.

Copying never changes live messages. Publishing and pruning use the internal
transaction endpoint; its database locks and compare-and-delete fences are the
authority, rather than an elapsed timer or a successful object upload alone.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import time
import uuid
from typing import Any
from backend.shared.python_utils.storage_archive_rollout_config import (
    archive_feature_enabled, archive_advancement_allowed, archive_billing_hold_reason, trusted_isolated_storage_profile,
)

from backend.core.api.app.services.bounded_archive_io import (
    ArchiveIntegrityError, put_verified_bytes, read_verified_bytes,
)

PAGE_MESSAGES = 20
PAGE_BYTES = 256 * 1024
LARGE_MESSAGE_BYTES = 2 * 1024 * 1024
INITIAL_ROLLBACK_SECONDS = 24 * 60 * 60
SEGMENTS = "chat_message_archive_segments"
PAGES = "chat_message_archive_pages"
ROLLOUT = "chat_message_archive_rollout"
LIFECYCLE_BATCH = 25


def encode_record(value: Any) -> bytes:
    """Use a deterministic ciphertext container; never decode message content."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def message_position(row: dict[str, Any]) -> tuple[int, str]:
    return int(row["created_at"]), str(row["client_message_id"])


def bounded_message_pages(rows: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Partition one admitted input batch without repeatedly recompressing it."""
    result: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    size = 2
    for row in rows:
        length = len(encode_record(row))
        if length > LARGE_MESSAGE_BYTES:
            raise ArchiveIntegrityError("ARCHIVE_LEGACY_MESSAGE_REQUIRES_BOUNDED_READER")
        if current and (len(current) == PAGE_MESSAGES or size + length + 1 > PAGE_BYTES):
            result.append(current)
            current, size = [], 2
        current.append(row)
        size += length + 1
    if current:
        result.append(current)
    return result


def position_filter(position: tuple[int, str], *, after: bool) -> dict[str, Any]:
    timestamp, message_id = position
    operator = "_gt" if after else "_lt"
    return {"_or": [
        {"created_at": {operator: timestamp}},
        {"_and": [{"created_at": {"_eq": timestamp}}, {"client_message_id": {operator: message_id}}]},
    ]}


class ChatMessageArchiveService:
    """Bounded copy/read API; caller supplies current authorized chat scope."""

    def __init__(self, *, directus_service: Any, s3_service: Any) -> None:
        self.directus = directus_service
        self.s3 = s3_service

    async def transaction(self, operation: str, data: dict[str, Any]) -> dict[str, Any]:
        if operation in {"claim_segment", "prepare_page", "publish_page", "verify_segment",
                         "activate_segment", "prune_page", "finish_pruning"} and archive_billing_hold_reason():
            raise ArchiveIntegrityError("ARCHIVE_BILLING_DISABLED")
        token = os.environ.get("INTERNAL_API_SHARED_TOKEN")
        if not token:
            raise RuntimeError("INTERNAL_API_SHARED_TOKEN_REQUIRED")
        response = await self.directus._make_api_request(
            "POST", f"{self.directus.base_url.rstrip('/')}/chat-archive-transaction",
            headers={"X-Internal-Service-Token": token}, json={"operation": operation, "data": data},
        )
        payload = response.json()
        if response.status_code != 200 or not isinstance(payload.get("data"), dict):
            code = (payload.get("error") or {}).get("code", "ARCHIVE_TRANSACTION_FAILED")
            raise ArchiveIntegrityError(str(code))
        return payload["data"]

    async def iter_history(self, *, chat_id: str):
        """Authorized exports/legacy reads page through ciphertext without a DB scan.

        Interactive clients use merge_window directly. This iterator does not
        keep a whole transcript or a whole set of message IDs in server memory.
        """
        cursor = (-2147483648, "")
        while True:
            hot = await self.directus.chat.get_message_window_for_chat(
                chat_id=chat_id, direction="after", limit=PAGE_MESSAGES,
                after_timestamp=cursor[0], after_message_id=cursor[1],
            )
            window = await self.merge_window(chat_id=chat_id, hot=hot, direction="after",
                                             after=cursor, limit=PAGE_MESSAGES)
            rows = window["messages"]
            if not rows:
                oversized = window.get("oversized_message_cursor")
                if not oversized:
                    return
                row = await self.find_message(chat_id=chat_id, message_id=oversized["message_id"])
                if row is None:
                    row = await self.directus.chat.get_message_for_chat_by_client_id(chat_id, oversized["message_id"])
                if row is None:
                    raise ArchiveIntegrityError("ARCHIVE_HISTORY_OVERSIZED_MESSAGE_MISSING")
                rows = [row]
            for row in rows:
                yield row
            next_cursor = message_position(rows[-1])
            if next_cursor <= cursor:
                raise ArchiveIntegrityError("ARCHIVE_HISTORY_CURSOR_DID_NOT_ADVANCE")
            cursor = next_cursor
            if not window.get("has_more_after"):
                return

    async def verify_reader_pages(self, segment: dict[str, Any], *, limit: int = LIFECYCLE_BATCH) -> bool:
        """Persist bounded read verification so restarts do not repeat a whole segment."""
        pages = await self.directus.get_items(PAGES, params={
            "filter": {"segment_id": {"_eq": segment["id"]}, "reader_verified": {"_neq": True}},
            "sort": "page_number", "limit": min(max(limit, 1), LIFECYCLE_BATCH),
        }, admin_required=True, no_cache=True, raise_on_error=True)
        if not isinstance(pages, list):
            raise ArchiveIntegrityError("ARCHIVE_READER_INDEX_UNAVAILABLE")
        for page in pages:
            self.require_configured_replication(page)
            records = await self.read_page(page)
            # Large records are also verified, one at a time; never assemble a
            # complete transcript or several large payloads in memory.
            for record in records:
                await self.hydrate_records([record])
            await self.transaction("record_reader_verification", {
                "segment_id": segment["id"], "expected_version": segment["version"],
                "page_id": page["id"], "checksum": page["checksum"],
                "source_checksum": page["source_checksum"],
            })
        return len(pages) < min(max(limit, 1), LIFECYCLE_BATCH)

    def require_configured_replication(self, page: dict[str, Any]) -> None:
        """A newly enabled region cannot inherit an earlier replication receipt."""
        regions = set(self.s3.region_clients)
        if not regions or not regions.issubset(set(page.get("verified_regions") or [])):
            raise ArchiveIntegrityError("ARCHIVE_CONFIGURED_REGION_NOT_VERIFIED")
        if any(not regions.issubset(set(ref.get("verified_regions") or [])) for ref in page.get("large_objects", [])):
            raise ArchiveIntegrityError("ARCHIVE_LARGE_OBJECT_REGION_NOT_VERIFIED")

    async def verify_pruning_replicas(self, page: dict[str, Any]) -> None:
        """Require fresh object integrity in every region before source removal.

        Normal reads may fail over to a surviving region. A stored copy receipt
        cannot authorize pruning after one of its regional objects disappears.
        """
        self.require_configured_replication(page)
        for reference in [page, *page.get("large_objects", [])]:
            for region in sorted(self.s3.region_clients):
                try:
                    verified = await self.s3.verify_regional_object(
                        bucket_key="cold_archives", object_key=reference["object_key"],
                        region=region, checksum=reference["checksum"],
                    )
                except Exception as exc:
                    raise ArchiveIntegrityError("ARCHIVE_PRUNE_REGION_UNAVAILABLE") from exc
                if not verified:
                    raise ArchiveIntegrityError("ARCHIVE_PRUNE_REGION_CHECKSUM_MISMATCH")

    async def advance_segment(self, segment: dict[str, Any]) -> dict[str, Any]:
        """Advance one disposable batch through independently gated lifecycle steps."""
        gates = await self.directus.get_items(ROLLOUT, params={
            "filter": {"id": {"_eq": "agentic-storage-v2"}}, "limit": 1,
        }, admin_required=True, no_cache=True, raise_on_error=True)
        gate = gates[0] if gates else {}
        if not gate.get("read_enabled") or not gate.get("compatibility_verified") or not gate.get("reader_receipt") or gate.get("failure_code"):
            return {"state": "rollout_paused_or_unverified"}
        if segment["state"] == "verified":
            if not archive_feature_enabled("CHAT_MESSAGE_ARCHIVE_READS_ENABLED"):
                return {"state": "reader_disabled"}
            if not await self.verify_reader_pages(segment):
                return {"state": "reader_verification_pending"}
            if not await archive_advancement_allowed(self.directus, phase="read"):
                return {"state": "release_or_client_gate_pending"}
            segment = await self.transaction("activate_segment", {
                "segment_id": segment["id"], "expected_version": segment["version"],
            })
        if segment["state"] != "reader_active" or not archive_feature_enabled("CHAT_MESSAGE_ARCHIVE_PRUNE_ENABLED"):
            return {"state": segment["state"]}
        if not gate.get("pruning_enabled") or not gate.get("validation_receipt"):
            return {"state": "prune_receipt_missing"}
        if int(segment.get("source_copy_until") or 0) > int(time.time()):
            return {"state": "rollback_buffer_active"}
        pages = await self.directus.get_items(PAGES, params={
            "filter": {"segment_id": {"_eq": segment["id"]}, "pruned": {"_neq": True}},
            "sort": "page_number", "limit": LIFECYCLE_BATCH,
        }, admin_required=True, no_cache=True, raise_on_error=True)
        if not isinstance(pages, list):
            raise ArchiveIntegrityError("ARCHIVE_PRUNE_INDEX_UNAVAILABLE")
        if not pages:
            if not await archive_advancement_allowed(self.directus, phase="prune"):
                return {"state": "release_or_client_gate_pending"}
            return await self.transaction("finish_pruning", {
                "segment_id": segment["id"], "expected_version": segment["version"],
            })
        for page in pages:
            await self.verify_pruning_replicas(page)
            # A file may have disappeared after activation. Check again before
            # removing its sole PostgreSQL copy, then let the SQL source fence
            # reject any concurrent canonical edit or recovery acknowledgement.
            for record in await self.read_page(page):
                await self.hydrate_records([record])
            if not await archive_advancement_allowed(self.directus, phase="prune"):
                return {"state": "release_or_client_gate_pending"}
            await self.transaction("prune_page", {
                "segment_id": segment["id"], "expected_version": segment["version"], "page_id": page["id"],
            })
        return {"state": "prune_batch_complete", "pages_pruned": len(pages)}

    async def pause_rollout(self, *, failure_code: str) -> None:
        """Keep existing cold reads available while blocking further payload removal."""
        if not await self.directus.update_item(ROLLOUT, "agentic-storage-v2", {
            "pruning_enabled": False, "failure_code": failure_code[:96],
        }, admin_required=True):
            raise RuntimeError("ARCHIVE_ROLLOUT_PAUSE_SAVE_FAILED")

    async def copy_segment(
        self, *, chat_id: str, checkpoint_id: str | None = None, end: tuple[int, str] | None = None,
        now_timestamp: int | None = None, reason: str | None = None, policy_id: str | None = None,
        resume_segment_id: str | None = None,
    ) -> dict[str, Any]:
        """Copy only the new prefix through an acknowledged stable checkpoint ID.

        A durable claimed segment records its starting cursor, so retrying after
        a worker restart cannot rewrite previous checkpoints or skip a prefix.
        """
        if archive_billing_hold_reason():
            raise ArchiveIntegrityError("ARCHIVE_BILLING_DISABLED")
        now = int(time.time() if now_timestamp is None else now_timestamp)
        claim = await self.transaction("claim_segment", {
            "chat_id": chat_id, "checkpoint_id": checkpoint_id,
            "end_timestamp": end[0] if end else None, "end_message_id": end[1] if end else None, "now": now,
            "reason": reason, "policy_id": policy_id,
            "resume_segment_id": resume_segment_id,
        })
        segment = claim["segment"]
        end = (int(segment["end_timestamp"]), str(segment["end_message_id"]))
        if segment["state"] in {"verified", "reader_active", "pruned"}:
            return segment
        start = None
        if segment.get("start_message_id"):
            start = int(segment["start_timestamp"]), str(segment["start_message_id"])
        cursor = start
        number = 0
        while True:
            source = await self.transaction("source_page", {
                "segment_id": segment["id"], "expected_version": segment["version"],
                "after_timestamp": cursor[0] if cursor else None,
                "after_message_id": cursor[1] if cursor else None,
                "now": int(time.time()) if now_timestamp is None else now,
            })
            rows = source.get("messages")
            if not isinstance(rows, list):
                raise ArchiveIntegrityError("ARCHIVE_SOURCE_QUERY_FAILED")
            if not rows:
                break
            from backend.shared.python_utils.client_ciphertext import is_client_encrypted_base64
            if len(rows) > PAGE_MESSAGES or any(not is_client_encrypted_base64(r.get("encrypted_content")) for r in rows):
                raise ArchiveIntegrityError("ARCHIVE_SOURCE_NOT_CANONICAL_OR_UNBOUNDED")
            for page_rows in bounded_message_pages(rows):
                number += 1
                await self._copy_page(segment, number, page_rows, int(time.time()) if now_timestamp is None else now)
            next_cursor = message_position(rows[-1])
            if cursor is not None and next_cursor <= cursor:
                raise ArchiveIntegrityError("ARCHIVE_SOURCE_CURSOR_DID_NOT_ADVANCE")
            cursor = next_cursor
            if cursor == end:
                break
        if cursor != end:
            raise ArchiveIntegrityError("ARCHIVE_CHECKPOINT_BOUNDARY_MISSING")
        return await self.transaction("verify_segment", {
            "segment_id": segment["id"], "expected_version": segment["version"],
            "page_count": number, "now": int(time.time()) if now_timestamp is None else now,
        })

    async def activate_isolated_capacity_segment(self, segment: dict[str, Any]) -> dict[str, Any]:
        """Exercise true cold reads only in the disposable, network-isolated CI stack.

        The normal operator path cannot call this method. The capacity cohort is
        synthetic and has no initial rollback delay; separate lifecycle tests
        exercise the real initial-cohort 24-hour gate with a controlled clock.
        """
        if not trusted_isolated_storage_profile(dict(os.environ)):
            raise ArchiveIntegrityError("ISOLATED_CAPACITY_PROFILE_REQUIRED")
        receipt = "ci-storage-capacity:" + os.environ["BUILD_COMMIT_SHA"]
        rows = await self.directus.get_items("chat_message_archive_rollout", params={
            "filter": {"id": {"_eq": "agentic-storage-v2"}}, "limit": 1,
        }, admin_required=True, no_cache=True, raise_on_error=True)
        if not rows:
            try:
                await self.directus.create_item("chat_message_archive_rollout", {
                    "id": "agentic-storage-v2", "read_enabled": True, "pruning_enabled": True,
                    "initial_cohort": False, "compatibility_verified": True,
                    "reader_receipt": receipt, "validation_receipt": receipt,
                }, admin_required=True)
            except Exception:
                # Concurrent fixture writers may create the same unique gate.
                rows = await self.directus.get_items("chat_message_archive_rollout", params={
                    "filter": {"id": {"_eq": "agentic-storage-v2"}}, "limit": 1,
                }, admin_required=True, no_cache=True, raise_on_error=True)
                if not rows or rows[0].get("validation_receipt") != receipt:
                    raise
        else:
            gate = rows[0]
            if gate.get("initial_cohort") or gate.get("validation_receipt") != receipt or gate.get("failure_code"):
                raise ArchiveIntegrityError("ISOLATED_ARCHIVE_GATE_MISMATCH")
        if segment["state"] == "verified":
            while not await self.verify_reader_pages(segment):
                pass
            if not await archive_advancement_allowed(self.directus, phase="read"):
                raise ArchiveIntegrityError("ISOLATED_ARCHIVE_RELEASE_OR_CLIENT_GATE_PENDING")
            segment = await self.transaction("activate_segment", {
                "segment_id": segment["id"], "expected_version": segment["version"], "now": int(time.time()),
            })
        # Use the production reader/reverification/SQL fences in bounded
        # batches; fixture isolation does not waive any per-page source fence.
        while True:
            result = await self.advance_segment(segment)
            if result.get("state") == "prune_batch_complete":
                continue
            if result.get("state") == "pruned":
                return result
            raise ArchiveIntegrityError("ISOLATED_ARCHIVE_ADVANCEMENT_DEFERRED")

    async def _copy_page(self, segment: dict[str, Any], number: int, rows: list[dict[str, Any]], now: int) -> None:
        if archive_billing_hold_reason():
            raise ArchiveIntegrityError("ARCHIVE_BILLING_DISABLED")
        digest = hashlib.sha256(encode_record(rows)).hexdigest()
        page_id = str(uuid.uuid5(uuid.UUID(segment["id"]), f"page:{number}:{digest}"))
        key_prefix = f"message-pages/{segment['chat_hash']}/{segment['id']}/{page_id}"
        records, objects, large_objects = [], [], []
        for row in rows:
            encoded = encode_record(row)
            if len(encoded) > PAGE_BYTES // 2:
                key = f"{key_prefix}/large-{hashlib.sha256(str(row['id']).encode()).hexdigest()}.json"
                ref = {"object_key": key, "checksum": hashlib.sha256(encoded).hexdigest(),
                       "size_bytes": len(encoded), "verified_regions": []}
                large_objects.append(ref)
                objects.append((key, encoded, "application/json", ref))
                records.append({"id": row["id"], "client_message_id": row["client_message_id"],
                                "created_at": row["created_at"], "large_payload": ref})
            else:
                records.append(row)
        # The container includes the expected regional set; bytes are immutable.
        regions = sorted(self.s3.region_clients)
        if not regions:
            raise ArchiveIntegrityError("ARCHIVE_NO_CONFIGURED_REGIONS")
        for ref in large_objects:
            ref["verified_regions"] = regions
        raw = encode_record({"format_version": 2, "chat_id": segment["chat_id"], "records": records})
        if len(raw) > PAGE_BYTES + 4096:
            raise ArchiveIntegrityError("ARCHIVE_PAGE_BYTE_BUDGET_EXCEEDED")
        content = gzip.compress(raw, mtime=0)
        key = f"{key_prefix}/page.json.gz"
        page = {"id": page_id, "page_number": number, "object_key": key,
                "source_checksum": digest, "message_count": len(rows),
                "first_timestamp": message_position(rows[0])[0], "first_message_id": message_position(rows[0])[1],
                "last_timestamp": message_position(rows[-1])[0], "last_message_id": message_position(rows[-1])[1],
                "message_ids": [r["client_message_id"] for r in rows], "source_fields": sorted(rows[0]),
                "message_positions": [[message_position(r)[0], message_position(r)[1]] for r in rows],
                "raw_size_bytes": len(raw), "large_objects": large_objects,
                "checksum": hashlib.sha256(content).hexdigest(), "size_bytes": len(content), "verified_regions": []}
        # Register every key BEFORE upload, so crashes and deletion can inventory
        # even partly written pages. This is durable intent, never reader visibility.
        prepared = await self.transaction("prepare_page", {
            "segment_id": segment["id"], "expected_version": segment["version"], "page": page, "now": now,
        })
        if prepared["page"].get("published"):
            return
        import asyncio
        async with asyncio.timeout(60):
            for object_key, payload, content_type, ref in objects:
                metadata = await put_verified_bytes(self.s3, object_key, payload, content_type=content_type)
                if metadata["verified_regions"] != regions:
                    raise ArchiveIntegrityError("ARCHIVE_REGIONAL_CONFIGURATION_CHANGED")
                ref.update(metadata)
            verified = await put_verified_bytes(self.s3, key, content, content_type="application/gzip")
        if verified["verified_regions"] != regions:
            raise ArchiveIntegrityError("ARCHIVE_REGIONAL_CONFIGURATION_CHANGED")
        page.update(verified)
        await self.transaction("publish_page", {
            "segment_id": segment["id"], "expected_version": segment["version"], "page": page,
            "now": int(time.time()),
        })

    async def read_page(self, page: dict[str, Any]) -> list[dict[str, Any]]:
        """Verify a whole small page before returning any ciphertext to clients."""
        compressed = await read_verified_bytes(
            self.s3, page["object_key"], checksum=page["checksum"],
            size_bytes=int(page["size_bytes"]), regions=page["verified_regions"], max_bytes=PAGE_BYTES + 8192,
        )
        # Never gzip.decompress an untrusted object without a decompressed limit.
        import zlib
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
        raw = decoder.decompress(compressed, PAGE_BYTES + 4097)
        if len(raw) > PAGE_BYTES + 4096 or not decoder.eof or decoder.unused_data:
            raise ArchiveIntegrityError("ARCHIVE_PAGE_DECOMPRESSION_BUDGET_EXCEEDED")
        payload = json.loads(raw)
        records = payload.get("records")
        if payload.get("format_version") != 2 or payload.get("chat_id") != page["chat_id"] or not isinstance(records, list) or len(records) != page["message_count"]:
            raise ArchiveIntegrityError("ARCHIVE_PAGE_CONTAINER_INVALID")
        if [r.get("client_message_id") for r in records] != page["message_ids"]:
            raise ArchiveIntegrityError("ARCHIVE_PAGE_IDENTITIES_INVALID")
        return records

    async def hydrate_records(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Admit separately stored large rows under an explicit aggregate budget."""
        result, total = [], 0
        for row in records:
            ref = row.get("large_payload")
            if ref:
                total += int(ref["size_bytes"])
                if total > LARGE_MESSAGE_BYTES:
                    raise ArchiveIntegrityError("ARCHIVE_LARGE_PAYLOAD_WINDOW_BUDGET_EXCEEDED")
                content = await read_verified_bytes(
                    self.s3, ref["object_key"], checksum=ref["checksum"],
                    size_bytes=int(ref["size_bytes"]), regions=ref["verified_regions"], max_bytes=LARGE_MESSAGE_BYTES,
                )
                restored = json.loads(content)
                if restored.get("client_message_id") != row["client_message_id"]:
                    raise ArchiveIntegrityError("ARCHIVE_LARGE_PAYLOAD_IDENTITY_MISMATCH")
                result.append(restored)
            else:
                result.append(row)
        return result

    async def page_metadata(self, *, chat_id: str, before: tuple[int, str] | None = None, limit: int = 2) -> list[dict[str, Any]]:
        """Find a bounded newest-first page window without scanning a transcript."""
        filters: list[dict[str, Any]] = [{"chat_id": {"_eq": chat_id}}, {"read_enabled": {"_eq": True}}]
        if before:
            filters.append({"_or": [
                {"first_timestamp": {"_lt": before[0]}},
                {"_and": [{"first_timestamp": {"_eq": before[0]}}, {"first_message_id": {"_lt": before[1]}}]},
            ]})
        pages = await self.directus.get_items(PAGES, params={
            "filter": {"_and": filters}, "sort": "-last_timestamp,-last_message_id",
            "limit": min(max(limit, 1), 3), "fields": "*",
        }, admin_required=True, no_cache=True, raise_on_error=True)
        if not isinstance(pages, list):
            raise ArchiveIntegrityError("ARCHIVE_PAGE_INDEX_QUERY_FAILED")
        return pages

    async def _read_locator_window(self, *, chat_id: str, cursor: tuple[int, str] | None,
                                   direction: str, limit: int) -> dict[str, Any]:
        """Locate exact message positions, including sparse overlapping pages.

        PostgreSQL expands only compact position tuples, never ciphertext. At
        most twenty selected messages and their distinct pages reach Python.
        Normal adjacent history usually needs one or two physical page reads.
        """
        limit = min(max(int(limit), 1), PAGE_MESSAGES)
        result = await self.transaction("window_locators", {
            "chat_id": chat_id, "direction": direction, "limit": limit,
            "cursor_timestamp": cursor[0] if cursor else None,
            "cursor_message_id": cursor[1] if cursor else None,
        })
        locators, pages = result.get("locators"), result.get("pages")
        if not isinstance(locators, list) or not isinstance(pages, list) or len(locators) > limit or len(pages) > limit:
            raise ArchiveIntegrityError("ARCHIVE_LOCATOR_WINDOW_UNBOUNDED_OR_INVALID")
        wanted = {item["message_id"]: item for item in locators}
        if len(wanted) != len(locators) or any(page.get("chat_id") != chat_id for page in pages):
            raise ArchiveIntegrityError("ARCHIVE_LOCATOR_IDENTITY_INVALID")
        found = {}
        for page in pages:
            for row in await self.read_page(page):
                locator = wanted.get(row["client_message_id"])
                if locator is None:
                    continue
                if locator["page_id"] != page["id"] or message_position(row) != (int(locator["created_at"]), locator["message_id"]):
                    raise ArchiveIntegrityError("ARCHIVE_LOCATOR_POSITION_CHANGED")
                found[row["client_message_id"]] = row
        if set(found) != set(wanted):
            raise ArchiveIntegrityError("ARCHIVE_LOCATOR_MESSAGE_MISSING")
        rows = sorted(found.values(), key=message_position)
        return {"messages": rows, "has_more": bool(result.get("has_more")),
                "archive_page_ids": [page["id"] for page in pages]}

    async def read_before(self, *, chat_id: str, before: tuple[int, str] | None, limit: int) -> dict[str, Any]:
        window = await self._read_locator_window(chat_id=chat_id, cursor=before, direction="before", limit=limit)
        rows = window["messages"]
        has_more = window.pop("has_more")
        return {**window, "has_more_before": has_more,
                "start_cursor": {"created_at": message_position(rows[0])[0], "message_id": message_position(rows[0])[1]} if rows else None}

    async def read_after(self, *, chat_id: str, after: tuple[int, str], limit: int) -> dict[str, Any]:
        window = await self._read_locator_window(chat_id=chat_id, cursor=after, direction="after", limit=limit)
        has_more = window.pop("has_more")
        return {**window, "has_more_after": has_more}

    async def find_message(self, *, chat_id: str, message_id: str, hydrate: bool = True) -> dict[str, Any] | None:
        result = await self.transaction("lookup_message", {"chat_id": chat_id, "message_id": message_id})
        page = result.get("page")
        if not page:
            return None
        for row in await self.read_page(page):
            if row.get("client_message_id") == message_id:
                return (await self.hydrate_records([row]))[0] if hydrate else row
        raise ArchiveIntegrityError("ARCHIVE_MESSAGE_INDEX_INCONSISTENT")

    async def merge_window(
        self, *, chat_id: str, hot: dict[str, Any], direction: str, limit: int,
        before: tuple[int, str] | None = None, after: tuple[int, str] | None = None,
        anchor_message_id: str | None = None, lower_bound_timestamp: int | None = None,
    ) -> dict[str, Any]:
        """Merge one authorized viewing window; hot rows win during copy overlap."""
        limit = min(max(limit, 1), PAGE_MESSAGES)
        cold: dict[str, Any] = {}
        anchor = None
        if direction in {"latest", "before"}:
            cold = await self.read_before(chat_id=chat_id, before=before, limit=limit)
        elif direction == "after" and after is not None:
            cold = await self.read_after(chat_id=chat_id, after=after, limit=limit)
        elif direction == "around" and anchor_message_id:
            anchor = await self.find_message(chat_id=chat_id, message_id=anchor_message_id, hydrate=False)
            if anchor:
                loc = message_position(anchor)
                left = await self.read_before(chat_id=chat_id, before=loc, limit=limit // 2)
                right = await self.read_after(chat_id=chat_id, after=loc, limit=max(1, limit // 2))
                cold = {"messages": [*left["messages"], anchor, *right["messages"]],
                        "archive_page_ids": list(dict.fromkeys([*left["archive_page_ids"], *right["archive_page_ids"]])),
                        "has_more_before": left["has_more_before"], "has_more_after": right["has_more_after"]}
        merged: dict[str, dict[str, Any]] = {}
        cold_ids = set()
        for row in cold.get("messages", []):
            if lower_bound_timestamp is None or message_position(row)[0] > lower_bound_timestamp:
                merged[row["client_message_id"]] = row
                cold_ids.add(row["client_message_id"])
        for item in hot.get("messages", []):
            row = json.loads(item) if isinstance(item, str) else item
            identity = row.get("client_message_id") or row.get("message_id") or row.get("id")
            if identity:
                merged[identity] = {**row, "client_message_id": identity}
        rows = sorted(merged.values(), key=message_position)
        excess = len(rows) > limit
        if direction in {"latest", "before"}:
            rows = rows[-limit:]
        elif direction == "after":
            rows = rows[:limit]
        elif anchor:
            i = next(i for i, r in enumerate(rows) if r["client_message_id"] == anchor_message_id)
            start = max(0, i - limit // 2)
            rows = rows[start:start + limit]
        else:
            rows = rows[:limit]
        from backend.core.api.app.services.bounded_message_window import bound_encrypted_message_window
        admitted = bound_encrypted_message_window({"messages": rows}, direction=direction, anchor_message_id=anchor_message_id if any(r["client_message_id"] == anchor_message_id for r in rows) else None)
        rows = await self.hydrate_records(admitted["messages"])
        oversized = admitted.get("oversized_message_cursor")
        used_cold = any(r["client_message_id"] in cold_ids for r in rows) or bool(oversized and oversized["message_id"] in cold_ids)
        def cursor(r):
            return {"created_at": message_position(r)[0], "message_id": message_position(r)[1]}
        return {**hot, "messages": rows,
                "has_more_before": bool(hot.get("has_more_before") or cold.get("has_more_before") or admitted.get("has_more_before") or (excess and direction != "after")),
                "has_more_after": bool(hot.get("has_more_after") or cold.get("has_more_after") or admitted.get("has_more_after") or (excess and direction == "after")),
                "start_cursor": cursor(rows[0]) if rows else None,
                "end_cursor": cursor(rows[-1]) if rows else None,
                "anchor_found": bool(anchor or hot.get("anchor_found", True)),
                "oversized_message": admitted["oversized_message"], "oversized_message_cursor": oversized,
                "payload_bytes": admitted["payload_bytes"],
                "storage_tier": "mixed" if used_cold and hot.get("messages") else "archive" if used_cold else "hot",
                "archive_payload_cache": "disabled" if used_cold else None,
                "archive_page_ids": cold.get("archive_page_ids", []) if used_cold else []}
