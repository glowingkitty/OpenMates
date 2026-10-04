"""Focused guards and failure cleanup for the isolated Directus write proof."""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
from pathlib import Path
import stat
from types import SimpleNamespace
import uuid

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "storage_accountability_integration.py"
spec = importlib.util.spec_from_file_location("storage_accountability_integration", MODULE_PATH)
probe = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(probe)


class FakeDirectus:
    base_url = "http://cms:8055"

    def __init__(self, audit_on: str | None = None):
        self.rows = {collection: {} for collection in probe.COLLECTIONS}
        self.meta = {collection: None for collection in probe.COLLECTIONS}
        self.audit = {name: {} for name in ("directus_activity", "directus_revisions")}
        self.audit_on = audit_on
        self.updated = []

    def record_audit(self, collection, row_id):
        if self.meta[collection] == "all":
            for kind in self.audit:
                self.audit[kind].setdefault((collection, row_id), []).append({
                    "id": str(uuid.uuid4()), "collection": collection, "item": row_id,
                    "synthetic": "x" * 32,
                })

    async def ensure_auth_token(self, admin_required=False):
        assert admin_required
        return "synthetic-admin-token"

    async def _make_api_request(self, method, url, headers=None, json=None):
        assert headers == {"Authorization": "Bearer synthetic-admin-token"}
        path = url.removeprefix(self.base_url + "/")
        if method == "GET" and path.startswith("collections/"):
            collection = path.split("/")[1]
            return SimpleNamespace(status_code=200, json=lambda: {"data": {"meta": {
                "accountability": self.meta[collection]}}})
        assert method == "PATCH"
        if path.startswith("collections/"):
            collection = path.split("/")[1]
            self.meta[collection] = json["meta"]["accountability"]
            return SimpleNamespace(status_code=200)
        _, collection, row_id = path.split("/")
        assert row_id in self.rows[collection]
        self.rows[collection][row_id].update(json)
        self.updated.append(collection)
        self.record_audit(collection, row_id)
        return SimpleNamespace(status_code=200)

    async def get_items(self, collection, params=None, **kwargs):
        assert kwargs == {"admin_required": True, "no_cache": True, "raise_on_error": True}
        if collection in {"directus_activity", "directus_revisions"}:
            filters = params["filter"]["_and"]
            target_collection = filters[0]["collection"]["_eq"]
            target_id = filters[1]["item"]["_eq"]
            if self.audit_on == target_collection and target_id in self.rows[target_collection]:
                return [{"id": "synthetic-audit"}]
            return self.audit[collection].get((target_collection, target_id), [])[:params["limit"]]
        row_id = params["filter"]["id"]["_eq"]
        return [self.rows[collection][row_id]] if row_id in self.rows[collection] else []

    async def create_item(self, collection, row, admin_required=False):
        assert admin_required and row["id"] not in self.rows[collection]
        self.rows[collection][row["id"]] = dict(row)
        self.record_audit(collection, row["id"])
        return True, dict(row)

    async def delete_item(self, collection, row_id, admin_required=False):
        assert admin_required
        del self.rows[collection][row_id]
        self.record_audit(collection, row_id)
        return True


# contract-test: infrastructure
def test_profile_and_private_selector_require_exact_source(tmp_path, monkeypatch):
    source = "a" * 40
    environ = {
        "OPENMATES_CI_ISOLATED": "1", "OPENMATES_CI_STORAGE_ACCOUNTABILITY": "1",
        "CI": "true", "SERVER_ENVIRONMENT": "development",
        "OPENMATES_DEPLOYMENT_MODE": "self_host", "MOCK_EXTERNAL_APIS": "true",
        "CMS_URL": "http://cms:8055", "BUILD_COMMIT_SHA": source,
        "DIRECTUS_TOKEN": "synthetic", "DATABASE_ADMIN_EMAIL": "runtime@example.com",
        "DATABASE_ADMIN_PASSWORD": "synthetic",
        "DB_HOST": "cms-database", "DB_DATABASE": "openmates", "DB_USER": "openmates",
        "OPENMATES_CI_PRIVATE_HOST_UID": str(os.getuid()),
        "OPENMATES_CI_PRIVATE_HOST_GID": str(os.getgid()),
    }
    assert probe.require_isolated_profile(environ) == source
    for key in ("OPENMATES_CI_ISOLATED", "OPENMATES_CI_STORAGE_ACCOUNTABILITY",
                "CI", "MOCK_EXTERNAL_APIS", "BUILD_COMMIT_SHA",
                "DATABASE_ADMIN_EMAIL", "DB_HOST", "DB_DATABASE", "DB_USER",
                "OPENMATES_CI_PRIVATE_HOST_UID", "OPENMATES_CI_PRIVATE_HOST_GID"):
        bad = dict(environ)
        bad[key] = "wrong"
        with pytest.raises(ValueError):
            probe.require_isolated_profile(bad)
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    monkeypatch.setattr(probe, "PRIVATE_DIR", private)
    selector = private / "selector.json"
    payload = {"schema": probe.SELECTOR_SCHEMA, "source_commit": source,
               "fixture_prefix": f"ci-accountability/{uuid.uuid4()}"}
    selector.write_text(json.dumps(payload))
    selector.chmod(0o600)
    host = {"host_uid": os.getuid(), "host_gid": os.getgid()}
    assert probe.load_selector(selector, source, **host) == payload
    with pytest.raises(ValueError, match="mismatch"):
        probe.load_selector(selector, "b" * 40, **host)
    with pytest.raises(ValueError, match="private"):
        probe.load_selector(selector, source, host_uid=os.getuid() + 1, host_gid=os.getgid())
    selector.chmod(0o644)
    with pytest.raises(ValueError, match="private"):
        probe.load_selector(selector, source, **host)
    selector.chmod(0o600)
    private.chmod(0o755)
    with pytest.raises(ValueError, match="private"):
        probe.load_selector(selector, source, **host)


