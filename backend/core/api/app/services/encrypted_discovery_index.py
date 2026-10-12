"""Bounded, ciphertext-only Project discovery index.

Every hit makes a fresh owner/Team-scoped Directus watermark read. The cache
holds only client-encrypted Project summary metadata, never keys, private
Project items, Focus bodies, or memory values. Authorization belongs to the
first-party route before this helper is called.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any

from backend.core.api.app.services.directus.project_methods import _owner_params

DISCOVERY_TTL_SECONDS = 2 * 60 * 60
MAX_PROJECTS = 200
MAX_INDEX_BYTES = 256 * 1024
MAX_OPAQUE_ROWS = 1000
logger = logging.getLogger(__name__)
_KEY_FIELD = "encrypted_project_key"
_CACHED_PROJECT_FIELDS = {
    "project_id", "encrypted_name", "encrypted_slug", "encrypted_description",
    "encrypted_icon", "encrypted_color", "pinned", "archived", "is_private",
    "is_shared", "version", "updated_at", "last_opened_at", "item_count",
}
_WATERMARK_FIELDS = (
    "id,project_id,hashed_user_id,hashed_team_id,created_by_user_hash,slug_lookup_hash,"
    "created_at,version,updated_at,last_opened_at,pinned,archived,item_count,"
    "is_private,is_shared,encrypted_project_key"
)


def _key(user_id: str, team_id: str | None, vault_key_id: str) -> str:
    scope = json.dumps([user_id, team_id, vault_key_id], separators=(",", ":"))
    return "project:discovery:encrypted:v1:" + hashlib.sha256(scope.encode()).hexdigest()


def _watermark(rows: list[dict[str, Any]]) -> str:
    fields = _WATERMARK_FIELDS.split(",")
    ordered = [
        [row.get(field) for field in fields]
        for row in sorted(rows, key=lambda row: str(row.get("project_id") or ""))
    ]
    return hashlib.sha256(json.dumps(ordered, separators=(",", ":"), sort_keys=True).encode()).hexdigest()


async def _fresh_watermark_rows(directus: Any, user_id: str, team_id: str | None) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "fields": _WATERMARK_FIELDS,
        "sort": "-pinned,-last_opened_at,-updated_at",
        "limit": -1,
        "filter[archived][_neq]": True,
    }
    params.update(_owner_params(user_id, team_id))
    rows = await directus.get_items("projects", params=params, no_cache=True, raise_on_error=True)
    if not isinstance(rows, list):
        raise RuntimeError("Project discovery watermark unavailable")
    return rows


def _ciphertext_index(rows: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    if len(rows) > MAX_PROJECTS:
        return None
    safe = [{key: value for key, value in row.items() if key in _CACHED_PROJECT_FIELDS} for row in rows]
    encoded = json.dumps(safe, separators=(",", ":"), ensure_ascii=True)
    return safe if len(encoded.encode()) <= MAX_INDEX_BYTES else None


async def list_encrypted_project_discovery(
    *, cache: Any, directus: Any, user_id: str, team_id: str | None,
) -> list[dict[str, Any]]:
    """Read encrypted summaries with a fresh visibility/version fence.

    A cache failure uses the original owner-scoped Directus list. Fresh wrapped
    keys come only from the watermark query and are never retained in cache.
    """
    try:
        vault_key_id = await cache.get_user_vault_key_id(user_id) if cache else None
    except Exception:
        vault_key_id = None
    if not vault_key_id:
        return await directus.project.list_projects(user_id, team_id=team_id)
    key = _key(user_id, team_id, vault_key_id)
    started = time.monotonic()
    try:
        cached = await cache.get(key)
        if isinstance(cached, dict) and isinstance(cached.get("rows"), list):
            fresh = await _fresh_watermark_rows(directus, user_id, team_id)
            if len(fresh) <= MAX_PROJECTS and cached.get("watermark") == _watermark(fresh):
                indexed = {
                    row.get("project_id"): row for row in cached["rows"]
                    if isinstance(row, dict) and isinstance(row.get("project_id"), str)
                }
                if len(indexed) == len(fresh) and all(row.get("project_id") in indexed for row in fresh):
                    client = await cache.client
                    if client:
                        await client.expire(key, DISCOVERY_TTL_SECONDS)
                    logger.info("encrypted_discovery_index kind=project cache=hit rows=%d watermark_ms=%d", len(fresh), int((time.monotonic() - started) * 1000))
                    return [
                        {**indexed[row["project_id"]], **row}
                        for row in fresh
                    ]
    except Exception:
        # The cold path remains authoritative. Cache/read failures cannot grant
        # access, serve stale data, or cause a denied Project discovery.
        pass

    rows = await directus.project.list_projects(user_id, team_id=team_id)
    logger.info("encrypted_discovery_index kind=project cache=miss rows=%d watermark_ms=%d", len(rows), int((time.monotonic() - started) * 1000))
    safe = _ciphertext_index(rows)
    if safe is not None:
        try:
            fresh = await _fresh_watermark_rows(directus, user_id, team_id)
            if _watermark(rows) == _watermark(fresh):
                await cache.set(key, {"watermark": _watermark(fresh), "rows": safe}, ttl=DISCOVERY_TTL_SECONDS)
        except Exception:
            pass
    return rows


async def _opaque_read_through(
    *, cache: Any, key: str, kind: str, fetch: Any,
) -> list[dict[str, Any]]:
    """Refresh an opaque ID/revision index against a fresh scoped listing.

    The fresh read is the visibility and revision authority. No cache entry is
    ever used without it, and all entries have a sliding two-hour TTL.
    """
    started = time.monotonic()
    rows = await fetch()
    if not isinstance(rows, list):
        raise RuntimeError(f"{kind} discovery unavailable")
    if len(rows) > MAX_OPAQUE_ROWS:
        return rows
    watermark = hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    try:
        cached = await cache.get(key) if cache else None
        if isinstance(cached, dict) and cached.get("watermark") == watermark and cached.get("rows") == rows:
            client = await cache.client
            if client:
                await client.expire(key, DISCOVERY_TTL_SECONDS)
            logger.info("encrypted_discovery_index kind=%s cache=hit rows=%d watermark_ms=%d", kind, len(rows), int((time.monotonic() - started) * 1000))
            return cached["rows"]
        if cache and len(json.dumps(rows).encode()) <= MAX_INDEX_BYTES:
            await cache.set(key, {"watermark": watermark, "rows": rows}, ttl=DISCOVERY_TTL_SECONDS)
    except Exception:
        pass
    logger.info("encrypted_discovery_index kind=%s cache=miss rows=%d watermark_ms=%d", kind, len(rows), int((time.monotonic() - started) * 1000))
    return rows


async def list_project_focus_discovery(
    *, cache: Any, directus: Any, user_id: str, team_id: str | None, project_id: str,
) -> list[dict[str, Any]]:
    """Project item IDs and revisions; never cache item or Focus ciphertext."""
    from backend.core.api.app.services.directus.project_methods import hash_id

    params: dict[str, Any] = {
        "fields": "project_item_id,updated_at,item_type",
        "filter[hashed_project_id][_eq]": hash_id(project_id),
        "sort": "project_item_id",
        "limit": -1,
    }
    params.update(_owner_params(user_id, team_id))
    try:
        vault_key_id = await cache.get_user_vault_key_id(user_id) if cache else None
    except Exception:
        vault_key_id = None
    key = _key(user_id, team_id, vault_key_id or "") + ":focus:" + hash_id(project_id)

    async def fetch() -> list[dict[str, Any]]:
        source = await directus.get_items("project_items", params=params, no_cache=True, raise_on_error=True)
        if not isinstance(source, list):
            raise RuntimeError("Project Focus discovery unavailable")
        return [
            {"project_item_id": row["project_item_id"], "revision": row.get("updated_at"), "item_type": row.get("item_type")}
            for row in source if isinstance(row, dict) and isinstance(row.get("project_item_id"), str)
        ]

    return await _opaque_read_through(cache=cache if vault_key_id else None, key=key, kind="focus", fetch=fetch)


async def list_team_memory_key_discovery(
    *, cache: Any, directus: Any, user_id: str, team_id: str,
    app_id: str | None = None, item_type: str | None = None,
) -> list[dict[str, Any]]:
    """Team memory key metadata only; no encrypted or decrypted item values."""
    from backend.core.api.app.services.directus.team_methods import hash_id

    filters: dict[str, Any] = {"hashed_team_id": {"_eq": hash_id(team_id)}}
    if app_id:
        filters["app_id"] = {"_eq": app_id}
    if item_type:
        filters["item_type"] = {"_eq": item_type}
    params = {
        "filter": filters,
        "fields": "id,app_id,item_key,item_type,item_version,updated_at",
        "sort": "-updated_at",
        "limit": -1,
    }
    try:
        vault_key_id = await cache.get_user_vault_key_id(user_id) if cache else None
    except Exception:
        vault_key_id = None
    scope = json.dumps([app_id, item_type], separators=(",", ":"))
    key = _key(user_id, team_id, vault_key_id or "") + ":memory_keys:" + hashlib.sha256(scope.encode()).hexdigest()

    async def fetch() -> list[dict[str, Any]]:
        source = await directus.get_items("user_app_settings_and_memories", params=params, no_cache=True, raise_on_error=True)
        if not isinstance(source, list):
            raise RuntimeError("Team memory discovery unavailable")
        return [
            {field: row.get(field) for field in ("id", "app_id", "item_key", "item_type", "item_version", "updated_at")}
            for row in source if isinstance(row, dict)
        ]

    return await _opaque_read_through(cache=cache if vault_key_id else None, key=key, kind="team_memory", fetch=fetch)
