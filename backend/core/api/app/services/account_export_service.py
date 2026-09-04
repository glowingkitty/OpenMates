"""Account Export V1 job service.

Purpose: build a resumable personal export contract shared by CLI, SDKs, web,
and later Apple parity.
Architecture: docs/specs/account-export-v1/spec.yml.
Security: emits user-owned metadata and encrypted payload references only; no
reusable credentials, raw keys, token hashes, or team-scoped rows.
Privacy: updates last_export_at only after complete or accepted partial exports.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
import hashlib
import uuid
from typing import Any

from backend.shared.python_utils.invoice_ciphertext_versions import (
    select_latest_invoice_ciphertext,
)

EXPORT_JOB_TTL_HOURS = 24
EXPORT_SCHEMA_VERSION = "account-export-v1"
DIRECTUS_RELATED_QUERY_BATCH_SIZE = 50
DIRECTUS_EXPORT_PAGE_SIZE = 100
DEFAULT_EXPORT_PART_ITEM_LIMIT = 100
ACCOUNT_EXPORT_JOB_COLLECTION = "account_export_jobs"
ACCOUNT_EXPORT_PART_COLLECTION = "account_export_parts"
TERMINAL_EXPORT_STATUSES = {"complete", "partial_accepted", "failed", "cancelled", "expired"}
TEAM_EXPORT_ROLES = {"owner", "admin", "member"}

DEFAULT_EXPORT_DOMAINS = [
    "chats",
    "embeds",
    "referenced_uploads",
    "projects",
    "tasks",
    "plans",
    "workflows_runs",
    "billing_invoices",
    "usage",
    "profile_account_settings",
    "memories_app_settings",
    "compliance_consent_history",
]

ADVANCED_OPTIONAL_EXPORT_DOMAINS = [
    "reminders",
    "connected_account_overview",
    "api_key_device_metadata",
    "webhook_metadata",
    "support_issue_reports",
    "notifications_email_delivery_newsletter_referrals",
    "storage_inventory_unreferenced_files",
    "detailed_operational_records",
]

FILTERABLE_EXPORT_DOMAINS = {"chats", "tasks", "projects", "plans", "workflows_runs", "usage"}
FILTER_FROM_KEYS = {"from", "since", "created_from", "updated_from"}
FILTER_TO_KEYS = {"to", "until", "created_to", "updated_to"}
FILTER_DATE_FIELDS = (
    "updated_at",
    "created_at",
    "completed_at",
    "archived_at",
    "started_at",
    "finished_at",
    "date",
    "year_month",
)
FILTER_ID_FIELDS = ("id", "chat_id", "task_id", "project_id", "plan_id", "workflow_id", "run_id", "resource_id", "archive_id")
FILTER_DIRECTUS_OPERATORS = {"_eq", "_in", "_gte", "_lte"}

DOMAIN_COLLECTIONS = {
    "chats": ("chats", "hashed_user_id"),
    "usage": ("usage", "user_id_hash"),
    "memories_app_settings": ("user_app_settings_and_memories", "hashed_user_id"),
}

COLD_RESOURCE_TYPES_BY_DOMAIN = {
    "chats": ("chat",),
    "projects": ("project",),
    "tasks": ("task",),
    "plans": ("plan",),
    "workflows_runs": ("workflow", "workflow_run"),
}

FORBIDDEN_EXPORT_SECRET_FIELDS = {
    "access_token",
    "aes_key",
    "api_key",
    "anonymous_encrypted_chat_key",
    "backup_code_hash",
    "chat_key",
    "chat_key_wrappers",
    "credential_secret",
    "device_key",
    "embed_key",
    "embed_key_wrappers",
    "encrypted_chat_key",
    "encrypted_embed_key",
    "encrypted_master_key",
    "encrypted_plan_key",
    "encrypted_project_key",
    "encrypted_task_key",
    "encrypted_workflow_secret_key",
    "key_wrappers",
    "lookup_hash",
    "master_key",
    "plan_key",
    "password",
    "password_hash",
    "private_key",
    "project_key",
    "raw_key",
    "refresh_token",
    "share_key",
    "shared_encrypted_chat_key",
    "signing_secret",
    "task_key",
    "token_hash",
    "totp_seed",
    "vault_key_id",
    "vault_wrapped_aes_key",
    "webhook_secret",
    "workflow_secret_key",
}


class AccountExportError(ValueError):
    """Base error for account export contract violations."""


class AccountExportFilterError(AccountExportError):
    """Raised when the requested export filters are unsupported."""


class AccountExportNotFoundError(AccountExportError):
    """Raised when an export job is not found for the authenticated user."""


class AccountExportAuthorizationError(AccountExportError):
    """Raised when the current user cannot access an export job or part."""


class AccountExportService:
    """In-process export job coordinator with an injectable Directus dependency."""

    default_domains = DEFAULT_EXPORT_DOMAINS
    advanced_optional_domains = ADVANCED_OPTIONAL_EXPORT_DOMAINS
    filterable_domains = FILTERABLE_EXPORT_DOMAINS

    def __init__(
        self,
        directus_service: Any,
        *,
        jobs: dict[str, dict[str, Any]] | None = None,
        part_item_limit: int = DEFAULT_EXPORT_PART_ITEM_LIMIT,
    ) -> None:
        self.directus_service = directus_service
        self._jobs = jobs if jobs is not None else {}
        if part_item_limit <= 0:
            raise ValueError("Account export part item limit must be positive")
        self.part_item_limit = part_item_limit

    async def start_export(
        self,
        *,
        user_id: str,
        domains: list[str] | None = None,
        filters: dict[str, Any] | None = None,
        include_advanced_metadata: bool = False,
        output_format: str = "zip",
        team_id: str | None = None,
        build_immediately: bool = True,
    ) -> dict[str, Any]:
        await self.purge_expired_exports()
        selected_domains = self._normalize_domains(domains, include_advanced_metadata=include_advanced_metadata)
        normalized_filters = dict(filters or {})
        self._validate_filters(selected_domains, normalized_filters)
        if team_id:
            await self._authorize_team_export(user_id=user_id, team_id=team_id)

        now = _utc_now()
        export_id = str(uuid.uuid4())
        job = {
            "export_id": export_id,
            "schema_version": EXPORT_SCHEMA_VERSION,
            "status": "queued",
            "selected_domains": selected_domains,
            "default_domains": list(DEFAULT_EXPORT_DOMAINS),
            "advanced_optional_domains": list(ADVANCED_OPTIONAL_EXPORT_DOMAINS),
            "filters": normalized_filters,
            "format": output_format,
            "progress": {
                "completed_domains": 0,
                "total_domains": len(selected_domains),
                "failed_items": 0,
                "total_parts": 0,
                "completed_parts": 0,
            },
            "chunks": [],
            "domain_results": {},
            "failures": [],
            "created_at": now,
            "updated_at": now,
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=EXPORT_JOB_TTL_HOURS)).isoformat(),
            "accepted_partial_at": None,
            "completed_at": None,
            "user_id_hash": _hash_id(user_id),
            "team_id_hash": _hash_id(team_id) if team_id else None,
        }
        self._jobs[export_id] = job
        can_persist = self._can_persist_exports()
        if can_persist:
            await self._create_persisted_job(job)
        if not build_immediately:
            return _public_job(job)
        return await self._build_export_job(user_id=user_id, team_id=team_id, job=job)

    async def build_export(self, *, user_id: str, export_id: str, team_id: str | None = None) -> dict[str, Any]:
        job = await self._get_user_job(user_id, export_id, team_id=team_id)
        return await self._build_export_job(user_id=user_id, team_id=team_id, job=job, mark_ready=True)

    async def _build_export_job(
        self,
        *,
        user_id: str,
        team_id: str | None,
        job: dict[str, Any],
        mark_ready: bool = False,
    ) -> dict[str, Any]:
        if job["status"] in TERMINAL_EXPORT_STATUSES or job["chunks"] or job["domain_results"]:
            return _public_job(job)
        can_persist = self._can_persist_exports()
        if mark_ready:
            job["status"] = "running"
            job["updated_at"] = _utc_now()
            await self._persist_job_update(job)
        try:
            await self._build_job_chunks(user_id=user_id, team_id=team_id, job=job, persist_parts=can_persist)
        except Exception:
            if can_persist and job.get("_row_id") and job.get("status") != "failed":
                await self._mark_job_failed(job, reason="build_export_failed")
            raise
        if mark_ready and job["status"] == "running":
            job["status"] = "ready"
        job["updated_at"] = _utc_now()
        await self._persist_job_update(job)
        if can_persist:
            job["chunks"] = [_chunk_manifest(chunk) for chunk in job["chunks"]]
        return _public_job(job)

    async def get_job(self, *, user_id: str, export_id: str, team_id: str | None = None) -> dict[str, Any]:
        return _public_job(await self._get_user_job(user_id, export_id, team_id=team_id))

    async def get_manifest(self, *, user_id: str, export_id: str, team_id: str | None = None) -> dict[str, Any]:
        job = await self._get_user_job(user_id, export_id, team_id=team_id)
        return {
            "export_id": export_id,
            "schema_version": EXPORT_SCHEMA_VERSION,
            "selected_domains": list(job["selected_domains"]),
            "filters": dict(job["filters"]),
            "domains": dict(job["domain_results"]),
            "excluded": {
                "team_data": "personal_export_excludes_team_scoped_rows",
                "secrets": "reusable_credentials_and_raw_key_material_redacted",
            },
            "report": self._build_report(job),
        }

    async def list_chunks(self, *, user_id: str, export_id: str, team_id: str | None = None) -> list[dict[str, Any]]:
        job = await self._get_user_job(user_id, export_id, team_id=team_id)
        persisted_parts = await self._load_persisted_parts(export_id=export_id)
        if persisted_parts:
            return persisted_parts
        return [dict(chunk) for chunk in job["chunks"]]

    async def get_chunk(self, *, user_id: str, export_id: str, chunk_id: str, team_id: str | None = None) -> dict[str, Any]:
        job = await self._get_user_job(user_id, export_id, team_id=team_id)
        persisted_part = await self._load_persisted_part(export_id=export_id, chunk_id=chunk_id)
        if persisted_part:
            return persisted_part
        for chunk in job["chunks"]:
            if chunk["chunk_id"] == chunk_id:
                return dict(chunk)
        raise AccountExportNotFoundError("Export chunk not found")

    async def record_domain_failure(
        self,
        *,
        user_id: str,
        export_id: str,
        domain: str,
        item_id: str,
        reason: str,
        team_id: str | None = None,
    ) -> dict[str, Any]:
        job = await self._get_user_job(user_id, export_id, team_id=team_id)
        failure = {"domain": domain, "item_id": item_id, "reason": reason}
        job["failures"].append(failure)
        job["status"] = "partial"
        job["progress"]["failed_items"] = len(job["failures"])
        job["updated_at"] = _utc_now()
        job["domain_results"][domain] = {
            **(job["domain_results"].get(domain) or {}),
            "status": "partial",
            "failures": [failure],
        }
        await self._persist_job_update(job)
        return _public_job(job)

    async def mark_complete(self, *, user_id: str, export_id: str, team_id: str | None = None) -> dict[str, Any]:
        job = await self._get_user_job(user_id, export_id, team_id=team_id)
        if job["failures"]:
            job["status"] = "partial"
            job["updated_at"] = _utc_now()
            await self._persist_job_update(job)
            return _public_job(job)
        job["status"] = "complete"
        job["completed_at"] = _utc_now()
        job["updated_at"] = job["completed_at"]
        job["progress"]["completed_domains"] = len(job["selected_domains"])
        job["progress"]["completed_parts"] = job["progress"].get("total_parts", len(job["chunks"]))
        await self._persist_job_update(job)
        if not team_id:
            await self._update_last_export_at(user_id)
        return _public_job(job)

    async def accept_partial(self, *, user_id: str, export_id: str, team_id: str | None = None) -> dict[str, Any]:
        job = await self._get_user_job(user_id, export_id, team_id=team_id)
        if job["status"] != "partial":
            raise AccountExportError("Only partial exports can be accepted")
        now = _utc_now()
        job["status"] = "partial_accepted"
        job["accepted_partial_at"] = now
        job["updated_at"] = now
        await self._persist_job_update(job)
        if not team_id:
            await self._update_last_export_at(user_id)
        return _public_job(job)

    async def cancel_export(self, *, user_id: str, export_id: str, team_id: str | None = None) -> dict[str, Any]:
        job = await self._get_user_job(user_id, export_id, team_id=team_id)
        if job["status"] in TERMINAL_EXPORT_STATUSES:
            return _public_job(job)
        job["status"] = "cancelled"
        job["updated_at"] = _utc_now()
        await self._persist_job_update(job)
        return _public_job(job)

    async def purge_expired_exports(self) -> dict[str, int]:
        expired = 0
        if self._can_persist_exports():
            rows = await self._get_items_bounded(
                collection=ACCOUNT_EXPORT_JOB_COLLECTION,
                params={"filter": {"expires_at": {"_lte": _utc_now()}}, "fields": "*"},
                admin_required=True,
            )
            for row in rows:
                await self._purge_expired_job(_job_from_storage(row))
                expired += 1
        else:
            for export_id, job in list(self._jobs.items()):
                if _job_is_expired(job):
                    self._jobs.pop(export_id, None)
                    expired += 1
        return {"expired_jobs": expired}

    async def _build_job_chunks(
        self,
        *,
        user_id: str,
        team_id: str | None,
        job: dict[str, Any],
        persist_parts: bool,
    ) -> None:
        manifest_domains: dict[str, dict[str, Any]] = {}
        job["chunks"] = []
        for domain in job["selected_domains"]:
            domain_failures: list[dict[str, Any]] = []
            domain_count = 0
            sources: list[str] = []
            sequence = 0
            async for payload in self._domain_payload_chunks(
                user_id=user_id,
                team_id=team_id,
                domain=domain,
                filters=_domain_filters(job["filters"], domain),
            ):
                payload = dict(payload)
                domain_failures.extend(payload.pop("failures", []))
                domain_count += _domain_count(payload)
                source = str(payload.get("source") or "generated")
                if source not in sources:
                    sources.append(source)
                sequence += 1
                chunk_id = f"{domain}-{sequence:04d}"
                chunk = {
                    "chunk_id": chunk_id,
                    "part_id": chunk_id,
                    "domain": domain,
                    "sequence": sequence,
                    "status": "ready",
                    "content_type": "application/json",
                    "payload": _redact_for_export(payload),
                }
                if persist_parts:
                    try:
                        await self._persist_part(job, chunk)
                    except Exception:
                        await self._mark_job_failed(job, reason="persist_part_failed")
                        raise
                job["chunks"].append(_chunk_manifest(chunk) if persist_parts else chunk)
            job["failures"].extend(domain_failures)
            manifest_domains[domain] = {
                "status": "partial" if domain_failures else "ready",
                "count": domain_count,
                "source": "+".join(sources) if sources else "generated",
                "failures": domain_failures,
            }
        job["domain_results"] = manifest_domains
        job["progress"]["total_parts"] = len(job["chunks"])
        job["progress"]["failed_items"] = len(job["failures"])
        if job["failures"]:
            job["status"] = "partial"

    async def _domain_payload_chunks(
        self,
        *,
        user_id: str,
        team_id: str | None,
        domain: str,
        filters: dict[str, Any],
    ) -> AsyncIterator[dict[str, Any]]:
        if domain == "chats":
            async for payload in self._chats_payload_chunks(user_id=user_id, team_id=team_id, filters=filters):
                yield payload
            async for payload in self._cold_archive_payload_chunks(user_id=user_id, team_id=team_id, domain=domain, filters=filters):
                yield payload
            return
        if domain == "embeds":
            async for payload in self._scoped_row_payload_chunks(
                collection="embeds",
                user_field="hashed_user_id",
                user_id=user_id,
                team_id=team_id,
                domain=domain,
                filters=filters,
                source="embeds",
            ):
                yield payload
            return
        if domain == "referenced_uploads":
            async for payload in self._referenced_uploads_payload_chunks(user_id=user_id, team_id=team_id):
                yield payload
            return
        if domain == "projects":
            async for payload in self._scoped_row_payload_chunks(
                collection="projects",
                user_field="hashed_user_id",
                user_id=user_id,
                team_id=team_id,
                domain=domain,
                filters=filters,
                source="projects",
            ):
                yield payload
            async for payload in self._cold_archive_payload_chunks(user_id=user_id, team_id=team_id, domain=domain, filters=filters):
                yield payload
            return
        if domain == "tasks":
            async for payload in self._scoped_row_payload_chunks(
                collection="user_tasks",
                user_field="hashed_user_id",
                user_id=user_id,
                team_id=team_id,
                domain=domain,
                filters=filters,
                source="user_tasks",
            ):
                yield payload
            archives = await self._get_scoped_rows(collection="user_task_archives", user_field="hashed_user_id", user_id=user_id, team_id=team_id)
            archives = self._apply_domain_filters(domain, archives, filters)
            archive_payloads = [_safe_task_archive_reference(row) for row in archives if row.get("archive_s3_key")]
            async for payload in self._list_payload_chunks(source="user_task_archives", list_field="archives", values=archive_payloads):
                yield payload
            async for payload in self._cold_archive_payload_chunks(user_id=user_id, team_id=team_id, domain=domain, filters=filters):
                yield payload
            return
        if domain == "plans":
            async for payload in self._scoped_row_payload_chunks(
                collection="user_plans",
                user_field="hashed_user_id",
                user_id=user_id,
                team_id=team_id,
                domain=domain,
                filters=filters,
                source="user_plans",
            ):
                yield payload
            async for payload in self._cold_archive_payload_chunks(user_id=user_id, team_id=team_id, domain=domain, filters=filters):
                yield payload
            return
        if domain == "workflows_runs":
            async for payload in self._scoped_row_payload_chunks(
                collection="workflows",
                user_field="hashed_user_id",
                user_id=user_id,
                team_id=team_id,
                domain=domain,
                filters=filters,
                source="workflows",
            ):
                yield payload
            async for payload in self._scoped_row_payload_chunks(
                collection="workflow_runs",
                user_field="hashed_user_id",
                user_id=user_id,
                team_id=team_id,
                domain=domain,
                filters=filters,
                source="workflow_runs",
                list_field="runs",
            ):
                yield payload
            async for payload in self._cold_archive_payload_chunks(user_id=user_id, team_id=team_id, domain=domain, filters=filters):
                yield payload
            return
        if domain == "usage":
            async for payload in self._scoped_row_payload_chunks(
                collection="usage",
                user_field="user_id_hash",
                user_id=user_id,
                team_id=team_id,
                domain=domain,
                filters=filters,
                source="usage",
            ):
                yield payload
            archives = await self._usage_archive_references(user_id=user_id, team_id=team_id)
            archives = self._apply_domain_filters(domain, archives, filters)
            async for payload in self._list_payload_chunks(source="usage_archives", list_field="archives", values=archives):
                yield payload
            return
        if domain in DOMAIN_COLLECTIONS:
            collection, user_field = DOMAIN_COLLECTIONS[domain]
            async for payload in self._scoped_row_payload_chunks(
                collection=collection,
                user_field=user_field,
                user_id=user_id,
                team_id=team_id,
                domain=domain,
                filters=filters,
                source=collection,
            ):
                yield payload
            return

        payload = await self._domain_payload(user_id=user_id, team_id=team_id, domain=domain, filters=filters)
        for chunk_payload in self._chunk_payloads(payload):
            yield chunk_payload

    async def _scoped_row_payload_chunks(
        self,
        *,
        collection: str,
        user_field: str,
        user_id: str,
        team_id: str | None,
        domain: str,
        filters: dict[str, Any],
        source: str,
        list_field: str = "items",
    ) -> AsyncIterator[dict[str, Any]]:
        buffer: list[dict[str, Any]] = []
        yielded = False
        async for row in self._iter_scoped_rows(collection=collection, user_field=user_field, user_id=user_id, team_id=team_id):
            if filters and not _matches_export_filters(row, filters):
                continue
            buffer.append(row)
            if len(buffer) >= self.part_item_limit:
                yielded = True
                yield {"source": source, list_field: buffer}
                buffer = []
        if buffer or not yielded:
            yield {"source": source, list_field: buffer}

    async def _list_payload_chunks(
        self,
        *,
        source: str,
        list_field: str,
        values: list[dict[str, Any]],
    ) -> AsyncIterator[dict[str, Any]]:
        for start in range(0, len(values), self.part_item_limit):
            yield {"source": source, list_field: values[start:start + self.part_item_limit]}

    async def _chats_payload_chunks(
        self,
        *,
        user_id: str,
        team_id: str | None,
        filters: dict[str, Any],
    ) -> AsyncIterator[dict[str, Any]]:
        async for payload in self._scoped_row_payload_chunks(
            collection="chats",
            user_field="hashed_user_id",
            user_id=user_id,
            team_id=team_id,
            domain="chats",
            filters=filters,
            source="chats+messages+embeds",
        ):
            chats = payload["items"]
            chat_ids = [str(chat["id"]) for chat in chats if chat.get("id")]
            messages = await self._get_related_rows(collection="messages", field="chat_id", values=chat_ids)
            embeds = await self._get_related_rows(collection="embeds", field="hashed_chat_id", values=[_hash_id(chat_id) for chat_id in chat_ids])
            messages_by_chat: dict[str, list[dict[str, Any]]] = {}
            for message in messages:
                messages_by_chat.setdefault(str(message.get("chat_id")), []).append(_redact_for_export(message))
            embeds_by_hash: dict[str, list[dict[str, Any]]] = {}
            for embed in embeds:
                embeds_by_hash.setdefault(str(embed.get("hashed_chat_id")), []).append(_redact_for_export(embed))
            for chat in chats:
                chat_id = str(chat.get("id"))
                chat["messages"] = messages_by_chat.get(chat_id, [])
                chat["embeds"] = embeds_by_hash.get(_hash_id(chat_id), [])
            yield payload

    async def _referenced_uploads_payload_chunks(self, *, user_id: str, team_id: str | None) -> AsyncIterator[dict[str, Any]]:
        buffer: list[dict[str, Any]] = []
        yielded = False
        async for upload in self._iter_scoped_rows(collection="upload_files", user_field="user_id", user_id=user_id, team_id=team_id):
            item = _redact_for_export(upload)
            item["s3_objects"] = _upload_s3_objects(upload)
            buffer.append(item)
            if len(buffer) >= self.part_item_limit:
                yielded = True
                yield {"source": "upload_files+chatfiles", "items": buffer}
                buffer = []
        if buffer or not yielded:
            yield {"source": "upload_files+chatfiles", "items": buffer}

    async def _domain_payload(
        self,
        *,
        user_id: str,
        team_id: str | None,
        domain: str,
        filters: dict[str, Any],
    ) -> dict[str, Any]:
        if domain == "chats":
            payload = await self._chats_payload(user_id=user_id, team_id=team_id, filters=filters)
            return await self._with_cold_archives(user_id=user_id, team_id=team_id, domain=domain, payload=payload, filters=filters)
        if domain == "embeds":
            rows = await self._get_scoped_rows(collection="embeds", user_field="hashed_user_id", user_id=user_id, team_id=team_id)
            return {"source": "embeds", "items": rows}
        if domain == "referenced_uploads":
            return await self._referenced_uploads_payload(user_id=user_id, team_id=team_id)
        if domain == "projects":
            rows = await self._get_scoped_rows(collection="projects", user_field="hashed_user_id", user_id=user_id, team_id=team_id)
            payload = {"source": "projects", "items": self._apply_domain_filters(domain, rows, filters)}
            return await self._with_cold_archives(user_id=user_id, team_id=team_id, domain=domain, payload=payload, filters=filters)
        if domain == "tasks":
            rows = await self._get_scoped_rows(collection="user_tasks", user_field="hashed_user_id", user_id=user_id, team_id=team_id)
            archives = await self._get_scoped_rows(collection="user_task_archives", user_field="hashed_user_id", user_id=user_id, team_id=team_id)
            archives = self._apply_domain_filters(domain, archives, filters)
            payload = {
                "source": "user_tasks+user_task_archives",
                "items": self._apply_domain_filters(domain, rows, filters),
                "archives": [_safe_task_archive_reference(row) for row in archives if row.get("archive_s3_key")],
            }
            return await self._with_cold_archives(user_id=user_id, team_id=team_id, domain=domain, payload=payload, filters=filters)
        if domain == "plans":
            rows = await self._get_scoped_rows(collection="user_plans", user_field="hashed_user_id", user_id=user_id, team_id=team_id)
            payload = {"source": "user_plans", "items": self._apply_domain_filters(domain, rows, filters)}
            return await self._with_cold_archives(user_id=user_id, team_id=team_id, domain=domain, payload=payload, filters=filters)
        if domain == "workflows_runs":
            workflows = await self._get_scoped_rows(collection="workflows", user_field="hashed_user_id", user_id=user_id, team_id=team_id)
            runs = await self._get_scoped_rows(collection="workflow_runs", user_field="hashed_user_id", user_id=user_id, team_id=team_id)
            payload = {
                "source": "workflows+workflow_runs",
                "items": self._apply_domain_filters(domain, workflows, filters),
                "runs": self._apply_domain_filters(domain, runs, filters),
            }
            return await self._with_cold_archives(user_id=user_id, team_id=team_id, domain=domain, payload=payload, filters=filters)
        if domain == "usage":
            rows = await self._get_scoped_rows(collection="usage", user_field="user_id_hash", user_id=user_id, team_id=team_id)
            archives = await self._usage_archive_references(user_id=user_id, team_id=team_id)
            return {
                "source": "usage+usage_archives",
                "items": self._apply_domain_filters(domain, rows, filters),
                "archives": self._apply_domain_filters(domain, archives, filters),
            }
        if domain == "billing_invoices":
            return await self._billing_invoices_payload(user_id=user_id, team_id=team_id)
        if domain == "profile_account_settings":
            profile = await self._safe_profile_payload(user_id=user_id)
            return {"source": "directus_users", "items": [profile] if profile else []}
        if domain == "compliance_consent_history":
            profile = await self._safe_profile_payload(user_id=user_id)
            return {"source": "directus_users.consent_metadata", "items": [_consent_metadata(profile)] if profile else []}
        if domain in DOMAIN_COLLECTIONS:
            collection, user_field = DOMAIN_COLLECTIONS[domain]
            rows = await self._get_scoped_rows(collection=collection, user_field=user_field, user_id=user_id, team_id=team_id)
            return {"source": collection, "items": rows}
        if domain == "connected_account_overview":
            return {"source": "safe_metadata", "items": []}
        return {"source": "not_yet_materialized", "items": []}

    async def _get_personal_rows(self, *, collection: str, user_field: str, user_id: str) -> list[dict[str, Any]]:
        return await self._get_scoped_rows(collection=collection, user_field=user_field, user_id=user_id, team_id=None)

    async def _get_scoped_rows(
        self,
        *,
        collection: str,
        user_field: str,
        user_id: str,
        team_id: str | None,
    ) -> list[dict[str, Any]]:
        return [
            row
            async for row in self._iter_scoped_rows(
                collection=collection,
                user_field=user_field,
                user_id=user_id,
                team_id=team_id,
            )
        ]

    async def _iter_scoped_rows(
        self,
        *,
        collection: str,
        user_field: str,
        user_id: str,
        team_id: str | None,
    ) -> AsyncIterator[dict[str, Any]]:
        if team_id:
            params = {
                "filter": {"hashed_team_id": {"_eq": _hash_id(team_id)}},
                "fields": "*",
            }
        else:
            params = {
                "filter": {
                    user_field: {"_eq": _hash_id(user_id)},
                },
                "fields": "*",
            }
            if user_field == "user_id":
                params["filter"][user_field] = {"_eq": user_id}
        offset = 0
        while True:
            page_params = dict(params)
            page_params["limit"] = DIRECTUS_EXPORT_PAGE_SIZE
            page_params["offset"] = offset
            page = await self._directus_get_items(collection, page_params)
            if not page:
                break
            for row in page:
                if team_id:
                    if _is_team_row(row, team_id=team_id):
                        yield _redact_for_export(row)
                    continue
                if _is_personal_row(row):
                    yield _redact_for_export(row)
            if len(page) < DIRECTUS_EXPORT_PAGE_SIZE:
                break
            offset += DIRECTUS_EXPORT_PAGE_SIZE

    async def _chats_payload(self, *, user_id: str, team_id: str | None, filters: dict[str, Any]) -> dict[str, Any]:
        chats = await self._get_scoped_rows(collection="chats", user_field="hashed_user_id", user_id=user_id, team_id=team_id)
        chats = self._apply_domain_filters("chats", chats, filters)
        chat_ids = [str(chat["id"]) for chat in chats if chat.get("id")]
        messages = await self._get_related_rows(collection="messages", field="chat_id", values=chat_ids)
        embeds = await self._get_related_rows(collection="embeds", field="hashed_chat_id", values=[_hash_id(chat_id) for chat_id in chat_ids])
        messages_by_chat: dict[str, list[dict[str, Any]]] = {}
        for message in messages:
            messages_by_chat.setdefault(str(message.get("chat_id")), []).append(_redact_for_export(message))
        embeds_by_hash: dict[str, list[dict[str, Any]]] = {}
        for embed in embeds:
            embeds_by_hash.setdefault(str(embed.get("hashed_chat_id")), []).append(_redact_for_export(embed))
        for chat in chats:
            chat_id = str(chat.get("id"))
            chat["messages"] = messages_by_chat.get(chat_id, [])
            chat["embeds"] = embeds_by_hash.get(_hash_id(chat_id), [])
        return {"source": "chats+messages+embeds", "items": chats}

    async def _referenced_uploads_payload(self, *, user_id: str, team_id: str | None) -> dict[str, Any]:
        uploads = await self._get_scoped_rows(collection="upload_files", user_field="user_id", user_id=user_id, team_id=team_id)
        items = []
        for upload in uploads:
            item = _redact_for_export(upload)
            item["s3_objects"] = _upload_s3_objects(upload)
            items.append(item)
        return {"source": "upload_files+chatfiles", "items": items}

    async def _billing_invoices_payload(self, *, user_id: str, team_id: str | None) -> dict[str, Any]:
        if team_id:
            return {"source": "invoices+invoice_ciphertext_versions", "items": []}
        user_id_hash = _hash_id(user_id)
        params = {"filter": {"user_id_hash": {"_eq": user_id_hash}}, "fields": "*"}
        invoices = await self._get_items_bounded(collection="invoices", params=params)
        versions = await self._get_items_bounded(collection="invoice_ciphertext_versions", params=params)
        selected = select_latest_invoice_ciphertext(invoices, versions)
        return {
            "source": "invoices+invoice_ciphertext_versions",
            "items": [_redact_for_export(invoice) for invoice in selected if _is_personal_row(invoice)],
        }

    async def _usage_archive_references(self, *, user_id: str, team_id: str | None) -> list[dict[str, Any]]:
        archives: list[dict[str, Any]] = []
        for collection in ("usage_monthly_chat_summaries", "usage_monthly_app_summaries", "usage_monthly_api_key_summaries"):
            rows = await self._get_scoped_rows(collection=collection, user_field="user_id_hash", user_id=user_id, team_id=team_id)
            for row in rows:
                if row.get("archive_s3_key"):
                    archives.append(_redact_for_export({"archive_s3_key": row.get("archive_s3_key"), "year_month": row.get("year_month")}))
        deduped: dict[str, dict[str, Any]] = {}
        for archive in archives:
            deduped[str(archive["archive_s3_key"])] = archive
        return list(deduped.values())

    async def _get_related_rows(self, *, collection: str, field: str, values: list[str]) -> list[dict[str, Any]]:
        if not values:
            return []
        rows: list[dict[str, Any]] = []
        for start in range(0, len(values), DIRECTUS_RELATED_QUERY_BATCH_SIZE):
            batch = values[start:start + DIRECTUS_RELATED_QUERY_BATCH_SIZE]
            result = await self._get_items_bounded(
                collection=collection,
                params={"filter": {field: {"_in": batch}}, "fields": "*"},
            )
            rows.extend(result or [])
        return [_redact_for_export(row) for row in rows if _is_personal_row(row)]

    async def _safe_profile_payload(self, *, user_id: str) -> dict[str, Any]:
        if hasattr(self.directus_service, "get_user"):
            profile = await self.directus_service.get_user(user_id)
        else:
            profile = {"id": user_id}
        return _redact_for_export(profile or {})

    def _apply_domain_filters(self, domain: str, rows: list[dict[str, Any]], filters: dict[str, Any]) -> list[dict[str, Any]]:
        if not filters:
            return rows
        if domain not in FILTERABLE_EXPORT_DOMAINS:
            raise AccountExportFilterError(f"Advanced filters are not supported for: {domain}")
        return [row for row in rows if _matches_export_filters(row, filters)]

    def _normalize_domains(self, domains: list[str] | None, *, include_advanced_metadata: bool) -> list[str]:
        selected = list(domains or DEFAULT_EXPORT_DOMAINS)
        if domains is None and include_advanced_metadata:
            selected.extend(ADVANCED_OPTIONAL_EXPORT_DOMAINS)
        allowed = set(DEFAULT_EXPORT_DOMAINS) | set(ADVANCED_OPTIONAL_EXPORT_DOMAINS)
        unknown = sorted(set(selected) - allowed)
        if unknown:
            raise AccountExportFilterError(f"Unsupported export domain(s): {', '.join(unknown)}")
        return selected

    def _validate_filters(self, selected_domains: list[str], filters: dict[str, Any]) -> None:
        unknown = sorted(set(filters) - set(selected_domains))
        if unknown:
            raise AccountExportFilterError(f"Filter provided for unselected domain(s): {', '.join(unknown)}")
        unsupported = sorted(set(filters) - FILTERABLE_EXPORT_DOMAINS)
        if unsupported:
            raise AccountExportFilterError(f"Advanced filters are not supported for: {', '.join(unsupported)}")
        invalid = sorted(domain for domain, value in filters.items() if value and not isinstance(value, dict))
        if invalid:
            raise AccountExportFilterError(f"Filter value must be an object for: {', '.join(invalid)}")

    def _chunk_payloads(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        list_fields = [(key, value) for key, value in payload.items() if isinstance(value, list)]
        if not list_fields:
            return [dict(payload)]
        if sum(len(values) for _, values in list_fields) <= self.part_item_limit:
            return [dict(payload)]
        non_list_values = {key: value for key, value in payload.items() if not isinstance(value, list)}
        chunks: list[dict[str, Any]] = []
        for field, values in list_fields:
            if not values:
                continue
            for start in range(0, len(values), self.part_item_limit):
                part_payload = {
                    **non_list_values,
                    **{other_field: [] for other_field, _ in list_fields},
                    field: values[start:start + self.part_item_limit],
                }
                chunks.append(part_payload)
        if chunks:
            return chunks
        return [{**non_list_values, **{field: [] for field, _ in list_fields}}]

    async def _with_cold_archives(
        self,
        *,
        user_id: str,
        team_id: str | None,
        domain: str,
        payload: dict[str, Any],
        filters: dict[str, Any],
    ) -> dict[str, Any]:
        resource_types = COLD_RESOURCE_TYPES_BY_DOMAIN.get(domain)
        if not resource_types:
            return payload
        cold = await self._cold_archive_references(user_id=user_id, team_id=team_id, resource_types=resource_types, filters=filters)
        if cold["items"]:
            payload["cold_archives"] = cold["items"]
        if cold["failures"]:
            payload.setdefault("failures", []).extend(
                {"domain": domain, "item_id": failure["item_id"], "reason": failure["reason"]}
                for failure in cold["failures"]
            )
        return payload

    async def _cold_archive_payload_chunks(
        self,
        *,
        user_id: str,
        team_id: str | None,
        domain: str,
        filters: dict[str, Any],
    ) -> AsyncIterator[dict[str, Any]]:
        resource_types = COLD_RESOURCE_TYPES_BY_DOMAIN.get(domain)
        if not resource_types:
            return
        cold = await self._cold_archive_references(user_id=user_id, team_id=team_id, resource_types=resource_types, filters=filters)
        failures = [
            {"domain": domain, "item_id": failure["item_id"], "reason": failure["reason"]}
            for failure in cold["failures"]
        ]
        yielded = False
        for start in range(0, len(cold["items"]), self.part_item_limit):
            yielded = True
            yield {
                "source": "cold_archive_manifests+parts",
                "items": [],
                "cold_archives": cold["items"][start:start + self.part_item_limit],
                "failures": failures if start == 0 else [],
            }
        if failures and not yielded:
            yield {"source": "cold_archive_manifests+parts", "items": [], "cold_archives": [], "failures": failures}

    async def _cold_archive_references(
        self,
        *,
        user_id: str,
        team_id: str | None,
        resource_types: tuple[str, ...],
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        scope_field = "hashed_team_id" if team_id else "hashed_user_id"
        scope_hash = _hash_id(team_id or user_id)
        manifests = await self._get_items_bounded(
            collection="cold_archive_manifests",
            params={
                "filter": {
                    "_and": [
                        {scope_field: {"_eq": scope_hash}},
                        {"resource_type": {"_in": list(resource_types)}},
                        {"state": {"_eq": "cold"}},
                    ]
                },
                "fields": "id,archive_id,resource_type,resource_id,hashed_user_id,hashed_team_id,encrypted_listing_metadata,active_generation,part_count,state,archived_at",
                "sort": "-archived_at,-archive_id",
            },
            admin_required=True,
        )
        items: list[dict[str, Any]] = []
        failures: list[dict[str, str]] = []
        for manifest in manifests:
            if filters and not _matches_export_filters(manifest, filters):
                continue
            archive_id = str(manifest.get("archive_id") or "")
            generation = int(manifest.get("active_generation") or 0)
            parts = await self._get_items_bounded(
                collection="cold_archive_parts",
                params={
                    "filter": {
                        "_and": [
                            {"archive_id": {"_eq": archive_id}},
                            {"generation": {"_eq": generation}},
                        ]
                    },
                    "fields": "archive_id,part_id,part_number,generation,checksum,size_bytes,regional_states",
                    "sort": "part_number",
                },
                admin_required=True,
            )
            expected_parts = int(manifest.get("part_count") or 0)
            if expected_parts and len(parts) < expected_parts:
                failures.append({"item_id": archive_id, "reason": "missing_cold_archive_part"})
            items.append(
                {
                    "archive_id": archive_id,
                    "resource_type": manifest.get("resource_type"),
                    "resource_id": manifest.get("resource_id"),
                    "active_generation": generation,
                    "encrypted_listing_metadata": manifest.get("encrypted_listing_metadata"),
                    "part_count": expected_parts,
                    "archived_at": manifest.get("archived_at"),
                    "parts": [_safe_cold_part(part) for part in parts],
                }
            )
        return {"items": items, "failures": failures}

    async def _get_items_bounded(
        self,
        *,
        collection: str,
        params: dict[str, Any],
        admin_required: bool = False,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        offset = 0
        while True:
            page_params = dict(params)
            page_params["limit"] = DIRECTUS_EXPORT_PAGE_SIZE
            page_params["offset"] = offset
            page = await self._directus_get_items(collection, page_params, admin_required=admin_required)
            if not page:
                break
            rows.extend(page)
            if len(page) < DIRECTUS_EXPORT_PAGE_SIZE:
                break
            offset += DIRECTUS_EXPORT_PAGE_SIZE
        return rows

    async def _directus_get_items(
        self,
        collection: str,
        params: dict[str, Any],
        *,
        admin_required: bool = False,
    ) -> list[dict[str, Any]]:
        try:
            rows = await self.directus_service.get_items(
                collection,
                params=params,
                no_cache=True,
                admin_required=admin_required,
                raise_on_error=True,
            )
        except TypeError as exc:
            if "unexpected keyword" not in str(exc):
                raise
            rows = await self.directus_service.get_items(collection, params=params)
        if not isinstance(rows, list):
            raise AccountExportError(f"Directus export read failed for {collection}")
        return rows

    async def _authorize_team_export(self, *, user_id: str, team_id: str) -> None:
        team_service = getattr(self.directus_service, "team", None)
        if team_service is None:
            raise AccountExportAuthorizationError("Team export permission denied")
        try:
            await team_service.require_team_role(team_id, user_id, TEAM_EXPORT_ROLES)
        except Exception as exc:
            raise AccountExportAuthorizationError("Team export permission denied") from exc

    async def _authorize_job_access(self, *, job: dict[str, Any], user_id: str, team_id: str | None) -> None:
        if job.get("user_id_hash") != _hash_id(user_id):
            raise AccountExportNotFoundError("Export job not found")
        job_team_hash = job.get("team_id_hash")
        if job_team_hash:
            if not team_id or job_team_hash != _hash_id(team_id):
                raise AccountExportAuthorizationError("Team export permission denied")
            await self._authorize_team_export(user_id=user_id, team_id=team_id)
        elif team_id:
            raise AccountExportAuthorizationError("Team export permission denied")

    async def _get_user_job(self, user_id: str, export_id: str, *, team_id: str | None) -> dict[str, Any]:
        job = self._jobs.get(export_id)
        if not job:
            job = await self._load_persisted_job(export_id=export_id)
            if not job:
                raise AccountExportNotFoundError("Export job not found")
            self._jobs[export_id] = job
        await self._authorize_job_access(job=job, user_id=user_id, team_id=team_id)
        if _job_is_expired(job):
            await self._purge_expired_job(job)
            raise AccountExportNotFoundError("Export job expired")
        return job

    def _can_persist_exports(self) -> bool:
        return all(
            callable(getattr(self.directus_service, method_name, None))
            for method_name in ("create_item", "get_items", "update_item")
        )

    async def _create_persisted_job(self, job: dict[str, Any]) -> None:
        if not self._can_persist_exports():
            return
        success, created = await self._directus_create_item(
            ACCOUNT_EXPORT_JOB_COLLECTION,
            _job_storage_payload(job),
        )
        if not success or not isinstance(created, dict):
            raise AccountExportError("Failed to persist export job")
        job["_row_id"] = created.get("id")

    async def _persist_parts(self, job: dict[str, Any]) -> None:
        for chunk in job["chunks"]:
            await self._persist_part(job, chunk)

    async def _persist_part(self, job: dict[str, Any], chunk: dict[str, Any]) -> None:
        success, created = await self._directus_create_item(
            ACCOUNT_EXPORT_PART_COLLECTION,
            _part_storage_payload(job, chunk),
        )
        if not success or not isinstance(created, dict):
            raise AccountExportError("Failed to persist export part")

    async def _mark_job_failed(self, job: dict[str, Any], *, reason: str) -> None:
        if not any(failure.get("reason") == reason for failure in job["failures"]):
            job["failures"].append({"domain": "export", "item_id": job["export_id"], "reason": reason})
        job["status"] = "failed"
        job["updated_at"] = _utc_now()
        job["progress"]["failed_items"] = len(job["failures"])
        await self._persist_job_update(job)

    async def _persist_job_update(self, job: dict[str, Any]) -> None:
        if not self._can_persist_exports() or not job.get("_row_id"):
            return
        updated = await self._directus_update_item(
            ACCOUNT_EXPORT_JOB_COLLECTION,
            str(job["_row_id"]),
            _job_storage_payload(job),
        )
        if not updated:
            raise AccountExportError("Failed to update export job")

    async def _directus_create_item(self, collection: str, payload: dict[str, Any]) -> tuple[bool, dict[str, Any] | None]:
        try:
            return await self.directus_service.create_item(collection, payload, admin_required=True)
        except TypeError as exc:
            if "unexpected keyword" not in str(exc):
                raise
            return await self.directus_service.create_item(collection, payload)

    async def _directus_update_item(self, collection: str, item_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        try:
            return await self.directus_service.update_item(collection, item_id, payload, admin_required=True)
        except TypeError as exc:
            if "unexpected keyword" not in str(exc):
                raise
            return await self.directus_service.update_item(collection, item_id, payload)

    async def _directus_delete_items(self, collection: str, filter_dict: dict[str, Any]) -> int | None:
        delete_items = getattr(self.directus_service, "delete_items", None)
        if not callable(delete_items):
            return None
        try:
            deleted = await delete_items(collection, filter_dict, admin_required=True)
        except TypeError as exc:
            if "unexpected keyword" not in str(exc):
                raise
            deleted = await delete_items(collection, filter_dict)
        return int(deleted or 0)

    async def _directus_delete_exact_rows(self, collection: str, filter_dict: dict[str, Any]) -> int:
        rows = await self._get_items_bounded(
            collection=collection,
            params={"filter": filter_dict, "fields": "id"},
            admin_required=True,
        )
        expected_count = len(rows)
        if expected_count == 0:
            return 0
        deleted_count = await self._directus_delete_items(collection, filter_dict)
        if deleted_count is None:
            raise AccountExportError(f"Directus export purge is unavailable for {collection}")
        if deleted_count < expected_count:
            raise AccountExportError(f"Failed to purge expired export rows from {collection}")
        return deleted_count

    async def _purge_expired_job(self, job: dict[str, Any]) -> None:
        export_id = str(job["export_id"])
        if self._can_persist_exports():
            await self._directus_delete_exact_rows(ACCOUNT_EXPORT_PART_COLLECTION, {"export_id": {"_eq": export_id}})
            await self._directus_delete_exact_rows(ACCOUNT_EXPORT_JOB_COLLECTION, {"export_id": {"_eq": export_id}})
        self._jobs.pop(export_id, None)
        job["chunks"] = []
        job["status"] = "expired"

    async def _load_persisted_job(self, *, export_id: str) -> dict[str, Any] | None:
        if not self._can_persist_exports():
            return None
        rows = await self._directus_get_items(
            ACCOUNT_EXPORT_JOB_COLLECTION,
            {"filter": {"export_id": {"_eq": export_id}}, "fields": "*", "limit": 1},
            admin_required=True,
        )
        if not rows:
            return None
        return _job_from_storage(rows[0])

    async def _load_persisted_parts(self, *, export_id: str) -> list[dict[str, Any]]:
        if not self._can_persist_exports():
            return []
        rows = await self._get_items_bounded(
            collection=ACCOUNT_EXPORT_PART_COLLECTION,
            params={"filter": {"export_id": {"_eq": export_id}}, "fields": "*", "sort": "sequence"},
            admin_required=True,
        )
        return [_part_from_storage(row) for row in rows]

    async def _load_persisted_part(self, *, export_id: str, chunk_id: str) -> dict[str, Any] | None:
        if not self._can_persist_exports():
            return None
        rows = await self._directus_get_items(
            ACCOUNT_EXPORT_PART_COLLECTION,
            {
                "filter": {"_and": [{"export_id": {"_eq": export_id}}, {"chunk_id": {"_eq": chunk_id}}]},
                "fields": "*",
                "limit": 1,
            },
            admin_required=True,
        )
        return _part_from_storage(rows[0]) if rows else None

    async def _update_last_export_at(self, user_id: str) -> None:
        await self.directus_service.update_user(user_id, {"last_export_at": _utc_now()})

    def _build_report(self, job: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": job["status"],
            "failures": list(job["failures"]),
            "redactions": sorted(FORBIDDEN_EXPORT_SECRET_FIELDS),
            "partial_requires_acceptance": job["status"] == "partial",
        }


def _hash_id(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _domain_filters(filters: dict[str, Any], domain: str) -> dict[str, Any]:
    value = filters.get(domain)
    return value if isinstance(value, dict) else {}


def _job_is_expired(job: dict[str, Any]) -> bool:
    expires_at = _parse_datetime(job.get("expires_at"))
    return expires_at is not None and expires_at <= datetime.now(timezone.utc)


def _matches_export_filters(row: dict[str, Any], filters: dict[str, Any]) -> bool:
    from_value = next((filters[key] for key in FILTER_FROM_KEYS if filters.get(key) not in (None, "", [])), None)
    to_value = next((filters[key] for key in FILTER_TO_KEYS if filters.get(key) not in (None, "", [])), None)
    row_timestamp = _row_filter_datetime(row)
    if from_value is not None:
        from_datetime = _required_filter_datetime(from_value, "from")
        if row_timestamp is None or row_timestamp < from_datetime:
            return False
    if to_value is not None:
        to_datetime = _required_filter_datetime(to_value, "to")
        if row_timestamp is None or row_timestamp > to_datetime:
            return False

    for key, expected in filters.items():
        if key in FILTER_FROM_KEYS or key in FILTER_TO_KEYS or expected in (None, "", []):
            continue
        if key == "ids":
            expected_ids = {str(value) for value in _list_value(expected)}
            if not expected_ids or not any(str(row.get(field)) in expected_ids for field in FILTER_ID_FIELDS):
                return False
            continue
        if key == "statuses":
            expected_statuses = {str(value) for value in _list_value(expected)}
            if str(row.get("status") or row.get("state") or "") not in expected_statuses:
                return False
            continue
        if isinstance(expected, dict):
            if not _matches_operator_filter(row.get(key), expected, key):
                return False
            continue
        if row.get(key) != expected:
            return False
    return True


def _matches_operator_filter(row_value: Any, operators: dict[str, Any], key: str) -> bool:
    unknown = sorted(set(operators) - FILTER_DIRECTUS_OPERATORS)
    if unknown:
        raise AccountExportFilterError(f"Unsupported filter operator(s) for {key}: {', '.join(unknown)}")
    if "_eq" in operators and row_value != operators["_eq"]:
        return False
    if "_in" in operators and row_value not in _list_value(operators["_in"]):
        return False
    if "_gte" in operators and _compare_filter_values(row_value, operators["_gte"]) < 0:
        return False
    if "_lte" in operators and _compare_filter_values(row_value, operators["_lte"]) > 0:
        return False
    return True


def _compare_filter_values(left: Any, right: Any) -> int:
    left_datetime = _parse_datetime(left)
    right_datetime = _parse_datetime(right)
    if left_datetime is not None and right_datetime is not None:
        return (left_datetime > right_datetime) - (left_datetime < right_datetime)
    try:
        left_number = float(left)
        right_number = float(right)
        return (left_number > right_number) - (left_number < right_number)
    except (TypeError, ValueError):
        left_text = str(left or "")
        right_text = str(right or "")
        return (left_text > right_text) - (left_text < right_text)


def _row_filter_datetime(row: dict[str, Any]) -> datetime | None:
    for field in FILTER_DATE_FIELDS:
        parsed = _parse_datetime(row.get(field))
        if parsed is not None:
            return parsed
    return None


def _required_filter_datetime(value: Any, key: str) -> datetime:
    parsed = _parse_datetime(value)
    if parsed is None:
        raise AccountExportFilterError(f"Invalid {key} filter datetime")
    return parsed


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)):
        parsed = datetime.fromtimestamp(value, tz=timezone.utc)
    elif isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None
        if len(normalized) == 7 and normalized[4] == "-":
            normalized = f"{normalized}-01"
        if normalized.endswith("Z"):
            normalized = f"{normalized[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _public_job(job: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in job.items()
        if key not in {"user_id_hash", "team_id_hash", "_row_id"}
    }


def _job_storage_payload(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "export_id": job["export_id"],
        "schema_version": job["schema_version"],
        "status": job["status"],
        "hashed_user_id": job["user_id_hash"],
        "hashed_team_id": job.get("team_id_hash"),
        "selected_domains": list(job["selected_domains"]),
        "default_domains": list(job["default_domains"]),
        "advanced_optional_domains": list(job["advanced_optional_domains"]),
        "filters": dict(job["filters"]),
        "format": job["format"],
        "progress": dict(job["progress"]),
        "chunks": [_chunk_manifest(chunk) for chunk in job["chunks"]],
        "domain_results": dict(job["domain_results"]),
        "failures": list(job["failures"]),
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
        "expires_at": job["expires_at"],
        "accepted_partial_at": job["accepted_partial_at"],
        "completed_at": job["completed_at"],
    }


def _part_storage_payload(job: dict[str, Any], chunk: dict[str, Any]) -> dict[str, Any]:
    payload = _redact_for_export(chunk["payload"])
    return {
        "export_id": job["export_id"],
        "chunk_id": chunk["chunk_id"],
        "part_id": chunk.get("part_id") or chunk["chunk_id"],
        "hashed_user_id": job["user_id_hash"],
        "hashed_team_id": job.get("team_id_hash"),
        "domain": chunk["domain"],
        "sequence": chunk["sequence"],
        "status": chunk["status"],
        "content_type": chunk["content_type"],
        "payload": payload,
        "payload_bytes": len(repr(payload).encode()),
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
    }


def _job_from_storage(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "_row_id": row.get("id"),
        "export_id": row["export_id"],
        "schema_version": row.get("schema_version") or EXPORT_SCHEMA_VERSION,
        "status": row.get("status") or "queued",
        "selected_domains": _list_value(row.get("selected_domains")),
        "default_domains": _list_value(row.get("default_domains")) or list(DEFAULT_EXPORT_DOMAINS),
        "advanced_optional_domains": _list_value(row.get("advanced_optional_domains")) or list(ADVANCED_OPTIONAL_EXPORT_DOMAINS),
        "filters": _dict_value(row.get("filters")),
        "format": row.get("format") or "zip",
        "progress": _dict_value(row.get("progress")),
        "chunks": _list_value(row.get("chunks")),
        "domain_results": _dict_value(row.get("domain_results")),
        "failures": _list_value(row.get("failures")),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "expires_at": row.get("expires_at"),
        "accepted_partial_at": row.get("accepted_partial_at"),
        "completed_at": row.get("completed_at"),
        "user_id_hash": row.get("hashed_user_id") or row.get("user_id_hash"),
        "team_id_hash": row.get("hashed_team_id") or row.get("team_id_hash"),
    }


def _part_from_storage(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "chunk_id": row.get("chunk_id") or row.get("part_id"),
        "part_id": row.get("part_id") or row.get("chunk_id"),
        "domain": row.get("domain"),
        "sequence": row.get("sequence"),
        "status": row.get("status") or "ready",
        "content_type": row.get("content_type") or "application/json",
        "payload": _dict_value(row.get("payload")),
    }


def _chunk_manifest(chunk: dict[str, Any]) -> dict[str, Any]:
    return {
        "chunk_id": chunk["chunk_id"],
        "part_id": chunk.get("part_id") or chunk["chunk_id"],
        "domain": chunk["domain"],
        "sequence": chunk["sequence"],
        "status": chunk["status"],
        "content_type": chunk["content_type"],
    }


def _safe_cold_part(part: dict[str, Any]) -> dict[str, Any]:
    return {
        "archive_id": part.get("archive_id"),
        "part_id": part.get("part_id"),
        "part_number": part.get("part_number"),
        "generation": part.get("generation"),
        "checksum": part.get("checksum"),
        "size_bytes": part.get("size_bytes"),
        "regional_states": dict(part.get("regional_states") or {}),
    }


def _safe_task_archive_reference(row: dict[str, Any]) -> dict[str, Any]:
    reference = {"archive_s3_key": row.get("archive_s3_key"), "task_count": row.get("task_count")}
    if row.get("archived_at") is not None:
        reference["archived_at"] = row.get("archived_at")
    return _redact_for_export(reference)


def _list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _domain_count(payload: dict[str, Any]) -> int:
    items = payload.get("items")
    count = len(items) if isinstance(items, list) else 0
    runs = payload.get("runs")
    if isinstance(runs, list):
        count += len(runs)
    cold_archives = payload.get("cold_archives")
    if isinstance(cold_archives, list):
        count += len(cold_archives)
    return count


def _is_personal_row(row: dict[str, Any]) -> bool:
    return not any(row.get(field) for field in ("hashed_team_id", "team_id_hash", "team_id"))


def _is_team_row(row: dict[str, Any], *, team_id: str) -> bool:
    team_hash = _hash_id(team_id)
    return row.get("hashed_team_id") == team_hash or row.get("team_id_hash") == team_hash or row.get("team_id") == team_id


def _upload_s3_objects(upload: dict[str, Any]) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    metadata = upload.get("files_metadata")
    if isinstance(metadata, dict):
        for variant in metadata.values():
            if not isinstance(variant, dict) or not variant.get("s3_key"):
                continue
            objects.append(
                {
                    "bucket": variant.get("bucket") or "chatfiles",
                    "key": variant.get("s3_key"),
                    "size_bytes": variant.get("size_bytes"),
                }
            )
    return objects


def _consent_metadata(profile: dict[str, Any]) -> dict[str, Any]:
    return _redact_for_export(
        {
            "user_id": profile.get("id"),
            "terms_accepted_at": profile.get("terms_accepted_at"),
            "privacy_policy_accepted_at": profile.get("privacy_policy_accepted_at"),
            "last_export_at": profile.get("last_export_at"),
        }
    )


def _redact_for_export(value: Any) -> Any:
    if isinstance(value, list):
        return [_redact_for_export(item) for item in value]
    if not isinstance(value, dict):
        return value
    redacted: dict[str, Any] = {}
    for key, item in value.items():
        normalized_key = key.lower()
        if normalized_key.startswith("encrypted_") or normalized_key in FORBIDDEN_EXPORT_SECRET_FIELDS or normalized_key.endswith("_secret"):
            continue
        redacted[key] = _redact_for_export(item)
    return redacted