# contract-test: infrastructure
def test_receipt_keeps_mode_0600_and_matches_private_host_owner(tmp_path, monkeypatch):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    monkeypatch.setattr(probe, "PRIVATE_DIR", private)
    receipt = private / "receipt.json"
    owner = {"host_uid": os.getuid(), "host_gid": os.getgid()}
    probe.write_private_receipt(receipt, {"schema": "synthetic"}, **owner)
    info = receipt.stat()
    assert (info.st_uid, info.st_gid) == (os.getuid(), os.getgid())
    assert stat.S_IMODE(info.st_mode) == 0o600
    assert json.loads(receipt.read_text()) == {"schema": "synthetic"}
    with pytest.raises(ValueError, match="owner_mismatch"):
        probe.write_private_receipt(private / "wrong.json", {},
                                    host_uid=os.getuid() + 1, host_gid=os.getgid())
    assert not (private / "wrong.json").exists()


# contract-test: infrastructure
def test_receipt_chown_failure_removes_only_new_empty_file(tmp_path, monkeypatch):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    monkeypatch.setattr(probe, "PRIVATE_DIR", private)
    receipt = private / "receipt.json"

    def fail_chown(*_args):
        raise PermissionError("synthetic_fchown_denied")

    monkeypatch.setattr(probe.os, "fchown", fail_chown)
    with pytest.raises(PermissionError, match="synthetic_fchown_denied"):
        probe.write_private_receipt(receipt, {}, host_uid=os.getuid(), host_gid=os.getgid())
    assert not receipt.exists()


# contract-test: infrastructure
def test_five_realistic_writes_preserve_product_diff_and_no_generic_audit():
    fake = FakeDirectus()
    result = asyncio.run(probe.prove(fake, {"fixture_prefix": f"ci-accountability/{uuid.uuid4()}"}))
    assert fake.updated == list(probe.COLLECTIONS) * 2
    assert all(not rows for rows in fake.rows.values())
    assert result["audit_before"] == {name: (0, 0) for name in probe.COLLECTIONS}
    assert result["audit_after"] == result["audit_before"]
    assert result["audit_after_cleanup"] == result["audit_before"]
    assert result["product_embed_diffs_persisted"] is True
    assert result["cleanup_complete"] is True
    assert all(value is None for value in fake.meta.values())
    comparison = result["comparison"]
    assert comparison["metadata_restored_to_null"] is True
    assert comparison["all_fixture_cleanup_complete"] is True
    assert comparison["audit_bytes_kind"] == "serialized_json_utf8_not_postgres_relation_bytes"
    assert set(comparison["null_write_elapsed_ms"]) == set(probe.COLLECTIONS)
    assert set(comparison["all_write_elapsed_ms"]) == set(probe.COLLECTIONS)
    assert all(comparison["null_audit"][name][key][kind] == 0
               for name in probe.COLLECTIONS for key in ("counts", "serialized_json_bytes")
               for kind in ("activity", "revisions"))
    assert all(comparison["all_audit"][name]["counts"][kind] >= 1
               and comparison["all_audit"][name]["serialized_json_bytes"][kind] > 0
               for name in probe.COLLECTIONS for kind in ("activity", "revisions"))


# contract-test: infrastructure
def test_detected_audit_row_fails_closed_and_cleans_all_created_rows():
    fake = FakeDirectus(audit_on="messages")
    with pytest.raises(RuntimeError, match="accountability_generic_audit_created"):
        asyncio.run(probe.prove(fake, {"fixture_prefix": f"ci-accountability/{uuid.uuid4()}"}))
    assert all(not rows for rows in fake.rows.values())


