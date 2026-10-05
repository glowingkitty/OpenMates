"""Team-scoped export/import service for Teams V1.

Exports are authorization-checked owner/admin artifacts containing selected Team
metadata plus hot and verified archived ciphertext. V1 imports support selected
metadata only; content restoration fails before persistence. The actor must be
destination owner/admin and the artifact must be marked as destination-rewrapped.

Specifications: features/teams and architecture/storage-lifecycle.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, AsyncIterator, Callable
from uuid import uuid4

from backend.core.api.app.services.directus.team_methods import hash_id


TEAM_SCOPED_COLLECTIONS = (
    "team_memberships",
    "team_invites",
    "team_credit_accounts",
    "team_credit_events",
    "team_usage_events",
    "user_app_settings_and_memories",
    "connected_accounts",
    "team_connected_account_grants",
)

# Exporting authority records for inspection does not authorize restoring them.
# Membership/invite APIs enforce role invariants; billing transactions alone may
# write spendable balances and their financial or usage ledgers.
TEAM_AUTHORITY_COLLECTIONS = frozenset({
    "team_memberships", "team_invites", "team_credit_accounts",
    "team_credit_events", "team_usage_events",
})
TEAM_IMPORTABLE_COLLECTIONS = frozenset({
    "user_app_settings_and_memories", "connected_accounts", "team_connected_account_grants",
})

SECRET_FIELDS = {
    "encrypted_team_key",
    "encrypted_refresh_token_bundle",
    "encrypted_server_access_ref",
    "one_time_token_hash",
}

MAX_TEAM_INLINE_EXPORT_BYTES = 8 * 1024 * 1024
TEAM_EXPORT_JOB_HINT = "Use POST /v1/account-exports with team_id for a persisted multipart Team export"


class TeamDataPortabilityError(ValueError):
    """Raised when an export/import artifact violates team isolation rules."""


class TeamDataPortabilityService:
    def __init__(self, directus_service: Any, *, s3_service: Any | None = None) -> None:
        self.directus_service = directus_service
        self.s3_service = s3_service

    async def export_team_data(self, team_id: str, actor_user_id: str, *, export_id: str | None = None, created_at: int | None = None) -> dict[str, Any]:
        await self.directus_service.team.require_team_role(team_id, actor_user_id, {"owner", "admin"})
        now = int(created_at or time.time())
        team_hash = hash_id(team_id)
        artifact: dict[str, Any] = {
            "schema": "openmates.team_export.v1",
            "export_id": export_id or str(uuid4()),
            "hashed_team_id": team_hash,
            "created_at": now,
            "collections": {},
        }
        collections = artifact["collections"]
        # The V1 endpoint returns one JSON artifact. Account export jobs provide
        # the persisted, resumable path for Teams whose data exceeds this limit.
        # Reserve envelope/list punctuation and admit each row/part before adding
        # it. iterencode avoids allocating a second giant serialized artifact.
        remaining = MAX_TEAM_INLINE_EXPORT_BYTES - 4096
        encoder = json.JSONEncoder(ensure_ascii=True, separators=(",", ":"), default=str)

        def admit(row: dict[str, Any]) -> dict[str, Any]:
            nonlocal remaining
            for fragment in encoder.iterencode(row):
                remaining -= len(fragment.encode("utf-8"))
                if remaining < 0:
                    raise TeamDataPortabilityError(f"Team export exceeds the inline byte limit. {TEAM_EXPORT_JOB_HINT}")
            remaining -= 1
            return row

        from backend.core.api.app.services.account_export_service import AccountExportService

        export = AccountExportService(self.directus_service, s3_service=self.s3_service)
        collections["teams"] = [admit(self._redact_row(row)) async for row in export._iter_items_bounded(
            collection="teams", params={"filter[hashed_team_id][_eq]": team_hash, "sort": "id"}, admin_required=True,
        ) if row.get("hashed_team_id") == team_hash]
        for collection in TEAM_SCOPED_COLLECTIONS:
            collections[collection] = [admit(self._redact_row(row)) async for row in export._iter_items_bounded(
                collection=collection, params={"filter[hashed_team_id][_eq]": team_hash, "sort": "id"}, admin_required=True,
            ) if row.get("hashed_team_id") == team_hash]
        # Reuse the account export's bounded, integrity checked ciphertext readers.
        # The Team role gate above grants this scope; importing these records still
        # requires the destination Team to rewrap its client ciphertext.
        for key in ("chats", "chat_message_archive_pages", "embeds", "embed_diffs"):
            collections[key] = []
        async for chunk in export._chats_payload_chunks(user_id=actor_user_id, team_id=team_id, filters={}):
            collections["chats"].extend(admit(row) for row in chunk.get("items") or [])
        async for embed in export._iter_export_embeds(user_id=actor_user_id, team_id=team_id):
            collections["embeds"].append(admit(self._redact_row(embed)))
        async for chunk in export._message_archive_payload_chunks(user_id=actor_user_id, team_id=team_id, filters={}):
            if chunk.get("failures"):
                raise TeamDataPortabilityError("Team message archive is incomplete or corrupt")
            collections["chat_message_archive_pages"].extend(admit(row) for row in chunk.get("items") or [])
        async for chunk in export._embed_version_payload_chunks(user_id=actor_user_id, team_id=team_id):
            if chunk.get("failures"):
                raise TeamDataPortabilityError("Team version archive is incomplete or corrupt")
            collections["embed_diffs"].extend(admit(row) for row in chunk.get("items") or [])
        collections["cold_archives"] = [archive async for archive in self._export_cold_archives(export, team_hash, admit)]
        artifact_hash = hashlib.sha256(repr(artifact).encode()).hexdigest()
        await self.directus_service.create_item(
            "team_data_exports",
            {
                "export_id": artifact["export_id"],
                "hashed_team_id": team_hash,
                "actor_user_hash": hash_id(actor_user_id),
                "artifact_hash": artifact_hash,
                "encrypted_manifest": "redacted-team-export-manifest",
                "status": "ready",
                "created_at": now,
                "expires_at": None,
            },
            admin_required=True,
        )
        return {"artifact": artifact, "artifact_hash": artifact_hash}

    async def get_team_export(self, team_id: str, actor_user_id: str, export_id: str) -> dict[str, Any]:
        await self.directus_service.team.require_team_role(team_id, actor_user_id, {"owner", "admin"})
        rows = await self.directus_service.get_items(
            "team_data_exports",
            params={
                "filter[hashed_team_id][_eq]": hash_id(team_id),
                "filter[export_id][_eq]": export_id,
                "filter[status][_eq]": "ready",
                "fields": "export_id,artifact_hash,encrypted_manifest,status,created_at,expires_at",
                "limit": 1,
            },
            no_cache=True,
            admin_required=True,
        )
        if not rows or not isinstance(rows, list):
            raise TeamDataPortabilityError("Team export not found")
        return {"export": rows[0]}

    async def import_team_data(self, destination_team_id: str, actor_user_id: str, artifact: dict[str, Any], *, imported_at: int | None = None) -> dict[str, Any]:
        await self.directus_service.team.require_team_role(destination_team_id, actor_user_id, {"owner", "admin"})
        if artifact.get("schema") != "openmates.team_export.v1":
            raise TeamDataPortabilityError("Invalid team export schema")
        if artifact.get("rewrapped_with_destination_team_key") is not True:
            raise TeamDataPortabilityError("Team export must be rewrapped with destination team key before import")
        collections = artifact.get("collections")
        if not isinstance(collections, dict):
            raise TeamDataPortabilityError("Team export collections are missing")
        # V1 imports selected metadata. Graph restore needs destination ciphertext
        # rewrapping and identity remapping, which this endpoint cannot perform.
        # Validate the whole artifact before writing any selected metadata so a
        # successful response can never silently discard exported content.
        for collection, rows in collections.items():
            if not isinstance(rows, list):
                raise TeamDataPortabilityError(f"Invalid rows for {collection}")
            if collection in TEAM_AUTHORITY_COLLECTIONS and rows:
                raise TeamDataPortabilityError(
                    f"Server-controlled Team records cannot be imported ({collection}); "
                    "use Team membership/invite or billing operations; no rows were imported"
                )
            if collection != "teams" and collection not in TEAM_IMPORTABLE_COLLECTIONS and rows:
                raise TeamDataPortabilityError(
                    f"Team content restore is unsupported for {collection}; no rows were imported"
                )
            for row in rows:
                if not isinstance(row, dict):
                    raise TeamDataPortabilityError(f"Invalid row for {collection}")
                if row.get("owner_context") == "personal" or row.get("hashed_user_id") and not row.get("hashed_team_id"):
                    raise TeamDataPortabilityError("Personal-context rows cannot be imported into a team")
        destination_hash = hash_id(destination_team_id)
        now = int(imported_at or time.time())
        imported_count = 0
        for collection, rows in collections.items():
            if collection not in TEAM_IMPORTABLE_COLLECTIONS:
                continue
            for row in rows:
                clean = {key: value for key, value in row.items() if key not in {"id", *SECRET_FIELDS}}
                clean["hashed_team_id"] = destination_hash
                if collection in {"user_app_settings_and_memories", "connected_accounts"}:
                    clean["owner_context"] = "team"
                    clean["updated_at"] = now
                await self.directus_service.create_item(collection, clean, admin_required=True)
                imported_count += 1
        return {"success": True, "imported_rows": imported_count, "hashed_team_id": destination_hash}

    async def _export_cold_archives(
        self, export: Any, team_hash: str, admit: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> AsyncIterator[dict[str, Any]]:
        """Export only this Team's verified immutable archive generations."""
        from backend.core.api.app.services.cold_archive_export import (
            ColdArchiveExportError, cold_archive_metadata, iter_cold_archive_parts,
        )

        manifests = export._iter_items_bounded(
            collection="cold_archive_manifests",
            params={"filter[hashed_team_id][_eq]": team_hash, "filter[state][_eq]": "cold", "sort": "id"},
            admin_required=True,
        )
        async for manifest in manifests:
            if manifest.get("hashed_team_id") != team_hash or manifest.get("state") != "cold":
                raise TeamDataPortabilityError("Team cold archive escaped authorized scope")
            try:
                item = admit({**cold_archive_metadata(manifest), "parts": []})
                async for part in iter_cold_archive_parts(export, manifest):
                    item["parts"].append(admit(part))
                yield item
            except ColdArchiveExportError as exc:
                raise TeamDataPortabilityError("Team cold archive is incomplete or corrupt") from exc

    def _redact_row(self, row: dict[str, Any]) -> dict[str, Any]:
        return {key: ("<redacted>" if key in SECRET_FIELDS else value) for key, value in row.items()}
