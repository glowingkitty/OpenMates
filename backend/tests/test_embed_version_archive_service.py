"""Opaque version archive copies are verified before they become indexed."""

import hashlib
import json
import json as json_module
import time
from types import SimpleNamespace

import pytest

from backend.core.api.app.services.embed_version_archive_service import (
    activate_version_reader,
    copy_archive_batch,
    copy_and_index_version,
    copy_verified_version,
    prune_version_payload,
    read_archived_version,
)


class FakeStorage:
    environment = "development"
    region_clients = {"eu-a": object(), "eu-b": object()}

    def __init__(self):
        self.objects = {}
        self.bad_region = None
        self.directus_service = object()
        self.deletion_tombstones = []

    async def upload_file(self, bucket_key, key, data, content_type, metadata, region):
        assert bucket_key == "chatfiles"
        assert content_type == "application/json"
        assert metadata["openmates-sha256"] == hashlib.sha256(data).hexdigest()
        self.objects[(region, key)] = data
        return {}

    async def verify_regional_object(self, *, bucket_key, object_key, region, checksum):
        return region != self.bad_region and hashlib.sha256(self.objects[(region, object_key)]).hexdigest() == checksum

    async def get_file(self, bucket, key):
        del bucket
        return self.objects.get(("eu-a", key))

    async def delete_file(self, bucket_key, key):
        assert bucket_key == "chatfiles"
        self.deletion_tombstones.append(key)


