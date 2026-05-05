"""
Purpose: Provides idempotent email delivery reservations backed by Directus.
Architecture: Email senders reserve a deterministic delivery row before calling Brevo.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.services.email_template import EmailTemplateService

logger = logging.getLogger(__name__)

COLLECTION = "email_deliveries"
DELIVERY_UUID_NAMESPACE = uuid.UUID("4d5fd979-0f7c-56c7-82d3-d50de814c2e5")


def normalize_email_hash(email: str | None) -> str | None:
    """Return a SHA-256 hash for a normalized email address, or None."""
    if not email:
        return None
    normalized = email.strip().lower()
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def build_delivery_key(
    *,
    email_type: str,
    campaign_key: str | None,
    recipient_kind: str,
    recipient_id: str,
    stage: str | None = None,
) -> str:
    """Build the canonical idempotency key used for delivery dedupe."""
    return ":".join([
        email_type,
        campaign_key or "",
        recipient_kind,
        recipient_id,
        stage or "",
    ])


def build_delivery_id(delivery_key: str) -> str:
    """Return a deterministic UUID for Directus primary key use."""
    return str(uuid.uuid5(DELIVERY_UUID_NAMESPACE, delivery_key))


async def reserve_delivery(
    directus: DirectusService,
    *,
    email_type: str,
    campaign_key: str | None,
    recipient_kind: str,
    recipient_id: str,
    recipient_hash: str | None = None,
    stage: str | None = None,
    lang: str | None = None,
    scheduled_for: str | None = None,
    metadata: Optional[dict[str, Any]] = None,
) -> tuple[bool, str, str]:
    """Reserve a delivery row.

    Returns (reserved, delivery_id, delivery_key). If the deterministic row
    already exists, reserved is False and callers must skip sending.
    """
    delivery_key = build_delivery_key(
        email_type=email_type,
        campaign_key=campaign_key,
        recipient_kind=recipient_kind,
        recipient_id=recipient_id,
        stage=stage,
    )
    delivery_id = build_delivery_id(delivery_key)
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "id": delivery_id,
        "delivery_key": delivery_key,
        "email_type": email_type,
        "campaign_key": campaign_key,
        "recipient_kind": recipient_kind,
        "recipient_id": recipient_id,
        "recipient_hash": recipient_hash,
        "stage": stage,
        "status": "processing",
        "lang": lang,
        "provider": "brevo",
        "scheduled_for": scheduled_for,
        "processing_started_at": now,
        "metadata": metadata,
    }

    token = await directus.login_admin()
    response = await directus._make_api_request(
        "POST",
        f"{directus.base_url}/items/{COLLECTION}",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )
    if 200 <= response.status_code < 300:
        return True, delivery_id, delivery_key

    text = response.text
    if "unique" in text.lower() or "duplicate" in text.lower() or "value is not unique" in text.lower():
        logger.info("Skipping already-reserved email delivery %s", delivery_key)
        return False, delivery_id, delivery_key

    # If Directus returns a generic failure for an existing deterministic ID,
    # fail closed by checking whether the row is present before raising.
    existing = await directus.get_items(
        COLLECTION,
        params={"filter": {"id": {"_eq": delivery_id}}, "fields": "id", "limit": 1},
        admin_required=True,
    )
    if existing:
        logger.info("Skipping existing email delivery %s", delivery_key)
        return False, delivery_id, delivery_key

    raise RuntimeError(f"Failed to reserve email delivery {delivery_key}: HTTP {response.status_code} {response.text[:500]}")


async def mark_delivery_sent(directus: DirectusService, delivery_id: str) -> None:
    await directus.update_item(
        COLLECTION,
        delivery_id,
        {"status": "sent", "sent_at": datetime.now(timezone.utc).isoformat(), "error": None},
        admin_required=True,
    )


async def mark_delivery_failed(directus: DirectusService, delivery_id: str, error: str) -> None:
    await directus.update_item(
        COLLECTION,
        delivery_id,
        {
            "status": "failed",
            "failed_at": datetime.now(timezone.utc).isoformat(),
            "error": error[:4000],
        },
        admin_required=True,
    )


async def send_email_once(
    *,
    directus: DirectusService,
    email_template_service: EmailTemplateService,
    email_type: str,
    campaign_key: str | None,
    recipient_kind: str,
    recipient_id: str,
    recipient_email: str,
    template: str,
    context: dict[str, Any],
    subject: str | None = None,
    recipient_name: str = "",
    sender_email: str | None = None,
    sender_name: str | None = None,
    stage: str | None = None,
    lang: str = "en",
    scheduled_for: str | None = None,
    metadata: Optional[dict[str, Any]] = None,
    attachments: Optional[list] = None,
) -> tuple[bool, str]:
    """Reserve and send one email. Returns (sent, status)."""
    reserved, delivery_id, _delivery_key = await reserve_delivery(
        directus,
        email_type=email_type,
        campaign_key=campaign_key,
        recipient_kind=recipient_kind,
        recipient_id=recipient_id,
        recipient_hash=normalize_email_hash(recipient_email),
        stage=stage,
        lang=lang,
        scheduled_for=scheduled_for,
        metadata=metadata,
    )
    if not reserved:
        return False, "already_reserved"

    try:
        sent = await email_template_service.send_email(
            template=template,
            recipient_email=recipient_email,
            recipient_name=recipient_name,
            context=context,
            subject=subject,
            sender_name=sender_name,
            sender_email=sender_email,
            lang=lang,
            attachments=attachments,
        )
    except Exception as exc:
        await mark_delivery_failed(directus, delivery_id, str(exc))
        raise

    if sent:
        await mark_delivery_sent(directus, delivery_id)
        return True, "sent"

    await mark_delivery_failed(directus, delivery_id, "EmailTemplateService.send_email returned False")
    return False, "failed"


async def fetch_existing_recipient_ids(
    directus: DirectusService,
    *,
    email_type: str,
    campaign_key: str | None,
    statuses: tuple[str, ...] = ("processing", "sent", "archived"),
) -> set[str]:
    """Return recipient IDs that already have protected delivery records."""
    params: dict[str, Any] = {
        "fields": "recipient_id",
        "filter": {
            "email_type": {"_eq": email_type},
            "status": {"_in": list(statuses)},
        },
        "limit": -1,
    }
    if campaign_key is None:
        params["filter"]["campaign_key"] = {"_null": True}
    else:
        params["filter"]["campaign_key"] = {"_eq": campaign_key}

    rows = await directus.get_items(COLLECTION, params=params, admin_required=True)
    return {row["recipient_id"] for row in rows if row.get("recipient_id")}
