"""Bounded message pages, integrity failures, and mixed-tier scrollback."""
from __future__ import annotations

import base64
import gzip
import hashlib
import uuid

import pytest

from backend.core.api.app.services.bounded_archive_io import ArchiveIntegrityError, read_verified_bytes, put_verified_bytes
from backend.core.api.app.services.chat_message_archive_service import (
    ChatMessageArchiveService, LARGE_MESSAGE_BYTES, PAGE_BYTES,
    bounded_message_pages, encode_record,
)


class ObjectStore:
    region_clients = {"nbg1": object(), "fsn1": object()}
    environment = "development"

    def __init__(self):
        self.region_clients = dict(type(self).region_clients)
        self.data = {}
        self.reads = []
        self.fail_region = None

    async def upload_file(self, *, file_key, content, region, **kwargs):
        if region == self.fail_region:
            raise OSError("regional outage")
        self.data[region, file_key] = content

    async def verify_regional_object(self, *, object_key, region, checksum, **kwargs):
        return hashlib.sha256(self.data[region, object_key]).hexdigest() == checksum

    async def get_replicated_file_stream(self, *, object_key, regions, chunk_size, **kwargs):
        self.reads.append(object_key)
        content = self.data[regions[0], object_key]
        for i in range(0, len(content), chunk_size):
            yield content[i:i + chunk_size]


def record(n, size=100):
    return {"id": str(uuid.UUID(int=n + 1)), "chat_id": "chat", "client_message_id": f"m{n:04}",
            "created_at": 100 + n // 3, "updated_at": 100 + n // 3, "role": "assistant",
            "encrypted_content": base64.b64encode(hashlib.shake_256(str(n).encode()).digest(size)).decode()}


class PageService(ChatMessageArchiveService):
    def __init__(self, s3):
        super().__init__(directus_service=object(), s3_service=s3)
        self.pages = []

    async def transaction(self, operation, data):
        if operation == "window_locators":
            cursor = (data["cursor_timestamp"], data["cursor_message_id"]) if data["cursor_timestamp"] is not None else None
            locators = [{"page_id": page["id"], "created_at": pos[0], "message_id": pos[1]}
                        for page in self.pages for pos in page["message_positions"]
                        if cursor is None or ((tuple(pos) < cursor) if data["direction"] == "before" else (tuple(pos) > cursor))]
            locators.sort(key=lambda r: (r["created_at"], r["message_id"]), reverse=data["direction"] == "before")
            selected = locators[:data["limit"]]
            wanted_pages = {r["page_id"] for r in selected}
            return {"locators": selected, "pages": [p for p in self.pages if p["id"] in wanted_pages],
                    "has_more": len(locators) > data["limit"]}
        if operation == "prepare_page":
            return {"page": {**data["page"], "published": False}}
        assert operation == "publish_page"
        page = {**data["page"], "chat_id": "chat"}
        self.pages.append(page)
        return {"page": page}

    async def page_metadata(self, *, before=None, limit=2, **kwargs):
        pages = [p for p in self.pages if before is None or (p["first_timestamp"], p["first_message_id"]) < before]
        return list(reversed(pages))[:limit]


# contract-test: direct surface=rest_api assertions=storage.cold.independent-message-pages
def test_pages_bound_count_and_bytes_without_rewriting_message_identities():
    original = [record(n, 9000) for n in range(85)]
    pages = bounded_message_pages(original)
    assert [row["client_message_id"] for p in pages for row in p] == [r["client_message_id"] for r in original]
    assert all(len(p) <= 20 and sum(len(encode_record(r)) + 1 for r in p) + 2 <= PAGE_BYTES for p in pages)


# contract-test: direct surface=rest_api assertions=storage.cold.independent-message-pages
def test_unsupported_legacy_oversize_keeps_source_eligible_for_a_future_reader():
    with pytest.raises(ArchiveIntegrityError, match="LEGACY_MESSAGE_REQUIRES_BOUNDED_READER"):
        bounded_message_pages([record(1, LARGE_MESSAGE_BYTES)])


# contract-test: direct surface=rest_api assertions=storage.cold.atomic-eligible-graphs
@pytest.mark.asyncio
async def test_failed_second_region_never_claims_a_verified_copy():
    s3 = ObjectStore()
    s3.fail_region = "fsn1"
    with pytest.raises(OSError, match="regional outage"):
        await put_verified_bytes(s3, "page", b"ciphertext")


