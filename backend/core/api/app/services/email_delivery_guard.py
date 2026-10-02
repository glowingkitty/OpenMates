"""
Purpose: Provides idempotent email delivery reservations backed by Directus.
Architecture: Email senders reserve a deterministic delivery row before calling Brevo.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from backend.core.api.app.services.directus.directus import DirectusService
from backend.core.api.app.services.email_template import EmailSendIneligible, EmailTemplateService

logger = logging.getLogger(__name__)

COLLECTION = "email_deliveries"
DELIVERY_UUID_NAMESPACE = uuid.UUID("4d5fd979-0f7c-56c7-82d3-d50de814c2e5")
RETRY_WINDOW_SECONDS = 600
RETRY_LOCK_SECONDS = 120
_RELEASE_LOCK = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"


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


def _provider_enforces_idempotency(email_template_service: EmailTemplateService) -> bool:
    """Fail closed for unknown transports; a MIME header alone is not deduplication."""
    capability = getattr(email_template_service, "supports_delivery_idempotency", None)
    if not callable(capability):
        return False
    try:
        return capability() is True
    except Exception:
        return False


def _selected_delivery_transport(email_template_service: EmailTemplateService) -> str:
    selected = getattr(email_template_service, "selected_delivery_transport", None)
    if callable(selected):
        try:
            name = selected()
            if isinstance(name, str) and name:
                return name
        except Exception:
            pass
    return "unknown"


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
    provider: str = "brevo",
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
        "provider": provider,
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


async def _prepare_bounded_retry(
    directus: DirectusService, delivery_id: str, delivery_key: str, recipient_hash: str | None,
    provider: str,
) -> str:
    """Reopen only a matching, recent failed/stale reservation without changing its first timestamp."""
    rows = await directus.get_items(
        COLLECTION,
        params={"filter": {"id": {"_eq": delivery_id}}, "fields": "id,delivery_key,recipient_hash,provider,status,processing_started_at", "limit": 1},
        admin_required=True,
    )
    if not rows:
        return "already_reserved"  # An uncertain create response must fail closed.
    row = rows[0]
    if row.get("delivery_key") != delivery_key or row.get("recipient_hash") != recipient_hash or row.get("provider") != provider:
        return "already_reserved"
    status = row.get("status")
    if status not in ("failed", "processing"):
        return "already_reserved"
    started_at = row.get("processing_started_at")
    try:
        started = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
        if started.tzinfo is None:
            return "retry_window_closed"
        age = (datetime.now(timezone.utc) - started.astimezone(timezone.utc)).total_seconds()
    except (TypeError, ValueError):
        return "retry_window_closed"
    if age < 0 or age >= RETRY_WINDOW_SECONDS:
        return "retry_window_closed"
    if status == "processing" and age < RETRY_LOCK_SECONDS:
        # The first worker may still be active, or its reservation response
        # was lost. Let the bounded task schedule another check after it ages.
        return "retry_locked"
    await directus.update_item(
        COLLECTION, delivery_id,
        {"status": "processing", "error": None},
        admin_required=True,
    )
    return "retry_ready"


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
    before_send: Callable[[], Awaitable[bool]] | None = None,
    send_options: dict[str, Any] | None = None,
    retry_cache: Any | None = None,
) -> tuple[bool, str]:
    """Reserve and send one email. Optional retries are bounded by provider deduplication."""
    delivery_key = build_delivery_key(
        email_type=email_type, campaign_key=campaign_key, recipient_kind=recipient_kind,
        recipient_id=recipient_id, stage=stage,
    )
    delivery_id = build_delivery_id(delivery_key)
    recipient_hash = normalize_email_hash(recipient_email)
    provider = _selected_delivery_transport(email_template_service) if retry_cache is not None else "brevo"
    cache_client = None
    lock_key = f"email_delivery_retry_lock:{delivery_id}"
    lock_token = str(uuid.uuid4())
    if retry_cache is not None:
        try:
            cache_client = await retry_cache.client
            if not cache_client or not await cache_client.set(lock_key, lock_token, nx=True, ex=RETRY_LOCK_SECONDS):
                return False, "retry_locked"
        except Exception:
            logger.warning("Email delivery retry lock unavailable for %s", delivery_id)
            return False, "retry_unavailable"
    can_mark_failed = False
    try:
        reserved, _, _ = await reserve_delivery(
            directus,
            email_type=email_type, campaign_key=campaign_key, recipient_kind=recipient_kind,
            recipient_id=recipient_id, recipient_hash=recipient_hash, stage=stage,
            lang=lang, scheduled_for=scheduled_for, metadata=metadata, provider=provider,
        )
        if not reserved:
            if retry_cache is None:
                return False, "already_reserved"
            if not _provider_enforces_idempotency(email_template_service):
                # SMTP may have accepted the previous call before failing.
                # Without a provider-enforced key it must never be replayed.
                return False, "retry_unsafe_transport"
            retry_status = await _prepare_bounded_retry(directus, delivery_id, delivery_key, recipient_hash, provider)
            if retry_status != "retry_ready":
                return False, retry_status
        can_mark_failed = True
        if before_send is not None and not await before_send():
            await directus.update_item(
                COLLECTION, delivery_id, {"status": "skipped", "error": None}, admin_required=True,
            )
            return False, "ineligible_at_dispatch"
        sent = await email_template_service.send_email(
            template=template,
            recipient_email=recipient_email,
            recipient_name=recipient_name,
            context=context,
            subject=(send_options or {}).get("subject", subject),
            sender_name=sender_name,
            sender_email=sender_email,
            lang=lang,
            attachments=attachments,
            **({"late_before_send": before_send, "subject_options": send_options} if before_send is not None else {}),
            **({"delivery_idempotency_key": delivery_id} if retry_cache is not None and _provider_enforces_idempotency(email_template_service) else {}),
        )
        if sent:
            await mark_delivery_sent(directus, delivery_id)
            return True, "sent"

        await mark_delivery_failed(directus, delivery_id, "EmailTemplateService.send_email returned False")
        return False, "failed"
    except EmailSendIneligible:
        await directus.update_item(
            COLLECTION, delivery_id, {"status": "skipped", "error": None}, admin_required=True,
        )
        return False, "ineligible_at_dispatch"
    except Exception as exc:
        # A failed ledger update is still uncertain; the original start time
        # bounds all subsequent attempts and the provider key stays stable.
        if can_mark_failed:
            await mark_delivery_failed(directus, delivery_id, type(exc).__name__)
        raise
    finally:
        if cache_client is not None:
            try:
                await cache_client.eval(_RELEASE_LOCK, 1, lock_key, lock_token)
            except Exception:
                logger.warning("Email delivery retry lock release failed for %s", delivery_id)


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
