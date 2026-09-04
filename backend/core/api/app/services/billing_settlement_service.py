"""
Coordinates cache-first personal billing settlement.

Dragonfly serializes the short read/decrypt/encrypt/commit section per hashed
billing subject. Directus CAS and charge identities remain the durable safety
boundary when the cache or lease is lost.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator

from fastapi import HTTPException

from backend.core.api.app.services.sub_chat_orchestration_service import (
    SubChatOrchestrationProtocolError,
    SubChatOrchestrationService,
)


logger = logging.getLogger(__name__)

BILLING_LOCK_TTL_SECONDS = 30
BILLING_LOCK_WAIT_SECONDS = 5.0
BILLING_LOCK_RETRY_SECONDS = 0.05
MAX_SETTLEMENT_ATTEMPTS = 5
SETTLEMENT_RETRY_DELAYS_SECONDS = (5, 30, 120, 300)

_RENEW_LOCK_SCRIPT = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then "
    "return redis.call('expire', KEYS[1], ARGV[2]) else return 0 end"
)
_RELEASE_LOCK_SCRIPT = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then "
    "return redis.call('del', KEYS[1]) else return 0 end"
)


@dataclass
class BillingSettlementLease:
    acquired: bool
    lock_lost: bool = False


class BillingSettlementLock:
    """Renewable token-safe Dragonfly lease for one hashed billing subject."""

    def __init__(self, cache_service: Any) -> None:
        self._cache = cache_service

    @asynccontextmanager
    async def hold(self, billing_subject: str) -> AsyncIterator[BillingSettlementLease]:
        client = await self._cache.client
        if client is None:
            logger.warning("Billing settlement lock backend unavailable; using durable CAS fallback")
            yield BillingSettlementLease(acquired=False, lock_lost=True)
            return

        key = f"billing:settlement:lock:{billing_subject}"
        token = secrets.token_urlsafe(24)
        deadline = time.monotonic() + BILLING_LOCK_WAIT_SECONDS
        acquired = False
        while time.monotonic() < deadline:
            acquired = bool(await client.set(key, token, nx=True, ex=BILLING_LOCK_TTL_SECONDS))
            if acquired:
                break
            await asyncio.sleep(BILLING_LOCK_RETRY_SECONDS)
        if not acquired:
            raise RuntimeError("billing_settlement_busy")

        lease = BillingSettlementLease(acquired=True)
        stop_renewal = asyncio.Event()

        async def renew() -> None:
            while not stop_renewal.is_set():
                try:
                    await asyncio.wait_for(
                        stop_renewal.wait(),
                        timeout=BILLING_LOCK_TTL_SECONDS / 3,
                    )
                    return
                except TimeoutError:
                    renewed = await client.eval(
                        _RENEW_LOCK_SCRIPT,
                        1,
                        key,
                        token,
                        BILLING_LOCK_TTL_SECONDS,
                    )
                    if not renewed:
                        lease.lock_lost = True
                        return

        renewal_task = asyncio.create_task(renew())
        operation_error: BaseException | None = None
        operation_traceback: Any = None
        try:
            yield lease
        except BaseException as exc:
            operation_error = exc
            operation_traceback = exc.__traceback__
        finally:
            stop_renewal.set()
            renewal_error: BaseException | None = None
            release_error: BaseException | None = None
            try:
                await renewal_task
            except BaseException as exc:
                renewal_error = exc
                lease.lock_lost = True
            try:
                released = await client.eval(_RELEASE_LOCK_SCRIPT, 1, key, token)
                if not released:
                    lease.lock_lost = True
            except BaseException as exc:
                release_error = exc
                lease.lock_lost = True

        if operation_error is not None:
            raise operation_error.with_traceback(operation_traceback)
        if renewal_error is not None:
            raise RuntimeError("billing_settlement_lock_renewal_failed") from renewal_error
        if release_error is not None:
            raise RuntimeError("billing_settlement_lock_release_failed") from release_error


async def process_pending_settlement(
    *,
    outbox_id: str,
    charge_id: str,
    user_id_hash: str,
    directus_service: Any,
    cache_service: Any,
    encryption_service: Any,
    billing_service_factory: Any = None,
) -> dict[str, Any]:
    """Claim and process one durable settlement attempt."""
    orchestration = SubChatOrchestrationService(directus_service)
    claimed = await orchestration.execute(
        "replay_pending_settlement",
        {
            "protocol_version": 1,
            "outbox_id": outbox_id,
            "charge_id": charge_id,
            "hashed_user_id": user_id_hash,
        },
    )
    if claimed["state"] in {"committed", "manual_review"}:
        return claimed
    if not claimed.get("claimed"):
        return {"state": "already_scheduled", "attempts": int(claimed["attempts"])}
    if billing_service_factory is None:
        from backend.core.api.app.services.billing_service import BillingService

        billing_service_factory = BillingService

    attempts = int(claimed["attempts"])
    try:
        plaintext = await encryption_service.decrypt_with_user_key(
            claimed["encrypted_settlement_payload"],
            claimed["vault_key_id"],
        )
        if not plaintext:
            raise ValueError("Settlement payload decryption returned no content")
        payload = json.loads(plaintext)
        if payload.get("idempotency_key") != charge_id:
            raise ValueError("Settlement charge identity does not match encrypted payload")

        result = await billing_service_factory(
            cache_service=cache_service,
            directus_service=directus_service,
            encryption_service=encryption_service,
        ).charge_user_credits(
            user_id=claimed["user_id"],
            credits_to_deduct=payload["credits_to_deduct"],
            user_id_hash=user_id_hash,
            app_id=payload["app_id"],
            skill_id=payload["skill_id"],
            idempotency_key=charge_id,
            usage_details=payload.get("usage_details"),
            api_key_hash=payload.get("api_key_hash"),
            device_hash=payload.get("device_hash"),
            _force_balance_refresh=True,
            _defer_exhausted_conflict=False,
        )
        if result.get("state") != "committed":
            raise RuntimeError("Settlement retry returned a non-committed result")
        return await orchestration.execute(
            "complete_pending_settlement",
            {
                "protocol_version": 1,
                "outbox_id": outbox_id,
                "charge_id": charge_id,
                "hashed_user_id": user_id_hash,
            },
        )
    except HTTPException as exc:
        error_code = str(exc.detail)
        retryable = error_code == "stale_credit_balance" or exc.status_code >= 500
    except SubChatOrchestrationProtocolError as exc:
        error_code = exc.code
        retryable = error_code == "stale_credit_balance" or exc.status_code >= 500
    except Exception as exc:
        error_code = type(exc).__name__[:64]
        retryable = True
        logger.exception(
            "Durable billing settlement attempt failed: charge_id=%s outbox_id=%s",
            charge_id,
            outbox_id,
        )

    if not retryable or attempts >= MAX_SETTLEMENT_ATTEMPTS:
        manual_review = await orchestration.execute(
            "transition_pending_settlement_to_manual_review",
            {
                "protocol_version": 1,
                "outbox_id": outbox_id,
                "charge_id": charge_id,
                "hashed_user_id": user_id_hash,
                "attempts": attempts,
                "retryable_error_code": error_code,
            },
        )
        await cache_service.increment_stat("billing_settlement_manual_review", 1)
        logger.critical(
            "settlement_manual_review: exhausted durable billing retries charge_id=%s outbox_id=%s",
            charge_id,
            outbox_id,
        )
        return manual_review

    return {
        "state": "retry_scheduled",
        "attempts": attempts,
        "countdown": SETTLEMENT_RETRY_DELAYS_SECONDS[attempts - 1],
    }
