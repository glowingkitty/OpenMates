"""File-mapped storage reference service tests.

The reconciliation suite covers the full reference lifecycle. This file keeps
storage_reference_service.py visible to session deploy coverage while asserting
the account-export rows added to deletion cleanup remain fail-closed.
Contract: architecture.storage-lifecycle.
"""

from __future__ import annotations

import importlib

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
