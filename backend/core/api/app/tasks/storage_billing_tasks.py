"""Weekly personal storage invoices, exact credit settlement, and delivered warnings.

The charge is based on one immutable Sunday 03:00 UTC usage snapshot. The
credit ledger is authoritative for payment; invoices and warning state are
serialized by the Directus transaction endpoint. Protected expiry removes only
the frozen warned units and waives their episode after verified usage reduction.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

from fastapi import HTTPException

from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.services.billing_service import (
    BillingService, PERSONAL_CREDIT_OVERDRAFT_LIMIT,
)
from backend.core.api.app.services.server_stats_service import ServerStatsService
from backend.core.api.app.services.email_template import EmailTemplateService
from backend.core.api.app.services.email_delivery_guard import (
    build_delivery_id,
    build_delivery_key,
    send_email_once,
)
from backend.core.api.app.services.sub_chat_orchestration_service import (
    SubChatOrchestrationService,
)
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.core.api.app.utils.server_mode import is_payment_enabled

logger = logging.getLogger(__name__)
FREE_BYTES = 1_073_741_824
CREDITS_PER_GB_PER_WEEK = 3
BATCH_SIZE = 100
WARNING_INTERVAL_SECONDS = 7 * 24 * 60 * 60
MAX_PROVIDER_EVENTS = 100
PROVIDER_RECEIPT_RECHECK_SECONDS = 3600
PROVIDER_RECEIPT_SWEEP_SECONDS = 45
FAILED_PROVIDER_EVENTS = frozenset({
    "bounces", "hardBounces", "softBounces", "invalid",
    "blocked", "spam", "error",
})
KNOWN_PROVIDER_EVENTS = FAILED_PROVIDER_EVENTS | frozenset({
    "delivered", "requests", "opened", "clicks",
    "deferred", "unsubscribed", "loadedByProxy",
})


def _compute_billable_credits(total_bytes: int) -> int:
    if not isinstance(total_bytes, int) or total_bytes < 0:
        raise ValueError("Storage usage must be a non-negative integer")
    return max(0, (total_bytes - FREE_BYTES + FREE_BYTES - 1) // FREE_BYTES) * CREDITS_PER_GB_PER_WEEK


def _period_start_at(now: datetime | None = None) -> int:
    """Stable Sunday 03:00 UTC boundary, including retries later in the week."""
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    days_since_sunday = (current.weekday() + 1) % 7
    sunday = (current - timedelta(days=days_since_sunday)).replace(
        hour=3, minute=0, second=0, microsecond=0
    )
    if current < sunday:
        sunday -= timedelta(days=7)
    return int(sunday.timestamp())


def _ledger_time_in_period(value: Any, period_start_at: int) -> bool:
    """An unreadable ledger timestamp is uncertain, so it fences the charge."""
    if not isinstance(value, str):
        return True
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp() >= period_start_at
    except ValueError:
        return True


async def _legacy_charge_in_period(
    directus: DirectusService, owner_hash: str, period_start_at: int,
) -> bool:
    """Fence the first Sunday invoice against either intersecting Unix week key.

    The old task used ``int(time.time()) // 604800``. Its Thursday rollover
    occurs inside our Sunday billing period, so both possible keys matter.
    Read the durable charge and retry ledgers; cache absence proves nothing.
    """
    old_week = period_start_at // WARNING_INTERVAL_SECONDS
    keys = [f"storage:{owner_hash}:{old_week + offset}" for offset in (0, 1)]
    for collection in ("billing_charge_identities", "billing_settlement_outbox"):
        fields = ("charge_id,state,committed_at" if collection == "billing_charge_identities"
                  else "charge_id,state,created_at,updated_at")
        rows = await directus.get_items(
            collection,
            params={
                "filter": {"charge_id": {"_in": keys}},
                "fields": fields,
                "limit": 2,
            },
            admin_required=True, no_cache=True, raise_on_error=True,
        )
        if not isinstance(rows, list) or len(rows) > 2:
            raise RuntimeError("Legacy storage charge ledger lookup was incomplete")
        for row in rows:
            if not isinstance(row, dict) or row.get("charge_id") not in keys:
                raise RuntimeError("Legacy storage charge ledger returned invalid evidence")
            if collection == "billing_charge_identities":
                if (row.get("state") != "committed"
                        or _ledger_time_in_period(row.get("committed_at"), period_start_at)):
                    return True
            elif row.get("state") in ("pending", "retry_scheduled"):
                return True
            elif row.get("state") not in ("committed", "failed", "cancelled"):
                return True
            elif (_ledger_time_in_period(row.get("created_at"), period_start_at)
                  or _ledger_time_in_period(row.get("updated_at"), period_start_at)):
                return True
    return False


async def _owner_operation(
    orchestration: SubChatOrchestrationService,
    operation: str,
    user_id: str,
    **data: Any,
) -> dict[str, Any]:
    return await orchestration.execute(operation, {
        "protocol_version": 1,
        "user_id": user_id,
        "hashed_user_id": hashlib.sha256(user_id.encode()).hexdigest(),
        **data,
    })


async def _apply_due_expiry(
    user_id: str, episode_id: str, *, directus: DirectusService,
    encryption: EncryptionService, orchestration: SubChatOrchestrationService,
) -> dict[str, Any]:
    """Fresh authoritative affordability check followed by a balance-CAS removal.

    The SQL operation repeats all receipt, ownership, unit, reference and usage
    checks under locks. A top-up after this read changes the ciphertext and stops
    removal. Neither a stale cache nor a 402 alone admits data deletion.
    """
    if os.getenv("STORAGE_UNPAID_EXPIRY_ENABLED", "0") != "1":
        return {"applied": False, "held": True, "reason": "expiry_disabled"}
    fields = await directus.get_user_fields_direct(
        user_id, ["encrypted_credit_balance", "vault_key_id"]
    )
    if not isinstance(fields, dict) or not all(fields.get(key) for key in (
        "encrypted_credit_balance", "vault_key_id",
    )):
        raise RuntimeError("Authoritative expiry balance is unavailable")
    balance = await encryption.decrypt_with_user_key(
        fields["encrypted_credit_balance"], fields["vault_key_id"]
    )
    if balance is None:
        raise RuntimeError("Authoritative expiry balance cannot be decrypted")
    try:
        credits = int(balance)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Authoritative expiry balance is invalid") from exc
    debt = await _owner_operation(orchestration, "list_storage_debt", user_id)
    periods = debt.get("periods")
    if not isinstance(periods, list):
        raise RuntimeError("Authoritative expiry debt is unavailable")
    if not periods:
        return {"applied": False, "held": True, "reason": "debt_settled"}
    due = int(periods[0]["credits_due"])
    if due <= 0:
        raise RuntimeError("Authoritative expiry invoice is invalid")
    if credits > PERSONAL_CREDIT_OVERDRAFT_LIMIT and credits - due >= PERSONAL_CREDIT_OVERDRAFT_LIMIT:
        return {"applied": False, "held": True, "reason": "payment_available"}
    from backend.shared.python_utils.object_storage_regions import parse_storage_regions
    return await _owner_operation(
        orchestration, "apply_storage_expiry", user_id,
        episode_id=episode_id, now_at=int(time.time()),
        expected_encrypted_balance=fields["encrypted_credit_balance"],
        regions=list(parse_storage_regions(os.getenv("S3_REGIONS"))),
    )


def _provider_delivery_decision(
    report: dict[str, Any], *, message_id: str, recipient_hash: str,
) -> tuple[str, int | None]:
    """Classify one exact Brevo message; missing, stale or truncated evidence is unknown."""
    events = report.get("events") if isinstance(report, dict) else None
    if not isinstance(report, dict) or report.get("error") or not isinstance(events, list) or len(events) > MAX_PROVIDER_EVENTS:
        return "unknown", None
    delivered_at: int | None = None
    failed = False
    for event in events:
        if not isinstance(event, dict) or event.get("messageId") != message_id:
            return "unknown", None
        email = event.get("email")
        if not isinstance(email, str) or hashlib.sha256(email.strip().lower().encode()).hexdigest() != recipient_hash:
            return "unknown", None
        kind = event.get("event")
        if kind not in KNOWN_PROVIDER_EVENTS:
            return "unknown", None
        if kind in FAILED_PROVIDER_EVENTS:
            failed = True
        elif kind == "delivered":
            try:
                observed = datetime.fromisoformat(str(event["date"]).replace("Z", "+00:00"))
                if observed.tzinfo is None:
                    return "unknown", None
                epoch = int(observed.timestamp())
                delivered_at = epoch if delivered_at is None else min(delivered_at, epoch)
            except (ValueError, TypeError, KeyError):
                return "unknown", None
    if failed:
        return "failed", int(time.time())
    if delivered_at is not None:
        return "delivered", delivered_at
    return "unknown", None


async def _reconcile_provider_receipt(
    user_id: str, episode: str, stage: int, row: dict[str, Any],
    *, email_service: EmailTemplateService, orchestration: SubChatOrchestrationService,
) -> bool:
    """Poll at most 101 exact-ID events within Brevo's 90-day report window."""
    message_id = row.get("provider_message_id")
    recipient_hash = row.get("recipient_hash")
    if (row.get("status") != "sent" or not isinstance(message_id, str)
            or not message_id or not isinstance(recipient_hash, str)
            or len(recipient_hash) != 64):
        return False
    report = await email_service.get_delivery_events_for_message(message_id)
    state, observed_at = _provider_delivery_decision(
        report, message_id=message_id, recipient_hash=recipient_hash,
    )
    if state == "unknown" or observed_at is None:
        return False
    receipt = await _owner_operation(
        orchestration, "record_storage_delivery_receipt", user_id,
        episode_id=episode, warning_stage=stage, delivery_id=row["id"],
        message_id=message_id, state=state, observed_at=observed_at,
        now_at=int(time.time()),
    )
    return receipt.get("state") == "delivered" and not receipt.get("held")


