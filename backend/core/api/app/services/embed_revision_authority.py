"""Server check that a registered producer may seal the next version of an existing child embed.

A registered AI producer normally seals only its primary embed and the UUIDv5
children of its own intent. A revision (images-generate changing a generated
image, specification images-generate.revision.*, or videos-generate changing a
generated video, videos-generate.change.same-video-next-version, of the same
chat) seals version
N+1 of a child that belongs to an earlier message's parent. It is admitted only
when the canonical row still is that child of this owner and chat at version N,
so a stale or forged revision never reaches the client.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping

from backend.shared.python_utils.chat_recovery_context import RequiredRecoveryOutputError
from backend.shared.python_utils.media_revision import REVISABLE_CHILD_MARKERS

REVISION_FIELDS = frozenset({
    "embed_id", "parent_embed_id", "expected_version", "base_snapshot_required",
    # The creating message's hash (kept by the head) and the file keys of every version.
    "hashed_message_id", "s3_file_keys",
})
_UUID_V5 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")


class RevisionRefused(RequiredRecoveryOutputError):
    """Raised before any output is sealed: the revision was not admitted, nothing was published."""


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


async def verify_producer_revision(
    directus_service: Any, *, producer: Any, data: Mapping[str, Any], revision: Mapping[str, Any],
) -> None:
    """Raise ``RequiredRecoveryOutputError`` unless ``data`` is the exact next version of the revised child."""
    if set(revision) != REVISION_FIELDS or not _positive_int(revision.get("expected_version")):
        raise RevisionRefused("Embed revision descriptor is malformed")
    embed_id, parent_id = revision.get("embed_id"), revision.get("parent_embed_id")
    expected = revision["expected_version"]
    if (producer is None or producer.classification != "registered_ai"
            or not isinstance(embed_id, str) or not embed_id
            or not isinstance(parent_id, str) or not parent_id
            or data.get("embed_id") != embed_id or data.get("parent_embed_id") != parent_id
            or parent_id == producer.primary_embed_id or embed_id == producer.primary_embed_id
            or data.get("version_number") != expected + 1
            or data.get("chat_id") != producer.target_chat_id
            or data.get("message_id") != producer.primary_message_id
            or not _UUID_V5.fullmatch(embed_id)
            or not isinstance(revision.get("hashed_message_id"), str)
            or not _HEX_64.fullmatch(revision["hashed_message_id"])
            or not isinstance(revision.get("s3_file_keys"), list)):
        raise RevisionRefused("Embed revision identity mismatch")
    rows = await directus_service.get_items(
        "embeds", params={
            "filter[embed_id][_eq]": embed_id,
            "filter[hashed_user_id][_eq]": producer.owner_hash,
            "fields": "id,hashed_chat_id,hashed_message_id,parent_embed_id,version_number,app_id,skill_id,s3_file_keys",
            "limit": 2,
        }, admin_required=True, no_cache=True, raise_on_error=True,
    )
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise RevisionRefused("Revised embed has no canonical head")
    row = rows[0]
    version = 1 if row.get("version_number") is None else row.get("version_number")
    if (row.get("hashed_chat_id") != _sha256(producer.target_chat_id)
            or row.get("parent_embed_id") != parent_id or version != expected
            or (row.get("app_id"), row.get("skill_id")) not in REVISABLE_CHILD_MARKERS
            or row.get("hashed_message_id") != revision["hashed_message_id"]):
        raise RevisionRefused("Revised embed canonical version changed")
    if not _stored_keys(row.get("s3_file_keys")) <= _stored_keys(revision["s3_file_keys"]):
        raise RevisionRefused("Embed revision would drop file keys of an earlier version")


def _stored_keys(value: Any) -> set[tuple[str, str]]:
    """``(bucket, key)`` pairs of a stored or proposed file index; malformed input refuses the revision."""
    if value is None:
        return set()
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise RevisionRefused("Stored file index is malformed") from exc
    if not isinstance(value, list):
        raise RevisionRefused("Stored file index is malformed")
    pairs = set()
    for ref in value:
        if not isinstance(ref, dict) or not isinstance(ref.get("bucket"), str) or not isinstance(ref.get("key"), str):
            raise RevisionRefused("Stored file index is malformed")
        pairs.add((ref["bucket"], ref["key"]))
    return pairs