# contract-test: direct surface=rest_api assertions=storage.cold.independent-message-pages,storage.integrity.observable-reconcilable
@pytest.mark.asyncio
async def test_bounded_reader_rejects_corruption_truncation_and_oversized_stream():
    s3 = ObjectStore()
    expected = b"encrypted-message-container"
    ref = await put_verified_bytes(s3, "page", expected)
    for replacement in (b"x" * len(expected), expected[:-1], expected + b"extra"):
        s3.data["fsn1", "page"] = replacement
        with pytest.raises(ArchiveIntegrityError):
            await read_verified_bytes(s3, "page", checksum=ref["checksum"], size_bytes=ref["size_bytes"], regions=["fsn1"], max_bytes=100)
    reads_before = len(s3.reads)
    with pytest.raises(ArchiveIntegrityError):
        await read_verified_bytes(s3, "page", checksum=ref["checksum"], size_bytes=ref["size_bytes"], regions=["fsn1"], max_bytes=1)
    assert len(s3.reads) == reads_before


# contract-test: direct surface=rest_api assertions=storage.cold.independent-message-pages
@pytest.mark.asyncio
async def test_scrolling_downloads_only_requested_pages_and_stable_timestamp_ties():
    s3, rows = ObjectStore(), [record(n) for n in range(60)]
    service = PageService(s3)
    segment = {"id": str(uuid.uuid4()), "chat_id": "chat", "chat_hash": "hash", "version": 1}
    for n, batch in enumerate(bounded_message_pages(rows), 1):
        await service._copy_page(segment, n, batch, 1)
    recent = await service.read_before(chat_id="chat", before=None, limit=5)
    assert [r["client_message_id"] for r in recent["messages"]] == [r["client_message_id"] for r in rows[-5:]]
    assert len(s3.reads) == 1  # only the selected page, never the three-page transcript
    cursor = recent["start_cursor"]
    earlier = await service.read_before(chat_id="chat", before=(cursor["created_at"], cursor["message_id"]), limit=5)
    assert [r["client_message_id"] for r in earlier["messages"]] == [r["client_message_id"] for r in rows[-10:-5]]


# contract-test: direct surface=rest_api assertions=storage.cold.independent-message-pages
@pytest.mark.asyncio
async def test_large_payload_is_separate_and_only_loaded_when_selected():
    service, s3 = PageService(ObjectStore()), None
    s3 = service.s3
    large = record(1, 110000)
    segment = {"id": str(uuid.uuid4()), "chat_id": "chat", "chat_hash": "hash", "version": 1}
    await service._copy_page(segment, 1, [large], 1)
    small_page = await service.read_page(service.pages[0])
    assert "large_payload" in small_page[0]
    assert s3.reads == [service.pages[0]["object_key"]]
    assert await service.hydrate_records(small_page) == [large]


# contract-test: direct surface=rest_api assertions=storage.integrity.observable-reconcilable
@pytest.mark.asyncio
async def test_verified_compressed_bomb_is_rejected_before_unbounded_allocation():
    service = PageService(ObjectStore())
    compressed = gzip.compress(b" " * (PAGE_BYTES * 5))
    ref = await put_verified_bytes(service.s3, "bomb", compressed)
    with pytest.raises(ArchiveIntegrityError, match="DECOMPRESSION_BUDGET"):
        await service.read_page({"object_key": "bomb", **ref, "chat_id": "chat", "message_count": 1, "message_ids": ["m"]})


# contract-test: direct surface=rest_api assertions=storage.cold.discoverable-bounded,storage.cold.rehydrate-on-mutation
@pytest.mark.asyncio
async def test_mixed_window_prefers_newer_hot_content_without_duplicate_messages():
    service = PageService(ObjectStore())
    rows = [record(n) for n in range(30)]
    segment = {"id": str(uuid.uuid4()), "chat_id": "chat", "chat_hash": "hash", "version": 1}
    for n, batch in enumerate(bounded_message_pages(rows), 1):
        await service._copy_page(segment, n, batch, 1)
    changed = {**rows[-1], "encrypted_content": "new-client-ciphertext"}
    window = await service.merge_window(chat_id="chat", hot={"messages": [changed], "has_more_before": False}, direction="latest", limit=5)
    assert len(window["messages"]) == 5
    assert len({r["client_message_id"] for r in window["messages"]}) == 5
    assert window["messages"][-1]["encrypted_content"] == "new-client-ciphertext"
    assert window["archive_page_ids"] and window["archive_payload_cache"] == "disabled"