# contract-test: infrastructure
def test_lost_create_receipt_still_cleans_committed_row():
    class LostReceiptDirectus(FakeDirectus):
        async def create_item(self, collection, row, admin_required=False):
            await super().create_item(collection, row, admin_required=admin_required)
            return False, {"error": "synthetic lost receipt"}

    fake = LostReceiptDirectus()
    with pytest.raises(RuntimeError, match="accountability_fixture_create_failed"):
        asyncio.run(probe.prove(fake, {"fixture_prefix": f"ci-accountability/{uuid.uuid4()}"}))
    assert all(not rows for rows in fake.rows.values())


# contract-test: infrastructure
def test_changed_owner_marker_prevents_deletion_of_unknown_row():
    class ChangedOwnerDirectus(FakeDirectus):
        async def _make_api_request(self, method, url, headers=None, json=None):
            response = await super()._make_api_request(method, url, headers=headers, json=json)
            if method == "PATCH" and "/items/messages/" in url:
                for row in self.rows["messages"].values():
                    row["hashed_user_id"] = "foreign-owner"
            return response

    fake = ChangedOwnerDirectus()
    with pytest.raises(RuntimeError, match="accountability_fixture_cleanup_failed"):
        asyncio.run(probe.prove(fake, {"fixture_prefix": f"ci-accountability/{uuid.uuid4()}"}))
    assert len(fake.rows["messages"]) == 1
    assert all(not rows for name, rows in fake.rows.items() if name != "messages")


# contract-test: infrastructure
def test_changed_result_prefix_prevents_deletion_of_unknown_row():
    class ChangedResultDirectus(FakeDirectus):
        async def _make_api_request(self, method, url, headers=None, json=None):
            response = await super()._make_api_request(method, url, headers=headers, json=json)
            if method == "PATCH" and "/items/test_results/" in url:
                for row in self.rows["test_results"].values():
                    row["result_key"] = "foreign/result"
            return response

    fake = ChangedResultDirectus()
    with pytest.raises(RuntimeError, match="accountability_fixture_cleanup_failed"):
        asyncio.run(probe.prove(fake, {"fixture_prefix": f"ci-accountability/{uuid.uuid4()}"}))
    assert len(fake.rows["test_results"]) == 1
    assert all(not rows for name, rows in fake.rows.items() if name != "test_results")


# contract-test: infrastructure
def test_selector_ids_allow_idempotent_recovery_cleanup_after_interruption():
    prefix = f"ci-accountability/{uuid.uuid4()}"
    first = probe.fixture_rows(prefix)
    second = probe.fixture_rows(prefix)
    assert [(name, row["id"]) for name, row, _ in first] == [
        (name, row["id"]) for name, row, _ in second
    ]
    fake = FakeDirectus()
    for collection, row, _ in first:
        fake.rows[collection][row["id"]] = dict(row)
    result = asyncio.run(probe.cleanup(fake, {"fixture_prefix": prefix}))
    assert result["deleted_count"] == len(probe.COLLECTIONS)
    assert result["cleanup_complete"] is True
    assert all(not rows for rows in fake.rows.values())
    assert asyncio.run(probe.cleanup(fake, {"fixture_prefix": prefix}))["deleted_count"] == 0


# contract-test: infrastructure
def test_interrupted_all_phase_cleanup_restores_metadata_before_deletion():
    prefix = f"ci-accountability/{uuid.uuid4()}"
    fake = FakeDirectus()
    for collection, row, _ in probe.fixture_rows(prefix + "/all"):
        fake.meta[collection] = "all"
        fake.rows[collection][row["id"]] = dict(row)
        fake.record_audit(collection, row["id"])
    result = asyncio.run(probe.cleanup(fake, {"fixture_prefix": prefix}))
    assert result["deleted_count"] == 5
    assert result["residual_product_rows"] == 0
    assert all(value is None for value in fake.meta.values())
    assert all(not rows for rows in fake.rows.values())
    assert all(fake.audit[kind] for kind in fake.audit)


# contract-test: infrastructure
def test_comparison_failure_restores_all_five_collection_policies():
    class FailedAllWriteDirectus(FakeDirectus):
        async def create_item(self, collection, row, admin_required=False):
            if collection == "embeds" and self.meta[collection] == "all":
                return False, {"error": "synthetic comparison failure"}
            return await super().create_item(collection, row, admin_required=admin_required)

    fake = FailedAllWriteDirectus()
    with pytest.raises(RuntimeError, match="accountability_fixture_create_failed"):
        asyncio.run(probe.prove(fake, {"fixture_prefix": f"ci-accountability/{uuid.uuid4()}"}))
    assert all(value is None for value in fake.meta.values())
    assert all(not rows for rows in fake.rows.values())
