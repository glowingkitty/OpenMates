"""Free testing credit budget service.

Server admins can configure a finite promotional credits budget. This service
owns safe public promotion metadata, admin budget state, idempotent per-user
signup grants, encrypted credit balance updates, notification broadcasts, and
the one-time exhausted-budget email trigger.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

FREE_TESTING_BUDGET_COLLECTION = "free_testing_credits_budget"
FREE_TESTING_GRANTS_COLLECTION = "free_testing_credit_grants"
FREE_TESTING_LOCK_KEY = "free_testing_credits_budget:grant_lock"
FREE_TESTING_LOCK_TTL_SECONDS = 10
FREE_TESTING_LOCK_WAIT_SECONDS = 2.0


@dataclass(frozen=True)
class FreeTestingBudgetStatus:
    enabled: bool
    total_budget_credits: int
    used_budget_credits: int
    remaining_budget_credits: int
    per_user_grant_credits: int
    active: bool
    exhausted: bool
    exhausted_email_sent_at: Optional[str]
    updated_at: Optional[str]


@dataclass(frozen=True)
class FreeTestingGrantResult:
    granted: bool
    credits_granted: int = 0
    current_credits: Optional[int] = None
    reason: Optional[str] = None


class FreeTestingCreditsService:
    """Coordinates free-testing budget and signup grants."""

    _local_lock = asyncio.Lock()

    def __init__(
        self,
        *,
        directus_service: Any,
        cache_service: Any,
        encryption_service: Any,
        websocket_manager: Any = None,
        celery_app: Any = None,
        admin_email_getter: Callable[[], Optional[str]] | None = None,
    ) -> None:
        self.directus = directus_service
        self.cache = cache_service
        self.encryption = encryption_service
        self.websocket_manager = websocket_manager
        self.celery_app = celery_app
        self.admin_email_getter = admin_email_getter or _default_admin_email

    async def get_budget_status(self) -> FreeTestingBudgetStatus:
        row = await self._get_budget_row()
        return self._status_from_row(row)

    async def get_public_promotion(self) -> dict[str, Any]:
        status = await self.get_budget_status()
        return {
            "active": status.active,
            "grant_credits": status.per_user_grant_credits,
        }

    async def has_grant_for_user(self, user_id: str) -> bool:
        """Return whether the grant ledger already contains a Free testing grant for this user."""
        if not user_id:
            return False
        user_id_hash = hashlib.sha256(user_id.encode()).hexdigest()
        return await self._grant_exists(user_id_hash)

    async def save_budget(
        self,
        *,
        enabled: bool,
        total_budget_credits: int,
        per_user_grant_credits: int,
        admin_user_id: Optional[str],
    ) -> FreeTestingBudgetStatus:
        if total_budget_credits < 0:
            raise ValueError("total_budget_credits must be >= 0")
        if enabled and per_user_grant_credits < 1:
            raise ValueError("per_user_grant_credits must be >= 1 when enabled")
        if per_user_grant_credits < 0:
            raise ValueError("per_user_grant_credits must be >= 0")

        existing = await self._get_budget_row()
        used = _safe_int((existing or {}).get("used_budget_credits"))
        if enabled and total_budget_credits < used:
            raise ValueError("total_budget_credits cannot be below used_budget_credits while enabled")

        now = _now_iso()
        exhausted_email_sent_at = (existing or {}).get("exhausted_email_sent_at")
        if enabled and total_budget_credits - used >= per_user_grant_credits:
            exhausted_email_sent_at = None

        payload = {
            "enabled": bool(enabled),
            "total_budget_credits": int(total_budget_credits),
            "used_budget_credits": used,
            "per_user_grant_credits": int(per_user_grant_credits),
            "exhausted_email_sent_at": exhausted_email_sent_at,
            "updated_at": now,
            "updated_by_admin_user_id": admin_user_id,
        }

        if existing and existing.get("id"):
            updated = await self.directus.update_item(
                FREE_TESTING_BUDGET_COLLECTION,
                existing["id"],
                payload,
                admin_required=True,
            )
            if not updated:
                raise RuntimeError("Failed to update free testing budget")
            row = updated
        else:
            success, created = await self.directus.create_item(
                FREE_TESTING_BUDGET_COLLECTION,
                {"created_at": now, **payload},
                admin_required=True,
            )
            if not success:
                raise RuntimeError("Failed to create free testing budget")
            row = created

        return self._status_from_row(row)

    async def grant_to_new_signup(self, user_id: str) -> FreeTestingGrantResult:
        if not user_id:
            return FreeTestingGrantResult(granted=False, reason="missing_user_id")

        async with self._grant_lock():
            return await self._grant_to_new_signup_locked(user_id)

    async def _grant_to_new_signup_locked(self, user_id: str) -> FreeTestingGrantResult:
        status = await self.get_budget_status()
        if not status.enabled or status.per_user_grant_credits <= 0:
            return FreeTestingGrantResult(granted=False, reason="inactive")
        if not status.active:
            return FreeTestingGrantResult(granted=False, reason="insufficient_budget")

        user_id_hash = hashlib.sha256(user_id.encode()).hexdigest()
        if await self._grant_exists(user_id_hash):
            return FreeTestingGrantResult(granted=False, reason="already_granted")

        user_cache = await self.cache.get_user_by_id(user_id)
        if not user_cache:
            logger.error("Cannot grant free testing credits: user %s missing from cache", user_id[:8])
            return FreeTestingGrantResult(granted=False, reason="user_not_cached")

        vault_key_id = user_cache.get("vault_key_id")
        if not vault_key_id:
            logger.error("Cannot grant free testing credits: user %s missing vault_key_id", user_id[:8])
            return FreeTestingGrantResult(granted=False, reason="missing_vault_key")

        current_credits = _safe_int(user_cache.get("credits"))
        grant_credits = status.per_user_grant_credits
        new_total = current_credits + grant_credits
        encrypted_credits, _ = await self.encryption.encrypt_with_user_key(str(new_total), vault_key_id)

        if not await self.directus.update_user(user_id, {"encrypted_credit_balance": encrypted_credits}):
            logger.error("Failed to update Directus credit balance for free testing grant: %s", user_id[:8])
            return FreeTestingGrantResult(granted=False, reason="credit_update_failed")

        user_cache["credits"] = new_total
        await self.cache.set_user(user_cache, user_id=user_id)

        created_at = _now_iso()
        success, _grant = await self.directus.create_item(
            FREE_TESTING_GRANTS_COLLECTION,
            {
                "user_id_hash": user_id_hash,
                "credits_granted": grant_credits,
                "created_at": created_at,
            },
            admin_required=True,
        )
        if not success:
            logger.error("Failed to record free testing grant ledger for user %s", user_id[:8])
            return FreeTestingGrantResult(granted=False, reason="grant_record_failed")

        await self._increment_budget_used(status, grant_credits)
        await self._record_promotional_stats(grant_credits)
        await self._broadcast_credit_update(user_id, new_total)
        await self._broadcast_user_notification(user_id, grant_credits)

        refreshed = await self.get_budget_status()
        if refreshed.exhausted and not refreshed.exhausted_email_sent_at:
            await self._mark_exhausted_email_sent_and_enqueue(refreshed)

        return FreeTestingGrantResult(
            granted=True,
            credits_granted=grant_credits,
            current_credits=new_total,
        )

    async def _increment_budget_used(self, status: FreeTestingBudgetStatus, grant_credits: int) -> None:
        row = await self._get_budget_row()
        if not row or not row.get("id"):
            raise RuntimeError("Free testing budget row missing during grant")
        new_used = status.used_budget_credits + grant_credits
        updated = await self.directus.update_item(
            FREE_TESTING_BUDGET_COLLECTION,
            row["id"],
            {"used_budget_credits": new_used, "updated_at": _now_iso()},
            admin_required=True,
        )
        if not updated:
            raise RuntimeError("Failed to update free testing used budget")

    async def _record_promotional_stats(self, grant_credits: int) -> None:
        try:
            await self.cache.increment_stat("free_testing_credits_granted", int(grant_credits))
            await self.cache.increment_stat("free_testing_grants_created", 1)
            await self.cache.update_liability(int(grant_credits))
        except Exception as exc:
            logger.error("Failed to record free testing promotional stats: %s", exc, exc_info=True)

    async def _broadcast_credit_update(self, user_id: str, new_total: int) -> None:
        payload = {"credits": new_total}
        try:
            await self.cache.publish_event(
                channel=f"user_updates::{user_id}",
                event_data={
                    "event_for_client": "user_credits_updated",
                    "user_id_uuid": user_id,
                    "payload": payload,
                },
            )
        except Exception as exc:
            logger.error("Failed to publish free testing credit update: %s", exc, exc_info=True)

        if self.websocket_manager:
            try:
                await self.websocket_manager.broadcast_to_user_specific_event(
                    user_id=user_id,
                    event_name="user_credits_updated",
                    payload=payload,
                )
            except Exception as exc:
                logger.error("Failed to broadcast free testing credit update: %s", exc, exc_info=True)

    async def _broadcast_user_notification(self, user_id: str, grant_credits: int) -> None:
        payload = {
            "notification_type": "success",
            "message_key": "signup.free_testing_credits_received",
            "message_values": {"credits": grant_credits},
            "message": f"You received {grant_credits} free credits for testing.",
            "dedupe_key": f"free-testing-credits:{user_id}",
            "duration": 12000,
        }
        try:
            await self.cache.publish_event(
                channel=f"user_updates::{user_id}",
                event_data={
                    "event_for_client": "user_notification",
                    "user_id_uuid": user_id,
                    "payload": payload,
                },
            )
        except Exception as exc:
            logger.error("Failed to publish free testing user notification: %s", exc, exc_info=True)

        if self.websocket_manager:
            try:
                await self.websocket_manager.broadcast_to_user_specific_event(
                    user_id=user_id,
                    event_name="user_notification",
                    payload=payload,
                )
            except Exception as exc:
                logger.error("Failed to broadcast free testing user notification: %s", exc, exc_info=True)

    async def _mark_exhausted_email_sent_and_enqueue(self, status: FreeTestingBudgetStatus) -> None:
        row = await self._get_budget_row()
        if not row or not row.get("id") or row.get("exhausted_email_sent_at"):
            return

        sent_at = _now_iso()
        updated = await self.directus.update_item(
            FREE_TESTING_BUDGET_COLLECTION,
            row["id"],
            {"exhausted_email_sent_at": sent_at, "updated_at": sent_at},
            admin_required=True,
        )
        if not updated:
            logger.error("Failed to mark free testing exhausted email as sent")
            return

        admin_email = self.admin_email_getter()
        if not admin_email:
            logger.warning("Free testing budget exhausted but no admin email is configured")
            return
        if not self.celery_app:
            logger.warning("Free testing budget exhausted but celery app is unavailable")
            return

        self.celery_app.send_task(
            name="app.tasks.email_tasks.free_testing_budget_email_task.send_free_testing_budget_exhausted_email",
            kwargs={
                "admin_email": admin_email,
                "total_budget_credits": status.total_budget_credits,
                "used_budget_credits": status.used_budget_credits,
                "per_user_grant_credits": status.per_user_grant_credits,
            },
            queue="email",
        )

    async def _grant_exists(self, user_id_hash: str) -> bool:
        rows = await self.directus.get_items(
            FREE_TESTING_GRANTS_COLLECTION,
            params={
                "filter[user_id_hash][_eq]": user_id_hash,
                "limit": 1,
                "fields": "id,user_id_hash",
            },
            no_cache=True,
            admin_required=True,
        )
        return bool(rows)

    async def _get_budget_row(self) -> Optional[dict[str, Any]]:
        rows = await self.directus.get_items(
            FREE_TESTING_BUDGET_COLLECTION,
            params={"limit": 1, "sort": "-updated_at"},
            no_cache=True,
            admin_required=True,
        )
        return rows[0] if rows else None

    def _status_from_row(self, row: Optional[dict[str, Any]]) -> FreeTestingBudgetStatus:
        if not row:
            return FreeTestingBudgetStatus(
                enabled=False,
                total_budget_credits=0,
                used_budget_credits=0,
                remaining_budget_credits=0,
                per_user_grant_credits=0,
                active=False,
                exhausted=False,
                exhausted_email_sent_at=None,
                updated_at=None,
            )

        enabled = bool(row.get("enabled"))
        total = _safe_int(row.get("total_budget_credits"))
        used = _safe_int(row.get("used_budget_credits"))
        grant = _safe_int(row.get("per_user_grant_credits"))
        remaining = max(0, total - used)
        active = enabled and grant > 0 and remaining >= grant
        exhausted = enabled and grant > 0 and remaining < grant
        return FreeTestingBudgetStatus(
            enabled=enabled,
            total_budget_credits=total,
            used_budget_credits=used,
            remaining_budget_credits=remaining,
            per_user_grant_credits=grant,
            active=active,
            exhausted=exhausted,
            exhausted_email_sent_at=row.get("exhausted_email_sent_at"),
            updated_at=row.get("updated_at"),
        )

    def _grant_lock(self) -> "_GrantLock":
        return _GrantLock(self.cache, self._local_lock)


class _GrantLock:
    def __init__(self, cache_service: Any, local_lock: asyncio.Lock) -> None:
        self.cache = cache_service
        self.local_lock = local_lock
        self.redis_client: Any = None
        self.token = secrets.token_hex(12)
        self.acquired_redis = False

    async def __aenter__(self) -> None:
        await self.local_lock.acquire()
        self.redis_client = await _get_cache_client(self.cache)
        if not self.redis_client:
            return

        loop = asyncio.get_running_loop()
        deadline = loop.time() + FREE_TESTING_LOCK_WAIT_SECONDS
        while loop.time() < deadline:
            acquired = await self.redis_client.set(
                FREE_TESTING_LOCK_KEY,
                self.token,
                nx=True,
                ex=FREE_TESTING_LOCK_TTL_SECONDS,
            )
            if acquired:
                self.acquired_redis = True
                return
            await asyncio.sleep(0.05)
        raise RuntimeError("Timed out acquiring free testing credits budget lock")

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        try:
            if self.redis_client and self.acquired_redis:
                current = await self.redis_client.get(FREE_TESTING_LOCK_KEY)
                if isinstance(current, bytes):
                    current = current.decode("utf-8")
                if current == self.token:
                    await self.redis_client.delete(FREE_TESTING_LOCK_KEY)
        finally:
            self.local_lock.release()


async def _get_cache_client(cache_service: Any) -> Any:
    try:
        client_attr = getattr(cache_service, "client", None)
        if client_attr is None:
            return None
        if hasattr(client_attr, "__await__"):
            return await client_attr
        return client_attr
    except Exception:
        return None


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_admin_email() -> Optional[str]:
    return os.getenv("SERVER_OWNER_EMAIL") or os.getenv("ADMIN_NOTIFY_EMAIL")
