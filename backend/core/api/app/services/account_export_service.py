"""Account Export V1 job service.

Purpose: build a resumable personal export contract shared by CLI, SDKs, web,
and later Apple parity.
Architecture: docs/specs/account-export-v1/spec.yml.
Security: emits user-owned metadata and encrypted payload references only; no
reusable credentials, raw keys, token hashes, or team-scoped rows.
Privacy: updates last_export_at only after complete or accepted partial exports.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import uuid
from typing import Any


EXPORT_JOB_TTL_HOURS = 24
EXPORT_SCHEMA_VERSION = "account-export-v1"
TERMINAL_EXPORT_STATUSES = {"complete", "partial_accepted", "failed", "cancelled", "expired"}

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

DOMAIN_COLLECTIONS = {
    "chats": ("chats", "hashed_user_id"),
    "usage": ("usage", "user_id_hash"),
    "billing_invoices": ("invoices", "user_id_hash"),
    "memories_app_settings": ("user_app_settings_and_memories", "hashed_user_id"),
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


class AccountExportService:
    """In-process export job coordinator with an injectable Directus dependency."""

    default_domains = DEFAULT_EXPORT_DOMAINS
    advanced_optional_domains = ADVANCED_OPTIONAL_EXPORT_DOMAINS
    filterable_domains = FILTERABLE_EXPORT_DOMAINS

    def __init__(self, directus_service: Any, *, jobs: dict[str, dict[str, Any]] | None = None) -> None:
        self.directus_service = directus_service
        self._jobs = jobs if jobs is not None else {}

    async def start_export(
        self,
        *,
        user_id: str,
        domains: list[str] | None = None,
        filters: dict[str, Any] | None = None,
        include_advanced_metadata: bool = False,
        output_format: str = "zip",
    ) -> dict[str, Any]:
        selected_domains = self._normalize_domains(domains, include_advanced_metadata=include_advanced_metadata)
        normalized_filters = filters or {}
        self._validate_filters(selected_domains, normalized_filters)

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
        }
        await self._build_job_chunks(user_id=user_id, job=job)
        self._jobs[export_id] = job
        return _public_job(job)

    async def get_job(self, *, user_id: str, export_id: str) -> dict[str, Any]:
        return _public_job(self._get_user_job(user_id, export_id))

    async def get_manifest(self, *, user_id: str, export_id: str) -> dict[str, Any]:
        job = self._get_user_job(user_id, export_id)
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

    async def list_chunks(self, *, user_id: str, export_id: str) -> list[dict[str, Any]]:
        job = self._get_user_job(user_id, export_id)
        return [dict(chunk) for chunk in job["chunks"]]

    async def get_chunk(self, *, user_id: str, export_id: str, chunk_id: str) -> dict[str, Any]:
        job = self._get_user_job(user_id, export_id)
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
    ) -> dict[str, Any]:
        job = self._get_user_job(user_id, export_id)
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
        return _public_job(job)

    async def mark_complete(self, *, user_id: str, export_id: str) -> dict[str, Any]:
        job = self._get_user_job(user_id, export_id)
        if job["failures"]:
            job["status"] = "partial"
            job["updated_at"] = _utc_now()
            return _public_job(job)
        job["status"] = "complete"
        job["completed_at"] = _utc_now()
        job["updated_at"] = job["completed_at"]
        job["progress"]["completed_domains"] = len(job["selected_domains"])
        await self._update_last_export_at(user_id)
        return _public_job(job)

    async def accept_partial(self, *, user_id: str, export_id: str) -> dict[str, Any]:
        job = self._get_user_job(user_id, export_id)
        if job["status"] != "partial":
            raise AccountExportError("Only partial exports can be accepted")
        now = _utc_now()
        job["status"] = "partial_accepted"
        job["accepted_partial_at"] = now
        job["updated_at"] = now
        await self._update_last_export_at(user_id)
        return _public_job(job)

    async def cancel_export(self, *, user_id: str, export_id: str) -> dict[str, Any]:
        job = self._get_user_job(user_id, export_id)
        if job["status"] in TERMINAL_EXPORT_STATUSES:
            return _public_job(job)
        job["status"] = "cancelled"
        job["updated_at"] = _utc_now()
        return _public_job(job)

    async def _build_job_chunks(self, *, user_id: str, job: dict[str, Any]) -> None:
        manifest_domains: dict[str, dict[str, Any]] = {}
        chunks: list[dict[str, Any]] = []
        for domain in job["selected_domains"]:
            payload = await self._domain_payload(user_id=user_id, domain=domain)
            manifest_domains[domain] = {
                "status": "ready",
                "count": _domain_count(payload),
                "source": payload.get("source", "generated"),
            }
            chunks.append(
                {
                    "chunk_id": f"{domain}-0001",
                    "domain": domain,
                    "sequence": 1,
                    "status": "ready",
                    "content_type": "application/json",
                    "payload": _redact_for_export(payload),
                }
            )
        job["chunks"] = chunks
        job["domain_results"] = manifest_domains

    async def _domain_payload(self, *, user_id: str, domain: str) -> dict[str, Any]:
        if domain == "chats":
            return await self._chats_payload(user_id=user_id)
        if domain == "embeds":
            rows = await self._get_personal_rows(collection="embeds", user_field="hashed_user_id", user_id=user_id)
            return {"source": "embeds", "items": rows}
        if domain == "referenced_uploads":
            return await self._referenced_uploads_payload(user_id=user_id)
        if domain == "projects":
            rows = await self._get_personal_rows(collection="projects", user_field="hashed_user_id", user_id=user_id)
            return {"source": "projects", "items": self._apply_domain_filters(domain, rows)}
        if domain == "tasks":
            rows = await self._get_personal_rows(collection="user_tasks", user_field="hashed_user_id", user_id=user_id)
            archives = await self._get_personal_rows(collection="user_task_archives", user_field="hashed_user_id", user_id=user_id)
            return {
                "source": "user_tasks+user_task_archives",
                "items": self._apply_domain_filters(domain, rows),
                "archives": [
                    _redact_for_export({"archive_s3_key": row.get("archive_s3_key"), "task_count": row.get("task_count")})
                    for row in archives
                    if row.get("archive_s3_key")
                ],
            }
        if domain == "plans":
            rows = await self._get_personal_rows(collection="user_plans", user_field="hashed_user_id", user_id=user_id)
            return {"source": "user_plans", "items": self._apply_domain_filters(domain, rows)}
        if domain == "workflows_runs":
            workflows = await self._get_personal_rows(collection="workflows", user_field="hashed_user_id", user_id=user_id)
            runs = await self._get_personal_rows(collection="workflow_runs", user_field="hashed_user_id", user_id=user_id)
            return {
                "source": "workflows+workflow_runs",
                "items": self._apply_domain_filters(domain, workflows),
                "runs": self._apply_domain_filters(domain, runs),
            }
        if domain == "usage":
            rows = await self._get_personal_rows(collection="usage", user_field="user_id_hash", user_id=user_id)
            archives = await self._usage_archive_references(user_id=user_id)
            return {"source": "usage+usage_archives", "items": rows, "archives": archives}
        if domain == "profile_account_settings":
            profile = await self._safe_profile_payload(user_id=user_id)
            return {"source": "directus_users", "items": [profile] if profile else []}
        if domain == "compliance_consent_history":
            profile = await self._safe_profile_payload(user_id=user_id)
            return {"source": "directus_users.consent_metadata", "items": [_consent_metadata(profile)] if profile else []}
        if domain in DOMAIN_COLLECTIONS:
            collection, user_field = DOMAIN_COLLECTIONS[domain]
            rows = await self._get_personal_rows(collection=collection, user_field=user_field, user_id=user_id)
            return {"source": collection, "items": rows}
        if domain == "connected_account_overview":
            return {"source": "safe_metadata", "items": []}
        return {"source": "not_yet_materialized", "items": []}

    async def _get_personal_rows(self, *, collection: str, user_field: str, user_id: str) -> list[dict[str, Any]]:
        params = {
            "filter": {
                user_field: {"_eq": _hash_id(user_id)},
            },
            "limit": -1,
        }
        if user_field == "user_id":
            params["filter"][user_field] = {"_eq": user_id}
        rows = await self.directus_service.get_items(collection, params=params)
        return [_redact_for_export(row) for row in (rows or []) if _is_personal_row(row)]

    async def _chats_payload(self, *, user_id: str) -> dict[str, Any]:
        chats = await self._get_personal_rows(collection="chats", user_field="hashed_user_id", user_id=user_id)
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
        return {"source": "chats+messages+embeds", "items": self._apply_domain_filters("chats", chats)}

    async def _referenced_uploads_payload(self, *, user_id: str) -> dict[str, Any]:
        uploads = await self._get_personal_rows(collection="upload_files", user_field="user_id", user_id=user_id)
        items = []
        for upload in uploads:
            item = _redact_for_export(upload)
            item["s3_objects"] = _upload_s3_objects(upload)
            items.append(item)
        return {"source": "upload_files+chatfiles", "items": items}

    async def _usage_archive_references(self, *, user_id: str) -> list[dict[str, Any]]:
        archives: list[dict[str, Any]] = []
        for collection in ("usage_monthly_chat_summaries", "usage_monthly_app_summaries", "usage_monthly_api_key_summaries"):
            rows = await self._get_personal_rows(collection=collection, user_field="user_id_hash", user_id=user_id)
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
        rows = await self.directus_service.get_items(
            collection,
            params={"filter": {field: {"_in": values}}, "limit": -1},
        )
        return [row for row in (rows or []) if _is_personal_row(row)]

    async def _safe_profile_payload(self, *, user_id: str) -> dict[str, Any]:
        if hasattr(self.directus_service, "get_user"):
            profile = await self.directus_service.get_user(user_id)
        else:
            profile = {"id": user_id}
        return _redact_for_export(profile or {})

    def _apply_domain_filters(self, domain: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return rows

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

    def _get_user_job(self, user_id: str, export_id: str) -> dict[str, Any]:
        job = self._jobs.get(export_id)
        if not job or job.get("user_id_hash") != _hash_id(user_id):
            raise AccountExportNotFoundError("Export job not found")
        return job

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


def _public_job(job: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in job.items()
        if key not in {"user_id_hash"}
    }


def _domain_count(payload: dict[str, Any]) -> int:
    items = payload.get("items")
    count = len(items) if isinstance(items, list) else 0
    runs = payload.get("runs")
    if isinstance(runs, list):
        count += len(runs)
    return count


def _is_personal_row(row: dict[str, Any]) -> bool:
    return not any(row.get(field) for field in ("hashed_team_id", "team_id_hash", "team_id"))


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
        if normalized_key in FORBIDDEN_EXPORT_SECRET_FIELDS or normalized_key.endswith("_secret"):
            continue
        redacted[key] = _redact_for_export(item)
    return redacted
