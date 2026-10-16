"""Weekly Team storage settlement and owner/admin delivered-warning lifecycle.

The existing Team numeric credit account is the payment authority. No user
balance, Team content key, or member actor is used for SYSTEM storage debits.
Both switches default off until focused PostgreSQL and S3 evidence is accepted.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.services.email_delivery_guard import (
    build_delivery_id, build_delivery_key, normalize_email_hash, send_email_once,
)
from backend.core.api.app.services.email_template import EmailTemplateService
from backend.core.api.app.services.storage_usage_metering import StorageUsageIncompleteError, StorageUsageMeteringService
from backend.core.api.app.services.sub_chat_orchestration_service import (
    SubChatOrchestrationProtocolError, SubChatOrchestrationService,
)
from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.tasks.storage_billing_tasks import (
    BATCH_SIZE, FREE_BYTES, WARNING_INTERVAL_SECONDS, _compute_billable_credits,
    _period_start_at, _provider_delivery_decision,
)
from backend.core.api.app.utils.encryption import EncryptionService
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.core.api.app.utils.server_mode import is_payment_enabled

logger = logging.getLogger(__name__)
TEAM_BILLING_SWITCH = "TEAM_STORAGE_BILLING_ENABLED"
TEAM_EXPIRY_SWITCH = "TEAM_STORAGE_UNPAID_EXPIRY_ENABLED"
TEAM_WARNING_TYPE = "team-storage-billing-warning"
TEAM_POLICY = "team-storage-1gb-3credits-week-v1"
TEAM_SOURCE = "logical-s3-v1"


async def _operation(orchestration: SubChatOrchestrationService, operation: str,
                     team_hash: str, **data: Any) -> dict[str, Any]:
    return await orchestration.execute(operation, {
        "protocol_version": 1, "hashed_team_id": team_hash, **data,
    })


async def _account_version(directus: DirectusService, team_hash: str) -> int:
    rows = await directus.get_items("team_credit_accounts", params={
        "filter[hashed_team_id][_eq]": team_hash, "fields": "id,version,balance_credits", "limit": 2,
    }, admin_required=True, no_cache=True, raise_on_error=True)
    if not isinstance(rows, list) or len(rows) != 1:
        raise RuntimeError("Team storage credit account is unavailable")
    version = rows[0].get("version")
    balance = rows[0].get("balance_credits")
    if not isinstance(version, int) or version < 0 or not isinstance(balance, int) or balance < 0:
        raise RuntimeError("Team storage credit account is invalid")
    return version


async def _recipients(orchestration: SubChatOrchestrationService, directus: DirectusService,
                      encryption: EncryptionService, team_hash: str,
                      expected_hashes: list[str]) -> list[dict[str, str]]:
    resolved = await _operation(orchestration, "list_team_storage_recipients", team_hash)
    rows = resolved.get("recipients")
    if not isinstance(rows, list) or len(rows) != len(expected_hashes) or not rows:
        raise RuntimeError("Team warning recipients are unresolved")
    recipients: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise RuntimeError("Team warning recipient mapping is invalid")
        user_id, user_hash = row.get("user_id"), row.get("user_hash")
        if (not isinstance(user_id, str) or not isinstance(user_hash, str)
                or hashlib.sha256(user_id.encode()).hexdigest() != user_hash
                or user_hash not in expected_hashes or user_hash in seen):
            raise RuntimeError("Team warning recipient mapping changed")
        seen.add(user_hash)
        users = await directus.get_items("directus_users", params={
            "filter[id][_eq]": user_id,
            "fields": "id,hashed_email,language",
            "limit": 1,
        }, admin_required=True, no_cache=True, raise_on_error=True)
        contacts = await directus.get_items("account_contact_emails", params={
            "filter[user_id][_eq]": user_id,
            "filter[purpose][_eq]": "account_lifecycle",
            "fields": "user_id,hashed_email,encrypted_email_address,purpose,verified_at",
            "limit": 2,
        }, admin_required=True, no_cache=True, raise_on_error=True)
        if (not isinstance(users, list) or len(users) != 1
                or not isinstance(contacts, list) or len(contacts) != 1
                or contacts[0].get("user_id") != user_id
                or contacts[0].get("purpose") != "account_lifecycle"
                or not contacts[0].get("verified_at")
                or not contacts[0].get("encrypted_email_address")):
            raise RuntimeError("Verified Team warning contact email is unavailable")
        address = await encryption.decrypt_account_contact_email(contacts[0]["encrypted_email_address"])
        if not isinstance(address, str) or "@" not in address:
            raise RuntimeError("Verified Team warning contact email cannot be decrypted")
        email_hash = normalize_email_hash(address)
        if (email_hash is None or users[0].get("hashed_email")
                != base64.b64encode(bytes.fromhex(email_hash)).decode("ascii")
                or contacts[0].get("hashed_email") != users[0].get("hashed_email")):
            raise RuntimeError("Team warning recipient email identity changed")
        recipients.append({"user_id": user_id, "user_hash": user_hash,
                           "email": address, "email_hash": email_hash,
                           "language": users[0].get("language") or "en"})
    if sorted(seen) != expected_hashes:
        raise RuntimeError("Team warning recipient set changed")
    return recipients


async def _receipt(orchestration: SubChatOrchestrationService, email_service: EmailTemplateService,
                   team_hash: str, episode: str, stage: int,
                   recipient: dict[str, str], row: dict[str, Any]) -> bool:
    async def hold_expired_uncertainty() -> None:
        try:
            started = datetime.fromisoformat(str(row.get("processing_started_at")).replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - started.astimezone(timezone.utc)).total_seconds()
        except (TypeError, ValueError):
            age = float("inf")
        state = row.get("status")
        if ((state in {"processing", "failed"} and age >= 600)
                or (state == "sent" and row.get("provider_delivery_state") == "accepted"
                    and age >= 90 * 86400)):
            await _operation(orchestration, "mark_team_storage_warning_manual_review", team_hash,
                episode_id=episode, warning_stage=stage, recipient_hash=recipient["user_hash"],
                delivery_id=row["id"], now_at=int(time.time()))

    message_id, email_hash = row.get("provider_message_id"), row.get("recipient_hash")
    if recipient.get("email_hash") != email_hash:
        return False
    if row.get("status") != "sent" or not isinstance(message_id, str) or not message_id or not isinstance(email_hash, str):
        await hold_expired_uncertainty()
        return False
    report = await email_service.get_delivery_events_for_message(message_id)
    state, observed = _provider_delivery_decision(report, message_id=message_id, recipient_hash=email_hash)
    if state == "unknown" or observed is None:
        await hold_expired_uncertainty()
        return False
    result = await _operation(orchestration, "record_team_storage_delivery_receipt", team_hash,
        episode_id=episode, warning_stage=stage, recipient_hash=recipient["user_hash"],
        delivery_id=row["id"], message_id=message_id, state=state,
        observed_at=observed, now_at=int(time.time()))
    return result.get("state") == "delivered" and not result.get("held")


async def _delivery_row(directus: DirectusService, episode: str, stage: int,
                        recipient_id: str) -> tuple[str, dict[str, Any] | None]:
    key = build_delivery_key(email_type=TEAM_WARNING_TYPE, campaign_key=episode,
        recipient_kind="directus_user", recipient_id=recipient_id, stage=f"week-{stage}")
    delivery_id = build_delivery_id(key)
    rows = await directus.get_items("email_deliveries", params={
        "filter[id][_eq]": delivery_id,
        "fields": "id,status,metadata,lang,recipient_hash,provider_message_id,provider_delivery_state,processing_started_at",
        "limit": 1,
    }, admin_required=True, no_cache=True, raise_on_error=True)
    if not isinstance(rows, list) or len(rows) > 1:
        raise RuntimeError("Team warning delivery lookup is incomplete")
    return delivery_id, rows[0] if rows else None


async def _deliver_warning(team_hash: str, warning: dict[str, Any], *,
                           directus: DirectusService, encryption: EncryptionService,
                           email_service: EmailTemplateService,
                           orchestration: SubChatOrchestrationService,
                           cache: CacheService) -> bool:
    episode, stage = str(warning["episode_id"]), int(warning["warning_stage"])
    expected = warning.get("recipient_hashes")
    selection_hash, units = warning.get("unit_selection_hash"), warning.get("units")
    if (not isinstance(expected, list) or expected != sorted(set(expected))
            or not isinstance(selection_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", selection_hash)
            or not isinstance(units, list) or not 1 <= len(units) <= 100):
        raise RuntimeError("Frozen Team warning scope is unavailable")
    # Resolve every current owner/admin before submitting any email. This
    # includes legacy and non-passkey identities; an unavailable one holds all.
    try:
        recipients = await _recipients(orchestration, directus, encryption, team_hash, expected)
    except RuntimeError:
        await _operation(orchestration, "set_team_storage_notice_hold", team_hash,
            episode_id=episode, reason="recipient_contact_unavailable")
        return False
    teams = await directus.get_items("teams", params={
        "filter[hashed_team_id][_eq]": team_hash, "filter[status][_eq]": "active",
        "fields": "team_id,slug", "limit": 1,
    }, admin_required=True, no_cache=True, raise_on_error=True)
    if not isinstance(teams, list) or len(teams) != 1:
        raise RuntimeError("Team warning owner is unavailable")
    now_at = int(time.time())
    first_at = int(warning.get("first_warning_at") or now_at)
    earliest = max(first_at + 4 * WARNING_INTERVAL_SECONDS, now_at + WARNING_INTERVAL_SECONDS)
    deadline_date = (datetime.fromtimestamp(earliest, tz=timezone.utc).date() + timedelta(days=1)).isoformat()
    base_url = os.getenv("WEBAPP_URL", "https://openmates.org").rstrip("/")
    context = {
        "team_slug": teams[0].get("slug") or teams[0]["team_id"],
        "warning_stage": stage,
        "storage_gb": round(int(warning["measured_bytes"]) / FREE_BYTES, 2),
        "credits_needed": int(warning["credits_due"]),
        "outstanding_credits": int(warning["outstanding_credits"]),
        "deadline_date": deadline_date,
        "team_url": f"{base_url}/#settings/teams/{teams[0]['team_id']}",
        "unit_selection_hash": selection_hash,
        "affected_units": [{
            "unit_id": unit["unit_id"], "kind": unit["kind"], "resource_id": unit["resource_id"],
            "oldest_date": datetime.fromtimestamp(int(unit["oldest_at"]), tz=timezone.utc).date().isoformat(),
            "size_mib": round(int(unit["bytes"]) / (1024 * 1024), 2),
        } for unit in units],
        "darkmode": False,
    }
    all_delivered = True
    for recipient in recipients:
        delivery_id, existing = await _delivery_row(directus, episode, stage, recipient["user_id"])
        if existing and existing.get("status") != "sent":
            metadata = existing.get("metadata")
            if not isinstance(metadata, dict) or metadata.get("template") != "team-storage-billing-failed" or metadata.get("context", {}).get("unit_selection_hash") != selection_hash:
                raise RuntimeError("Team warning retry payload changed")
            send_context, language = metadata["context"], existing.get("lang") or "en"
        else:
            send_context, language = context, recipient["language"]
        if not existing or existing.get("status") != "sent":
            async def still_eligible() -> bool:
                current = await _operation(orchestration, "claim_team_storage_warning", team_hash,
                    now_at=int(time.time()))
                return bool(current.get("due") and current.get("episode_id") == episode
                    and int(current.get("warning_stage", 0)) == stage
                    and current.get("recipient_hashes") == expected)
            sent, _ = await send_email_once(
                directus=directus, email_template_service=email_service,
                email_type=TEAM_WARNING_TYPE, campaign_key=episode,
                recipient_kind="directus_user", recipient_id=recipient["user_id"],
                recipient_email=recipient["email"], template="team-storage-billing-failed",
                context=send_context, stage=f"week-{stage}", lang=language,
                metadata={"oldest_period_id": warning["oldest_period_id"],
                          "template": "team-storage-billing-failed", "context": send_context},
                retry_cache=cache, before_send=still_eligible,
            )
            if not sent:
                _, held_row = await _delivery_row(directus, episode, stage, recipient["user_id"])
                if held_row:
                    await _receipt(orchestration, email_service, team_hash, episode, stage, recipient, held_row)
                all_delivered = False
                continue
        _, row = await _delivery_row(directus, episode, stage, recipient["user_id"])
        if not row or not await _receipt(orchestration, email_service, team_hash, episode, stage, recipient, row):
            all_delivered = False
    if not all_delivered:
        return False
    await _operation(orchestration, "acknowledge_team_storage_warning", team_hash,
        episode_id=episode, warning_stage=stage, recipient_hashes=expected, now_at=int(time.time()))
    return True


async def _recheck_four(team_hash: str, episode: str, *, directus: DirectusService,
                        encryption: EncryptionService, email_service: EmailTemplateService,
                        orchestration: SubChatOrchestrationService) -> bool:
    resolved = await _operation(orchestration, "list_team_storage_recipients", team_hash)
    rows = resolved.get("recipients")
    if not isinstance(rows, list) or not rows:
        return False
    try:
        recipients = await _recipients(orchestration, directus, encryption, team_hash,
                                       sorted(row["user_hash"] for row in rows))
    except RuntimeError:
        await _operation(orchestration, "set_team_storage_notice_hold", team_hash,
            episode_id=episode, reason="recipient_contact_unavailable")
        return False
    for stage in range(1, 5):
        for recipient in recipients:
            _, delivery = await _delivery_row(directus, episode, stage, recipient["user_id"])
            if delivery and delivery.get("recipient_hash") != recipient["email_hash"]:
                await _operation(orchestration, "set_team_storage_notice_hold", team_hash,
                    episode_id=episode, reason="recipient_contact_unavailable")
                return False
            if not delivery or not await _receipt(orchestration, email_service, team_hash,
                                                  episode, stage, recipient, delivery):
                return False
    await _operation(orchestration, "set_team_storage_notice_hold", team_hash,
        episode_id=episode, reason=None)
    return True


async def _settle_team(team_hash: str, quote: Any | None, *, period_start_at: int,
                       directus: DirectusService, orchestration: SubChatOrchestrationService,
                       encryption: EncryptionService, email_service: EmailTemplateService,
                       cache: CacheService, final_check: bool = False) -> dict[str, int]:
    result = {"billed": 0, "credits": 0, "insufficient": 0, "warnings_delivered": 0,
              "expiry_due": 0, "expiry_applied": 0, "periods_waived": 0}
    if quote is not None:
        if (not quote.complete or quote.owner_kind != "team" or quote.owner_id != team_hash
                or quote.policy_version != TEAM_POLICY or quote.source_version != TEAM_SOURCE
                or not isinstance(quote.total_bytes, int)):
            raise StorageUsageIncompleteError("team_storage_quote_invalid")
        credits = _compute_billable_credits(quote.total_bytes)
        if credits:
            await _operation(orchestration, "freeze_team_storage_period", team_hash,
                period_start_at=period_start_at, measured_bytes=quote.total_bytes,
                credits_due=credits, charge_id=f"team-storage:{team_hash}:{period_start_at}",
                free_bytes=FREE_BYTES, credits_per_gib=3, policy_version=TEAM_POLICY,
                source_version=TEAM_SOURCE, category_bytes=quote.categories)
    while True:
        debt = await _operation(orchestration, "list_team_storage_debt", team_hash)
        periods = debt.get("periods")
        if not isinstance(periods, list) or debt.get("has_more") and not periods:
            raise RuntimeError("Team storage debt lookup is incomplete")
        if not periods:
            break
        period = periods[0]
        try:
            charged = await _operation(orchestration, "commit_team_storage_charge", team_hash,
                period_id=period["id"], expected_version=await _account_version(directus, team_hash),
                occurred_at=int(time.time()))
        except SubChatOrchestrationProtocolError as exc:
            if exc.status_code == 402 and exc.code == "insufficient_team_credits":
                result["insufficient"] = 1
                break
            if exc.code == "stale_team_credit_balance":
                # A top-up or member charge won the CAS. The next scheduled
                # pass re-reads; no warning or expiry is admitted on a race.
                raise RuntimeError("Team storage balance changed during settlement") from exc
            raise
        if charged.get("state") != "paid" or int(charged.get("charged_credits", -1)) != int(period["credits_due"]):
            raise RuntimeError("Team storage charge not committed")
        result["billed"] += int(not charged.get("idempotent"))
        result["credits"] += int(period["credits_due"]) if not charged.get("idempotent") else 0
    if result["insufficient"]:
        warning = await _operation(orchestration, "claim_team_storage_warning", team_hash,
            now_at=int(time.time()))
        if warning.get("due") and not final_check:
            selection = await _operation(orchestration, "freeze_team_storage_warning_units", team_hash,
                episode_id=warning["episode_id"], now_at=int(time.time()))
            if selection.get("frozen") and not selection.get("held"):
                result["warnings_delivered"] = int(await _deliver_warning(team_hash,
                    {**warning, **selection}, directus=directus, encryption=encryption,
                    email_service=email_service, orchestration=orchestration, cache=cache))
        if warning.get("reason") == "four_delivered":
            if not await _recheck_four(team_hash, warning["episode_id"],
                                      directus=directus, encryption=encryption,
                                      email_service=email_service, orchestration=orchestration):
                return result
        expiry = await _operation(orchestration, "inspect_team_storage_expiry", team_hash,
            now_at=int(time.time()))
        result["expiry_due"] = int(bool(expiry.get("due")))
        if result["expiry_due"] and not final_check and os.getenv(TEAM_EXPIRY_SWITCH, "0") == "1":
            final = await _settle_team(team_hash, None, period_start_at=period_start_at,
                directus=directus, orchestration=orchestration, encryption=encryption,
                email_service=email_service, cache=cache, final_check=True)
            if final["insufficient"] and final["expiry_due"]:
                from backend.shared.python_utils.object_storage_regions import parse_storage_regions
                applied = await _operation(orchestration, "apply_team_storage_expiry", team_hash,
                    episode_id=expiry["episode_id"], expected_version=await _account_version(directus, team_hash),
                    now_at=int(time.time()), regions=list(parse_storage_regions(os.getenv("S3_REGIONS"))))
                result["expiry_applied"] = int(bool(applied.get("applied")))
                result["periods_waived"] = len(applied.get("waived_period_ids") or [])
    return result


async def _iter_team_hashes(directus: DirectusService, *, due_only: bool = False):
    collection = "team_storage_billing_owner_state" if due_only else "teams"
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {"fields": "id,hashed_team_id", "sort": "id", "limit": BATCH_SIZE}
        if due_only:
            params["filter[episode_id][_nnull]"] = True
            params["filter[warning_manual_review_at][_null]"] = True
        else:
            params["filter[status][_eq]"] = "active"
        if cursor is not None:
            params["filter[id][_gt]"] = cursor
        page = await directus.get_items(collection, params=params,
            admin_required=True, no_cache=True, raise_on_error=True)
        if not isinstance(page, list) or len(page) > BATCH_SIZE:
            raise RuntimeError("Team storage owner page is incomplete")
        if not page:
            return
        for row in page:
            team_hash = row.get("hashed_team_id")
            if not isinstance(team_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", team_hash):
                raise RuntimeError("Team storage owner page is invalid")
            yield team_hash
        next_cursor = str(page[-1].get("id") or "")
        if not next_cursor or cursor is not None and next_cursor <= cursor:
            raise RuntimeError("Team storage owner cursor did not advance")
        cursor = next_cursor
        if len(page) < BATCH_SIZE:
            return


async def _run(*, due_only: bool) -> dict[str, Any]:
    if not is_payment_enabled() or os.getenv(TEAM_BILLING_SWITCH, "0") != "1":
        return {"skipped": "team_storage_billing_disabled"}
    secrets = SecretsManager()
    directus = DirectusService()
    cache = CacheService()
    encryption = EncryptionService()
    orchestration = SubChatOrchestrationService(directus)
    metering = StorageUsageMeteringService(directus)
    summary = {"teams_checked": 0, "teams_billed": 0, "credits_charged": 0,
               "warnings_delivered": 0, "teams_expired": 0, "periods_waived": 0,
               "teams_failed": 0}
    try:
        await directus.ensure_auth_token()
        await secrets.initialize()
        email_service = EmailTemplateService(secrets_manager=secrets)
        period_start = _period_start_at()
        async for team_hash in _iter_team_hashes(directus, due_only=due_only):
            try:
                quote = None if due_only else (await metering.quote_team([team_hash]))[team_hash]
                outcome = await _settle_team(team_hash, quote, period_start_at=period_start,
                    directus=directus, orchestration=orchestration, encryption=encryption,
                    email_service=email_service, cache=cache)
                summary["teams_checked"] += 1
                summary["teams_billed"] += outcome["billed"]
                summary["credits_charged"] += outcome["credits"]
                summary["warnings_delivered"] += outcome["warnings_delivered"]
                summary["teams_expired"] += outcome["expiry_applied"]
                summary["periods_waived"] += outcome["periods_waived"]
                summary["teams_failed"] += outcome["insufficient"]
            except Exception:
                summary["teams_failed"] += 1
                logger.exception("[TeamStorageBilling] Team settlement held for %s", team_hash)
        return summary
    finally:
        await cache.close()
        await secrets.aclose()


@app.task(name="app.tasks.team_storage_billing_tasks.charge_team_storage_fees", bind=True,
          max_retries=1, default_retry_delay=120)
def charge_team_storage_fees(self) -> dict[str, Any]:
    del self
    return asyncio.run(_run(due_only=False))


@app.task(name="app.tasks.team_storage_billing_tasks.retry_team_storage_warnings", bind=True,
          max_retries=1, default_retry_delay=120)
def retry_team_storage_warnings(self) -> dict[str, Any]:
    del self
    return asyncio.run(_run(due_only=True))
