"""Owner-bound recovery of encrypted fresh-upload metadata for internal skills.

Uses the existing internal upload resolver, which reads ``upload_files`` after
cache eviction. Recovery never creates a chat embed or renews the upload's
original 24-hour processing window. No plaintext image or key is returned here.
"""
from __future__ import annotations

import time
from typing import Any, Awaitable, Callable, Mapping


FRESH_UPLOAD_WINDOW_SECONDS = 86400


class FreshUploadImageUnavailable(ValueError):
    """Safe rejection for missing, foreign or expired fresh-upload metadata."""


async def recover_fresh_upload_image(
    *, embed_id: str, user_id: str,
    request_internal: Callable[..., Awaitable[Any]] | None,
) -> dict[str, Any]:
    """Recheck the internal resolver's owner, identifier and absolute expiry."""
    if not user_id or not callable(request_internal):
        raise FreshUploadImageUnavailable("Reference image is unavailable to this caller")
    try:
        response = await request_internal(
            "POST", "internal/uploads/resolve-image", payload={"embed_id": embed_id, "user_id": user_id},
        )
    except Exception as exc:
        if getattr(exc, "status_code", None) in {401, 403, 404}:
            raise FreshUploadImageUnavailable("Reference image is unavailable to this caller") from exc
        raise
    content = response.get("content") if isinstance(response, Mapping) and response.get("status") == "success" else None
    if (not isinstance(content, dict) or content.get("user_id") != user_id
            or content.get("embed_id") != embed_id):
        raise FreshUploadImageUnavailable("Reference image is unavailable to this caller")
    now = int(time.time())
    created_at, expires_at = content.get("created_at"), content.get("expires_at")
    if (type(created_at) is not int or type(expires_at) is not int
            or expires_at != created_at + FRESH_UPLOAD_WINDOW_SECONDS
            or not 0 <= now - created_at < FRESH_UPLOAD_WINDOW_SECONDS):
        raise FreshUploadImageUnavailable("Reference image is no longer available")
    files, wrapped_key = content.get("files"), content.get("vault_wrapped_aes_key")
    if (not isinstance(files, dict) or not 1 <= len(files) <= 16
            or not isinstance(wrapped_key, str) or not wrapped_key
            or not str(content.get("content_type") or "").startswith("image/")):
        raise FreshUploadImageUnavailable("Reference image metadata is unavailable")
    return content
