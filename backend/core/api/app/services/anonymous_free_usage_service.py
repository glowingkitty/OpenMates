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
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Optional
from uuid import uuid4


ANONYMOUS_BUDGET_COLLECTION = "anonymous_free_usage_budget"
ANONYMOUS_IDENTITY_DAILY_COLLECTION = "anonymous_free_usage_identity_daily"
ANONYMOUS_RESERVATIONS_COLLECTION = "anonymous_free_usage_reservations"
DEFAULT_ANONYMOUS_CTA = "Sign up to keep using OpenMates"


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
        hmac_secret: Optional[str] = None,
    ) -> None:
        self.directus = directus_service
        self.hmac_secret = hmac_secret or os.getenv("ANONYMOUS_FREE_USAGE_HMAC_SECRET") or os.getenv("SECRET_KEY") or "dev-anonymous-free-usage-secret"

    async def get_budget_status(self) -> AnonymousBudgetStatus:
        row = await self._get_budget_row()
        return self._status_from_row(row)

    async def get_public_status(
        self,
        *,
        anonymous_id: str | None = None,
        ip_address: str | None = None,
        estimated_credits: int = 10,
    ) -> dict[str, Any]:
        status = await self.get_budget_status()
        active = status.active
        reason = status.reason
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
        if daily_hard_cap_percent < 0 or daily_hard_cap_percent > 100:
            raise ValueError("daily_hard_cap_percent must be between 0 and 100")
        if weekly_cap_percent < 0 or weekly_cap_percent > 100:
            raise ValueError("weekly_cap_percent must be between 0 and 100")
        if per_identity_daily_cap_credits < 0:
            raise ValueError("per_identity_daily_cap_credits must be >= 0")
        if enabled and per_identity_daily_cap_credits < 1:
            raise ValueError("per_identity_daily_cap_credits must be >= 1 when enabled")

        existing = await self._get_budget_row()
        now = _now_iso()
        payload = {
            "enabled": bool(enabled),
            "monthly_budget_credits": int(monthly_budget_credits),
            "daily_hard_cap_percent": int(daily_hard_cap_percent),
            "weekly_cap_percent": int(weekly_cap_percent),
            "per_identity_daily_cap_credits": int(per_identity_daily_cap_credits),
            "daily_used_credits": _safe_int((existing or {}).get("daily_used_credits")),
            "weekly_used_credits": _safe_int((existing or {}).get("weekly_used_credits")),
            "monthly_used_credits": _safe_int((existing or {}).get("monthly_used_credits")),
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
            if not success:
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

        async with self._local_lock:
            existing = await self._get_reservation(request_id)
            if existing:
                return AnonymousReservationResult(
                    accepted=existing.get("status") in {"reserved", "finalized"},
                    request_id=request_id,
                    reserved_credits=_safe_int(existing.get("reserved_credits")),
                    reason=existing.get("status"),
                )

            status = await self.get_budget_status()
            if not status.enabled or not status.active:
                reason = status.reason or "inactive"
                if reason in {"daily_exhausted", "weekly_exhausted", "monthly_exhausted"}:
                    reason = "budget_exhausted"
                return AnonymousReservationResult(accepted=False, request_id=request_id, reason=reason)
            if (
                estimated_credits > status.daily_remaining_credits
                or estimated_credits > status.weekly_remaining_credits
                or estimated_credits > status.monthly_remaining_credits
            ):
                return AnonymousReservationResult(accepted=False, request_id=request_id, reason="budget_exhausted")

            local_hash = self._hmac_identity("local", anonymous_id)
            ip_hash = self._hmac_identity("ip", ip_address)
            if await self._identity_would_exceed(local_hash, estimated_credits, status.per_identity_daily_cap_credits):
                return AnonymousReservationResult(accepted=False, request_id=request_id, reason="per_identity_exhausted")
            if await self._identity_would_exceed(ip_hash, estimated_credits, status.per_identity_daily_cap_credits):
                return AnonymousReservationResult(accepted=False, request_id=request_id, reason="per_identity_exhausted")

            await self._increment_budget_usage(estimated_credits)
            await self._increment_identity_usage(local_hash, estimated_credits)
            if ip_hash != local_hash:
                await self._increment_identity_usage(ip_hash, estimated_credits)

            success, _row = await self.directus.create_item(
                ANONYMOUS_RESERVATIONS_COLLECTION,
                {
                    "request_id": request_id,
                    "local_id_hash": local_hash,
                    "ip_hash": ip_hash,
                    "reserved_credits": int(estimated_credits),
                    "finalized_credits": 0,
                    "status": "reserved",
                    "created_at": _now_iso(),
                    "expires_at": _future_iso(minutes=15),
                },
                admin_required=True,
            )
            if not success:
                await self._increment_budget_usage(-estimated_credits)
                await self._increment_identity_usage(local_hash, -estimated_credits)
                if ip_hash != local_hash:
                    await self._increment_identity_usage(ip_hash, -estimated_credits)
                raise RuntimeError("Failed to create anonymous free usage reservation")

            return AnonymousReservationResult(
                accepted=True,
                request_id=request_id,
                reserved_credits=int(estimated_credits),
            )

    async def finalize_reservation(self, request_id: str, *, actual_credits: int) -> None:
        if actual_credits < 0:
            raise ValueError("actual_credits must be >= 0")
        async with self._local_lock:
            row = await self._get_reservation(request_id)
            if not row:
                raise ValueError("reservation not found")
            if row.get("status") == "finalized":
                return
            reserved = _safe_int(row.get("reserved_credits"))
            delta = int(actual_credits) - reserved
            local_hash = row.get("local_id_hash")
            ip_hash = row.get("ip_hash")
            await self._increment_budget_usage(delta)
            if local_hash:
                await self._increment_identity_usage(local_hash, delta)
            if ip_hash and ip_hash != local_hash:
                await self._increment_identity_usage(ip_hash, delta)
            await self.directus.update_item(
                ANONYMOUS_RESERVATIONS_COLLECTION,
                row["id"],
                {"finalized_credits": int(actual_credits), "status": "finalized", "updated_at": _now_iso()},
                admin_required=True,
            )

    async def release_reservation(self, request_id: str, *, reason: str) -> None:
        async with self._local_lock:
            row = await self._get_reservation(request_id)
            if not row or row.get("status") != "reserved":
                return
            reserved = _safe_int(row.get("reserved_credits"))
            local_hash = row.get("local_id_hash")
            ip_hash = row.get("ip_hash")
            await self._increment_budget_usage(-reserved)
            if local_hash:
                await self._increment_identity_usage(local_hash, -reserved)
            if ip_hash and ip_hash != local_hash:
                await self._increment_identity_usage(ip_hash, -reserved)
            await self.directus.update_item(
                ANONYMOUS_RESERVATIONS_COLLECTION,
                row["id"],
                {"status": "released", "release_reason": reason, "updated_at": _now_iso()},
                admin_required=True,
            )

    async def _get_budget_row(self) -> dict[str, Any] | None:
        rows = await self.directus.get_items(
            ANONYMOUS_BUDGET_COLLECTION,
            params={"sort": "-updated_at", "limit": 1},
            no_cache=True,
            admin_required=True,
        )
        return rows[0] if rows else None

    async def _get_reservation(self, request_id: str) -> dict[str, Any] | None:
        rows = await self.directus.get_items(
            ANONYMOUS_RESERVATIONS_COLLECTION,
            params={"filter[request_id][_eq]": request_id, "limit": 1},
            no_cache=True,
            admin_required=True,
        )
        return rows[0] if rows else None

    async def _identity_would_exceed(self, identity_hash: str, estimated_credits: int, cap: int) -> bool:
        if cap <= 0:
            return True
        row = await self._get_identity_row(identity_hash)
        return _safe_int((row or {}).get("used_credits")) + estimated_credits > cap

    async def _increment_budget_usage(self, delta: int) -> None:
        row = await self._get_budget_row()
        if not row or not row.get("id"):
            raise RuntimeError("Anonymous budget row missing")
        await self.directus.update_item(
            ANONYMOUS_BUDGET_COLLECTION,
            row["id"],
            {
                "daily_used_credits": max(0, _safe_int(row.get("daily_used_credits")) + int(delta)),
                "weekly_used_credits": max(0, _safe_int(row.get("weekly_used_credits")) + int(delta)),
                "monthly_used_credits": max(0, _safe_int(row.get("monthly_used_credits")) + int(delta)),
                "updated_at": _now_iso(),
            },
            admin_required=True,
        )

    async def _increment_identity_usage(self, identity_hash: str, delta: int) -> None:
        row = await self._get_identity_row(identity_hash)
        if row:
            await self.directus.update_item(
                ANONYMOUS_IDENTITY_DAILY_COLLECTION,
                row["id"],
                {
                    "used_credits": max(0, _safe_int(row.get("used_credits")) + int(delta)),
                    "updated_at": _now_iso(),
                },
                admin_required=True,
            )
            return
        await self.directus.create_item(
            ANONYMOUS_IDENTITY_DAILY_COLLECTION,
            {
                "identity_hash": identity_hash,
                "used_credits": max(0, int(delta)),
                "window_date": _today_key(),
                "created_at": _now_iso(),
                "updated_at": _now_iso(),
            },
            admin_required=True,
        )

    async def _get_identity_row(self, identity_hash: str) -> dict[str, Any] | None:
        rows = await self.directus.get_items(
            ANONYMOUS_IDENTITY_DAILY_COLLECTION,
            params={"filter[identity_hash][_eq]": identity_hash, "filter[window_date][_eq]": _today_key(), "limit": 1},
            no_cache=True,
            admin_required=True,
        )
        return rows[0] if rows else None

    def _hmac_identity(self, prefix: str, value: str) -> str:
        msg = f"{prefix}:{value or ''}".encode("utf-8")
        return hmac.new(self.hmac_secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()

    def _status_from_row(self, row: dict[str, Any] | None) -> AnonymousBudgetStatus:
        row = row or {}
        monthly = _safe_int(row.get("monthly_budget_credits"))
        daily_percent = _safe_int(row.get("daily_hard_cap_percent"))
        weekly_percent = _safe_int(row.get("weekly_cap_percent"))
        daily_cap = monthly * daily_percent // 100
        weekly_cap = monthly * weekly_percent // 100
        daily_used = _safe_int(row.get("daily_used_credits"))
        weekly_used = _safe_int(row.get("weekly_used_credits"))
        monthly_used = _safe_int(row.get("monthly_used_credits"))
        per_identity_cap = _safe_int(row.get("per_identity_daily_cap_credits"))
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
            reset_at=_next_utc_midnight_iso(),
            updated_at=row.get("updated_at"),
        )


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _future_iso(*, minutes: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


def _today_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _next_utc_midnight_iso() -> str:
    now = datetime.now(timezone.utc)
    tomorrow = (now + timedelta(days=1)).date()
    return datetime(tomorrow.year, tomorrow.month, tomorrow.day, tzinfo=timezone.utc).isoformat()
