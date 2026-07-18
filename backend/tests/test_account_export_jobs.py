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
                {
                    "id": "personal-chat",
                    "hashed_user_id": _hash("user-1"),
                    "hashed_team_id": None,
                    "anonymous_encrypted_chat_key": "anonymous-wrapped-chat-key",
                    "encrypted_chat_key": "wrapped-chat-key",
                    "chat_key_wrappers": {"device-1": "wrapped-key"},
                    "shared_encrypted_chat_key": "shared-wrapped-chat-key",
                },
                {"id": "team-chat", "hashed_user_id": _hash("user-1"), "hashed_team_id": "team-hash"},
            ],
            "messages": [
                {"id": "message-1", "client_message_id": "msg-1", "chat_id": "personal-chat", "encrypted_content": "ciphertext-1"},
                {"id": "message-2", "client_message_id": "msg-2", "chat_id": "personal-chat", "encrypted_content": "ciphertext-2"},
                {"id": "team-message", "client_message_id": "msg-team", "chat_id": "team-chat", "encrypted_content": "team"},
            ],
            "embeds": [
                {
                    "id": "embed-row-1",
                    "embed_id": "embed-1",
                    "hashed_user_id": _hash("user-1"),
                    "hashed_chat_id": _hash("personal-chat"),
                    "status": "finished",
                    "s3_file_keys": [{"bucket": "chatfiles", "key": "user-1/embed-1/original.bin"}],
                },
                {"id": "team-embed", "embed_id": "embed-team", "hashed_user_id": _hash("user-1"), "hashed_team_id": "team-hash"},
            ],
            "upload_files": [
                {
                    "id": "upload-1",
                    "embed_id": "embed-1",
                    "user_id": "user-1",
                    "original_filename": "export-test.pdf",
                    "files_metadata": {"original": {"s3_key": "user-1/embed-1/original.bin", "size_bytes": 123}},
                    "aes_key": "raw-upload-key",
                    "vault_wrapped_aes_key": "vault-wrapped-upload-key",
                },
            ],
            "projects": [{"id": "project-row-1", "project_id": "project-1", "hashed_user_id": _hash("user-1"), "hashed_team_id": None}],
            "user_tasks": [{"id": "task-row-1", "task_id": "task-1", "hashed_user_id": _hash("user-1"), "hashed_team_id": None}],
            "user_task_archives": [{"id": "task-archive-1", "hashed_user_id": _hash("user-1"), "archive_s3_key": "task-archives/hash/tasks.json.gz", "task_count": 1}],
            "user_plans": [{"id": "plan-row-1", "plan_id": "plan-1", "hashed_user_id": _hash("user-1"), "hashed_team_id": None}],
            "workflows": [{"id": "workflow-row-1", "workflow_id": "workflow-1", "hashed_user_id": _hash("user-1"), "hashed_team_id": None}],
            "workflow_runs": [{"id": "workflow-run-row-1", "run_id": "run-1", "workflow_id": "workflow-1", "hashed_user_id": _hash("user-1")}],
            "usage": [{"id": "usage-1", "user_id_hash": _hash("user-1"), "hashed_team_id": None}],
            "usage_monthly_chat_summaries": [{"id": "usage-archive-1", "user_id_hash": _hash("user-1"), "year_month": "2026-01", "is_archived": True, "archive_s3_key": "usage-archives/hash/2026-01/usage.json.gz"}],
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
            if isinstance(condition, dict) and "_in" in condition:
                rows = [row for row in rows if row.get(field) in condition["_in"]]
        return rows

    async def get_user(self, user_id: str):
        return {
            "id": user_id,
            "email": "person@example.invalid",
            "first_name": "Test",
            "last_name": "User",
            "password": "password-hash",
            "vault_key_id": "vault-key-id",
            "last_export_at": None,
            "terms_accepted_at": "2026-01-01T00:00:00Z",
            "privacy_policy_accepted_at": "2026-01-01T00:00:00Z",
        }

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
async def test_default_export_materializes_all_default_domains() -> None:
    service = AccountExportService(directus_service=FakeDirectusService())

    job = await service.start_export(user_id="user-1")
    manifest = await service.get_manifest(user_id="user-1", export_id=job["export_id"])

    for domain in service.default_domains:
        assert manifest["domains"][domain]["status"] == "ready"
        assert manifest["domains"][domain]["source"] != "not_yet_materialized"
    assert manifest["domains"]["chats"]["count"] == 1
    assert manifest["domains"]["embeds"]["count"] == 1
    assert manifest["domains"]["referenced_uploads"]["count"] == 1
    assert manifest["domains"]["projects"]["count"] == 1
    assert manifest["domains"]["tasks"]["count"] == 1
    assert manifest["domains"]["plans"]["count"] == 1
    assert manifest["domains"]["workflows_runs"]["count"] == 2
    assert manifest["domains"]["profile_account_settings"]["count"] == 1
    assert manifest["domains"]["compliance_consent_history"]["count"] == 1


@pytest.mark.asyncio
async def test_export_payload_includes_related_messages_embeds_uploads_and_s3_references() -> None:
    service = AccountExportService(directus_service=FakeDirectusService())

    job = await service.start_export(user_id="user-1")
    chunks = await service.list_chunks(user_id="user-1", export_id=job["export_id"])
    by_domain = {chunk["domain"]: chunk["payload"] for chunk in chunks}

    chat = by_domain["chats"]["items"][0]
    assert [message["client_message_id"] for message in chat["messages"]] == ["msg-1", "msg-2"]
    assert chat["embeds"][0]["embed_id"] == "embed-1"
    assert by_domain["embeds"]["items"][0]["embed_id"] == "embed-1"
    referenced_upload = by_domain["referenced_uploads"]["items"][0]
    assert referenced_upload["embed_id"] == "embed-1"
    assert referenced_upload["s3_objects"] == [{"bucket": "chatfiles", "key": "user-1/embed-1/original.bin", "size_bytes": 123}]
    assert by_domain["usage"]["archives"] == [{"archive_s3_key": "usage-archives/hash/2026-01/usage.json.gz", "year_month": "2026-01"}]
    assert by_domain["tasks"]["archives"] == [{"archive_s3_key": "task-archives/hash/tasks.json.gz", "task_count": 1}]


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
    job = await service.start_export(user_id="user-1", domains=["chats", "connected_account_overview"])

    chunks = await service.list_chunks(user_id="user-1", export_id=job["export_id"])
    serialized = repr(chunks).lower()

    for forbidden in (
        "refresh_token",
        "access_token",
        "api_key",
        "password_hash",
        "totp",
        "private_key",
        "anonymous_encrypted_chat_key",
        "encrypted_chat_key",
        "chat_key_wrappers",
        "shared_encrypted_chat_key",
        "anonymous-wrapped-chat-key",
        "wrapped-chat-key",
        "shared-wrapped-chat-key",
    ):
        assert forbidden not in serialized
