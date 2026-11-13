"""Aggregate growth numbers for the founder's daily meeting briefing (admin-only, read-only).

API surface classification: internal-only admin tooling. ``POST /v1/admin/debug/growth-metrics``
requires the admin API key (``require_admin_api_key``), is not in the public schema, is rate
limited, writes nothing, and returns counts only — never ids, hashes, emails or per-user rows.
Caddy reaches it through the existing ``/v1/admin/*`` path, like the other admin debug routes.

Counted population: accounts with a completed signup, minus
  - admins (``is_admin``),
  - accounts whose ``hashed_email`` (base64 SHA-256 of the lowercased email, the value the
    clients store) is in the caller's ``exclude_email_hashes`` (the founder's own accounts),
  - the server's configured test accounts (``OPENMATES_TEST_ACCOUNT*EMAIL`` environment values).
Invoices of excluded accounts are dropped too (matched by ``user_id_hash`` = SHA-256 hex of the
user id). Gift-card redemptions are not purchases. Amounts are client-encrypted, so only counts.

Windows: "since" (the previous meeting) and the last 7 days, each with the equally long period
right before it, so the briefing can show a trend. Active users come from
``last_online_timestamp`` (the last session check), so they exist only for "now"; the briefing
keeps its own snapshots to compare them day over day.
Docs: docs/contributing/guides/daily-meeting.md
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend.core.api.app.models.user import User
from backend.core.api.app.routes.admin_debug import require_admin_api_key
from backend.core.api.app.routes.auth_routes.auth_dependencies import get_directus_service
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.limiter import limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/admin/debug", tags=["Admin Debug"])

MAX_EXCLUDED_HASHES = 200
MAX_WINDOW_DAYS = 31
USER_FIELDS = ["id", "is_admin", "signup_completed", "signup_started_at", "last_online_timestamp", "hashed_email"]
INVOICE_FIELDS = ["user_id_hash", "date", "is_gift_card", "refund_status", "has_chargeback"]


class GrowthMetricsRequest(BaseModel):
    since: datetime = Field(description="Start of the 'since the last meeting' window (ISO 8601, with zone)")
    exclude_email_hashes: list[str] = Field(default_factory=list, max_length=MAX_EXCLUDED_HASHES,
                                            description="base64 SHA-256 of lowercased emails to leave out")


def email_hash(email: str) -> str:
    """Same hash the clients store in ``directus_users.hashed_email``."""
    return base64.b64encode(hashlib.sha256(email.strip().lower().encode()).digest()).decode()


def configured_test_account_hashes(environ: dict[str, str] | None = None) -> set[str]:
    env = os.environ if environ is None else environ
    return {email_hash(value) for key, value in env.items()
            if key.startswith("OPENMATES_TEST_ACCOUNT") and key.endswith("EMAIL") and "@" in (value or "")}


def parse_moment(value: Any) -> datetime | None:
    """ISO strings and unix seconds (``last_online_timestamp`` is stored as ``str(int(time.time()))``)."""
    if value in (None, ""):
        return None
    text = str(value).strip()
    if text.lstrip("-").isdigit():
        return datetime.fromtimestamp(int(text), tz=timezone.utc)
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _windows(now: datetime, since: datetime) -> dict[str, tuple[datetime, datetime]]:
    span = now - since
    week = timedelta(days=7)
    return {"since_last_meeting": (since, now), "since_last_meeting_previous": (since - span, since),
            "last_7_days": (now - week, now), "previous_7_days": (now - 2 * week, now - week)}


def _inside(moment: datetime | None, window: tuple[datetime, datetime]) -> bool:
    return moment is not None and window[0] <= moment < window[1]


def compute_growth_metrics(users: Iterable[dict], invoices: Iterable[dict], *, now: datetime,
                           since: datetime, excluded_email_hashes: set[str]) -> dict[str, Any]:
    """Counts only. ``users``/``invoices`` are raw Directus rows; nothing per-user is returned."""
    counted, excluded_ids, started = [], set(), []
    for user in users:
        if user.get("is_admin") or (user.get("hashed_email") or "") in excluded_email_hashes:
            excluded_ids.add(hashlib.sha256(str(user.get("id", "")).encode()).hexdigest())
            continue
        started.append(parse_moment(user.get("signup_started_at")))
        if user.get("signup_completed"):
            counted.append(user)

    first_purchase: dict[str, datetime] = {}
    purchases: list[datetime] = []
    for invoice in invoices:
        owner = invoice.get("user_id_hash") or ""
        moment = parse_moment(invoice.get("date"))
        if invoice.get("is_gift_card") or owner in excluded_ids or moment is None:
            continue
        if owner and (owner not in first_purchase or moment < first_purchase[owner]):
            first_purchase[owner] = moment
        if (invoice.get("refund_status") in (None, "", "none")) and not invoice.get("has_chargeback"):
            purchases.append(moment)

    windows = _windows(now, since)
    signed_up = [parse_moment(u.get("signup_started_at")) for u in counted]
    online = [parse_moment(u.get("last_online_timestamp")) for u in counted]
    periods = {name: {"signups_completed": sum(_inside(m, window) for m in signed_up),
                      "signups_started": sum(_inside(m, window) for m in started),
                      "new_paying_users": sum(_inside(m, window) for m in first_purchase.values()),
                      "credit_purchases": sum(_inside(m, window) for m in purchases)}
               for name, window in windows.items()}
    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "since": since.isoformat(timespec="seconds"),
        "total_users": len(counted),
        "paying_users_total": len(first_purchase),
        "active_users": {"last_24_hours": sum(_inside(m, (now - timedelta(days=1), now + timedelta(minutes=5)))
                                              for m in online),
                         "last_7_days": sum(_inside(m, (now - timedelta(days=7), now + timedelta(minutes=5)))
                                            for m in online)},
        "periods": periods,
        "excluded_accounts": len(excluded_ids),
        "definitions": {
            "total_users": "accounts with a completed signup, admin/test/own accounts left out",
            "signups_completed": "accounts created in the period that finished signup",
            "signups_started": "accounts created in the period, finished or not",
            "active_users": "accounts whose last session check falls in the period",
            "new_paying_users": "accounts whose first paid (non gift card) invoice falls in the period",
            "credit_purchases": "paid invoices in the period, refunds and chargebacks left out",
        },
    }


@router.post("/growth-metrics", include_in_schema=False)
@limiter.limit("10/minute")
async def get_growth_metrics(
    request: Request,
    body: GrowthMetricsRequest,
    admin_user: User = Depends(require_admin_api_key),
    directus_service: DirectusService = Depends(get_directus_service),
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    since = body.since if body.since.tzinfo else body.since.replace(tzinfo=timezone.utc)
    if not now - timedelta(days=MAX_WINDOW_DAYS) <= since < now:
        raise HTTPException(status_code=422, detail=f"since must lie within the last {MAX_WINDOW_DAYS} days")
    logger.info("Admin %s querying aggregate growth metrics since %s", admin_user.id, since.isoformat())
    try:
        users = await directus_service.get_items("directus_users", {"fields": USER_FIELDS, "limit": -1},
                                                 admin_required=True, raise_on_error=True)
        invoices = await directus_service.get_items("invoices", {"fields": INVOICE_FIELDS, "limit": -1},
                                                    admin_required=True, raise_on_error=True)
    except RuntimeError as error:
        logger.error("Growth metrics read failed: %s", error)
        raise HTTPException(status_code=502, detail="Directus read failed") from error
    excluded = set(body.exclude_email_hashes) | configured_test_account_hashes()
    metrics = compute_growth_metrics(users or [], invoices or [], now=now, since=since,
                                     excluded_email_hashes=excluded)
    return {"success": True, "metrics": metrics}
