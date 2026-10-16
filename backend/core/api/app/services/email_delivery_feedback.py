"""Private, durable delivery eligibility and read-only Brevo event reconciliation.

SMTP text and message identifiers only live in memory. Persistence contains
normalized recipient/event hashes, bounded reason codes and UTC timestamps.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, uuid5

import httpx

logger = logging.getLogger(__name__)
COLLECTION = "email_delivery_suppressions"
ENVIRONMENTS = {"development", "production", "staging", "self-host", "ci", "other"}
FAILURES = {"hardbounce", "softbounce", "hardbounces", "softbounces", "blocked", "invalid", "deferred", "error"}


class DeliveryFeedbackUnavailable(RuntimeError):
    """Eligibility or polling failed; never silently interpret this as no history."""


def delivery_environment(value: str | None = None) -> str:
    value = (value or os.getenv("SERVER_ENVIRONMENT", "development")).strip().lower()
    value = {"dev": "development", "prod": "production", "self_host": "self-host"}.get(value, value)
    return value if value in ENVIRONMENTS else "other"


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _at(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(microsecond=0)


async def _read(directus, collection: str, params: dict) -> list[dict]:
    try:
        rows = await directus.get_items(collection, params=params, admin_required=True, no_cache=True, raise_on_error=True)
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise DeliveryFeedbackUnavailable("Delivery eligibility response invalid")
        return rows
    except Exception as exc:
        raise DeliveryFeedbackUnavailable("Delivery eligibility read unavailable") from exc


async def email_recipient_allowed(recipient_email: str, *, secrets_manager, directus=None) -> bool:
    """Database is authoritative; no cache miss or unavailable read permits mail.

    secrets_manager is caller-owned. Only a Directus instance constructed here
    is closed here. CI SMTP bypass is applied by the caller before this helper.
    """
    email = recipient_email.strip().lower()
    if not email or "@" not in email:
        return False
    own_directus = directus is None
    if own_directus:
        from backend.core.api.app.services.directus import DirectusService
        directus = DirectusService()
    try:
        # Existing ignored_emails uses base64 SHA-256; allow legacy hex hashes
        # and exact-case pre-normalization hashes without storing the address.
        hashes = {_hash(email), base64.b64encode(hashlib.sha256(email.encode()).digest()).decode(),
                  base64.b64encode(hashlib.sha256(recipient_email.encode()).digest()).decode()}
        ignored = await _read(directus, "ignored_emails", {
            "filter[hashed_email][_in]": ",".join(sorted(hashes)), "fields": "id", "limit": 1,
        })
        if ignored:
            return False
        rows = await _read(directus, COLLECTION, {
            "filter[id][_eq]": str(uuid5(NAMESPACE_URL, f"email-feedback:{delivery_environment()}:{_hash(email)}")),
            "fields": "status,suppressed_until", "limit": 1,
        })
        if not rows:
            return True
        status = rows[0].get("status")
        if status == "permanent":
            return False
        if status == "clear":
            return True
        if status == "temporary":
            try:
                return _at(rows[0]["suppressed_until"]) <= datetime.now(timezone.utc)
            except (KeyError, TypeError, ValueError) as exc:
                raise DeliveryFeedbackUnavailable("Delivery suppression state invalid") from exc
        raise DeliveryFeedbackUnavailable("Delivery suppression status invalid")
    finally:
        if own_directus:
            await directus.close()


def classify_event(event: dict) -> str:
    kind = str(event.get("event", "")).lower().replace("_", "")
    reason = str(event.get("reason", "")).lower()
    if kind == "delivered":
        return "delivered"
    if kind in {"spam", "unsubscribed"}:
        return "recipient_opt_out"
    if kind not in FAILURES:
        return "observe"
    # Sender trouble takes precedence even when the provider labels it hard.
    if any(word in reason for word in ("spamcop", "spamhaus", "blacklist", "blocklist", "reputation", "sending ip", "sender ip", "ip address", "unsolicited", "spam content", "spam detected", "blocked for spam", "message content", "content rejected", "security policy", "policy reasons", "dkim", "spf", "dmarc")):
        return "sender_rejection"
    if any(word in reason for word in ("account has been disabled", "mailbox disabled", "mailbox is disabled", "recipient disabled", "inactive mailbox")):
        return "recipient_disabled"
    if kind == "invalid" or any(word in reason for word in ("user unknown", "unknown user", "no such user", "recipient does not exist", "mailbox does not exist", "mailbox not found", "invalid recipient", "invalid address", "5.1.1")):
        return "recipient_invalid"
    if re.search(r"\b5\.7\.\d+", reason):
        return "sender_rejection"
    if any(word in reason for word in ("mailbox full", "quota exceeded", "over quota", "5.2.2", "4.2.2")):
        return "mailbox_full"
    if any(word in reason for word in ("authentication failed", "relay denied", "sender rejected", "access denied", "policy rejection")):
        return "sender_rejection"
    if kind == "deferred" or any(word in reason for word in ("temporary", "temporarily", "timeout", "try again", "greylist", "connection")):
        return "temporary_failure"
    return "unknown_failure"


def event_tags(event: dict) -> dict[str, str]:
    raw = event.get("tags", event.get("tag", []))
    if isinstance(raw, str):
        raw = re.split(r"[,|;\s]+", raw.strip("[]\"'"))
    tags: dict[str, str] = {}
    if isinstance(raw, list):
        for tag in raw:
            if isinstance(tag, str) and ":" in tag:
                key, value = tag.strip("\"'").split(":", 1)
                # Never preserve arbitrary user-controlled tag text in metrics.
                if key == "environment":
                    value = {"dev": "development", "prod": "production", "self_host": "self-host"}.get(value, value)
                    value = value if value in ENVIRONMENTS else "__invalid__"
                    tags[key] = value if key not in tags or tags[key] == value else "__invalid__"
                elif key == "audience":
                    tags[key] = value if value in {"user", "admin", "test"} else "other"
                elif key == "email-type" and re.fullmatch(r"[a-z0-9_-]{1,80}", value):
                    tags[key] = value
    return tags


async def event_in_scope(event: dict, *, environment: str, directus) -> bool:
    tags = event_tags(event)
    if "environment" in tags:
        return tags["environment"] == environment
    email = str(event.get("email", "")).strip().lower()
    if not email or "@" not in email:
        return False
    digest = base64.b64encode(hashlib.sha256(email.encode()).digest()).decode()
    for collection in ("users", "newsletter_subscribers"):
        if await _read(directus, collection, {"filter[hashed_email][_eq]": digest, "fields": "id", "limit": 1}):
            return True
    return False


def transition(row: dict | None, event: dict, *, environment: str) -> dict | None:
    """Pure reducer: replay/out-of-order cannot extend a suppression deadline."""
    code = classify_event(event)
    # Provider complaints/unsubscribe events lack application preference scope.
    # Newsletter preference routes remain authoritative; never suppress security
    # mail globally because someone opted out of one provider campaign.
    if code in {"observe", "sender_rejection", "recipient_opt_out"}:
        return None
    at = _at(event["date"])
    digest = _hash(str(event["email"]).strip().lower())
    fingerprint = _hash(f"{digest}:{event.get('messageId', '')}:{at.isoformat()}:{code}")
    failure_hash = _hash(f"{digest}:{event['messageId']}") if event.get("messageId") else fingerprint
    if row and (at < _at(row["last_event_at"]) or fingerprint == row.get("last_event_hash")):
        return None
    # Equal-time contradictory events must not relax an existing suppression.
    if row and at == _at(row["last_event_at"]) and code == "delivered":
        return None
    result = dict(row or {})
    result.update(id=str(uuid5(NAMESPACE_URL, f"email-feedback:{environment}:{digest}")),
                  recipient_hash=digest, environment=environment, last_event_at=at.isoformat(),
                  last_event_hash=fingerprint, reason_code=code, version=int(result.get("version", 0)) + 1)
    if result.get("status") == "permanent":
        result["reason_code"] = row["reason_code"]
        return result
    if code == "delivered":
        result.update(status="clear", suppressed_until=None, recent_failures=[])
    elif code in {"recipient_invalid", "recipient_disabled"}:
        result.update(status="permanent", suppressed_until=None, recent_failures=[])
    else:
        failures = [failure for failure in result.get("recent_failures", [])
                    if _at(failure["at"]) >= at - timedelta(hours=48)]
        if any(failure["hash"] == failure_hash for failure in failures):
            return None
        failures = (failures + [{"hash": failure_hash, "at": at.isoformat()}])[-3:]
        result["recent_failures"] = failures
        if code == "unknown_failure" and len(failures) < 3:
            result.setdefault("status", "clear")
            result.setdefault("suppressed_until", None)
            if result["status"] == "temporary" and _at(result["suppressed_until"]) <= at:
                result.update(status="clear", suppressed_until=None)
        else:
            hours = min(24, (6 if code == "mailbox_full" else 1) * 2 ** (len(failures) - 1))
            result.update(status="temporary", suppressed_until=(at + timedelta(hours=hours)).isoformat())
    return result


async def apply_event(directus, event: dict, *, environment: str) -> bool:
    item_id = str(uuid5(NAMESPACE_URL, f"email-feedback:{environment}:{_hash(event['email'].strip().lower())}"))
    # CAS handles concurrent pollers; a duplicate create retries through DB.
    for _ in range(3):
        rows = await _read(directus, COLLECTION, {"filter[id][_eq]": item_id, "limit": 1})
        row = rows[0] if rows else None
        updated = transition(row, event, environment=environment)
        if updated is None:
            return False
        if row:
            saved = await update_suppression_if_version(directus, updated, row["version"])
            if saved:
                return True
        else:
            success, _ = await directus.create_item(COLLECTION, updated, admin_required=True)
            if success:
                return True
    raise DeliveryFeedbackUnavailable("Delivery feedback write unavailable")


async def update_suppression_if_version(directus, row: dict, expected_version: int) -> dict | None:
    """Scoped atomic CMS endpoint; generic Directus updateMany is not a CAS."""
    try:
        token = await directus.ensure_auth_token(admin_required=True)
        if not token:
            raise DeliveryFeedbackUnavailable("Delivery feedback admin auth unavailable")
        response = await directus._make_api_request(
            "POST", f"{directus.base_url}/email-delivery-feedback/",
            headers={"Authorization": f"Bearer {token}"},
            json={"id": row["id"], "expected_version": expected_version, "data": row},
        )
        if response is not None and response.status_code == 409:
            return None
        if response is None or response.status_code != 200:
            raise DeliveryFeedbackUnavailable("Delivery feedback atomic update unavailable")
        saved = response.json().get("data")
        if not isinstance(saved, dict) or saved.get("id") != row["id"] or saved.get("version") != expected_version + 1:
            raise DeliveryFeedbackUnavailable("Delivery feedback atomic response invalid")
        return saved
    except Exception as exc:
        raise DeliveryFeedbackUnavailable("Delivery feedback atomic update unavailable") from exc


async def fetch_brevo_events(api_key: str, *, client=None, now: datetime | None = None) -> list[dict]:
    """Bounded 48h overlap, at most 4x5000 events, GET requests only.

    Date-only API parameters cover 3 calendar dates; trim to exactly 48h in
    memory. A full final page is an explicit incomplete result, never healthy.
    """
    now = now or datetime.now(timezone.utc)
    start = now - timedelta(hours=48)
    own_client = client is None
    client = client or httpx.AsyncClient(timeout=30)
    events = []
    try:
        for page in range(4):
            response = await client.get("https://api.brevo.com/v3/smtp/statistics/events", headers={"api-key": api_key},
                                        params={"startDate": start.date().isoformat(), "endDate": now.date().isoformat(),
                                                "limit": 5000, "offset": page * 5000, "sort": "asc"})
            if response.status_code != 200:
                raise DeliveryFeedbackUnavailable("Delivery feedback polling HTTP failure")
            batch = response.json().get("events", [])
            if not isinstance(batch, list) or any(not isinstance(event, dict) for event in batch):
                raise DeliveryFeedbackUnavailable("Delivery feedback polling response invalid")
            events.extend(event for event in batch if start <= _at(event["date"]) <= now)
            if len(batch) < 5000:
                return sorted(events, key=lambda event: _at(event["date"]))
        raise DeliveryFeedbackUnavailable("Delivery feedback polling page limit exceeded")
    except Exception as exc:
        raise DeliveryFeedbackUnavailable("Delivery feedback polling unavailable") from exc
    finally:
        if own_client:
            await client.aclose()


async def reconcile_delivery_feedback(*, directus, api_key: str, environment: str, client=None) -> dict:
    events = await fetch_brevo_events(api_key, client=client)
    return await reconcile_events(directus=directus, events=events, environment=environment)


async def reconcile_events(*, directus, events: list[dict], environment: str) -> dict:
    """Production persistence path, also usable with synthetic CI event evidence."""
    metrics = Counter()
    changes = 0
    sender_failure = False
    for event in sorted(events, key=lambda event: _at(event["date"])):
        if not await event_in_scope(event, environment=environment, directus=directus):
            continue
        email = str(event.get("email", "")).strip().lower()
        if "@" not in email:
            continue
        code = classify_event(event)
        tags = event_tags(event)
        metrics[(environment, tags.get("email-type", "legacy"), tags.get("audience", "unknown"), code)] += 1
        sender_failure |= code == "sender_rejection"
        if code not in {"observe", "sender_rejection", "recipient_opt_out"}:
            changes += await apply_event(directus, event, environment=environment)
    # Distinct service identity: sender delivery trouble is not API availability.
    service_id = f"email-delivery-{environment}"
    prior = await directus.health_event.get_last_status("external", service_id)
    status = "degraded" if sender_failure else "healthy"
    if (prior and prior["new_status"] != status) or (not prior and sender_failure):
        saved = await directus.health_event.record_health_event(
            "external", service_id, prior["new_status"] if prior else None, status,
            error_message="sender_rejection_in_delivery_events" if sender_failure else None,
        )
        if not saved:
            raise DeliveryFeedbackUnavailable("Delivery feedback operator state unavailable")
        logger.warning("Email delivery operator state changed environment=%s status=%s", environment, status)
    return {"status": "ok", "changed": changes, "metrics": [
        {"environment": env, "email_type": kind, "audience": audience, "reason_code": reason, "count": count}
        for (env, kind, audience, reason), count in sorted(metrics.items())
    ]}
