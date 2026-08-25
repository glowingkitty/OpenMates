"""Anonymous free usage budget service.

Coordinates official-cloud anonymous free chat budget configuration, public-safe
availability metadata, HMAC-based daily identity caps, and request reservation
accounting. Anonymous callers never receive a credit balance; actual provider
usage is subtracted from shared daily, weekly, and monthly budgets.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import secrets
from contextlib import suppress
from dataclasses import dataclass
from datetime import date, datetime, timezone, timedelta
from typing import Any, Callable, Optional
from uuid import uuid4


ANONYMOUS_BUDGET_COLLECTION = "anonymous_free_usage_budget"
ANONYMOUS_IDENTITY_DAILY_COLLECTION = "anonymous_free_usage_identity_daily"
ANONYMOUS_RESERVATIONS_COLLECTION = "anonymous_free_usage_reservations"
DEFAULT_ANONYMOUS_CTA = "Sign up to keep using OpenMates"
ANONYMOUS_HARD_MAX_MONTHLY_CREDITS = 60_000
ANONYMOUS_HARD_MAX_WEEKLY_CREDITS = 15_000
ANONYMOUS_HARD_MAX_DAILY_CREDITS = 3_000
ANONYMOUS_HARD_MAX_PER_IDENTITY_DAILY_CREDITS = 400
ANONYMOUS_BUDGET_LOCK_KEY = "anonymous_free_usage:budget_lock"
ANONYMOUS_BUDGET_LOCK_TTL_SECONDS = 300
ANONYMOUS_BUDGET_LOCK_RENEW_SECONDS = 30
ANONYMOUS_BUDGET_LOCK_WAIT_SECONDS = 5.0
ANONYMOUS_USAGE_TRANSACTION_PATH = "anonymous-usage-transaction"
ANONYMOUS_RATE_LIMIT_WINDOW_SECONDS = 60
ANONYMOUS_RATE_LIMIT_TTL_SECONDS = 90


class AnonymousUsageTransactionError(RuntimeError):
    def __init__(self, status_code: int, code: str) -> None:
        self.status_code = status_code
        self.code = code
        super().__init__(f"Anonymous usage transaction failed: {code}")


@dataclass(frozen=True)
class AnonymousBudgetStatus:
    enabled: bool
    monthly_budget_credits: int
    daily_hard_cap_percent: int
    daily_hard_cap_credits: int
    weekly_cap_percent: int
    weekly_cap_credits: int
    per_identity_daily_cap_credits: int
    daily_used_credits: int
    weekly_used_credits: int
    monthly_used_credits: int
    monthly_remaining_credits: int
    daily_remaining_credits: int
    weekly_remaining_credits: int
    active: bool
    reason: Optional[str]
    reset_at: str
    updated_at: Optional[str]


@dataclass(frozen=True)
class AnonymousReservationResult:
    accepted: bool
    request_id: str
    reserved_credits: int = 0
    reason: Optional[str] = None


class AnonymousFreeUsageService:
    """Owns anonymous free-usage budget and reservation accounting."""

    _local_lock = asyncio.Lock()

    def __init__(
        self,
        *,
        directus_service: Any,
        cache_service: Any = None,
        hmac_secret: Optional[str] = None,
        require_distributed_lock: bool = False,
        now_provider: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self.directus = directus_service
        self.cache = cache_service
        self.hmac_secret = hmac_secret or os.getenv("ANONYMOUS_FREE_USAGE_HMAC_SECRET") or os.getenv("SECRET_KEY") or "dev-anonymous-free-usage-secret"
        self.require_distributed_lock = require_distributed_lock
        self.now_provider = now_provider or (lambda: datetime.now(timezone.utc))

    async def consume_local_rate_limit(self, anonymous_id: str, *, max_requests: int) -> bool:
        """Atomically enforce a per-minute limit without storing the raw local ID."""
        if max_requests < 1:
            raise ValueError("max_requests must be >= 1")
        client = await _get_cache_client(self.cache)
        if client is None:
            raise RuntimeError("Anonymous local-ID rate limiter is unavailable")
        minute = int(self._now().timestamp()) // ANONYMOUS_RATE_LIMIT_WINDOW_SECONDS
        identity_hash = self._hmac_identity("rate", anonymous_id)
        key = f"anonymous_free_usage:rate:{identity_hash}:{minute}"
        count = await client.incr(key)
        if count == 1:
            expiry_set = await client.expire(key, ANONYMOUS_RATE_LIMIT_TTL_SECONDS)
            if not expiry_set:
                raise RuntimeError("Anonymous local-ID rate-limit expiry could not be set")
        return count <= max_requests

    async def get_budget_status(self) -> AnonymousBudgetStatus:
        if self.require_distributed_lock:
            return self._status_from_row(await self._execute_transaction("get_status", {}))
        async with self._budget_lock():
            await self._release_expired_reservations_locked()
            row = await self._get_current_budget_row_locked()
            return self._status_from_row(row)

    async def get_public_status(
        self,
        *,
        anonymous_id: str | None = None,
        ip_address: str | None = None,
        estimated_credits: int = 10,
    ) -> dict[str, Any]:
        if self.require_distributed_lock:
            status = self._status_from_row(await self._execute_transaction("get_status", {}))
            return await self._public_status_locked(
                status=status,
                anonymous_id=anonymous_id,
                ip_address=ip_address,
                estimated_credits=estimated_credits,
            )
        async with self._budget_lock():
            await self._release_expired_reservations_locked()
            row = await self._get_current_budget_row_locked()
            status = self._status_from_row(row)
            return await self._public_status_locked(
                status=status,
                anonymous_id=anonymous_id,
                ip_address=ip_address,
                estimated_credits=estimated_credits,
            )

    async def _public_status_locked(
        self,
        *,
        status: AnonymousBudgetStatus,
        anonymous_id: str | None,
        ip_address: str | None,
        estimated_credits: int,
    ) -> dict[str, Any]:
        active = status.active
        reason = status.reason
        if active and estimated_credits > 0 and (
            estimated_credits > status.daily_remaining_credits
            or estimated_credits > status.weekly_remaining_credits
            or estimated_credits > status.monthly_remaining_credits
        ):
            active = False
            reason = "budget_exhausted"
        if active and anonymous_id and ip_address and estimated_credits > 0:
            local_hash = self._hmac_identity("local", anonymous_id)
            ip_hash = self._hmac_identity("ip", ip_address)
            if await self._identity_would_exceed(local_hash, estimated_credits, status.per_identity_daily_cap_credits):
                active = False
                reason = "per_identity_exhausted"
            elif await self._identity_would_exceed(ip_hash, estimated_credits, status.per_identity_daily_cap_credits):
                active = False
                reason = "per_identity_exhausted"
        return {
            "active": active,
            "can_send_text": active,
            "reason": reason,
            "reset_at": status.reset_at,
            "cta": DEFAULT_ANONYMOUS_CTA,
        }

    async def save_budget(
        self,
        *,
        enabled: bool,
        monthly_budget_credits: int,
        daily_hard_cap_percent: int,
        weekly_cap_percent: int,
        per_identity_daily_cap_credits: int,
        admin_user_id: Optional[str],
    ) -> AnonymousBudgetStatus:
        if monthly_budget_credits < 0:
            raise ValueError("monthly_budget_credits must be >= 0")
        if monthly_budget_credits > ANONYMOUS_HARD_MAX_MONTHLY_CREDITS:
            raise ValueError(f"monthly_budget_credits must be <= {ANONYMOUS_HARD_MAX_MONTHLY_CREDITS}")
        if daily_hard_cap_percent < 0 or daily_hard_cap_percent > 100:
            raise ValueError("daily_hard_cap_percent must be between 0 and 100")
        if weekly_cap_percent < 0 or weekly_cap_percent > 100:
            raise ValueError("weekly_cap_percent must be between 0 and 100")
        if per_identity_daily_cap_credits < 0:
            raise ValueError("per_identity_daily_cap_credits must be >= 0")
        if per_identity_daily_cap_credits > ANONYMOUS_HARD_MAX_PER_IDENTITY_DAILY_CREDITS:
            raise ValueError(
                "per_identity_daily_cap_credits must be <= "
                f"{ANONYMOUS_HARD_MAX_PER_IDENTITY_DAILY_CREDITS}"
            )
        if enabled and per_identity_daily_cap_credits < 1:
            raise ValueError("per_identity_daily_cap_credits must be >= 1 when enabled")
        derived_daily_cap = monthly_budget_credits * daily_hard_cap_percent // 100
        derived_weekly_cap = monthly_budget_credits * weekly_cap_percent // 100
        if derived_daily_cap > ANONYMOUS_HARD_MAX_DAILY_CREDITS:
            raise ValueError(f"derived daily cap must be <= {ANONYMOUS_HARD_MAX_DAILY_CREDITS}")
        if derived_weekly_cap > ANONYMOUS_HARD_MAX_WEEKLY_CREDITS:
            raise ValueError(f"derived weekly cap must be <= {ANONYMOUS_HARD_MAX_WEEKLY_CREDITS}")

        if self.require_distributed_lock:
            row = await self._execute_transaction(
                "save_budget",
                {
                    "enabled": bool(enabled),
                    "monthly_budget_credits": int(monthly_budget_credits),
                    "daily_hard_cap_percent": int(daily_hard_cap_percent),
                    "weekly_cap_percent": int(weekly_cap_percent),
                    "per_identity_daily_cap_credits": int(per_identity_daily_cap_credits),
                    "updated_by_admin_user_id": admin_user_id,
                },
            )
            return self._status_from_row(row)

        async with self._budget_lock():
            existing = await self._get_current_budget_row_locked()
            now = self._now_iso()
            payload = {
                "enabled": bool(enabled),
                "monthly_budget_credits": int(monthly_budget_credits),
                "daily_hard_cap_percent": int(daily_hard_cap_percent),
                "weekly_cap_percent": int(weekly_cap_percent),
                "per_identity_daily_cap_credits": int(per_identity_daily_cap_credits),
                "daily_used_credits": _safe_nonnegative_int((existing or {}).get("daily_used_credits")),
                "weekly_used_credits": _safe_nonnegative_int((existing or {}).get("weekly_used_credits")),
                "monthly_used_credits": _safe_nonnegative_int((existing or {}).get("monthly_used_credits")),
                "daily_window_date": (existing or {}).get("daily_window_date") or self._today_key(),
                "weekly_window_start": (existing or {}).get("weekly_window_start") or self._week_start_key(),
                "monthly_window_month": (existing or {}).get("monthly_window_month") or self._month_key(),
                "updated_at": now,
                "updated_by_admin_user_id": admin_user_id,
            }

            if existing and existing.get("id"):
                row = await self.directus.update_item(
                    ANONYMOUS_BUDGET_COLLECTION,
                    existing["id"],
                    payload,
                    admin_required=True,
                )
                if not row:
                    raise RuntimeError("Failed to update anonymous free usage budget")
            else:
                success, row = await self.directus.create_item(
                    ANONYMOUS_BUDGET_COLLECTION,
                    {"id": str(uuid4()), "created_at": now, **payload},
                    admin_required=True,
                )
                if not success or not row:
                    raise RuntimeError("Failed to create anonymous free usage budget")

            return self._status_from_row(row)

    async def reserve_budget(
        self,
        *,
        request_id: str,
        anonymous_id: str,
        ip_address: str,
        estimated_credits: int,
    ) -> AnonymousReservationResult:
        if not request_id:
            return AnonymousReservationResult(accepted=False, request_id=request_id, reason="missing_request_id")
        if estimated_credits < 1:
            return AnonymousReservationResult(accepted=False, request_id=request_id, reason="invalid_estimate")

        async with self._budget_lock():
            await self._release_expired_reservations_locked()
            return await self._reserve_hashed_operation_locked(
                request_id=request_id,
                parent_request_id=None,
                charge_id=request_id,
                local_hash=self._hmac_identity("local", anonymous_id),
                ip_hash=self._hmac_identity("ip", ip_address),
                estimated_credits=estimated_credits,
            )

    async def open_request(
        self,
        *,
        request_id: str,
        anonymous_id: str,
        ip_address: str,
    ) -> AnonymousReservationResult:
        """Open a zero-cost request ledger that operations can safely charge."""
        if not request_id or not anonymous_id or not ip_address:
            return AnonymousReservationResult(accepted=False, request_id=request_id, reason="invalid_identity")
        if self.require_distributed_lock:
            try:
                row = await self._execute_transaction(
                    "open_request",
                    {
                        "request_id": request_id,
                        "local_id_hash": self._hmac_identity("local", anonymous_id),
                        "ip_hash": self._hmac_identity("ip", ip_address),
                    },
                )
            except AnonymousUsageTransactionError as exc:
                if exc.code in {"budget_inactive", "budget_not_configured"}:
                    return AnonymousReservationResult(accepted=False, request_id=request_id, reason="inactive")
                if exc.code == "budget_exhausted":
                    return AnonymousReservationResult(accepted=False, request_id=request_id, reason="budget_exhausted")
                raise
            accepted = row.get("status") == "request_open"
            return AnonymousReservationResult(
                accepted=accepted,
                request_id=request_id,
                reason=None if accepted else str(row.get("status") or "request_closed"),
            )
        async with self._budget_lock():
            await self._release_expired_reservations_locked()
            existing = await self._get_reservation(request_id)
            if existing:
                return AnonymousReservationResult(
                    accepted=existing.get("status") == "request_open",
                    request_id=request_id,
                    reason=existing.get("status"),
                )
            row = await self._get_current_budget_row_locked()
            status = self._status_from_row(row)
            if not status.active:
                return AnonymousReservationResult(
                    accepted=False,
                    request_id=request_id,
                    reason=self._public_rejection_reason(status.reason),
                )
            success, created = await self.directus.create_item(
                ANONYMOUS_RESERVATIONS_COLLECTION,
                {
                    "request_id": request_id,
                    "parent_request_id": None,
                    "charge_id": None,
                    "local_id_hash": self._hmac_identity("local", anonymous_id),
                    "ip_hash": self._hmac_identity("ip", ip_address),
                    "reserved_credits": 0,
                    "finalized_credits": 0,
                    "status": "request_open",
                    "created_at": self._now_iso(),
                    "updated_at": self._now_iso(),
                    "expires_at": self._future_iso(minutes=120),
                },
                admin_required=True,
            )
            if not success or not created:
                raise RuntimeError("Failed to open anonymous usage request")
            return AnonymousReservationResult(accepted=True, request_id=request_id)

    async def reserve_operation(
        self,
        *,
        parent_request_id: str,
        operation_id: str,
        charge_id: str,
        quoted_credits: int,
    ) -> AnonymousReservationResult:
        if quoted_credits < 1:
            return AnonymousReservationResult(accepted=False, request_id=operation_id, reason="invalid_estimate")
        if self.require_distributed_lock:
            try:
                row = await self._execute_transaction(
                    "reserve_operation",
                    {
                        "parent_request_id": parent_request_id,
                        "operation_id": operation_id,
                        "charge_id": charge_id,
                        "quoted_credits": int(quoted_credits),
                    },
                )
            except AnonymousUsageTransactionError as exc:
                reason_by_code = {
                    "budget_inactive": "inactive",
                    "budget_not_configured": "inactive",
                    "budget_exhausted": "budget_exhausted",
                    "identity_budget_exhausted": "per_identity_exhausted",
                    "request_closed": "request_closed",
                }
                if exc.code in reason_by_code:
                    return AnonymousReservationResult(
                        accepted=False,
                        request_id=operation_id,
                        reason=reason_by_code[exc.code],
                    )
                raise
            accepted = row.get("status") in {"reserved", "finalized"}
            return AnonymousReservationResult(
                accepted=accepted,
                request_id=operation_id,
                reserved_credits=_safe_nonnegative_int(row.get("reserved_credits")),
                reason=None if accepted else str(row.get("status") or "request_closed"),
            )
        async with self._budget_lock():
            await self._release_expired_reservations_locked()
            parent = await self._get_reservation(parent_request_id)
            if not parent or parent.get("status") != "request_open":
                return AnonymousReservationResult(accepted=False, request_id=operation_id, reason="request_closed")
            return await self._reserve_hashed_operation_locked(
                request_id=operation_id,
                parent_request_id=parent_request_id,
                charge_id=charge_id,
                local_hash=str(parent.get("local_id_hash") or ""),
                ip_hash=str(parent.get("ip_hash") or ""),
                estimated_credits=quoted_credits,
            )

    async def _reserve_hashed_operation_locked(
        self,
        *,
        request_id: str,
        parent_request_id: str | None,
        charge_id: str,
        local_hash: str,
        ip_hash: str,
        estimated_credits: int,
    ) -> AnonymousReservationResult:
        existing = await self._get_reservation(request_id)
        if existing:
            return AnonymousReservationResult(
                accepted=existing.get("status") in {"reserved", "finalized"},
                request_id=request_id,
                reserved_credits=_safe_nonnegative_int(existing.get("reserved_credits")),
                reason=existing.get("status"),
            )
        if not local_hash or not ip_hash:
            return AnonymousReservationResult(accepted=False, request_id=request_id, reason="invalid_identity")

        row = await self._get_current_budget_row_locked()
        status = self._status_from_row(row)
        if not status.active:
            return AnonymousReservationResult(
                accepted=False,
                request_id=request_id,
                reason=self._public_rejection_reason(status.reason),
            )
        if (
            estimated_credits > status.daily_remaining_credits
            or estimated_credits > status.weekly_remaining_credits
            or estimated_credits > status.monthly_remaining_credits
        ):
            return AnonymousReservationResult(accepted=False, request_id=request_id, reason="budget_exhausted")
        if await self._identity_would_exceed(local_hash, estimated_credits, status.per_identity_daily_cap_credits):
            return AnonymousReservationResult(accepted=False, request_id=request_id, reason="per_identity_exhausted")
        if await self._identity_would_exceed(ip_hash, estimated_credits, status.per_identity_daily_cap_credits):
            return AnonymousReservationResult(accepted=False, request_id=request_id, reason="per_identity_exhausted")

        await self._increment_budget_usage(estimated_credits)
        await self._increment_identity_usage(local_hash, estimated_credits)
        if ip_hash != local_hash:
            await self._increment_identity_usage(ip_hash, estimated_credits)
        try:
            success, created = await self.directus.create_item(
                ANONYMOUS_RESERVATIONS_COLLECTION,
                {
                    "request_id": request_id,
                    "parent_request_id": parent_request_id,
                    "charge_id": charge_id,
                    "local_id_hash": local_hash,
                    "ip_hash": ip_hash,
                    "reserved_credits": int(estimated_credits),
                    "finalized_credits": 0,
                    "status": "reserved",
                    "created_at": self._now_iso(),
                    "updated_at": self._now_iso(),
                    "expires_at": self._future_iso(minutes=60),
                },
                admin_required=True,
            )
            if not success or not created:
                raise RuntimeError("Failed to create anonymous free usage reservation")
        except Exception:
            await self._increment_budget_usage(-estimated_credits)
            await self._increment_identity_usage(local_hash, -estimated_credits)
            if ip_hash != local_hash:
                await self._increment_identity_usage(ip_hash, -estimated_credits)
            raise

        return AnonymousReservationResult(
            accepted=True,
            request_id=request_id,
            reserved_credits=int(estimated_credits),
        )

    async def finalize_reservation(self, request_id: str, *, actual_credits: int) -> None:
        await self.finalize_charge(request_id, actual_credits=actual_credits)

    async def finalize_charge(self, charge_id: str, *, actual_credits: int) -> None:
        if actual_credits < 0:
            raise ValueError("actual_credits must be >= 0")
        if self.require_distributed_lock:
            try:
                await self._execute_transaction(
                    "finalize_charge",
                    {"charge_id": charge_id, "actual_credits": int(actual_credits)},
                )
            except AnonymousUsageTransactionError as exc:
                if exc.code == "reservation_not_found":
                    raise ValueError("reservation not found") from exc
                if exc.code == "actual_exceeds_quote":
                    raise ValueError("actual credits exceed reserved quote") from exc
                raise
            return
        async with self._budget_lock():
            rows = await self._get_charge_reservations(charge_id)
            if not rows:
                row = await self._get_reservation(charge_id)
                rows = [row] if row else []
            if not rows:
                raise ValueError("reservation not found")

            finalized_total = sum(
                _safe_nonnegative_int(row.get("finalized_credits"))
                for row in rows
                if row.get("status") == "finalized"
            )
            reserved_rows = [row for row in rows if row.get("status") == "reserved"]
            reserved_total = sum(_safe_nonnegative_int(row.get("reserved_credits")) for row in reserved_rows)
            if actual_credits > finalized_total + reserved_total:
                raise ValueError("actual credits exceed reserved quote")
            if not reserved_rows:
                if actual_credits != finalized_total:
                    raise ValueError("finalized charge does not match existing settlement")
                return

            remaining_actual = max(0, actual_credits - finalized_total)
            for row in reserved_rows:
                reserved = _safe_nonnegative_int(row.get("reserved_credits"))
                row_actual = min(reserved, remaining_actual)
                remaining_actual -= row_actual
                delta = row_actual - reserved
                local_hash = row.get("local_id_hash")
                ip_hash = row.get("ip_hash")
                updated = await self.directus.update_item(
                    ANONYMOUS_RESERVATIONS_COLLECTION,
                    row["id"],
                    {
                        "finalized_credits": row_actual,
                        "status": "finalized",
                        "updated_at": self._now_iso(),
                    },
                    admin_required=True,
                )
                if not updated:
                    raise RuntimeError("Failed to finalize anonymous usage reservation")
                if delta:
                    await self._increment_budget_usage(delta)
                    if local_hash:
                        await self._increment_identity_usage(str(local_hash), delta)
                    if ip_hash and ip_hash != local_hash:
                        await self._increment_identity_usage(str(ip_hash), delta)

    async def release_reservation(self, request_id: str, *, reason: str) -> None:
        if self.require_distributed_lock:
            try:
                await self._execute_transaction(
                    "release_operation",
                    {"operation_id": request_id, "reason": reason},
                )
            except AnonymousUsageTransactionError as exc:
                if exc.code == "reservation_not_found":
                    return
                raise
            return
        async with self._budget_lock():
            row = await self._get_reservation(request_id)
            if not row or row.get("status") != "reserved":
                return
            await self._release_reservation_row_locked(row, reason=reason)

    async def _get_budget_row(self) -> dict[str, Any] | None:
        rows = await self.directus.get_items(
            ANONYMOUS_BUDGET_COLLECTION,
            params={"sort": "-updated_at", "limit": 1},
            no_cache=True,
            admin_required=True,
        )
        return rows[0] if rows else None

    async def _get_current_budget_row_locked(self) -> dict[str, Any] | None:
        row = await self._get_budget_row()
        if not row or not row.get("id"):
            return row
        updates: dict[str, Any] = {}
        if row.get("daily_window_date") and row.get("daily_window_date") != self._today_key():
            updates.update({"daily_used_credits": 0, "daily_window_date": self._today_key()})
        if row.get("weekly_window_start") and row.get("weekly_window_start") != self._week_start_key():
            updates.update({"weekly_used_credits": 0, "weekly_window_start": self._week_start_key()})
        if row.get("monthly_window_month") and row.get("monthly_window_month") != self._month_key():
            updates.update({"monthly_used_credits": 0, "monthly_window_month": self._month_key()})
        legacy_window_updates = {
            "daily_window_date": self._today_key(),
            "weekly_window_start": self._week_start_key(),
            "monthly_window_month": self._month_key(),
        }
        for field, value in legacy_window_updates.items():
            if not row.get(field):
                updates[field] = value
        if not updates:
            return row
        updates["updated_at"] = self._now_iso()
        updated = await self.directus.update_item(
            ANONYMOUS_BUDGET_COLLECTION,
            row["id"],
            updates,
            admin_required=True,
        )
        if not updated:
            raise RuntimeError("Failed to roll anonymous budget windows")
        return updated

    async def _get_reservation(self, request_id: str) -> dict[str, Any] | None:
        rows = await self.directus.get_items(
            ANONYMOUS_RESERVATIONS_COLLECTION,
            params={"filter[request_id][_eq]": request_id, "limit": 1},
            no_cache=True,
            admin_required=True,
        )
        return rows[0] if rows else None

    async def _get_charge_reservations(self, charge_id: str) -> list[dict[str, Any]]:
        return await self.directus.get_items(
            ANONYMOUS_RESERVATIONS_COLLECTION,
            params={"filter[charge_id][_eq]": charge_id, "sort": "created_at", "limit": -1},
            no_cache=True,
            admin_required=True,
        )

    async def _release_expired_reservations_locked(self) -> None:
        rows = await self.directus.get_items(
            ANONYMOUS_RESERVATIONS_COLLECTION,
            params={
                "filter[status][_in]": "reserved,request_open",
                "filter[expires_at][_lt]": self._now_iso(),
                "limit": -1,
            },
            no_cache=True,
            admin_required=True,
        )
        for row in rows:
            if row.get("status") == "reserved":
                await self._release_reservation_row_locked(row, reason="expired", status="expired")
            elif row.get("status") == "request_open":
                updated = await self.directus.update_item(
                    ANONYMOUS_RESERVATIONS_COLLECTION,
                    row["id"],
                    {"status": "expired", "release_reason": "expired", "updated_at": self._now_iso()},
                    admin_required=True,
                )
                if not updated:
                    raise RuntimeError("Failed to expire anonymous request ledger")

    async def _release_reservation_row_locked(
        self,
        row: dict[str, Any],
        *,
        reason: str,
        status: str = "released",
    ) -> None:
        reserved = _safe_nonnegative_int(row.get("reserved_credits"))
        local_hash = row.get("local_id_hash")
        ip_hash = row.get("ip_hash")
        updated = await self.directus.update_item(
            ANONYMOUS_RESERVATIONS_COLLECTION,
            row["id"],
            {"status": status, "release_reason": reason, "updated_at": self._now_iso()},
            admin_required=True,
        )
        if not updated:
            raise RuntimeError("Failed to release anonymous usage reservation")
        if reserved:
            await self._increment_budget_usage(-reserved)
            if local_hash:
                await self._increment_identity_usage(str(local_hash), -reserved)
            if ip_hash and ip_hash != local_hash:
                await self._increment_identity_usage(str(ip_hash), -reserved)

    async def _identity_would_exceed(self, identity_hash: str, estimated_credits: int, cap: int) -> bool:
        if cap <= 0:
            return True
        row = await self._get_identity_row(identity_hash)
        return _safe_nonnegative_int((row or {}).get("used_credits")) + estimated_credits > cap

    async def _increment_budget_usage(self, delta: int) -> None:
        row = await self._get_budget_row()
        if not row or not row.get("id"):
            raise RuntimeError("Anonymous budget row missing")
        updated = await self.directus.update_item(
            ANONYMOUS_BUDGET_COLLECTION,
            row["id"],
            {
                "daily_used_credits": max(0, _safe_nonnegative_int(row.get("daily_used_credits")) + int(delta)),
                "weekly_used_credits": max(0, _safe_nonnegative_int(row.get("weekly_used_credits")) + int(delta)),
                "monthly_used_credits": max(0, _safe_nonnegative_int(row.get("monthly_used_credits")) + int(delta)),
                "updated_at": self._now_iso(),
            },
            admin_required=True,
        )
        if not updated:
            raise RuntimeError("Failed to update anonymous budget usage")

    async def _increment_identity_usage(self, identity_hash: str, delta: int) -> None:
        row = await self._get_identity_row(identity_hash)
        if row:
            updated = await self.directus.update_item(
                ANONYMOUS_IDENTITY_DAILY_COLLECTION,
                row["id"],
                {
                    "used_credits": max(0, _safe_nonnegative_int(row.get("used_credits")) + int(delta)),
                    "updated_at": self._now_iso(),
                },
                admin_required=True,
            )
            if not updated:
                raise RuntimeError("Failed to update anonymous identity usage")
            return
        success, created = await self.directus.create_item(
            ANONYMOUS_IDENTITY_DAILY_COLLECTION,
            {
                "identity_hash": identity_hash,
                "used_credits": max(0, int(delta)),
                "window_date": self._today_key(),
                "created_at": self._now_iso(),
                "updated_at": self._now_iso(),
            },
            admin_required=True,
        )
        if not success or not created:
            raise RuntimeError("Failed to create anonymous identity usage")

    async def _get_identity_row(self, identity_hash: str) -> dict[str, Any] | None:
        rows = await self.directus.get_items(
            ANONYMOUS_IDENTITY_DAILY_COLLECTION,
            params={"filter[identity_hash][_eq]": identity_hash, "filter[window_date][_eq]": self._today_key(), "limit": 1},
            no_cache=True,
            admin_required=True,
        )
        return rows[0] if rows else None

    def _hmac_identity(self, prefix: str, value: str) -> str:
        msg = f"{prefix}:{value or ''}".encode("utf-8")
        return hmac.new(self.hmac_secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()

    def _status_from_row(self, row: dict[str, Any] | None) -> AnonymousBudgetStatus:
        row = row or {}
        monthly = min(_safe_nonnegative_int(row.get("monthly_budget_credits")), ANONYMOUS_HARD_MAX_MONTHLY_CREDITS)
        daily_percent = min(_safe_nonnegative_int(row.get("daily_hard_cap_percent")), 100)
        weekly_percent = min(_safe_nonnegative_int(row.get("weekly_cap_percent")), 100)
        daily_cap = min(monthly * daily_percent // 100, ANONYMOUS_HARD_MAX_DAILY_CREDITS)
        weekly_cap = min(monthly * weekly_percent // 100, ANONYMOUS_HARD_MAX_WEEKLY_CREDITS)
        daily_used = _safe_nonnegative_int(row.get("daily_used_credits"))
        weekly_used = _safe_nonnegative_int(row.get("weekly_used_credits"))
        monthly_used = _safe_nonnegative_int(row.get("monthly_used_credits"))
        per_identity_cap = min(
            _safe_nonnegative_int(row.get("per_identity_daily_cap_credits")),
            ANONYMOUS_HARD_MAX_PER_IDENTITY_DAILY_CREDITS,
        )
        monthly_remaining = max(0, monthly - monthly_used)
        daily_remaining = max(0, daily_cap - daily_used)
        weekly_remaining = max(0, weekly_cap - weekly_used)
        enabled = bool(row.get("enabled", False))
        reason = None
        if not enabled:
            reason = "inactive"
        elif per_identity_cap < 1:
            reason = "per_identity_exhausted"
        elif daily_remaining < 1:
            reason = "daily_exhausted"
        elif weekly_remaining < 1:
            reason = "weekly_exhausted"
        elif monthly_remaining < 1:
            reason = "monthly_exhausted"
        return AnonymousBudgetStatus(
            enabled=enabled,
            monthly_budget_credits=monthly,
            daily_hard_cap_percent=daily_percent,
            daily_hard_cap_credits=daily_cap,
            weekly_cap_percent=weekly_percent,
            weekly_cap_credits=weekly_cap,
            per_identity_daily_cap_credits=per_identity_cap,
            daily_used_credits=daily_used,
            weekly_used_credits=weekly_used,
            monthly_used_credits=monthly_used,
            monthly_remaining_credits=monthly_remaining,
            daily_remaining_credits=daily_remaining,
            weekly_remaining_credits=weekly_remaining,
            active=reason is None,
            reason=reason,
            reset_at=self._reset_at(reason),
            updated_at=row.get("updated_at"),
        )

    def _public_rejection_reason(self, reason: str | None) -> str:
        if reason in {"daily_exhausted", "weekly_exhausted", "monthly_exhausted"}:
            return "budget_exhausted"
        return reason or "inactive"

    def _now(self) -> datetime:
        now = self.now_provider()
        return now if now.tzinfo else now.replace(tzinfo=timezone.utc)

    def _now_iso(self) -> str:
        return self._now().isoformat()

    def _future_iso(self, *, minutes: int) -> str:
        return (self._now() + timedelta(minutes=minutes)).isoformat()

    def _today_key(self) -> str:
        return self._now().strftime("%Y-%m-%d")

    def _week_start_key(self) -> str:
        current = self._now().date()
        return (current - timedelta(days=current.weekday())).isoformat()

    def _month_key(self) -> str:
        return self._now().strftime("%Y-%m")

    def _reset_at(self, reason: str | None) -> str:
        now = self._now()
        if reason == "monthly_exhausted":
            if now.month == 12:
                target = date(now.year + 1, 1, 1)
            else:
                target = date(now.year, now.month + 1, 1)
        elif reason == "weekly_exhausted":
            target = now.date() + timedelta(days=7 - now.weekday())
        else:
            target = now.date() + timedelta(days=1)
        return datetime(target.year, target.month, target.day, tzinfo=timezone.utc).isoformat()

    def _budget_lock(self) -> "_AnonymousBudgetLock":
        return _AnonymousBudgetLock(
            cache_service=self.cache,
            local_lock=self._local_lock,
            require_distributed_lock=self.require_distributed_lock,
        )

    async def _execute_transaction(self, operation: str, data: dict[str, Any]) -> dict[str, Any]:
        internal_token = os.getenv("INTERNAL_API_SHARED_TOKEN")
        if not internal_token:
            raise RuntimeError("INTERNAL_API_SHARED_TOKEN is required for anonymous usage transactions")
        response = await self.directus._make_api_request(
            "POST",
            f"{self.directus.base_url.rstrip('/')}/{ANONYMOUS_USAGE_TRANSACTION_PATH}",
            headers={"X-Internal-Service-Token": internal_token},
            json={"operation": operation, "data": {"protocol_version": 1, **data}},
        )
        if response is None:
            raise RuntimeError("Anonymous usage transaction returned no response")
        try:
            payload = response.json()
        except (TypeError, ValueError) as exc:
            raise RuntimeError("Anonymous usage transaction returned malformed JSON") from exc
        if response.status_code != 200:
            error = payload.get("error") if isinstance(payload, dict) else None
            code = error.get("code") if isinstance(error, dict) else None
            raise AnonymousUsageTransactionError(
                response.status_code,
                code if isinstance(code, str) and code else "transaction_failed",
            )
        result = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(result, dict):
            raise RuntimeError("Anonymous usage transaction returned malformed success data")
        return result


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _safe_nonnegative_int(value: Any) -> int:
    return max(0, _safe_int(value))


class _AnonymousBudgetLock:
    """Serialize budget mutations across API processes and fail closed when required."""

    def __init__(self, *, cache_service: Any, local_lock: asyncio.Lock, require_distributed_lock: bool) -> None:
        self.cache_service = cache_service
        self.local_lock = local_lock
        self.require_distributed_lock = require_distributed_lock
        self.redis_client: Any = None
        self.token = secrets.token_hex(16)
        self.acquired_redis = False
        self.renewal_task: asyncio.Task[None] | None = None
        self.lock_lost = False

    async def __aenter__(self) -> None:
        await self.local_lock.acquire()
        try:
            self.redis_client = await _get_cache_client(self.cache_service)
            if not self.redis_client:
                if self.require_distributed_lock:
                    raise RuntimeError("Anonymous budget distributed lock is unavailable")
                return
            loop = asyncio.get_running_loop()
            deadline = loop.time() + ANONYMOUS_BUDGET_LOCK_WAIT_SECONDS
            while loop.time() < deadline:
                acquired = await self.redis_client.set(
                    ANONYMOUS_BUDGET_LOCK_KEY,
                    self.token,
                    nx=True,
                    ex=ANONYMOUS_BUDGET_LOCK_TTL_SECONDS,
                )
                if acquired:
                    self.acquired_redis = True
                    self.renewal_task = asyncio.create_task(self._renew_lease())
                    return
                await asyncio.sleep(0.05)
            raise RuntimeError("Timed out acquiring anonymous budget distributed lock")
        except Exception:
            self.local_lock.release()
            raise

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        try:
            if self.renewal_task:
                self.renewal_task.cancel()
                with suppress(asyncio.CancelledError):
                    await self.renewal_task
            if self.redis_client and self.acquired_redis:
                release_script = """
                if redis.call('GET', KEYS[1]) == ARGV[1] then
                    return redis.call('DEL', KEYS[1])
                end
                return 0
                """
                await self.redis_client.eval(release_script, 1, ANONYMOUS_BUDGET_LOCK_KEY, self.token)
        finally:
            self.local_lock.release()
        if self.lock_lost and exc_type is None:
            raise RuntimeError("Anonymous budget distributed lock was lost")

    async def _renew_lease(self) -> None:
        renew_script = """
        if redis.call('GET', KEYS[1]) == ARGV[1] then
            return redis.call('EXPIRE', KEYS[1], ARGV[2])
        end
        return 0
        """
        while True:
            await asyncio.sleep(ANONYMOUS_BUDGET_LOCK_RENEW_SECONDS)
            try:
                renewed = await self.redis_client.eval(
                    renew_script,
                    1,
                    ANONYMOUS_BUDGET_LOCK_KEY,
                    self.token,
                    ANONYMOUS_BUDGET_LOCK_TTL_SECONDS,
                )
            except Exception:
                self.lock_lost = True
                return
            if not renewed:
                self.lock_lost = True
                return


async def _get_cache_client(cache_service: Any) -> Any:
    if cache_service is None:
        return None
    client = getattr(cache_service, "client", None)
    if client is None:
        return None
    return await client if hasattr(client, "__await__") else client
