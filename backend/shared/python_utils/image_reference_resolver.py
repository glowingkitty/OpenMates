"""Owner-bound image metadata recovery shared by direct-reference app skills.

Only metadata is cached. Client-encrypted durable contents are never treated as
Vault ciphertext; an owner-scoped fresh-media record may recover them for the
original 24-hour processing window.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, Mapping
from uuid import UUID

from backend.shared.python_utils.fresh_upload_images import recover_fresh_upload_image

logger = logging.getLogger(__name__)


class ImageReferenceUnavailable(ValueError):
    """Safe error with no private reference, object location or key material."""


def image_reference_id(reference: str, file_path_index: Mapping[str, str]) -> str:
    resolved = file_path_index.get(reference)
    if isinstance(resolved, str) and resolved:
        return resolved
    try:
        return str(UUID(reference))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ImageReferenceUnavailable(
            "Reference image is unavailable to this caller"
        ) from exc


def _authorized(record: Mapping[str, Any], user_id: str) -> bool:
    owner_hash = hashlib.sha256(user_id.encode()).hexdigest()
    if (record.get("user_id") and record["user_id"] != user_id) or (
        record.get("hashed_user_id") and record["hashed_user_id"] != owner_hash
    ):
        raise ImageReferenceUnavailable("Reference image is unavailable to this caller")
    expiry = record.get("expires_at")
    if expiry is not None and (type(expiry) is not int or expiry <= time.time()):
        raise ImageReferenceUnavailable("Reference image is no longer available")
    return (
        record.get("user_id") == user_id or record.get("hashed_user_id") == owner_hash
    )


def _server_readable(record: Mapping[str, Any]) -> bool:
    ciphertext = record.get("encrypted_content")
    return (
        isinstance(ciphertext, str)
        and ciphertext.startswith("vault:v")
        or isinstance(record.get("files"), dict)
        and bool(record.get("vault_wrapped_aes_key"))
    )


async def load_owned_image_record(
    *,
    embed_id: str,
    user_id: str,
    cache_client: Any,
    directus_service: Any,
    request_internal: Any = None,
) -> dict[str, Any]:
    if not isinstance(user_id, str) or not user_id:
        raise ImageReferenceUnavailable(
            "Reference images require an authenticated owner"
        )
    record = None
    try:
        if hasattr(cache_client, "get_embed_from_cache"):
            record = await cache_client.get_embed_from_cache(embed_id)
        else:
            record = await cache_client.get(f"embed:{embed_id}")
        if isinstance(record, (str, bytes)):
            record = json.loads(record)
    except Exception:
        logger.warning("Image reference cache read unavailable")
        record = None
    if isinstance(record, dict):
        if record.get("embed_id") not in (None, embed_id):
            raise ImageReferenceUnavailable(
                "Reference image is unavailable to this caller"
            )
        if _authorized(record, user_id) and _server_readable(record):
            return record

    # Persisted embeds store hashed ownership; filter at the authoritative read
    # as well as rechecking the returned row before any decryption or cache write.
    from backend.core.api.app.services.directus.embed_methods import EMBED_ALL_FIELDS

    rows = await directus_service.get_items(
        "embeds",
        params={
            "filter[embed_id][_eq]": embed_id,
            "filter[hashed_user_id][_eq]": hashlib.sha256(user_id.encode()).hexdigest(),
            "fields": EMBED_ALL_FIELDS,
            "limit": 1,
        },
        no_cache=True,
    )
    record = (
        rows[0]
        if isinstance(rows, list) and len(rows) == 1 and isinstance(rows[0], dict)
        else None
    )
    if isinstance(record, dict):
        if record.get("embed_id") not in (None, embed_id) or not _authorized(
            record, user_id
        ):
            raise ImageReferenceUnavailable(
                "Reference image is unavailable to this caller"
            )
    if not isinstance(record, dict) or not _server_readable(record):
        record = await recover_fresh_upload_image(
            embed_id=embed_id, user_id=user_id, request_internal=request_internal
        )
        if not _authorized(record, user_id):
            raise ImageReferenceUnavailable(
                "Reference image is unavailable to this caller"
            )
    ttl = (
        max(1, int(record["expires_at"] - time.time()))
        if record.get("expires_at")
        else 86400
    )
    try:
        # Both CacheService and raw async Redis are used by skill callers.
        try:
            await cache_client.set(f"embed:{embed_id}", record, ttl=ttl)
        except TypeError:
            await cache_client.set(f"embed:{embed_id}", json.dumps(record), ex=ttl)
    except Exception:
        logger.warning("Image reference metadata cache write unavailable")
    return record
