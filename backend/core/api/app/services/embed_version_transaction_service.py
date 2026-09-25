"""Internal client for atomic client-encrypted Project embed revisions."""

from __future__ import annotations

import hashlib
import logging
import os
import re
from collections.abc import Mapping
from typing import Any

logger = logging.getLogger(__name__)

HOSTED_PROJECT_EMBED_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


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