class LifecycleDirectus:
    def __init__(self, service):
        self.service = service
        self.gate = {"read_enabled": True, "pruning_enabled": False, "compatibility_verified": True,
                     "reader_receipt": "reviewed-read", "validation_receipt": None, "initial_cohort": True}
        self.queries = []

    async def get_items(self, collection, *, params, **kwargs):
        self.queries.append((collection, params))
        if collection == "chat_message_archive_rollout":
            return [self.gate]
        assert collection == "chat_message_archive_pages"
        assert params["limit"] <= 25
        rows = self.service.pages
        if "reader_verified" in params["filter"]:
            rows = [p for p in rows if not p.get("reader_verified")]
        if "pruned" in params["filter"]:
            rows = [p for p in rows if not p.get("pruned")]
        return rows[:params["limit"]]


class LifecycleService(PageService):
    def __init__(self, s3):
        super().__init__(s3)
        self.directus = LifecycleDirectus(self)
        self.calls = []

    async def transaction(self, operation, data):
        if operation in {"prepare_page", "publish_page", "window_locators"}:
            return await super().transaction(operation, data)
        self.calls.append(operation)
        if operation == "record_reader_verification":
            page = next(p for p in self.pages if p["id"] == data["page_id"])
            assert page["checksum"] == data["checksum"]
            page["reader_verified"] = True
            return {"reader_verified": True}
        if operation == "activate_segment":
            assert all(p.get("reader_verified") for p in self.pages)
            return {"id": data["segment_id"], "version": data["expected_version"] + 1,
                    "state": "reader_active", "source_copy_until": 10**12}
        if operation == "prune_page":
            next(p for p in self.pages if p["id"] == data["page_id"])["pruned"] = True
            return {"pruned": True}
        raise AssertionError(operation)


async def lifecycle_fixture(page_count=1, size=100):
    service = LifecycleService(ObjectStore())
    segment = {"id": str(uuid.uuid4()), "chat_id": "chat", "chat_hash": "hash", "version": 2, "state": "verified"}
    for n in range(page_count):
        await service._copy_page(segment, n + 1, [record(n, size)], 1)
    return service, segment


# contract-test: direct surface=rest_api assertions=storage.integrity.observable-reconcilable,storage.rollout.verified-24-hour-buffer
@pytest.mark.asyncio
async def test_reader_verification_resumes_bounded_batches_after_worker_restart(monkeypatch):
    monkeypatch.setenv("CHAT_MESSAGE_ARCHIVE_READS_ENABLED", "1")
    service, segment = await lifecycle_fixture(26)
    first = await service.advance_segment(segment)
    assert first["state"] == "reader_verification_pending"
    assert service.calls.count("record_reader_verification") == 25
    assert "activate_segment" not in service.calls
    restarted = LifecycleService(service.s3)
    restarted.pages = service.pages  # persisted rows, not a process-local cursor
    second = await restarted.advance_segment(segment)
    assert second["state"] == "reader_active"
    assert restarted.calls == ["record_reader_verification", "activate_segment"]
    assert len(service.s3.reads) == 26


# contract-test: direct surface=rest_api assertions=storage.rollout.verified-24-hour-buffer,storage.integrity.observable-reconcilable
@pytest.mark.asyncio
async def test_prune_rechecks_object_integrity_and_keeps_pg_when_an_object_changes(monkeypatch):
    monkeypatch.setenv("CHAT_MESSAGE_ARCHIVE_PRUNE_ENABLED", "1")
    service, segment = await lifecycle_fixture()
    service.directus.gate.update(pruning_enabled=True, validation_receipt="reviewed-capacity")
    segment.update(state="reader_active", source_copy_until=1)
    for region in service.s3.region_clients:
        service.s3.data[region, service.pages[0]["object_key"]] = b"corrupt"
    with pytest.raises(ArchiveIntegrityError):
        await service.advance_segment(segment)
    assert "prune_page" not in service.calls