async def _recheck_four_provider_receipts(
    user_id: str, episode: str, *, directus: DirectusService,
    email_service: EmailTemplateService, orchestration: SubChatOrchestrationService,
) -> bool:
    """Final bounded provider check; a later bounce suppresses expiry admission."""
    for stage in range(1, 5):
        key = build_delivery_key(
            email_type="storage-billing-warning", campaign_key=episode,
            recipient_kind="directus_user", recipient_id=user_id, stage=f"week-{stage}",
        )
        delivery_id = build_delivery_id(key)
        rows = await directus.get_items(
            "email_deliveries",
            params={"filter[id][_eq]": delivery_id,
                    "fields": "id,status,recipient_hash,provider_message_id",
                    "limit": 1},
            admin_required=True, no_cache=True, raise_on_error=True,
        )
        if not isinstance(rows, list) or len(rows) != 1:
            return False
        if not await _reconcile_provider_receipt(
            user_id, episode, stage, rows[0],
            email_service=email_service, orchestration=orchestration,
        ):
            return False
    return True


async def _deliver_warning(
    user_id: str,
    warning: dict[str, Any],
    *,
    directus: DirectusService,
    encryption: EncryptionService,
    email_service: EmailTemplateService,
    orchestration: SubChatOrchestrationService,
    cache: CacheService,
) -> bool:
    """Count a warning only after an exact provider delivered event is recorded."""
    stage = int(warning["warning_stage"])
    episode = str(warning["episode_id"])
    selection_hash = warning.get("unit_selection_hash")
    units = warning.get("units")
    if (not isinstance(selection_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", selection_hash)
            or not isinstance(units, list) or not 1 <= len(units) <= 100):
        raise RuntimeError("Frozen affected storage list is unavailable")
    delivery_key = build_delivery_key(
        email_type="storage-billing-warning",
        campaign_key=episode,
        recipient_kind="directus_user",
        recipient_id=user_id,
        stage=f"week-{stage}",
    )
    delivery_id = build_delivery_id(delivery_key)
    existing = await directus.get_items(
        "email_deliveries",
        params={"filter[id][_eq]": delivery_id,
                "fields": "id,status,metadata,lang,recipient_hash,provider_message_id",
                "limit": 1},
        admin_required=True, no_cache=True, raise_on_error=True,
    )
    if not isinstance(existing, list):
        raise RuntimeError("Storage warning delivery lookup was incomplete")
    if not existing or existing[0].get("status") != "sent":
        users = await directus.get_items(
            "directus_users",
            params={
                "filter[id][_eq]": user_id,
                "fields": "id,encrypted_email_address,vault_key_id,language",
                "limit": 1,
            },
            admin_required=True, no_cache=True, raise_on_error=True,
        )
        if not isinstance(users, list) or len(users) != 1:
            raise RuntimeError("Storage warning recipient is unavailable")
        user = users[0]
        if not user.get("encrypted_email_address") or not user.get("vault_key_id"):
            raise RuntimeError("Storage warning recipient encryption metadata is incomplete")
        address = await encryption.decrypt_with_user_key(
            ciphertext=user["encrypted_email_address"], key_id=user["vault_key_id"]
        )
        if not address:
            raise RuntimeError("Storage warning recipient cannot be decrypted")
        now_at = int(time.time())
        first_at = int(warning.get("first_warning_at") or now_at)
        earliest = max(
            first_at + 4 * WARNING_INTERVAL_SECONDS,
            now_at + WARNING_INTERVAL_SECONDS,
        )
        # Show the first whole UTC calendar day after every known minimum.
        # Delivery can cross midnight during the bounded retry window; the
        # transaction also fences expiry behind the advertised date.
        deadline_date = (
            datetime.fromtimestamp(earliest, tz=timezone.utc).date()
            + timedelta(days=1)
        ).isoformat()
        base_url = os.getenv("WEBAPP_URL", "https://openmates.org").rstrip("/")
        if existing:
            metadata = existing[0].get("metadata")
            if not isinstance(metadata, dict) or metadata.get("template") != f"storage-billing-failed-{stage}":
                raise RuntimeError("Storage warning retry payload is unavailable")
            context = metadata.get("context")
            if not isinstance(context, dict):
                raise RuntimeError("Storage warning retry context is unavailable")
            if context.get("unit_selection_hash") != selection_hash:
                raise RuntimeError("Storage warning retry selection changed")
            language = existing[0].get("lang") or "en"
        else:
            context = {
                "storage_gb": round(int(warning["measured_bytes"]) / FREE_BYTES, 2),
                "credits_needed": int(warning["credits_due"]),
                "outstanding_credits": int(warning["outstanding_credits"]),
                "deadline_date": deadline_date,
                "credits_url": f"{base_url}/#settings/billing",
                "export_url": f"{base_url}/#settings/account/export",
                "storage_url": f"{base_url}/#settings/account/storage",
                "unit_selection_hash": selection_hash,
                "affected_units": [{
                    "unit_id": unit["unit_id"], "kind": unit["kind"],
                    "resource_id": unit["resource_id"],
                    "oldest_date": datetime.fromtimestamp(
                        int(unit["oldest_at"]), tz=timezone.utc,
                    ).date().isoformat(),
                    "size_mib": round(int(unit["bytes"]) / (1024 * 1024), 2),
                } for unit in units],
                "darkmode": False,
            }
            language = user.get("language") or "en"
        async def still_eligible() -> bool:
            current = await _owner_operation(
                orchestration, "claim_storage_warning", user_id,
                now_at=int(time.time()),
            )
            return bool(
                current.get("due") and current.get("episode_id") == episode
                and int(current.get("warning_stage", 0)) == stage
            )
        sent, _ = await send_email_once(
            directus=directus,
            email_template_service=email_service,
            email_type="storage-billing-warning",
            campaign_key=episode,
            recipient_kind="directus_user",
            recipient_id=user_id,
            recipient_email=address,
            template=f"storage-billing-failed-{stage}",
            context=context,
            stage=f"week-{stage}",
            lang=language,
            metadata={
                "oldest_period_id": warning["oldest_period_id"],
                "template": f"storage-billing-failed-{stage}",
                "context": context,
            },
            retry_cache=cache,
            before_send=still_eligible,
        )
        if not sent:
            return False

    receipt_rows = await directus.get_items(
        "email_deliveries",
        params={"filter[id][_eq]": delivery_id,
                "fields": "id,status,recipient_hash,provider_message_id",
                "limit": 1},
        admin_required=True, no_cache=True, raise_on_error=True,
    )
    if not isinstance(receipt_rows, list) or len(receipt_rows) != 1:
        raise RuntimeError("Storage warning provider receipt lookup was incomplete")
    if not await _reconcile_provider_receipt(
        user_id, episode, stage, receipt_rows[0],
        email_service=email_service, orchestration=orchestration,
    ):
        return False

    # The provider delivered event, not its submission acceptance, starts the clock.
    await _owner_operation(
        orchestration, "acknowledge_storage_warning", user_id,
        episode_id=episode, warning_stage=stage, delivery_id=delivery_id,
        now_at=int(time.time()),
    )
    return True


async def _settle_owner(
    user_id: str,
    quote: Any,
    *,
    period_start_at: int,
    directus: DirectusService,
    billing: BillingService,
    orchestration: SubChatOrchestrationService,
    encryption: EncryptionService,
    email_service: EmailTemplateService,
    cache: CacheService,
    _final_check: bool = False,
) -> dict[str, int]:
    """Freeze this week, settle old debt first, then advance one owner warning."""
    result = {"billed": 0, "credits": 0, "insufficient": 0, "operational_error": 0,
              "warnings_delivered": 0, "expiry_due": 0, "legacy_period_ignored": 0,
              "expiry_applied": 0, "periods_waived": 0}
    total_bytes = quote.total_bytes
    credits = _compute_billable_credits(total_bytes)
    owner_hash = hashlib.sha256(user_id.encode()).hexdigest()
    try:
        legacy_attempt = await _legacy_charge_in_period(directus, owner_hash, period_start_at)
    except Exception:
        logger.exception("[StorageBilling] Legacy charge ledger unavailable for owner %s", user_id)
        result["operational_error"] = 1
        return result
    if legacy_attempt:
        # Keep the old charge as this period's settlement. Do not freeze a new
        # invoice, mark paid, increment debt, or send a warning. Retry next week.
        logger.info("[StorageBilling] Ignoring overlapping legacy billing period for owner %s", user_id)
        result["legacy_period_ignored"] = 1
        return result
    if credits:
        await _owner_operation(
            orchestration, "freeze_storage_period", user_id,
            period_start_at=period_start_at, measured_bytes=total_bytes,
            credits_due=credits, charge_id=f"storage:{owner_hash}:{period_start_at}",
            free_bytes=FREE_BYTES, credits_per_gib=CREDITS_PER_GB_PER_WEEK,
            policy_version=quote.policy_version, source_version=quote.source_version,
            category_bytes=quote.categories,
        )

    # The extension returns at most 20 oldest unpaid rows. Settlement removes
    # the head, so repeating this read drains arbitrarily old debt in bounds.
    while True:
        debt = await _owner_operation(orchestration, "list_storage_debt", user_id)
        periods = debt.get("periods")
        if not isinstance(periods, list):
            raise RuntimeError("Storage debt lookup was incomplete")
        if not periods:
            break
        period = periods[0]
        due = int(period["credits_due"])
        try:
            charged = await billing.charge_user_credits(
                user_id=user_id,
                credits_to_deduct=due,
                user_id_hash=owner_hash,
                app_id="system",
                skill_id="storage",
                idempotency_key=period["charge_id"],
                usage_details={
                    "storage_bytes": int(period["measured_bytes"]),
                    "period_start_at": int(period["period_start_at"]),
                    "free_gb": 1,
                    "credits_per_gb": CREDITS_PER_GB_PER_WEEK,
                },
                require_full_charge=True,
                _defer_exhausted_conflict=False,
            )
        except HTTPException as exc:
            if exc.status_code == 402:
                result["insufficient"] = 1
                break
            raise
        if not isinstance(charged, dict) or charged.get("state") != "committed" or int(
            charged.get("charged_credits", -1)
        ) != due:
            # Includes retry_scheduled and partial charges. The extension also
            # checks the committed ledger before it can mark an invoice paid.
            result["operational_error"] = 1
            break
        await _owner_operation(
            orchestration, "mark_storage_period_paid", user_id, period_id=period["id"]
        )
        result["billed"] += 1
        result["credits"] += due

    if result["insufficient"]:
        warning = await _owner_operation(
            orchestration, "claim_storage_warning", user_id, now_at=int(time.time())
        )
        if warning.get("due") and not _final_check:
            selection = await _owner_operation(
                orchestration, "freeze_storage_warning_units", user_id,
                episode_id=warning["episode_id"], now_at=int(time.time()),
            )
            if selection.get("frozen") and not selection.get("held"):
                result["warnings_delivered"] = int(await _deliver_warning(
                    user_id, {**warning, **selection}, directus=directus, encryption=encryption,
                    email_service=email_service, orchestration=orchestration,
                    cache=cache,
                ))
        if warning.get("reason") == "four_delivered":
            episode = warning.get("episode_id")
            if not isinstance(episode, str) or not await _recheck_four_provider_receipts(
                user_id, episode, directus=directus,
                email_service=email_service, orchestration=orchestration,
            ):
                return result
        expiry = await _owner_operation(
            orchestration, "inspect_storage_expiry", user_id, now_at=int(time.time())
        )
        result["expiry_due"] = int(bool(expiry.get("due")))
        if result["expiry_due"] and not _final_check:
            # Re-read and try every outstanding invoice immediately before
            # admitting expiry. A late top-up or a settlement outage must
            # suppress admission even if the old four-warning clock elapsed.
            final = await _settle_owner(
                user_id, quote, period_start_at=period_start_at,
                directus=directus, billing=billing, orchestration=orchestration,
                encryption=encryption, email_service=email_service, cache=cache,
                _final_check=True,
            )
            result["expiry_due"] = int(
                bool(final["insufficient"] and final["expiry_due"]
                     and not final["operational_error"])
            )
            if result["expiry_due"]:
                applied = await _apply_due_expiry(
                    user_id, expiry["episode_id"], directus=directus,
                    encryption=encryption, orchestration=orchestration,
                )
                result["expiry_applied"] = int(bool(applied.get("applied")))
                result["periods_waived"] = len(applied.get("waived_period_ids") or [])
    return result


async def _metered_owner_ids(metering):
    cursor: str | None = None
    while True:
        page = await metering.list_personal_owner_ids(
            after_user_id=cursor, limit=BATCH_SIZE
        )
        if not isinstance(page, list) or len(page) > BATCH_SIZE:
            raise RuntimeError("Storage owner page was incomplete")
        if not page:
            return
        if any(not isinstance(item, str) for item in page) or page != sorted(set(page)):
            raise RuntimeError("Storage owner page order was invalid")
        if cursor is not None and page[0] <= cursor:
            raise RuntimeError("Storage owner cursor did not advance")
        for owner_id in page:
            yield owner_id
        cursor = page[-1]
        if len(page) < BATCH_SIZE:
            return


async def _debt_owner_ids(directus: DirectusService):
    """Page all unpaid periods by stable ID; sort and dedupe one bounded batch."""
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {
            "filter[state][_eq]": "unpaid", "fields": "id,user_id",
            "sort": "id", "limit": BATCH_SIZE,
        }
        if cursor is not None:
            params["filter[id][_gt]"] = cursor
        page = await directus.get_items(
            "storage_billing_periods", params=params, admin_required=True,
            no_cache=True, raise_on_error=True,
        )
        if not isinstance(page, list) or len(page) > BATCH_SIZE:
            raise RuntimeError("Storage debt owner page was incomplete")
        if not page:
            return
        # Period hashes do not order by owner. The unique owner set here is
        # limited to a page; duplicates across pages are harmless because the
        # same immutable charge ID and extension locks make retries idempotent.
        for row in page:
            if not row.get("id") or not row.get("user_id"):
                raise RuntimeError("Storage debt owner row was incomplete")
            yield str(row["user_id"])
        next_cursor = str(page[-1]["id"])
        if cursor is not None and next_cursor <= cursor:
            raise RuntimeError("Storage debt cursor did not advance")
        cursor = next_cursor
        if len(page) < BATCH_SIZE:
            return


async def _iter_billing_owner_batches(directus: DirectusService, metering):
    """Bound memory while including archive-only and unpaid owners."""
    batch: list[str] = []
    seen_in_batch: set[str] = set()
    for owner_source in (_metered_owner_ids(metering), _debt_owner_ids(directus)):
        async for owner_id in owner_source:
            if owner_id in seen_in_batch:
                continue
            batch.append(owner_id)
            seen_in_batch.add(owner_id)
            if len(batch) == BATCH_SIZE:
                yield batch
                batch, seen_in_batch = [], set()
    if batch:
        yield batch


async def _quote_owners_isolating_incomplete(metering, ids: list[str]):
    """Keep one corrupt owner from suppressing every other owner in its page."""
    from backend.core.api.app.services.storage_usage_metering import StorageUsageIncompleteError

    try:
        quotes = await metering.quote_personal(ids)
        if not isinstance(quotes, dict) or set(quotes) != set(ids):
            raise StorageUsageIncompleteError("storage_metering_missing_owner")
        return quotes, []
    except StorageUsageIncompleteError as exc:
        if str(exc) in {
            "storage_metering_unavailable",
            "storage_metering_internal_token_missing",
            "storage_metering_invalid_response",
        }:
            raise
        if len(ids) == 1:
            return {}, ids
        middle = len(ids) // 2
        left, left_failed = await _quote_owners_isolating_incomplete(metering, ids[:middle])
        right, right_failed = await _quote_owners_isolating_incomplete(metering, ids[middle:])
        return {**left, **right}, left_failed + right_failed


async def _async_charge_storage_fees() -> dict[str, Any]:
    if not is_payment_enabled():
        return {"skipped": "payment_disabled"}
    run_start = time.time()
    secrets = SecretsManager()
    directus = DirectusService()
    cache = CacheService()
    encryption = EncryptionService()
    billing = BillingService(
        cache_service=cache, directus_service=directus,
        encryption_service=encryption,
        server_stats_service=ServerStatsService(cache, directus),
    )
    orchestration = SubChatOrchestrationService(directus)
    summary: dict[str, Any] = {
        "users_checked": 0, "users_billed": 0, "users_failed": 0,
        "warnings_delivered": 0, "users_expiry_due": 0,
        "total_credits_charged": 0, "duration_seconds": 0.0,
        "legacy_periods_ignored": 0,
        "users_expired": 0, "periods_waived": 0,
    }
    try:
        await directus.ensure_auth_token()
        await secrets.initialize()
        email_service = EmailTemplateService(secrets_manager=secrets)
        from backend.core.api.app.services.storage_usage_metering import StorageUsageMeteringService
        metering = StorageUsageMeteringService(directus)
        period_start = _period_start_at()
        async for ids in _iter_billing_owner_batches(directus, metering):
            quotes, incomplete_owners = await _quote_owners_isolating_incomplete(metering, ids)
            summary["users_failed"] += len(incomplete_owners)
            for user_id in ids:
                if user_id in incomplete_owners:
                    continue
                quote = quotes[user_id]
                if not quote.complete or not isinstance(quote.total_bytes, int):
                    raise RuntimeError("Storage usage quote was incomplete")
                try:
                    outcome = await _settle_owner(
                        user_id, quote, period_start_at=period_start,
                        directus=directus, billing=billing, orchestration=orchestration,
                        encryption=encryption, email_service=email_service, cache=cache,
                    )
                    summary["users_checked"] += 1
                    summary["users_billed"] += outcome["billed"]
                    summary["total_credits_charged"] += outcome["credits"]
                    summary["warnings_delivered"] += outcome["warnings_delivered"]
                    summary["users_expiry_due"] += outcome["expiry_due"]
                    summary["legacy_periods_ignored"] += outcome["legacy_period_ignored"]
                    summary["users_expired"] += outcome["expiry_applied"]
                    summary["periods_waived"] += outcome["periods_waived"]
                    summary["users_failed"] += int(bool(outcome["insufficient"] or outcome["operational_error"]))
                except Exception:
                    summary["users_failed"] += 1
                    logger.exception("[StorageBilling] Owner settlement failed for %s", user_id)
        summary["duration_seconds"] = round(time.time() - run_start, 2)
        return summary
    finally:
        await cache.close()
        await secrets.aclose()


async def _async_retry_storage_warning_deliveries() -> dict[str, int | str]:
    """Reconcile recent notice rows after worker restart without a second ID.

    The first reservation timestamp is immutable. The existing delivery guard
    retries with the same Brevo UUID only inside its 10-minute window and a
    Redis lease; uncertain rows beyond that window require manual review.
    """
    if not is_payment_enabled():
        return {"skipped": "payment_disabled"}
    from backend.core.api.app.services.storage_usage_metering import StorageUsageMeteringService

    secrets = SecretsManager()
    directus = DirectusService()
    cache = CacheService()
    encryption = EncryptionService()
    billing = BillingService(
        cache_service=cache, directus_service=directus,
        encryption_service=encryption,
        server_stats_service=ServerStatsService(cache, directus),
    )
    orchestration = SubChatOrchestrationService(directus)
    metering = StorageUsageMeteringService(directus)
    summary: dict[str, int | str] = {"examined": 0, "warnings_delivered": 0, "errors": 0}
    try:
        await directus.ensure_auth_token()
        await secrets.initialize()
        email_service = EmailTemplateService(secrets_manager=secrets)
        # This task runs every two minutes. Bound all provider-capable phases
        # under one clock so an outage cannot build overlapping sweeps.
        sweep_deadline = time.monotonic() + PROVIDER_RECEIPT_SWEEP_SECONDS
        retry_deadline = min(sweep_deadline, time.monotonic() + 15)
        now = datetime.now(timezone.utc)
        # Allow the original provider call to finish, and never cross the
        # documented idempotency lifetime. The guard checks exact age again.
        earliest = (now - timedelta(seconds=600)).isoformat()
        latest = (now - timedelta(seconds=120)).isoformat()
        cursor: str | None = None
        while True:
            if time.monotonic() >= retry_deadline:
                break
            filters: dict[str, Any] = {
                "email_type": {"_eq": "storage-billing-warning"},
                "status": {"_in": ["processing", "failed", "sent"]},
                "storage_warning_acknowledged_at": {"_null": True},
                "processing_started_at": {"_gte": earliest, "_lte": latest},
            }
            if cursor is not None:
                filters["id"] = {"_gt": cursor}
            page = await directus.get_items(
                "email_deliveries",
                params={
                    "filter": filters, "fields": "id,recipient_id,recipient_kind",
                    "sort": "id", "limit": BATCH_SIZE,
                },
                admin_required=True, no_cache=True, raise_on_error=True,
            )
            if not isinstance(page, list) or len(page) > BATCH_SIZE:
                raise RuntimeError("Storage warning retry page was incomplete")
            if not page:
                break
            for row in page:
                if time.monotonic() >= retry_deadline:
                    break
                summary["examined"] += 1
                user_id = row.get("recipient_id")
                if row.get("recipient_kind") != "directus_user" or not isinstance(user_id, str):
                    summary["errors"] += 1
                    continue
                try:
                    quotes = await asyncio.wait_for(
                        metering.quote_personal([user_id]),
                        timeout=max(0.001, retry_deadline - time.monotonic()),
                    )
                    quote = quotes[user_id]
                    if time.monotonic() >= retry_deadline:
                        raise TimeoutError("Storage warning retry budget exhausted")
                    outcome = await asyncio.wait_for(
                        _settle_owner(
                            user_id, quote, period_start_at=_period_start_at(),
                            directus=directus, billing=billing, orchestration=orchestration,
                            encryption=encryption, email_service=email_service, cache=cache,
                        ),
                        timeout=max(0.001, retry_deadline - time.monotonic()),
                    )
                    summary["warnings_delivered"] += outcome["warnings_delivered"]
                except Exception:
                    summary["errors"] += 1
                    logger.exception("[StorageBilling] Warning reconciliation failed for %s", user_id)
            next_cursor = str(page[-1].get("id") or "")
            if not next_cursor or (cursor is not None and next_cursor <= cursor):
                raise RuntimeError("Storage warning retry cursor did not advance")
            cursor = next_cursor
            if time.monotonic() >= retry_deadline:
                break
            if len(page) < BATCH_SIZE:
                break
        # Expired uncertainty cannot be replayed after the provider's
        # idempotency window. Move it to an explicit durable operator hold
        # instead of silently retrying each week or counting a warning.
        cursor = None
        expired_deadline = min(sweep_deadline, time.monotonic() + 5)
        for _page_number in range(10):
            if time.monotonic() >= expired_deadline:
                break
            filters = {
                "email_type": {"_eq": "storage-billing-warning"},
                "status": {"_in": ["processing", "failed"]},
                "processing_started_at": {"_lt": earliest},
            }
            if cursor is not None:
                filters["id"] = {"_gt": cursor}
            page = await directus.get_items(
                "email_deliveries",
                params={
                    "filter": filters,
                    "fields": "id,recipient_id,recipient_kind,campaign_key,stage",
                    "sort": "id", "limit": BATCH_SIZE,
                },
                admin_required=True, no_cache=True, raise_on_error=True,
            )
            if not isinstance(page, list) or len(page) > BATCH_SIZE:
                raise RuntimeError("Expired storage warning page was incomplete")
            if not page:
                break
            for row in page:
                if time.monotonic() >= expired_deadline:
                    break
                user_id = row.get("recipient_id")
                stage = row.get("stage")
                if (row.get("recipient_kind") != "directus_user"
                    or not isinstance(user_id, str) or not isinstance(stage, str)
                    or not stage.startswith("week-") or not stage[5:].isdigit()):
                    summary["errors"] += 1
                    logger.error("[StorageBilling] Malformed expired warning delivery %s", row.get("id"))
                    continue
                try:
                    held = await asyncio.wait_for(
                        _owner_operation(
                            orchestration, "mark_storage_warning_manual_review", user_id,
                            episode_id=row["campaign_key"], warning_stage=int(stage[5:]),
                            delivery_id=row["id"], now_at=int(time.time()),
                        ),
                        timeout=max(0.001, expired_deadline - time.monotonic()),
                    )
                    if held.get("held"):
                        logger.error(
                            "[StorageBilling] Warning requires manual provider reconciliation: delivery=%s",
                            row["id"],
                        )
                except Exception:
                    summary["errors"] += 1
                    logger.exception(
                        "[StorageBilling] Could not hold expired warning delivery %s", row.get("id")
                    )
            next_cursor = str(page[-1].get("id") or "")
            if not next_cursor or (cursor is not None and next_cursor <= cursor):
                raise RuntimeError("Expired storage warning cursor did not advance")
            cursor = next_cursor
            if time.monotonic() >= expired_deadline:
                break
            if len(page) < BATCH_SIZE:
                break
        # Submission acceptance is not delivery. Poll pending exact message
        # IDs independently of the 10-minute send retry window, including a
        # first warning whose owner warning_count is still zero. Each row is
        # checked at most hourly and each sweep reads at most 10 x 100 rows.
        cursor = None
        receipt_sweep_deadline = min(sweep_deadline, time.monotonic() + 15)
        checked_before = (now - timedelta(seconds=PROVIDER_RECEIPT_RECHECK_SECONDS)).isoformat()
        for _page_number in range(10):
            if time.monotonic() >= receipt_sweep_deadline:
                break
            filters = {
                "email_type": {"_eq": "storage-billing-warning"},
                "status": {"_eq": "sent"},
                "provider_delivery_state": {"_eq": "accepted"},
                "storage_warning_acknowledged_at": {"_null": True},
                "processing_started_at": {"_lt": earliest},
                "_or": [
                    {"provider_receipt_checked_at": {"_null": True}},
                    {"provider_receipt_checked_at": {"_lte": checked_before}},
                ],
            }
            if cursor is not None:
                filters["id"] = {"_gt": cursor}
            page = await directus.get_items(
                "email_deliveries",
                params={
                    "filter": filters,
                    "fields": "id,recipient_id,recipient_kind,recipient_hash,campaign_key,"
                              "stage,status,provider_message_id,processing_started_at",
                    "sort": "id", "limit": BATCH_SIZE,
                },
                admin_required=True, no_cache=True, raise_on_error=True,
            )
            if not isinstance(page, list) or len(page) > BATCH_SIZE:
                raise RuntimeError("Storage receipt page was incomplete")
            if not page:
                break
            for row in page:
                if time.monotonic() >= receipt_sweep_deadline:
                    break
                summary["examined"] += 1
                user_id = row.get("recipient_id")
                episode = row.get("campaign_key")
                stage_text = row.get("stage")
                if (row.get("recipient_kind") != "directus_user"
                    or not isinstance(user_id, str) or not isinstance(episode, str)
                    or not isinstance(stage_text, str) or not stage_text.startswith("week-")
                    or not stage_text[5:].isdigit()):
                    summary["errors"] += 1
                    continue
                stage = int(stage_text[5:])
                try:
                    try:
                        started = datetime.fromisoformat(
                            str(row.get("processing_started_at")).replace("Z", "+00:00"))
                        beyond_event_horizon = (
                            started.tzinfo is None or
                            now - started.astimezone(timezone.utc) >= timedelta(days=90)
                        )
                    except (TypeError, ValueError):
                        beyond_event_horizon = True
                    if beyond_event_horizon:
                        await _owner_operation(
                            orchestration, "mark_storage_warning_manual_review", user_id,
                            episode_id=episode, warning_stage=stage,
                            delivery_id=row["id"], now_at=int(time.time()),
                        )
                        continue
                    if await asyncio.wait_for(
                        _reconcile_provider_receipt(
                            user_id, episode, stage, row,
                            email_service=email_service, orchestration=orchestration,
                        ),
                        timeout=max(0.001, receipt_sweep_deadline - time.monotonic()),
                    ):
                        await _owner_operation(
                            orchestration, "acknowledge_storage_warning", user_id,
                            episode_id=episode, warning_stage=stage,
                            delivery_id=row["id"], now_at=int(time.time()),
                        )
                        summary["warnings_delivered"] += 1
                    updated = await directus.update_item(
                        "email_deliveries", row["id"],
                        {"provider_receipt_checked_at": datetime.now(timezone.utc).isoformat()},
                        admin_required=True,
                    )
                    if not updated:
                        raise RuntimeError("Storage receipt poll marker not persisted")
                except Exception:
                    summary["errors"] += 1
                    logger.exception("[StorageBilling] Provider receipt reconciliation failed")
            next_cursor = str(page[-1].get("id") or "")
            if not next_cursor or (cursor is not None and next_cursor <= cursor):
                raise RuntimeError("Storage receipt cursor did not advance")
            cursor = next_cursor
            if time.monotonic() >= receipt_sweep_deadline:
                break
            if len(page) < BATCH_SIZE:
                break
        # Weekly warnings are seven days from the previous delivery receipt,
        # which may be minutes after Sunday's billing run. A two-minute sweep
        # avoids accidentally postponing the next stage by an entire week.
        due_before = int(time.time()) - WARNING_INTERVAL_SECONDS
        cursor = None
        for _page_number in range(10):
            if time.monotonic() >= sweep_deadline:
                break
            filters = {
                "warning_count": {"_gte": 1, "_lte": 3},
                "last_warning_at": {"_lte": due_before},
                "closed_at": {"_null": True},
                "warning_manual_review_at": {"_null": True},
            }
            if cursor is not None:
                filters["id"] = {"_gt": cursor}
            page = await directus.get_items(
                "storage_billing_owner_state",
                params={"filter": filters, "fields": "id,user_id",
                        "sort": "id", "limit": BATCH_SIZE},
                admin_required=True, no_cache=True, raise_on_error=True,
            )
            if not isinstance(page, list) or len(page) > BATCH_SIZE:
                raise RuntimeError("Storage dunning page was incomplete")
            if not page:
                break
            for row in page:
                if time.monotonic() >= sweep_deadline:
                    break
                user_id = row.get("user_id")
                if not isinstance(user_id, str):
                    summary["errors"] += 1
                    continue
                try:
                    # Existing frozen debt is the only chargeable source here.
                    # The regular Sunday run owns the new weekly usage quote.
                    outcome = await asyncio.wait_for(
                        _settle_owner(
                            user_id, SimpleNamespace(total_bytes=0),
                            period_start_at=_period_start_at(),
                            directus=directus, billing=billing, orchestration=orchestration,
                            encryption=encryption, email_service=email_service, cache=cache,
                        ),
                        timeout=max(0.001, sweep_deadline - time.monotonic()),
                    )
                    summary["warnings_delivered"] += outcome["warnings_delivered"]
                except Exception:
                    summary["errors"] += 1
                    logger.exception("[StorageBilling] Due warning failed for %s", user_id)
            next_cursor = str(page[-1].get("id") or "")
            if not next_cursor or (cursor is not None and next_cursor <= cursor):
                raise RuntimeError("Storage dunning cursor did not advance")
            cursor = next_cursor
            if time.monotonic() >= sweep_deadline:
                break
            if len(page) < BATCH_SIZE:
                break
        return summary
    finally:
        await cache.close()
        await secrets.aclose()


@app.task(
    name="app.tasks.storage_billing_tasks.retry_storage_warning_deliveries",
    bind=True,
    max_retries=1,
    default_retry_delay=120,
)
def retry_storage_warning_deliveries(self) -> dict[str, int | str]:
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(_async_retry_storage_warning_deliveries())
    except Exception as exc:
        logger.exception("[StorageBilling] Warning reconciliation failed")
        raise self.retry(exc=exc)
    finally:
        loop.close()


@app.task(
    name="app.tasks.storage_billing_tasks.charge_storage_fees",
    bind=True,
    max_retries=1,
    default_retry_delay=300,
)
def charge_storage_fees(self) -> dict[str, Any]:
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(_async_charge_storage_fees())
    except Exception as exc:
        logger.exception("[StorageBilling] Weekly run failed")
        raise self.retry(exc=exc)
    finally:
        loop.close()
