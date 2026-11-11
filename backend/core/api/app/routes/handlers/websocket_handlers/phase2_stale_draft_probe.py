# backend/core/api/app/routes/handlers/websocket_handlers/phase2_stale_draft_probe.py
# Phase 2 answer to the client's stale-draft probe. A device that was closed
# while drafts were deleted elsewhere keeps showing them: Redis draft and chat
# tombstones expire after 30 minutes, a draft-only chat has no chat row (so no
# durable deletion fence), and inferred deletions only cover the top-100 window.
# The client therefore sends a bounded list of its own idle local draft chat ids
# with their draft_v. An id is reported only with positive delete evidence: this
# user's durable delete record (services/draft_deletion_record.py) at a version
# >= the probed one and no draft present. A merely missing server draft is never
# reported, because replayed and async-persisted drafts can live only in Redis.
# spec: specifications/architecture/drafts#drafts.sync.version-authoritative
#       specifications/architecture/drafts#drafts.draft-only.lifecycle

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from typing import Any, Dict, List, Optional

from backend.core.api.app.services.draft_deletion_record import draft_deletion_record_key

logger = logging.getLogger(__name__)

# One request per reconnect, at most this many ids (client and server both cap).
STALE_DRAFT_PROBE_LIMIT = 200


class StaleDraftProbeUnavailable(RuntimeError):
    """A lookup failed; no absence may be reported (fail closed)."""