# contract-test: direct surface=rest_api assertions=storage.cold.atomic-eligible-graphs,storage.integrity.observable-reconcilable
@pytest.mark.asyncio
@pytest.mark.parametrize("large", [False, True])
@pytest.mark.parametrize("missing", [False, True])
async def test_surviving_replica_allows_reads_but_degraded_replication_never_allows_prune(monkeypatch, large, missing):
    monkeypatch.setenv("CHAT_MESSAGE_ARCHIVE_PRUNE_ENABLED", "1")
    service, segment = await lifecycle_fixture(size=400000 if large else 100)
    service.directus.gate.update(pruning_enabled=True, validation_receipt="reviewed-capacity")
    segment.update(state="reader_active", source_copy_until=1)
    page = service.pages[0]
    reference = page["large_objects"][0] if large else page
    key = ("nbg1", reference["object_key"])
    if missing:
        del service.s3.data[key]
    else:
        service.s3.data[key] = b"corrupt"
    # Read failover is preserved while PostgreSQL remains the rollback copy.
    assert await service.hydrate_records(await service.read_page(page)) == [record(0, 400000 if large else 100)]
    with pytest.raises(ArchiveIntegrityError, match="PRUNE_REGION"):
        await service.advance_segment(segment)
    assert "prune_page" not in service.calls


# contract-test: direct surface=rest_api assertions=storage.rollout.verified-24-hour-buffer
@pytest.mark.asyncio
async def test_missing_receipts_buffer_and_new_region_never_allow_pruning(monkeypatch):
    monkeypatch.setenv("CHAT_MESSAGE_ARCHIVE_PRUNE_ENABLED", "1")
    service, segment = await lifecycle_fixture()
    segment.update(state="reader_active", source_copy_until=1)
    assert (await service.advance_segment(segment))["state"] == "prune_receipt_missing"
    assert not service.s3.reads
    service.directus.gate.update(pruning_enabled=True, validation_receipt="reviewed-capacity")
    segment["source_copy_until"] = 10**12
    assert (await service.advance_segment(segment))["state"] == "rollback_buffer_active"
    assert not service.s3.reads
    segment["source_copy_until"] = 1
    service.s3.region_clients["new-region"] = object()
    with pytest.raises(ArchiveIntegrityError, match="CONFIGURED_REGION_NOT_VERIFIED"):
        await service.advance_segment(segment)
    assert not service.s3.reads and "prune_page" not in service.calls


# contract-test: direct surface=rest_api assertions=storage.cold.independent-message-pages,storage.cold.discoverable-bounded
@pytest.mark.asyncio
async def test_ordinary_archive_window_does_not_download_a_large_body_before_exact_read():
    service, _segment = await lifecycle_fixture(size=400000)
    window = await service.merge_window(chat_id="chat", hot={"messages": []}, direction="latest", limit=20)
    assert window["messages"] == []
    assert window["oversized_message_cursor"]["message_id"] == "m0000"
    assert window["oversized_message"] is True
    assert len(service.s3.reads) == 1
    assert service.s3.reads[0] == service.pages[0]["object_key"]
    # The selected record remains complete behind a separately bounded read.
    row = (await service.hydrate_records(await service.read_page(service.pages[0])))[0]
    assert row["encrypted_content"] == record(0, 400000)["encrypted_content"]


# contract-test: direct surface=rest_api assertions=storage.cold.discoverable-bounded,storage.cold.independent-message-pages
@pytest.mark.asyncio
async def test_sparse_overlapping_archive_pages_never_skip_messages_at_a_cursor():
    service = PageService(ObjectStore())
    segment = {"id": str(uuid.uuid4()), "chat_id": "chat", "chat_hash": "hash", "version": 1}
    batches = [[{**record(t), "created_at": t} for t in positions]
               for positions in ([10, 100], [20, 99], [96, 97])]
    for number, batch in enumerate(batches, 1):
        await service._copy_page(segment, number, batch, 1)
    latest = await service.read_before(chat_id="chat", before=None, limit=3)
    assert [r["created_at"] for r in latest["messages"]] == [97, 99, 100]
    cursor = latest["start_cursor"]
    previous = await service.read_before(chat_id="chat", before=(cursor["created_at"], cursor["message_id"]), limit=3)
    assert [r["created_at"] for r in previous["messages"]] == [10, 20, 96]
    first = await service.read_after(chat_id="chat", after=(0, ""), limit=3)
    assert [r["created_at"] for r in first["messages"]] == [10, 20, 96]
    last = first["messages"][-1]
    following = await service.read_after(chat_id="chat", after=(last["created_at"], last["client_message_id"]), limit=3)
    assert [r["created_at"] for r in following["messages"]] == [97, 99, 100]
