"""Account Export V1 backend contract tests.

Purpose: prove the resumable job contract before CLI, SDK, web, or Apple work.
Architecture: docs/specs/account-export-v1/spec.yml.
Security: personal exports must exclude team data and reusable credentials.
Privacy: last_export_at changes only after complete or accepted partial exports.
Run: python3 -m pytest backend/tests/test_account_export_jobs.py
"""

from __future__ import annotations

import hashlib

import pytest

from backend.core.api.app.services.account_export_service import (
    AccountExportFilterError,
    AccountExportService,
)


class FakeDirectusService:
    def __init__(self) -> None:
        self.collections: dict[str, list[dict]] = {
            "chats": [
                {"id": "personal-chat", "hashed_user_id": _hash("user-1"), "hashed_team_id": None},
                {"id": "team-chat", "hashed_user_id": _hash("user-1"), "hashed_team_id": "team-hash"},
            ],
            "usage": [{"id": "usage-1", "user_id_hash": _hash("user-1"), "hashed_team_id": None}],
            "invoices": [{"id": "invoice-1", "user_id_hash": _hash("user-1")}],
            "user_app_settings_and_memories": [{"id": "memory-1", "hashed_user_id": _hash("user-1"), "hashed_team_id": None}],
        }
        self.updated_users: list[tuple[str, dict]] = []

    async def get_items(self, collection: str, params: dict | None = None):
        rows = list(self.collections.get(collection, []))
        filters = (params or {}).get("filter") or {}
        for field, condition in filters.items():
            if isinstance(condition, dict) and "_eq" in condition:
                rows = [row for row in rows if row.get(field) == condition["_eq"]]
            if isinstance(condition, dict) and condition.get("_null") is True:
                rows = [row for row in rows if row.get(field) is None]
        return rows

    async def update_user(self, user_id: str, payload: dict) -> None:
        self.updated_users.append((user_id, payload))


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@pytest.mark.asyncio
async def test_start_export_creates_resumable_job_without_updating_last_export_at() -> None:
    directus = FakeDirectusService()
    service = AccountExportService(directus_service=directus)

    job = await service.start_export(user_id="user-1")

    assert job["status"] == "queued"
    assert job["selected_domains"] == service.default_domains
    assert job["default_domains"] == service.default_domains
    assert job["progress"]["total_domains"] == len(service.default_domains)
    assert [chunk["domain"] for chunk in job["chunks"]] == service.default_domains
    assert directus.updated_users == []


@pytest.mark.asyncio
async def test_manifest_excludes_team_scoped_rows_and_counts_defaults() -> None:
    service = AccountExportService(directus_service=FakeDirectusService())

    job = await service.start_export(user_id="user-1", domains=["chats", "usage", "memories_app_settings"])
    manifest = await service.get_manifest(user_id="user-1", export_id=job["export_id"])

    assert manifest["domains"]["chats"]["count"] == 1
    assert manifest["domains"]["usage"]["count"] == 1
    assert manifest["domains"]["memories_app_settings"]["count"] == 1
    assert manifest["excluded"]["team_data"] == "personal_export_excludes_team_scoped_rows"


@pytest.mark.asyncio
async def test_start_export_rejects_unsupported_domain_filters() -> None:
    service = AccountExportService(directus_service=FakeDirectusService())

    with pytest.raises(AccountExportFilterError):
        await service.start_export(
            user_id="user-1",
            domains=["billing_invoices"],
            filters={"billing_invoices": {"from": "2026-01-01"}},
        )


@pytest.mark.asyncio
async def test_partial_export_requires_explicit_acceptance_for_last_export_at() -> None:
    directus = FakeDirectusService()
    service = AccountExportService(directus_service=directus)
    job = await service.start_export(user_id="user-1", domains=["chats"])

    partial = await service.record_domain_failure(
        user_id="user-1",
        export_id=job["export_id"],
        domain="chats",
        item_id="chat-missing-key",
        reason="missing_key_material",
    )
    assert partial["status"] == "partial"
    assert directus.updated_users == []

    accepted = await service.accept_partial(user_id="user-1", export_id=job["export_id"])

    assert accepted["status"] == "partial_accepted"
    assert directus.updated_users[0][0] == "user-1"
    assert "last_export_at" in directus.updated_users[0][1]


@pytest.mark.asyncio
async def test_download_chunks_never_emit_forbidden_secret_fields() -> None:
    service = AccountExportService(directus_service=FakeDirectusService())
    job = await service.start_export(user_id="user-1", domains=["connected_account_overview"])

    chunks = await service.list_chunks(user_id="user-1", export_id=job["export_id"])
    serialized = repr(chunks).lower()

    for forbidden in ("refresh_token", "access_token", "api_key", "password_hash", "totp", "private_key"):
        assert forbidden not in serialized