def _is_canonical_uuid(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(uuid.UUID(value)) == value
    except (ValueError, AttributeError):
        return False


def parse_stale_draft_probe(raw: Any) -> Dict[str, int]:
    """Return `{chat_id: probed draft_v}` of a `stale_draft_probe` request, in order.

    Wire format: a list of `{"chat_id": "<uuid>", "draft_v": <int >= 1>}` entries.
    Malformed entries are dropped; the result is capped at STALE_DRAFT_PROBE_LIMIT
    so one reconnect never costs more than one bounded batch of reads.
    """
    if not isinstance(raw, list):
        return {}
    probe: Dict[str, int] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        chat_id, draft_v = entry.get("chat_id"), entry.get("draft_v")
        if not _is_canonical_uuid(chat_id) or chat_id in probe:
            continue
        if isinstance(draft_v, bool) or not isinstance(draft_v, int) or draft_v < 1:
            continue
        probe[chat_id] = draft_v
        if len(probe) >= STALE_DRAFT_PROBE_LIMIT:
            break
    return probe

def _decode(value: Any) -> Any:
    return value.decode("utf-8") if isinstance(value, bytes) else value


def _cached_draft_state(draft_hash: Any) -> str:
    """`present`, `deleted` (versioned tombstone) or `unknown` (ask Directus)."""
    if not draft_hash:
        return "unknown"
    fields = {_decode(key): _decode(value) for key, value in draft_hash.items()}
    if fields.get("deleted") == "true":
        return "deleted"
    encrypted_md = fields.get("encrypted_draft_md")
    try:
        version = int(fields.get("draft_v") or 0)
    except (TypeError, ValueError):
        return "unknown"
    if encrypted_md and encrypted_md != "null" and version > 0:
        return "present"
    return "unknown"


def _recorded_delete_version(record_hash: Any) -> Optional[int]:
    """Deleted draft version of a durable delete record, or None without one."""
    if not record_hash:
        return None
    fields = {_decode(key): _decode(value) for key, value in record_hash.items()}
    try:
        version = int(fields.get("draft_v") or 0)
    except (TypeError, ValueError):
        return None
    return version if version > 0 else None

def _cached_chat_alive(metadata_value: Any) -> bool:
    """A live cached chat header (not yet persisted rows count as existing)."""
    if not metadata_value:
        return False
    try:
        metadata = json.loads(_decode(metadata_value))
    except (TypeError, ValueError):
        # Unreadable header: keep the chat (never infer absence from garbage).
        return True
    if not isinstance(metadata, dict):
        return True
    # A deletion tombstone is the only cached header that does not prove a chat.
    deleted = metadata.get("deleted")
    return not (deleted is True or str(deleted).lower() in {"1", "true", "yes"})


async def _read_cache_state(cache_service: Any, user_id: str, chat_ids: List[str]):
    client = await cache_service.client
    if not client:
        raise StaleDraftProbeUnavailable("cache_unavailable")
    try:
        async with client.pipeline(transaction=False) as pipe:
            for chat_id in chat_ids:
                pipe.hgetall(cache_service._get_user_chat_draft_key(user_id, chat_id))
                pipe.get(f"chat:{chat_id}:metadata")
                pipe.hgetall(draft_deletion_record_key(user_id, chat_id))
            responses = await pipe.execute()
    except Exception as exc:  # Redis errors of any kind must not read as absence.
        raise StaleDraftProbeUnavailable("cache_read_failed") from exc
    drafts: Dict[str, str] = {}
    alive: set[str] = set()
    deleted_versions: Dict[str, int] = {}
    for index, chat_id in enumerate(chat_ids):
        draft_hash, metadata, record = responses[3 * index:3 * index + 3]
        drafts[chat_id] = _cached_draft_state(draft_hash)
        if _cached_chat_alive(metadata):
            alive.add(chat_id)
        deleted_v = _recorded_delete_version(record)
        if deleted_v is not None:
            deleted_versions[chat_id] = deleted_v
    return drafts, alive, deleted_versions

async def _read_rows(directus_service: Any, collection: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = await directus_service.get_items(
        collection, params=params, no_cache=True, admin_required=True, raise_on_error=True,
    )
    if not isinstance(rows, list):
        raise StaleDraftProbeUnavailable(f"{collection}_lookup_failed")
    return [row for row in rows if isinstance(row, dict)]


async def evaluate_stale_draft_probe(
    cache_service: Any,
    directus_service: Any,
    user_id: str,
    probe: Dict[str, int],
) -> Dict[str, List[str]]:
    """Answer the probe for Personal-workspace ids from positive delete evidence.

    An id is reported only when this user's durable draft delete record exists,
    its deleted version is >= the probed `draft_v` and no draft of this user is
    present (cached, or persisted at a version above the delete). Absence of a
    server draft alone is never reported: replayed and async-persisted drafts
    can live only in Redis, so "missing" does not mean "deleted".

    Returns `absent_chat_ids` (delete recorded, no chat row of anyone, neither
    persisted nor cached) and `draft_absent_chat_ids` (delete recorded, a
    Personal chat row owned by this user exists). A chat row of another user or
    of a Team is never reported, so a readable shared chat is never removed.

    Raises StaleDraftProbeUnavailable when any lookup fails or returns an
    unusable shape; the caller then omits the result instead of guessing.
    """
    empty: Dict[str, List[str]] = {"absent_chat_ids": [], "draft_absent_chat_ids": []}
    chat_ids = list(probe)
    if not chat_ids:
        return empty
    cached_drafts, cached_alive, deleted_versions = await _read_cache_state(cache_service, user_id, chat_ids)
    candidates = [
        chat_id for chat_id in chat_ids
        if deleted_versions.get(chat_id, 0) >= probe[chat_id] and cached_drafts.get(chat_id) != "present"
    ]
    if not candidates:
        return empty
    owner_hash = hashlib.sha256(user_id.encode()).hexdigest()
    joined_ids = ",".join(candidates)
    try:
        draft_rows = await _read_rows(directus_service, "drafts", {
            "filter[hashed_user_id][_eq]": owner_hash,
            "filter[chat_id][_in]": joined_ids,
            "fields": "chat_id,encrypted_content,version",
            "limit": -1,
        })
        chat_rows = await _read_rows(directus_service, "chats", {
            "filter[id][_in]": joined_ids,
            "fields": "id,hashed_user_id,hashed_team_id",
            "limit": -1,
        })
    except StaleDraftProbeUnavailable:
        raise
    except Exception as exc:  # Directus/transport errors must not read as absence.
        raise StaleDraftProbeUnavailable("directus_lookup_failed") from exc

    newer_persisted_ids = set()
    for row in draft_rows:
        chat_id, content = row.get("chat_id"), row.get("encrypted_content")
        if not chat_id or not content or content == "null":
            continue
        try:
            version = int(row.get("version") or 0)
        except (TypeError, ValueError):
            # Unreadable version: keep the draft rather than guess it is older.
            newer_persisted_ids.add(chat_id)
            continue
        # A persisted copy at or below the recorded delete is the deleted one
        # (Directus cleanup may lag); a newer one is a re-created draft.
        if version > deleted_versions.get(chat_id, 0):
            newer_persisted_ids.add(chat_id)
    rows_by_id = {row.get("id"): row for row in chat_rows if row.get("id")}

    absent: List[str] = []
    draft_absent: List[str] = []
    for chat_id in candidates:
        if chat_id in newer_persisted_ids:
            continue
        row = rows_by_id.get(chat_id)
        if row is None:
            if chat_id not in cached_alive:
                absent.append(chat_id)
            continue
        if row.get("hashed_user_id") == owner_hash and not row.get("hashed_team_id"):
            draft_absent.append(chat_id)
    return {"absent_chat_ids": absent, "draft_absent_chat_ids": draft_absent}

async def stale_draft_probe_fields(
    cache_service: Any,
    directus_service: Any,
    user_id: str,
    probe: Dict[str, int],
    team_id: Optional[str],
) -> Dict[str, Any]:
    """Phase 2 payload fields for a probe; empty when none applies or a read failed.

    Team workspaces are never probed: Team drafts carry their own pending-sync
    protocol and are excluded on the client as well.
    """
    if team_id or not probe:
        return {}
    try:
        result = await evaluate_stale_draft_probe(cache_service, directus_service, user_id, probe)
    except StaleDraftProbeUnavailable as exc:
        logger.warning("Phase 2: stale draft probe unavailable for user %s: %s", user_id[:8], exc)
        return {}
    logger.info(
        "Phase 2: stale draft probe of %d id(s): %d deleted without chat, %d deleted on own chat",
        len(probe), len(result["absent_chat_ids"]), len(result["draft_absent_chat_ids"]),
    )
    return {"stale_draft_probe_result": result}
