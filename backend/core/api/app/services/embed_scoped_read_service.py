"""Internal typed-UUID continuation reads for already authorized embed scopes."""

import os
from typing import Any


async def read_embed_uuid_page(directus: Any, request: dict[str, Any]) -> list[dict[str, Any]]:
    # Directus's UUID filter validator rejects REST _lt/_gt. Its internal
    # extension compares PostgreSQL UUIDs without changing public cursors.
    token = os.getenv("INTERNAL_API_SHARED_TOKEN")
    if not token:
        raise RuntimeError("INTERNAL_API_SHARED_TOKEN is required for embed continuation")
    response = await directus._make_api_request(
        "POST", f"{directus.base_url.rstrip('/')}/embed-version-transaction/scoped-read",
        headers={"X-Internal-Service-Token": token}, json=request,
    )
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise RuntimeError("Embed continuation page unavailable")
    return rows
