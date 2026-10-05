"""Authoritative, read-only storage quote client.

The internal Directus endpoint groups canonical references by logical
(bucket, key) in SQL. Object IDs, ciphertext, and regional replica rows are
never transferred to the API worker. Incomplete metadata blocks a quote.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


MAX_OWNER_PAGE = 100
SOURCE_VERSION = "logical-s3-v1"
PERSONAL_POLICY_VERSION = "personal-storage-1gb-3credits-week-v1"
LEGACY_SOURCE_VERSION = "legacy-upload-files-v1"
LEGACY_PERSONAL_POLICY_VERSION = "legacy-upload-storage-1gb-3credits-week-v1"
LOGICAL_S3_BILLING_SWITCH = "STORAGE_LOGICAL_S3_BILLING_ENABLED"
TEAM_POLICY_VERSION = "unrated-team-usage-v1"
CATEGORIES = frozenset({
    "legacy_uploads", "chat_pages", "chat_oversized", "cold_chat_graphs",
    "sealed_recovery", "embed_versions",
})
UPLOAD_CATEGORIES = frozenset({
    "images", "videos", "audio", "pdf", "code", "docs", "sheets", "archives", "other",
})


class StorageUsageIncompleteError(RuntimeError):
    """No charge or complete settings quote may be made from this result."""


@dataclass(frozen=True)
class StorageUsageQuote:
    owner_kind: str
    owner_id: str
    policy_version: str
    source_version: str
    complete: bool
    categories: dict[str, int]
    legacy_upload_bytes: int
    logical_s3_bytes: int
    total_bytes: int
    measurement_at: int


def _bytes(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise StorageUsageIncompleteError("storage_usage_invalid_bytes")
    return value


def _parse_quote(row: Any, *, owner_kind: str, legacy_only: bool = False) -> StorageUsageQuote:
    if not isinstance(row, dict) or row.get("owner_kind") != owner_kind or row.get("complete") is not True:
        raise StorageUsageIncompleteError("storage_usage_incomplete")
    owner_id = row.get("owner_id")
    categories = row.get("categories")
    if not isinstance(owner_id, str) or not owner_id or not isinstance(categories, dict):
        raise StorageUsageIncompleteError("storage_usage_invalid_owner")
    if any(key not in CATEGORIES for key in categories):
        raise StorageUsageIncompleteError("storage_usage_invalid_category")
    parsed = {key: _bytes(value) for key, value in categories.items()}
    legacy = _bytes(row.get("legacy_upload_bytes"))
    logical = _bytes(row.get("logical_s3_bytes"))
    total = _bytes(row.get("total_bytes"))
    measurement_at = _bytes(row.get("measurement_at"))
    if measurement_at == 0:
        raise StorageUsageIncompleteError("storage_usage_invalid_measurement_time")
    if legacy != parsed.get("legacy_uploads", 0) or logical != sum(
        value for key, value in parsed.items() if key != "legacy_uploads"
    ) or total != legacy + logical:
        raise StorageUsageIncompleteError("storage_usage_total_mismatch")
    policy = (LEGACY_PERSONAL_POLICY_VERSION if legacy_only else
              PERSONAL_POLICY_VERSION if owner_kind == "personal" else TEAM_POLICY_VERSION)
    source = LEGACY_SOURCE_VERSION if legacy_only else SOURCE_VERSION
    if legacy_only and (owner_kind != "personal" or logical != 0 or set(parsed) != {"legacy_uploads"}):
        raise StorageUsageIncompleteError("storage_usage_legacy_scope_mismatch")
    if row.get("policy_version") != policy or row.get("source_version") != source:
        raise StorageUsageIncompleteError("storage_usage_version_mismatch")
    return StorageUsageQuote(
        owner_kind=owner_kind, owner_id=owner_id, policy_version=policy,
        source_version=source, complete=True, categories=parsed,
        legacy_upload_bytes=legacy, logical_s3_bytes=logical, total_bytes=total,
        measurement_at=measurement_at,
    )


class StorageUsageMeteringService:
    def __init__(self, directus_service: Any) -> None:
        self._directus = directus_service

    async def _execute(self, body: dict[str, Any]) -> list[Any]:
        token = os.getenv("INTERNAL_API_SHARED_TOKEN")
        if not token:
            raise StorageUsageIncompleteError("storage_metering_internal_token_missing")
        response = await self._directus._make_api_request(
            "POST", f"{self._directus.base_url.rstrip('/')}/storage-usage-metering",
            headers={"X-Internal-Service-Token": token}, json=body,
        )
        if response.status_code != 200:
            raise StorageUsageIncompleteError("storage_metering_unavailable")
        try:
            data = response.json().get("data")
        except (ValueError, AttributeError) as exc:
            raise StorageUsageIncompleteError("storage_metering_invalid_response") from exc
        if not isinstance(data, list):
            raise StorageUsageIncompleteError("storage_metering_invalid_response")
        return data

    async def list_personal_owner_ids(
        self, after_user_id: str | None = None, limit: int = MAX_OWNER_PAGE,
    ) -> list[str]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_OWNER_PAGE:
            raise ValueError("invalid_owner_page")
        if after_user_id is not None and (not isinstance(after_user_id, str) or not after_user_id):
            raise ValueError("invalid_owner_cursor")
        rows = await self._execute({
            "operation": "list_personal_owners", "after_user_id": after_user_id, "limit": limit,
        })
        if len(rows) > limit or any(not isinstance(row, str) or not row for row in rows):
            raise StorageUsageIncompleteError("storage_metering_invalid_owner_page")
        if rows != sorted(set(rows)) or (after_user_id and rows and rows[0] <= after_user_id):
            raise StorageUsageIncompleteError("storage_metering_invalid_owner_page")
        return rows

    async def upload_breakdown(self, user_id: str) -> list[dict[str, int | str]]:
        if not isinstance(user_id, str) or not user_id:
            raise ValueError("invalid_owner")
        rows = await self._execute({"operation": "upload_breakdown", "user_id": user_id})
        if len(rows) > len(UPLOAD_CATEGORIES):
            raise StorageUsageIncompleteError("storage_usage_invalid_breakdown")
        result: list[dict[str, int | str]] = []
        seen: set[str] = set()
        for row in rows:
            if not isinstance(row, dict) or row.get("category") not in UPLOAD_CATEGORIES:
                raise StorageUsageIncompleteError("storage_usage_invalid_breakdown")
            category = row["category"]
            if category in seen or _bytes(row.get("file_count")) == 0:
                raise StorageUsageIncompleteError("storage_usage_invalid_breakdown")
            seen.add(category)
            result.append({
                "category": category,
                "file_count": _bytes(row.get("file_count")),
                "bytes_used": _bytes(row.get("bytes_used")),
            })
        return result

    async def quote_personal(self, user_ids: list[str]) -> dict[str, StorageUsageQuote]:
        return await self._quote(
            user_ids, owner_kind="personal",
            legacy_only=os.getenv(LOGICAL_S3_BILLING_SWITCH) != "1",
        )

    async def quote_team(self, team_hashes: list[str]) -> dict[str, StorageUsageQuote]:
        """Unrated Team usage; callers must not apply personal billing policy."""
        return await self._quote(team_hashes, owner_kind="team", legacy_only=False)

    async def _quote(
        self, owner_ids: list[str], *, owner_kind: str, legacy_only: bool,
    ) -> dict[str, StorageUsageQuote]:
        if (not isinstance(owner_ids, list) or len(owner_ids) > MAX_OWNER_PAGE
                or any(not isinstance(item, str) or not item for item in owner_ids)
                or len(set(owner_ids)) != len(owner_ids)):
            raise ValueError("invalid_owner_page")
        if not owner_ids:
            return {}
        rows = await self._execute({
            "operation": "quote",
            "user_ids": owner_ids if owner_kind == "personal" else [],
            "team_hashes": owner_ids if owner_kind == "team" else [],
            "legacy_only": legacy_only,
        })
        quotes = [_parse_quote(row, owner_kind=owner_kind, legacy_only=legacy_only) for row in rows]
        by_owner = {quote.owner_id: quote for quote in quotes}
        if len(by_owner) != len(owner_ids) or set(by_owner) != set(owner_ids):
            raise StorageUsageIncompleteError("storage_metering_missing_owner")
        return by_owner