class FakeDirectus:
    base_url = "http://directus.test"

    def __init__(self, row):
        self.row = row
        self.updates = []
        self.before_finalize = None
        self.reject_prepare = False

    async def get_items(self, collection, params, **kwargs):
        assert collection == "embed_diffs"
        return [dict(self.row)]

    async def update_item(self, collection, row_id, data):
        assert collection == "embed_diffs" and row_id == self.row["id"]
        self.row.update(data)
        self.updates.append(data)
        return self.row

    async def _make_api_request(self, method, url, headers, json):
        assert method == "POST" and "/embed-version-transaction/archive-" in url
        assert headers["X-Internal-Service-Token"] == "test-token"
        if url.endswith("/archive-activate"):
            self.row.update({"archive_state": "reader_active", "archive_reader_activated_at": 10,
                             "archive_source_copy_until": 86410})
            return SimpleNamespace(status_code=200, json=lambda: {"data": {"status": "reader_active"}})
        if url.endswith("/archive-prune"):
            self.row.update({"archive_state": "pruned", "encrypted_snapshot": None,
                             "encrypted_patch": None})
            return SimpleNamespace(status_code=200, json=lambda: {"data": {"status": "pruned", "pruned_count": 1}})
        if url.endswith("/archive-prepare"):
            if self.reject_prepare:
                return SimpleNamespace(status_code=409, json=lambda: {"error": {"code": "blocked"}})
            self.row.update({"archive_pending_object_key": json["archive_object_key"],
                             "archive_pending_checksum": json["source_checksum"],
                             "archive_copy_lease_until": int(time.time()) + 300,
                             "archive_state": "pruned" if self.row.get("archive_state") == "pruned" else "preparing"})
            return SimpleNamespace(status_code=200, json=lambda: {"data": {
                "status": "preparing", "archive_object_key": json["archive_object_key"]}})
        if url.endswith("/archive-retire"):
            self.row.update({"archive_pending_object_key": None,
                             "archive_pending_checksum": None,
                             "archive_copy_lease_until": None, "archive_state": "stale"})
            return SimpleNamespace(status_code=200, json=lambda: {"data": {"status": "retired"}})
        assert url.endswith("/archive-copy")
        if self.before_finalize:
            self.before_finalize(self.row)
        assert self.row["archive_pending_object_key"] == json["archive_object_key"]
        if self.row.get("archive_state") == "pruned":
            self.row.update({"archive_regions": json["archive_regions"],
                             "archive_pending_object_key": None, "archive_pending_checksum": None,
                             "archive_copy_lease_until": None})
            return SimpleNamespace(status_code=200, json=lambda: {"data": {"status": "pruned"}})
        envelope = {
            "version_number": self.row["version_number"],
            "encrypted_snapshot": self.row.get("encrypted_snapshot"),
            "encrypted_patch": self.row.get("encrypted_patch"),
        }
        checksum = hashlib.sha256(json_module.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if checksum != json["source_checksum"]:
            return SimpleNamespace(status_code=200, json=lambda: {"data": {"status": "stale"}})
        old_key = self.row.get("archive_object_key")
        superseded = old_key if old_key and old_key != json["archive_object_key"] else None
        self.row.update({
            "archive_state": "copied", "archive_object_key": json["archive_object_key"],
            "archive_checksum": checksum, "archive_regions": json["archive_regions"],
            "archive_superseded_object_key": superseded,
            "archive_pending_object_key": None, "archive_pending_checksum": None,
            "archive_copy_lease_until": None,
        })
        return SimpleNamespace(status_code=200, json=lambda: {
            "data": {"status": "copied", "superseded_object_key": superseded},
        })


# contract-test: direct surface=rest_api assertions=storage.versions.metadata-and-payload
@pytest.mark.asyncio
async def test_old_ciphertext_is_copied_to_both_regions_before_indexing_without_prune(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "test-token")
    row = {"id": "row-1", "embed_id": "embed-1", "version_number": 65,
           "encrypted_snapshot": "opaque-snapshot", "encrypted_patch": "opaque-patch",
           "archive_state": None, "snapshot_digest": "digest"}
    storage = FakeStorage()
    directus = FakeDirectus(row)
    locator = await copy_and_index_version(
        directus_service=directus, s3_service=storage, embed_id="embed-1",
        hashed_user_id="owner-hash", version_number=65, current_version=129,
    )
    assert locator["archive_regions"] == ["eu-a", "eu-b"]
    assert len(storage.objects) == 2
    assert row["encrypted_snapshot"] == "opaque-snapshot"
    assert row["encrypted_patch"] == "opaque-patch"
    assert row["archive_pending_object_key"] is None
    payload = await read_archived_version(s3_service=storage, row=row)
    assert payload["encrypted_snapshot"] == "opaque-snapshot"
    assert payload["encrypted_patch"] == "opaque-patch"


# contract-test: direct surface=rest_api assertions=storage.versions.bounded-reconstruction
@pytest.mark.asyncio
async def test_snapshot_race_rejects_stale_copy_and_recopies_with_prior_key_tombstone(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "test-token")
    row = {"id": "row-1", "embed_id": "embed-1", "version_number": 65,
           "encrypted_snapshot": None, "encrypted_patch": "opaque-patch",
           "archive_state": None, "snapshot_digest": None}
    storage = FakeStorage()
    directus = FakeDirectus(row)
    directus.before_finalize = lambda source: source.update({
        "encrypted_snapshot": "late-client-snapshot", "snapshot_digest": "late-digest",
        "archive_state": "stale",
    })
    with pytest.raises(RuntimeError, match="source fence"):
        await copy_and_index_version(
            directus_service=directus, s3_service=storage, embed_id="embed-1",
            hashed_user_id="owner-hash", version_number=65, current_version=129,
        )
    assert row.get("archive_object_key") is None
    assert row["archive_pending_object_key"] in {key for _, key in storage.objects}
    row["archive_copy_lease_until"] = 1
    directus.before_finalize = None
    first = await copy_and_index_version(
        directus_service=directus, s3_service=storage, embed_id="embed-1",
        hashed_user_id="owner-hash", version_number=65, current_version=129,
    )
    row.update({"encrypted_snapshot": "newer-client-snapshot", "snapshot_digest": "newer-digest", "archive_state": "stale"})
    second = await copy_and_index_version(
        directus_service=directus, s3_service=storage, embed_id="embed-1",
        hashed_user_id="owner-hash", version_number=65, current_version=129,
    )
    assert first["archive_object_key"] != second["archive_object_key"]
    assert storage.deletion_tombstones[-1] == first["archive_object_key"]
    assert len(storage.deletion_tombstones) == 2  # stale pending key, then superseded canonical copy
    assert row["archive_superseded_object_key"] is None


# contract-test: direct surface=rest_api assertions=storage.versions.bounded-reconstruction
@pytest.mark.asyncio
async def test_pruned_version_expands_to_new_region_from_verified_ciphertext(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "test-token")
    row = {"id": "row-1", "embed_id": "embed-1", "version_number": 1,
           "encrypted_snapshot": "opaque-snapshot", "encrypted_patch": None,
           "archive_state": None, "snapshot_digest": None}
    storage = FakeStorage()
    directus = FakeDirectus(row)
    await copy_and_index_version(
        directus_service=directus, s3_service=storage, embed_id="embed-1",
        hashed_user_id="owner-hash", version_number=1, current_version=65,
    )
    row.update({"archive_state": "pruned", "encrypted_snapshot": None,
                "encrypted_patch": None})
    old_key = row["archive_object_key"]
    storage.region_clients = {**storage.region_clients, "eu-c": object()}

    result = await copy_and_index_version(
        directus_service=directus, s3_service=storage, embed_id="embed-1",
        hashed_user_id="owner-hash", version_number=1, current_version=65,
    )
    assert result["archive_state"] == "pruned"
    assert row["archive_object_key"] == old_key
    assert set(row["archive_regions"]) == {"eu-a", "eu-b", "eu-c"}
    assert ("eu-c", old_key) in storage.objects
    assert (await read_archived_version(s3_service=storage, row=row))["encrypted_snapshot"] == "opaque-snapshot"


# contract-test: direct surface=rest_api assertions=storage.versions.bounded-reconstruction
@pytest.mark.asyncio
async def test_reader_activation_and_prune_verify_archive_and_leave_metadata(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "test-token")
    monkeypatch.setenv("EMBED_VERSION_ARCHIVE_COPY_ENABLED", "1")
    monkeypatch.setenv("EMBED_VERSION_ARCHIVE_READ_ENABLED", "1")
    monkeypatch.setenv("EMBED_VERSION_ARCHIVE_PRUNE_ENABLED", "1")
    row = {"id": "row-1", "embed_id": "embed-1", "version_number": 1,
           "encrypted_snapshot": "opaque-snapshot", "encrypted_patch": None,
           "archive_state": None, "snapshot_digest": None, "has_snapshot": True}
    storage = FakeStorage()
    directus = FakeDirectus(row)
    await copy_and_index_version(
        directus_service=directus, s3_service=storage, embed_id="embed-1",
        hashed_user_id="owner-hash", version_number=1, current_version=65,
    )
    activated = await activate_version_reader(
        directus_service=directus, s3_service=storage, embed_id="embed-1",
        hashed_user_id="owner-hash", version_number=1,
    )
    assert activated["status"] == "reader_active"
    pruned = await prune_version_payload(
        directus_service=directus, s3_service=storage, embed_id="embed-1",
        hashed_user_id="owner-hash", version_number=1,
    )
    assert pruned["pruned_count"] == 1
    assert row["encrypted_snapshot"] is None
    assert row["has_snapshot"] is True
    assert (await read_archived_version(s3_service=storage, row=row))["encrypted_snapshot"] == "opaque-snapshot"


# contract-test: direct surface=rest_api assertions=storage.versions.bounded-reconstruction
@pytest.mark.asyncio
async def test_prune_service_rejects_unverified_region_and_changed_hot_source(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "test-token")
    monkeypatch.setenv("EMBED_VERSION_ARCHIVE_COPY_ENABLED", "1")
    monkeypatch.setenv("EMBED_VERSION_ARCHIVE_READ_ENABLED", "1")
    monkeypatch.setenv("EMBED_VERSION_ARCHIVE_PRUNE_ENABLED", "1")
    row = {"id": "row-1", "embed_id": "embed-1", "version_number": 1,
           "encrypted_snapshot": "opaque-snapshot", "encrypted_patch": None,
           "archive_state": None, "snapshot_digest": None}
    storage = FakeStorage()
    directus = FakeDirectus(row)
    await copy_and_index_version(
        directus_service=directus, s3_service=storage, embed_id="embed-1",
        hashed_user_id="owner-hash", version_number=1, current_version=65,
    )
    row.update({"archive_state": "reader_active", "archive_reader_activated_at": 10,
                "archive_source_copy_until": 11})
    storage.bad_region = "eu-b"
    with pytest.raises(RuntimeError, match="regional verification"):
        await prune_version_payload(
            directus_service=directus, s3_service=storage, embed_id="embed-1",
            hashed_user_id="owner-hash", version_number=1,
        )
    storage.bad_region = None
    row["encrypted_snapshot"] = "changed"
    with pytest.raises(RuntimeError, match="source changed"):
        await prune_version_payload(
            directus_service=directus, s3_service=storage, embed_id="embed-1",
            hashed_user_id="owner-hash", version_number=1,
        )


# contract-test: direct surface=rest_api assertions=storage.versions.metadata-and-payload
@pytest.mark.asyncio
async def test_missing_region_or_tampered_envelope_never_becomes_authoritative():
    row = {"embed_id": "embed-1", "version_number": 1,
           "encrypted_snapshot": "opaque", "encrypted_patch": None}
    storage = FakeStorage()
    storage.bad_region = "eu-b"
    with pytest.raises(RuntimeError, match="not verified"):
        await copy_verified_version(s3_service=storage, row=row)
    storage.bad_region = None
    locator = await copy_verified_version(s3_service=storage, row=row)
    storage.objects[("eu-a", locator["archive_object_key"])] = json.dumps({"version_number": 1}).encode()
    with pytest.raises(RuntimeError, match="checksum"):
        await read_archived_version(s3_service=storage, row={**row, **locator})


# contract-test: direct surface=rest_api assertions=storage.versions.metadata-and-payload
@pytest.mark.asyncio
async def test_recent_window_cannot_be_copied_as_older_history():
    with pytest.raises(ValueError, match="recent"):
        await copy_and_index_version(
            directus_service=FakeDirectus({}), s3_service=FakeStorage(),
            embed_id="embed-1", hashed_user_id="owner-hash",
            version_number=99, current_version=100,
        )


# contract-test: direct surface=rest_api assertions=storage.versions.metadata-and-payload
@pytest.mark.asyncio
async def test_copy_scheduler_scans_one_bounded_page_and_skips_recent_payloads(monkeypatch):
    rows = [
        {"id": "1", "embed_id": "embed-1", "hashed_user_id": "owner", "version_number": 1, "archive_state": None},
        {"id": "2", "embed_id": "embed-1", "hashed_user_id": "owner", "version_number": 99, "archive_state": None},
    ]
    calls = []

    class Directus:
        class embed:
            @staticmethod
            async def get_embed_by_id(embed_id):
                assert embed_id == "embed-1"
                return {"hashed_user_id": "owner", "version_number": 100}

        async def get_items(self, collection, params, **kwargs):
            assert collection == "embed_diffs"
            assert params["limit"] == 2
            return rows

    async def copy_one(**kwargs):
        calls.append(kwargs["version_number"])

    monkeypatch.setattr(
        "backend.core.api.app.services.embed_version_archive_service.copy_and_index_version",
        copy_one,
    )
    result = await copy_archive_batch(
        directus_service=Directus(), s3_service=FakeStorage(), limit=2,
    )
    assert calls == [1]
    assert result == {"copied": 1, "skipped": 1, "failed": 0, "next_cursor": "2"}
