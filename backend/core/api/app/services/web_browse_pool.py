"""Prepared blank VMs: encrypted journal, exclusive claim, no recycling.

Only never-assigned VMs enter ready. User work starts after a durable claim and
owner-encrypted handoff. Preparation is platform overhead; the existing user
ledger starts with the explicitly admitted resume, without changing its tariff.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
import json
import logging
import os
import time
import uuid
from typing import Any

from fastapi import HTTPException

from backend.shared.providers.e2b_browser import BrowserUnavailable
from backend.shared.python_schemas.web_browse import owner_hash
from backend.shared.python_utils.private_inference_logging import (
    private_inference_logging,
)

COLLECTION = "browser_pool"
CLAIMS = "browser_pool_claims"
logger = logging.getLogger(__name__)


def pool_size() -> int:
    return max(0, min(10, int(os.environ.get("E2B_BROWSE_POOL_SIZE", "0"))))


class BrowsePool:
    def __init__(self, store: Any, driver: Any) -> None:
        self.store = store
        self.db = store.db
        self.encryption = store.encryption
        self.driver = driver
        self.scope = driver.scope
        self.template = driver.validate_creation()
        self.owner = owner_hash("platform-blank-pool:" + self.scope)

    async def rows(self, filters: dict, limit: int = 20) -> list[dict]:
        return await self.db.get_items(
            COLLECTION,
            params={
                "filter": json.dumps({**filters, "scope": {"_eq": self.scope}}),
                "fields": "*",
                "limit": limit,
            },
            no_cache=True,
            admin_required=True,
            raise_on_error=True,
        )

    async def update(self, row: dict, values: dict) -> None:
        transitions = {
            "preparing": {"preparing", "ready", "retired"},
            "ready": {"ready", "claimed", "retired"},
            "claimed": {"claimed", "retired"},
            "retired": {"retired"},
        }
        if values.get("status", row["status"]) not in transitions[row["status"]] or (
            row.get("claimed_session_id")
            and values.get("claimed_session_id", row["claimed_session_id"])
            != row["claimed_session_id"]
        ):
            raise BrowserUnavailable("A claimed browser cannot reenter the pool.")
        version = row["version"]
        updated = await self.db.update_item_if_version(
            COLLECTION,
            row["id"],
            {**values, "version": version + 1},
            version,
            owner_hash_field="scope",
            owner_hash=self.scope,
            admin_required=True,
        )
        if not updated or updated.get("version") != version + 1:
            raise BrowserUnavailable("The browser pool journal changed.")
        row.update(updated)

    async def provider(self, row: dict) -> dict:
        plain = await self.encryption.decrypt(row.get("encrypted_payload", ""))
        if not plain:
            raise BrowserUnavailable("The blank browser could not be restored.")
        value = json.loads(plain)
        if (
            value.get("sandbox_id") != row["sandbox_id"]
            or value.get("pool_slot_id") != row["id"]
            or value.get("pool_assigned") is not False
        ):
            raise BrowserUnavailable("The blank browser identity is invalid.")
        return value

    async def receipt(self, row: dict) -> dict | None:
        receipts = await self.db.get_items(
            CLAIMS,
            params={"filter[id][_eq]": row["id"], "fields": "*", "limit": 1},
            no_cache=True,
            admin_required=True,
            raise_on_error=True,
        )
        if not receipts:
            return None
        if receipts[0]["scope"] != self.scope:
            raise BrowserUnavailable("The browser claim scope is invalid.")
        return receipts[0]

    async def reconcile_claim(self, row: dict) -> bool:
        receipt = await self.receipt(row)
        if not receipt:
            return False
        if row.get("claimed_session_id") not in (None, receipt["session_id"]):
            raise BrowserUnavailable("The browser claim owner is inconsistent.")
        if row["status"] != "claimed":
            await self.update(
                row,
                {
                    "status": "claimed",
                    "claimed_session_id": receipt["session_id"],
                    "claimed_at": receipt["created_at"],
                },
            )
        return True

    async def scrub(self, row: dict) -> None:
        try:
            await self.update(row, {"encrypted_payload": ""})
        except BrowserUnavailable:
            latest = await self.rows({"id": {"_eq": row["id"]}}, limit=1)
            if (
                latest
                and latest[0]["status"] == "claimed"
                and latest[0].get("claimed_session_id") == row["claimed_session_id"]
                and not latest[0].get("encrypted_payload")
            ):
                row.update(latest[0])
                return
            raise

    async def owned_record(self, row: dict) -> dict | None:
        rows = await self.db.get_items(
            "browser_sessions",
            params={
                "filter[id][_eq]": row["claimed_session_id"],
                "fields": "id,status,expires_at",
                "limit": 1,
            },
            no_cache=True,
            admin_required=True,
            raise_on_error=True,
        )
        if (
            not rows
            or rows[0]["status"] in ("closed", "expired")
            or rows[0]["expires_at"] <= time.time()
        ):
            return None
        return await self.store.load(row["claimed_session_id"], None)

    @staticmethod
    def pending_handoff(row: dict, record: dict | None) -> bool:
        return bool(
            record
            and not record.get("provider")
            and record.get("active_run")
            and record["status"] == "ai"
            and time.time() - row.get("claimed_at", 0) < 90
        )

    async def retire(self, row: dict) -> None:
        if row.get("sandbox_id"):
            try:
                await self.driver.kill({"sandbox_id": row["sandbox_id"]})
            except Exception as exc:
                if getattr(exc, "status_code", None) != 404:
                    raise
        await self.update(
            row,
            {
                "status": "retired",
                "encrypted_payload": "",
                "expires_at": int(time.time()),
            },
        )

    async def claim(self, session_id: str, on_created: Any) -> dict | None:
        """Only a successful unique SQL insert grants access to a blank VM."""
        now = int(time.time())
        candidates = await self.rows(
            {
                "status": {"_eq": "ready"},
                "template_id": {"_eq": self.template},
                "expires_at": {"_gt": now},
            },
            limit=10,
        )
        for candidate in candidates:
            # The primary-key constraint, not a cache lease or a read/update
            # sequence, arbitrates ownership across processes. A lost response
            # also grants no access; the journal reconciler destroys that VM.
            won, _ = await self.db.create_item(
                CLAIMS,
                {
                    "id": candidate["id"],
                    "scope": self.scope,
                    "session_id": session_id,
                    "created_at": now,
                },
                admin_required=True,
                expected_unique_conflict_field="id",
            )
            if not won:
                continue
            row = candidate
            try:
                await self.update(
                    row,
                    {
                        "status": "claimed",
                        "claimed_session_id": session_id,
                        "claimed_at": now,
                    },
                )
                provider = await self.provider(row)
                provider.update(pool_assigned=True, pool_verified=False)
                # The owner-keyed record must exist before removing the service
                # copy, and both writes must finish before any user resume.
                await on_created(provider)
                await self.scrub(row)
                return provider
            except BaseException:
                # Never put even a failed claim back. No cookie/cache clearing
                # can substitute for a fresh VM at the next assignment.
                await self.retire(row)
                raise
        return None

    async def prepare(self) -> None:
        slot = str(uuid.uuid4())
        cipher, _ = await self.encryption.encrypt("{}")
        row = {
            "id": slot,
            "scope": self.scope,
            "template_id": self.template,
            "status": "preparing",
            "sandbox_id": None,
            "claimed_session_id": None,
            "claimed_at": None,
            "encrypted_payload": cipher,
            "preparation_cost_usd": "0",
            "expires_at": int(time.time()) + 300,
            "version": 1,
        }
        ok, _ = await self.db.create_item(COLLECTION, row, admin_required=True)
        if not ok:
            raise BrowserUnavailable("The blank browser journal is unavailable.")

        async def created(provider):
            provider.update(pool_slot_id=slot, pool_assigned=False, pool_verified=False)
            cipher, _ = await self.encryption.encrypt(json.dumps(provider))
            await self.update(
                row, {"sandbox_id": provider["sandbox_id"], "encrypted_payload": cipher}
            )

        try:
            with private_inference_logging():
                provider = await self.driver.create(
                    session_id=slot, owner=self.owner, on_created=created
                )
                checked = await self.driver.rpc(
                    provider,
                    {
                        "operation": "control",
                        "mode": "ai",
                        "check_ready": True,
                        "require_pristine": True,
                    },
                )
                if checked.get("pristine") is not True:
                    raise BrowserUnavailable(
                        "Only pristine browsers may enter the pool."
                    )
                await self.driver.pause(provider)
                info = await self.driver.info(provider)
                if str(getattr(info.state, "value", info.state)) != "paused":
                    raise BrowserUnavailable("The prepared browser is not paused.")
                elapsed = max(
                    0,
                    min(time.time(), provider["provider_deadline"])
                    - provider["running_since"],
                )
                rate = Decimal(provider["cpu_count"]) * Decimal("0.000014") + Decimal(
                    provider["memory_mb"]
                ) / 1024 * Decimal("0.0000045")
                provider.update(running_since=None, provider_deadline=time.time())
                await created(provider)
                await self.update(
                    row,
                    {
                        "status": "ready",
                        "expires_at": int(time.time()) + 3600,
                        "preparation_cost_usd": str(Decimal(str(elapsed)) * rate),
                    },
                )
        except BaseException:
            await self.retire(row)
            raise

    async def refill(self) -> int:
        if not pool_size():
            return 0
        if os.environ.get("E2B_BROWSE_PREBOOTED") != "true":
            raise BrowserUnavailable(
                "The blank pool requires a qualified prepared template."
            )
        try:
            async with self.store.lease("pool-refill:" + self.scope, wait_seconds=0):
                existing = await self.rows(
                    {
                        "status": {"_in": ["ready", "preparing"]},
                        "template_id": {"_eq": self.template},
                        "expires_at": {"_gt": int(time.time())},
                    }
                )
                needed = min(2, max(0, pool_size() - len(existing)))
                results = await asyncio.gather(
                    *(self.prepare() for _ in range(needed)), return_exceptions=True
                )
                for result in results:
                    if isinstance(result, BaseException):
                        logger.warning(
                            "A public blank browser needs a preparation retry."
                        )
                return sum(not isinstance(r, BaseException) for r in results)
        except HTTPException as exc:
            if exc.status_code == 409:
                return 0
            raise

    async def retain_native(self, info: Any) -> bool:
        """The durable journal follows assigned resources across cache restarts."""
        slot = str(uuid.UUID(info.metadata["openmates_browser_session"]))
        rows = await self.rows({"id": {"_eq": slot}}, limit=1)
        if not rows or rows[0].get("sandbox_id") != info.sandbox_id:
            return False
        row = rows[0]
        if row["status"] == "retired":
            return False
        claimed = await self.reconcile_claim(row)
        if not claimed and row["status"] in ("preparing", "ready"):
            return (
                row["expires_at"] > time.time()
                and row["template_id"] == self.template
                and pool_size() > 0
            )
        if not claimed:
            return False
        try:
            record = await self.owned_record(row)
        except HTTPException as exc:
            if exc.status_code == 404:
                return False
            raise
        if self.pending_handoff(row, record):
            return True
        if not record:
            return False
        matches = (record.get("provider") or {}).get("sandbox_id") == info.sandbox_id
        live = (
            record["status"] not in ("closed", "expired")
            and record["last_activity"] + 86400 > time.time()
        )
        if matches and live and row.get("encrypted_payload"):
            # Recover a crash between owner persistence and service-copy removal.
            await self.scrub(row)
        return matches and live

    async def sweep(self) -> int:
        count = 0
        rows = await self.rows(
            {"status": {"_in": ["ready", "preparing", "claimed"]}}, limit=100
        )
        for row in rows:
            try:
                if await self.reconcile_claim(row):
                    # Its owner's lifecycle, not the blank-pool TTL, is authoritative.
                    try:
                        record = await self.owned_record(row)
                    except HTTPException as exc:
                        if exc.status_code != 404:
                            raise
                        record = None
                    if self.pending_handoff(row, record):
                        continue
                    if (
                        record
                        and record["status"] not in ("closed", "expired")
                        and record["last_activity"] + 86400 > time.time()
                        and (record.get("provider") or {}).get("sandbox_id")
                        == row["sandbox_id"]
                    ):
                        if row.get("encrypted_payload"):
                            await self.scrub(row)
                        continue
                elif row["status"] != "claimed" and (
                    row["expires_at"] > time.time()
                    and row["template_id"] == self.template
                    and pool_size() > 0
                ):
                    continue
                await self.retire(row)
                count += 1
            except Exception:
                logger.warning("A blank browser requires a cleanup retry.")
        retired = await self.rows(
            {
                "status": {"_eq": "retired"},
                "expires_at": {"_lte": int(time.time()) - 86400},
            },
            limit=100,
        )
        if retired:
            await self.db.bulk_delete_items(CLAIMS, [r["id"] for r in retired])
            await self.db.bulk_delete_items(COLLECTION, [r["id"] for r in retired])
        return count
