"""Recipient-held email image capability; no public chat/embed read API."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from backend.core.api.app.services.limiter import limiter
from backend.core.api.app.services.reminder_notification_context import (
    PREVIEW_TOKEN_PATTERN, normalize_notification_context,
)

router = APIRouter(prefix="/v1/email/reminder-preview", tags=["Email"])
logger = logging.getLogger(__name__)


@router.api_route("/{reminder_id}/{token}.png", methods=["GET", "HEAD"], response_class=Response)
@limiter.limit("120/minute")
async def get_reminder_email_preview(reminder_id: str, token: str, request: Request) -> Response:
    """Read one bounded image using a 256-bit recipient-held capability.

    Access: unauthenticated capability GET for email clients, forwarded by the
    existing /v1/email/* Caddy rule; no developer API-key or cookie authority.
    The primary-key lookup and constant-time bearer digest check bind the
    capability to exactly one owner-encrypted reminder, for at most 90 days
    after its latest delivery. Cancel/delete/expiry revokes access. No paid
    inference, arbitrary URLs, HTML, or unrestricted rendering are accepted.
    """
    unavailable = HTTPException(status_code=404, detail="Reminder preview unavailable")
    try:
        UUID(reminder_id)
    except ValueError:
        raise unavailable from None
    if not PREVIEW_TOKEN_PATTERN.fullmatch(token):
        raise unavailable
    directus = request.app.state.directus_service
    row = await directus.reminder.get_reminder(reminder_id)
    try:
        expires_at = int((row or {}).get("notification_preview_expires_at") or 0)
    except (ValueError, TypeError):
        raise unavailable from None
    if (not row or row.get("status") in {"cancelled", "failed"}
            or expires_at < int(time.time())):
        raise unavailable
    digest = hashlib.sha256(token.encode()).hexdigest()
    expected = row.get("notification_preview_token_hash")
    if not isinstance(expected, str) or not hmac.compare_digest(expected, digest):
        raise unavailable
    ciphertext = row.get("encrypted_notification_context")
    key_id = row.get("vault_key_id")
    if not ciphertext or not key_id:
        raise unavailable
    try:
        stored = json.loads(await request.app.state.encryption_service.decrypt_with_user_key(
            ciphertext=ciphertext, key_id=key_id,
        ))
        context = normalize_notification_context({key: value for key, value in stored.items() if not key.startswith("_")})
        if context is None:
            raise ValueError("Missing context")
        from backend.core.api.app.services.reminder_preview_renderer import render_reminder_preview

        image = await asyncio.to_thread(
            render_reminder_preview, context, darkmode=False, language=stored.get("_language", "en"),
        )
    except Exception as error:
        # Neither exception messages nor tracebacks can contain private input.
        logger.warning("Reminder preview unavailable (%s)", type(error).__name__)
        raise unavailable from None
    return Response(content=b"" if getattr(request, "method", "GET") == "HEAD" else image, media_type="image/png", headers={
        "Cache-Control": "private, max-age=300",
        "Content-Length": str(len(image)),
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "Content-Security-Policy": "default-src 'none'",
        "Content-Disposition": 'inline; filename="reminder.png"',
    })
