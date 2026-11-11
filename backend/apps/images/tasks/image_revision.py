"""A change to a generated image of the same chat becomes the next version of that image.

Specification: feature.app-skill.images-generate (images-generate.revision.*).
Plan: docs/plans/image-edit-as-embed-version (Lane A). Wire contract for the
clients: docs/plans/image-edit-as-embed-version/wire-contract.md.

When a request names exactly one generated image of the same chat as its
reference, the task publishes version N+1 of that image embed instead of a new
image. The image keeps its original parent and key; the changing message's
skill result only records which version it shows (a pinned pointer), because a
child embed is never listed under a second parent. Uploaded images, images of
another chat and every other case keep today's behaviour (a new image).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from backend.shared.python_utils.chat_recovery_context import active_verified_output_producer
from backend.shared.python_utils.generated_media_graph import generated_media_embed_ref

logger = logging.getLogger(__name__)

# Off until the client lanes persist child revisions (plan Lane B/C); see wire-contract.md.
REVISIONS_ENV = "IMAGE_EDIT_AS_EMBED_VERSION"
GENERATED_IMAGE_SOURCE = "openmates_image_generate"
APP_ID = "images"
CHILD_TYPE = "generated_image"
S3_KEYS_CACHE_TTL_SECONDS = 3600
_UUID_V5 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")

# Embeds already claimed for a revision in the running batch: two requests of one
# call never both produce the same next version of one image.
_batch_claims: ContextVar[Optional[set]] = ContextVar("image_revision_batch_claims", default=None)


class RevisionPreconditionFailed(RuntimeError):
    """The image changed since the request started; nothing is charged or published."""


class RevisionNotSupported(RevisionPreconditionFailed):
    """The stored image lacks its images-generate catalog marker; nothing is charged or published.

    ``embeds.app_id``/``skill_id`` stay null when the chat had not synced when the
    first version was stored. The Directus extension then refuses every revision
    write, so the change must stop before the charge instead of being lost after it.
    """


@dataclass(frozen=True)
class RevisionTarget:
    """The canonical state of the image a request changes, read before any work."""

    embed_id: str
    parent_embed_id: str
    current_version: int
    s3_file_keys: Tuple[Mapping[str, str], ...]
    upload_record_id: str
    base_snapshot_required: bool
    # Hash of the message that created the image; the head keeps it for every version.
    hashed_message_id: str
    # Bytes of all earlier versions still stored (``upload_files.file_size_bytes``).
    retained_size_bytes: int
    # Identity of this change (changing message + producer intent); stable across task retries.
    change_id: str

    @property
    def next_version(self) -> int:
        return self.current_version + 1

    @property
    def embed_ref(self) -> str:
        return generated_media_embed_ref(APP_ID, self.embed_id)


def revisions_enabled() -> bool:
    return os.getenv(REVISIONS_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def billing_event_id(embed_id: str, version: int, change_id: Optional[str] = None) -> str:
    """Billing identity of one image version.

    Version 1 keeps the event id every image has been charged under (the embed
    id), so nothing charged before is charged again. A later version is charged
    under ``{embed_id}:v{N}:{change_id}``: the billing ledger deduplicates on
    this key alone, so the change's own identity must be in it. Two changes that
    both see version N (the head did not advance because no client persisted the
    first) are two charges; a retry of the same task has the same change id and
    is charged once.
    """
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValueError("Image version must be a positive integer")
    if version == 1:
        return str(embed_id)
    if not isinstance(change_id, str) or not change_id:
        raise ValueError("A later image version needs the identity of its change")
    return f"{embed_id}:v{version}:{change_id}"


def change_identity(*, message_id: str, intent_id: str) -> str:
    """Stable id of one change: the changing message and the producer intent that drew it."""
    if not message_id or not intent_id:
        raise ValueError("An image change needs its message and producer intent")
    return hashlib.sha256(f"{message_id}:{intent_id}".encode("utf-8")).hexdigest()[:32]


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _logical_version(value: Any) -> int:
    """Missing or null versions are logical version 1; anything else malformed fails closed."""
    if value is None:
        return 1
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise RevisionPreconditionFailed("Canonical image version is malformed")
    return value


def _json_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, list):
        raise RevisionPreconditionFailed("Canonical image file index is malformed")
    return value


async def _canonical_row(directus_service: Any, *, embed_id: str, owner_hash: str) -> Optional[Dict[str, Any]]:
    rows = await directus_service.get_items(
        "embeds", params={
            "filter[embed_id][_eq]": embed_id,
            "filter[hashed_user_id][_eq]": owner_hash,
            "fields": ("id,embed_id,hashed_user_id,hashed_chat_id,hashed_message_id,parent_embed_id,"
                       "version_number,s3_file_keys,app_id,skill_id"),
            "limit": 2,
        }, admin_required=True, no_cache=True, raise_on_error=True,
    )
    if not isinstance(rows, list):
        raise RuntimeError("Canonical embed lookup failed")
    return rows[0] if len(rows) == 1 and isinstance(rows[0], dict) else None


async def _generated_upload_record(directus_service: Any, *, embed_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    rows = await directus_service.get_items(
        "upload_files", params={
            "filter[embed_id][_eq]": embed_id,
            "filter[user_id][_eq]": user_id,
            "fields": "id,embed_id,ai_detection,file_size_bytes",
            "limit": 2,
        }, admin_required=True, no_cache=True, raise_on_error=True,
    )
    if not isinstance(rows, list):
        raise RuntimeError("Generated image index lookup failed")
    if len(rows) != 1 or not isinstance(rows[0], dict):
        return None
    detection = rows[0].get("ai_detection")
    if isinstance(detection, str):
        detection = json.loads(detection)
    if not isinstance(detection, Mapping) or detection.get("source") != GENERATED_IMAGE_SOURCE:
        return None
    return rows[0]


async def history_row_exists(directus_service: Any, *, embed_id: str, owner_hash: str, version: int) -> bool:
    rows = await directus_service.get_items(
        "embed_diffs", params={
            "filter[embed_id][_eq]": embed_id,
            "filter[hashed_user_id][_eq]": owner_hash,
            "filter[version_number][_eq]": version,
            "fields": "id", "limit": 1,
        }, admin_required=True, no_cache=True, raise_on_error=True,
    )
    if not isinstance(rows, list):
        raise RuntimeError("Canonical history lookup failed")
    return bool(rows)


def _same_chat_generated_child(row: Mapping[str, Any], *, chat_hash: str) -> bool:
    parent = row.get("parent_embed_id")
    return row.get("hashed_chat_id") == chat_hash and isinstance(parent, str) and bool(parent)


async def find_revision_target(
    directus_service: Any,
    *,
    reference_embed_ids: Sequence[str],
    chat_id: Optional[str],
    user_id: str,
    external_request: bool,
) -> Optional[RevisionTarget]:
    """Return the image a request changes, or ``None`` for a new image (today's behaviour).

    A revision needs: the feature switch, a registered chat producer (a durable
    output intent of this chat turn), and exactly one reference that is a stored
    images-generate child embed of this chat owned by this user. Uploaded images
    (no parent, no generated index) and images of another chat never qualify.
    Several qualifying references are a combination and make a new image.
    """
    if not revisions_enabled() or external_request or not chat_id or not reference_embed_ids:
        return None
    producer = active_verified_output_producer.get()
    if producer is None or producer.classification != "registered_ai" or producer.target_chat_id != chat_id:
        return None
    owner_hash, chat_hash = _hash(user_id), _hash(chat_id)
    candidates: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    for embed_id in dict.fromkeys(reference_embed_ids):
        row = await _canonical_row(directus_service, embed_id=embed_id, owner_hash=owner_hash)
        if row is None or not _same_chat_generated_child(row, chat_hash=chat_hash):
            continue
        record = await _generated_upload_record(directus_service, embed_id=embed_id, user_id=user_id)
        if record is not None:
            candidates.append((row, record))
    if len(candidates) != 1:
        return None
    row, record = candidates[0]
    embed_id = str(row["embed_id"])
    claims = _batch_claims.get()
    if claims is not None:
        if embed_id in claims:
            logger.info("Image %s already changes in this call; this request makes a new image", embed_id[:8])
            return None
        claims.add(embed_id)
    current_version = _logical_version(row.get("version_number"))
    keys = tuple(_json_list(row.get("s3_file_keys")))
    base_present = await history_row_exists(
        directus_service, embed_id=embed_id, owner_hash=owner_hash, version=current_version,
    )
    return RevisionTarget(
        embed_id=embed_id, parent_embed_id=str(row["parent_embed_id"]), current_version=current_version,
        s3_file_keys=keys, upload_record_id=str(record["id"]), base_snapshot_required=not base_present,
        hashed_message_id=str(row.get("hashed_message_id") or ""),
        retained_size_bytes=int(record.get("file_size_bytes") or 0),
        change_id=change_identity(message_id=str(producer.primary_message_id or ""),
                                  intent_id=str(producer.intent_id or "")),
    )


async def assert_current_version(directus_service: Any, target: RevisionTarget, *, user_id: str, chat_id: str) -> None:
    """Fail before charging when the image moved on or can never take this revision."""
    row = await _canonical_row(directus_service, embed_id=target.embed_id, owner_hash=_hash(user_id))
    if (row is None or not _same_chat_generated_child(row, chat_hash=_hash(chat_id))
            or row.get("parent_embed_id") != target.parent_embed_id
            or row.get("hashed_message_id") != target.hashed_message_id
            or _logical_version(row.get("version_number")) != target.current_version):
        raise RevisionPreconditionFailed(
            f"Image {target.embed_id[:8]} is no longer at version {target.current_version}"
        )
    if (not _UUID_V5.fullmatch(target.embed_id) or not _HEX_64.fullmatch(target.hashed_message_id)
            or (row.get("app_id"), row.get("skill_id")) != (APP_ID, CHILD_TYPE)):
        raise RevisionNotSupported(f"Image {target.embed_id[:8]} has no stored images-generate marker")


def union_file_keys(existing: Iterable[Mapping[str, Any]], new: Iterable[Mapping[str, Any]]) -> List[Dict[str, str]]:
    """Files of every version, in first-seen order: old versions stay viewable and are deleted with the embed."""
    merged: List[Dict[str, str]] = []
    seen: set = set()
    for ref in [*existing, *new]:
        bucket, key = ref.get("bucket"), ref.get("key")
        if not isinstance(bucket, str) or not isinstance(key, str) or not key:
            raise ValueError("Malformed file reference")
        if (bucket, key) not in seen:
            seen.add((bucket, key))
            merged.append({"bucket": bucket, "key": key})
    return merged


async def cache_file_keys(task: Any, *, target: RevisionTarget, new_keys: Sequence[Mapping[str, str]]) -> List[Dict[str, str]]:
    """Leave the union for ``store_embed`` to persist with the client's write of version N+1.

    Runs before the charge. The sidecar lives an hour; the durable copy of the
    union travels in the sealed recovery output (``publish_revision``).
    """
    union = union_file_keys(target.s3_file_keys, new_keys)
    client = await task._cache_service.client
    if not client:
        raise RuntimeError("File index cache is unavailable for an image revision")
    await client.set(f"embed:{target.embed_id}:s3_file_keys", json.dumps(union), ex=S3_KEYS_CACHE_TTL_SECONDS)
    return union


async def forget_cached_reference(task: Any, *, embed_id: str) -> None:
    """The cached media record names the old files; the next change must read the new version."""
    client = await task._cache_service.client
    if client:
        await client.delete(f"embed:{embed_id}")


def revision_content_fields(target: RevisionTarget) -> Dict[str, Any]:
    """Stored with the new version: which version it was made from (shown as the input picture)."""
    return {"revised_from": {"embed_id": target.embed_id, "version": target.current_version}}


def version_history_rows(target: RevisionTarget, *, content_toon: str, created_at: int) -> List[Dict[str, Any]]:
    """Full-replacement history row of the new version: its complete content, no patch.

    A text diff of image metadata carries no meaning. The server cannot read the
    client-encrypted current version, so a missing base snapshot is written by
    the client from its own head (``revision.base_snapshot_required``).
    """
    return [{
        "embed_id": target.embed_id,
        "version_number": target.next_version,
        "snapshot": content_toon,
        "created_at": created_at,
    }]


def pinned_pointer(target: RevisionTarget) -> Dict[str, Any]:
    """What the changing message shows: this embed at this version (absent version means 1)."""
    return {
        "embed_id": target.embed_id, "version": target.next_version, "embed_ref": target.embed_ref,
        "previous_version": target.current_version,
    }


def producer_outputs(target: RevisionTarget) -> List[Dict[str, Any]]:
    """Outputs the revision registers with the producer, for its closing manifest."""
    return [
        {"subject_id": target.embed_id, "output_kind": "embed", "output_version": target.next_version},
        {"subject_id": target.embed_id, "output_kind": "diff", "output_version": target.next_version},
    ]


def revision_note(target: RevisionTarget) -> str:
    """Tool result text for the chat model."""
    return (
        f"This change is version {target.next_version} of the existing image {target.embed_ref}; "
        f"no new image was created. Earlier messages keep showing the version they had "
        f"(version {target.current_version} before this change). Refer to it as {target.embed_ref}."
    )


def revision_result_fields(target: RevisionTarget) -> Dict[str, Any]:
    """Task result fields of a revision, read by the batch and the chat model."""
    return {
        "revision": True,
        "version": target.next_version,
        "previous_version": target.current_version,
        "pinned_embed": pinned_pointer(target),
        "producer_outputs": producer_outputs(target),
        "revision_note": revision_note(target),
    }


async def publish_revision(
    embed_service: Any,
    *,
    target: RevisionTarget,
    content: Dict[str, Any],
    s3_file_keys: Sequence[Mapping[str, str]],
    chat_id: str,
    message_id: str,
    user_id: str,
    user_id_hash: str,
    created_at: int,
    log_prefix: str,
) -> str:
    """Publish version N+1 of the image under its original parent, with its history row.

    The changing message is the producer's message; the embed service checks
    the canonical version again under the producer before sealing the output.
    """
    from toon_format import encode as toon_encode

    child_content = {**content, "type": CHILD_TYPE, "embed_ref": target.embed_ref}
    content_toon = toon_encode(child_content)
    await embed_service.send_embed_data_to_client(
        embed_id=target.embed_id,
        embed_type=CHILD_TYPE,
        content_toon=content_toon,
        chat_id=chat_id,
        message_id=message_id,
        user_id=user_id,
        user_id_hash=user_id_hash,
        status="finished",
        encryption_mode="client",
        created_at=created_at,
        updated_at=created_at,
        parent_embed_id=target.parent_embed_id,
        version_number=target.next_version,
        version_history_rows=version_history_rows(target, content_toon=content_toon, created_at=created_at),
        log_prefix=log_prefix,
        check_cache_status=False,
        app_id=APP_ID,
        skill_id=CHILD_TYPE,
        producer_revision={
            "embed_id": target.embed_id,
            "parent_embed_id": target.parent_embed_id,
            "expected_version": target.current_version,
            "base_snapshot_required": target.base_snapshot_required,
            "hashed_message_id": target.hashed_message_id,
            "s3_file_keys": [dict(ref) for ref in s3_file_keys],
        },
    )
    return target.embed_ref


async def refund_refused_revision(
    *, user_id: str, user_id_hash: str, credits: int, app_id: str, skill_id: str,
    event_id: str, team_id: Optional[str], log_prefix: str,
    reason: str = "Image change was refused before its new version was published",
) -> None:
    """Give back the charge of a change whose version the server refused to seal.

    Called for ``RevisionRefused``, which is raised before any output is sealed,
    so the user received nothing, and for an image Enhance result that never
    became a version (``enhance_jobs.refund``). Personal charges are refunded through
    ``/internal/billing/refund`` under ``app-skill:{event_id}:refund`` (idempotent
    per change). Team billing has no refund route: the charge stays and is
    logged as an error for manual correction.
    """
    if credits <= 0:
        return
    if team_id:
        logger.error("%s Refused image revision stays charged to its Team (%s credits): no Team refund route",
                     log_prefix, credits)
        return
    import httpx

    from backend.shared.python_utils.team_skill_billing import skill_billing_request

    _, charge = skill_billing_request({"user_id": user_id, "credits": credits}, None, event_id=event_id)
    base_url = os.getenv("INTERNAL_API_BASE_URL", "http://api:8000")
    token = os.getenv("INTERNAL_API_SHARED_TOKEN", "")
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(f"{base_url}/internal/billing/refund", json={
            "user_id": user_id, "user_id_hash": user_id_hash, "credits": credits,
            "app_id": app_id, "skill_id": skill_id,
            "idempotency_key": f"{charge['idempotency_key']}:refund",
            "reason": reason,
        }, headers={"Content-Type": "application/json", "X-Internal-Service-Token": token})
    response.raise_for_status()
    logger.info("%s Refunded %s credits of a refused image revision", log_prefix, credits)


async def finish_published_revision(task: Any, *, target: RevisionTarget, index: Any, log_prefix: str) -> None:
    """After version N+1 is sealed: re-point the image's file index, then drop the stale reference cache.

    The change is delivered and charged at this point, so a failure here does
    not fail the change; it is logged as an error. Every version's files stay
    referenced (head ``s3_file_keys`` union, sealed output) whatever happens here.
    """
    if not await index():
        logger.error("%s Image %s version %s is published but its file index still names version %s",
                     log_prefix, target.embed_id[:8], target.next_version, target.current_version)
    await forget_cached_reference(task, embed_id=target.embed_id)


async def run_with_batch_claims(awaitable: Any) -> Any:
    """Run one images-generate call with its own revision claim set."""
    token = _batch_claims.set(set())
    try:
        return await awaitable
    finally:
        _batch_claims.reset(token)
