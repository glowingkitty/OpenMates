"""Internal client for atomic client-encrypted Project embed revisions."""

from __future__ import annotations

import hashlib
import logging
import os
import re
from collections.abc import Mapping
from typing import Any, TypedDict

logger = logging.getLogger(__name__)

HOSTED_PROJECT_EMBED_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


def logical_embed_version(value: object) -> int:
    """Interpret legacy nullable initial heads without coercing corrupt values."""
    if value is None:
        return 1
    if type(value) is not int or not 1 <= value <= 2_147_483_647:
        raise ValueError("Invalid canonical embed version")
    return value


class CanonicalEmbedPrecondition(TypedDict):
    version: int | None
    ciphertext_sha256: str | None


def validate_canonical_precondition(value: object) -> CanonicalEmbedPrecondition:
    """Validate the protocol-only compare-and-swap condition for an opaque head."""
    if not isinstance(value, dict) or set(value) != {"version", "ciphertext_sha256"}:
        raise ValueError("Invalid canonical embed precondition")
    version, digest = value["version"], value["ciphertext_sha256"]
    if version is None and digest is None:
        return {"version": None, "ciphertext_sha256": None}
    if (version is None or logical_embed_version(version) != version
            or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
        raise ValueError("Invalid canonical embed precondition")
    return {"version": version, "ciphertext_sha256": digest}


def is_hosted_project_embed_id(embed_id: object) -> bool:
    """Identify deterministic opaque hosted-file ids reserved for atomic commits."""
    return isinstance(embed_id, str) and HOSTED_PROJECT_EMBED_ID_RE.fullmatch(embed_id) is not None


async def requires_atomic_project_embed_write(directus_service: Any, embed_id: str) -> bool:
    """Return whether a legacy head/history writer must reject this embed.

    UUIDv5-formatted ids close the initial-create gap before a Project link
    exists. Existing non-v5 Project embeds are detected by opaque target hash.
    """
    if is_hosted_project_embed_id(embed_id):
        return True
    rows = await directus_service.get_items(
        "project_items",
        params={
            "filter[target_id_hash][_eq]": hashlib.sha256(embed_id.encode()).hexdigest(),
            "filter[item_type][_in]": "embed,upload",
            "fields": "id",
            "limit": 1,
        },
        no_cache=True,
        admin_required=True,
    )
    return isinstance(rows, list) and bool(rows)


class EmbedVersionTransactionError(RuntimeError):
    def __init__(self, status_code: int, code: str) -> None:
        self.status_code = status_code
        self.code = code
        super().__init__(f"Embed revision transaction failed: {code}")


class EmbedVersionTransactionService:
    def __init__(self, directus_service: Any) -> None:
        self._directus = directus_service

    async def write_legacy_embed_diff(self, embed_id: str, row: Mapping[str, Any], *, user_id: str) -> dict[str, Any]:
        """Internal-only history initialization, serialized with atomic edits."""
        token = os.getenv("INTERNAL_API_SHARED_TOKEN")
        if not token:
            raise RuntimeError("INTERNAL_API_SHARED_TOKEN is required for embed transactions")
        response = await self._directus._make_api_request(
            "POST", f"{self._directus.base_url.rstrip('/')}/embed-version-transaction/legacy-embed-diff-write",
            headers={"X-Internal-Service-Token": token},
            json={"embed_id": embed_id, "actor_user_hash": hashlib.sha256(user_id.encode()).hexdigest(), "row": dict(row)},
        )
        body = response.json()
        if response.status_code != 200:
            error = body.get("error") if isinstance(body, dict) else None
            raise EmbedVersionTransactionError(response.status_code,
                error.get("code", "history_transaction_failed") if isinstance(error, dict) else "history_transaction_failed")
        result = body.get("data") if isinstance(body, dict) else None
        if (not isinstance(result, dict) or result.get("embed_id") != embed_id
                or result.get("version_number") != row.get("version_number")
                or result.get("canonical_source") != "version_row"):
            raise RuntimeError("Encrypted history transaction returned malformed success data")
        return result

    async def write_legacy_embed_key(
        self, embed_id: str, wrapper: Mapping[str, Any], *, user_id: str,
    ) -> dict[str, Any]:
        """Upsert a wrapper under the canonical head's shared database lock."""
        token = os.getenv("INTERNAL_API_SHARED_TOKEN")
        if not token:
            raise RuntimeError("INTERNAL_API_SHARED_TOKEN is required for embed transactions")
        response = await self._directus._make_api_request(
            "POST", f"{self._directus.base_url.rstrip('/')}/embed-version-transaction/legacy-embed-key-write",
            headers={"X-Internal-Service-Token": token},
            json={"embed_id": embed_id, "actor_user_hash": hashlib.sha256(user_id.encode()).hexdigest(),
                  "wrapper": dict(wrapper)},
        )
        body = response.json()
        if response.status_code != 200:
            error = body.get("error") if isinstance(body, dict) else None
            raise EmbedVersionTransactionError(
                response.status_code, error.get("code", "key_transaction_failed") if isinstance(error, dict)
                else "key_transaction_failed",
            )
        result = body.get("data") if isinstance(body, dict) else None
        if not isinstance(result, dict) or not isinstance(result.get("embed"), dict):
            raise RuntimeError("Legacy embed key transaction returned malformed success data")
        return result

    async def write_legacy_embed(
        self, embed_id: str, payload: Mapping[str, Any], *, user_id: str,
        bundle_context: Mapping[str, Any] | None = None,
        canonical_metadata_enrichment: Mapping[str, Any] | None = None,
        canonical_precondition: CanonicalEmbedPrecondition | None = None,
    ) -> dict[str, Any]:
        """Persist one client-encrypted embed under the Project revision lock."""
        token = os.getenv("INTERNAL_API_SHARED_TOKEN")
        if not token:
            raise RuntimeError("INTERNAL_API_SHARED_TOKEN is required for embed transactions")
        response = await self._directus._make_api_request(
            "POST",
            f"{self._directus.base_url.rstrip('/')}/embed-version-transaction/legacy-embed-write",
            headers={"X-Internal-Service-Token": token},
            json={
                "embed_id": embed_id,
                "actor_user_hash": hashlib.sha256(user_id.encode()).hexdigest(),
                "payload": dict(payload),
                **({"bundle_context": dict(bundle_context)} if bundle_context is not None else {}),
                **({"canonical_metadata_enrichment": dict(canonical_metadata_enrichment)}
                   if canonical_metadata_enrichment is not None else {}),
                **({"canonical_precondition": validate_canonical_precondition(canonical_precondition)}
                   if canonical_precondition is not None else {}),
            },
        )
        try:
            body = response.json()
        except (TypeError, ValueError) as exc:
            raise RuntimeError("Legacy embed transaction returned malformed JSON") from exc
        if response.status_code != 200:
            error = body.get("error") if isinstance(body, dict) else None
            code = error.get("code") if isinstance(error, dict) else None
            raise EmbedVersionTransactionError(response.status_code, code or "transaction_failed")
        result = body.get("data") if isinstance(body, dict) else None
        if not isinstance(result, dict):
            raise RuntimeError("Legacy embed transaction returned malformed success data")
        return result

    async def commit(self, data: Mapping[str, Any], *, user_id: str) -> dict[str, Any]:
        if not isinstance(data, Mapping):
            raise TypeError("Embed revision transaction data must be a mapping")
        token = os.getenv("INTERNAL_API_SHARED_TOKEN")
        if not token:
            raise RuntimeError("INTERNAL_API_SHARED_TOKEN is required for embed revision transactions")
        body = dict(data)
        body["actor_user_hash"] = hashlib.sha256(user_id.encode()).hexdigest()
        response = await self._directus._make_api_request(
            "POST",
            f"{self._directus.base_url.rstrip('/')}/embed-version-transaction",
            headers={"X-Internal-Service-Token": token},
            json=body,
        )
        try:
            payload = response.json()
        except (TypeError, ValueError) as exc:
            raise RuntimeError("Embed revision extension returned malformed JSON") from exc
        if response.status_code != 200:
            error = payload.get("error") if isinstance(payload, dict) else None
            code = error.get("code") if isinstance(error, dict) else None
            safe_code = code if isinstance(code, str) and code else "transaction_failed"
            logger.warning(
                "Embed revision transaction rejected: code=%s status=%s",
                safe_code,
                response.status_code,
            )
            raise EmbedVersionTransactionError(response.status_code, safe_code)
        result = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(result, dict):
            raise RuntimeError("Embed revision extension returned malformed success data")
        return result

    async def commit_chat_diagram(self, data: Mapping[str, Any], *, user_id: str) -> dict[str, Any]:
        if not isinstance(data, Mapping):
            raise TypeError("Chat diagram revision transaction data must be a mapping")
        token = os.getenv("INTERNAL_API_SHARED_TOKEN")
        if not token:
            raise RuntimeError("INTERNAL_API_SHARED_TOKEN is required for embed revision transactions")
        body = dict(data)
        body["actor_user_hash"] = hashlib.sha256(user_id.encode()).hexdigest()
        response = await self._directus._make_api_request(
            "POST",
            f"{self._directus.base_url.rstrip('/')}/embed-version-transaction/chat-diagram-revision",
            headers={"X-Internal-Service-Token": token},
            json=body,
        )
        try:
            payload = response.json()
        except (TypeError, ValueError) as exc:
            raise RuntimeError("Chat diagram revision extension returned malformed JSON") from exc
        if response.status_code != 200:
            error = payload.get("error") if isinstance(payload, dict) else None
            code = error.get("code") if isinstance(error, dict) else None
            safe_code = code if isinstance(code, str) and code else "transaction_failed"
            logger.warning(
                "Chat diagram revision transaction rejected: code=%s status=%s",
                safe_code,
                response.status_code,
            )
            raise EmbedVersionTransactionError(response.status_code, safe_code)
        result = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(result, dict):
            raise RuntimeError("Chat diagram revision extension returned malformed success data")
        return result
