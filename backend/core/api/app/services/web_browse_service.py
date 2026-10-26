"""Owner-scoped browser sessions, durable encrypted state and execution lifecycle."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from decimal import Decimal
import hashlib
import json
import logging
import os
import time
from typing import Any, AsyncIterator, Awaitable, Callable
import uuid

from fastapi import HTTPException
from jsonschema import Draft202012Validator

from backend.shared.providers.browser_models import BrowserModels, BrowserModelError
from backend.shared.providers.e2b_browser import (
    E2BBrowser,
    BrowserUnavailable,
    BrowserAdmissionRejected,
)
from backend.shared.providers.e2b_code_runner import get_e2b_api_key_async
from backend.core.api.app.services.web_browse_pool import BrowsePool, pool_size
from backend.shared.python_schemas.web_browse import (
    BrowseRequest,
    BrowseResult,
    BrowseControl,
    BrowseJob,
    browse_identity,
    IDLE_DELETE_SECONDS,
    SIGN_IN_NOTICE,
    charged_credits,
    owner_hash,
    session_lifecycle,
)
from backend.shared.python_utils.private_inference_logging import (
    private_inference_logging,
)

from backend.shared.python_utils.strict_output_safety import StrictSafetyUnavailable

COLLECTION = "browser_sessions"
logger = logging.getLogger(__name__)


class BrowseBudgetExceeded(RuntimeError):
    pass


class BrowseControlChanged(RuntimeError):
    pass


class BrowseStore:
    def __init__(self, directus: Any, encryption: Any, cache: Any) -> None:
        self.db = directus
        self.encryption = encryption
        self.cache = cache

    async def load_result(self, run_id: str, user_id: str) -> BrowseResult:
        rows = await self.db.get_items(
            "browser_runs",
            params={
                "filter[id][_eq]": run_id,
                "filter[owner_hash][_eq]": owner_hash(user_id),
                "fields": "*",
                "limit": 1,
            },
            no_cache=True,
            admin_required=True,
            raise_on_error=True,
        )
        if not rows or rows[0]["expires_at"] <= time.time():
            raise HTTPException(
                404, "The browser result has expired; use its saved chat embed."
            )
        text = await self.encryption.decrypt_with_user_key(
            rows[0]["encrypted_payload"], rows[0]["vault_key_id"]
        )
        if not text:
            raise HTTPException(409, "The browser result could not be restored.")
        result = BrowseResult.model_validate_json(text)
        if result.run_id != run_id or result.session_id != rows[0]["session_id"]:
            raise HTTPException(409, "The browser result identity is invalid.")
        return result

    async def save_result(
        self, result: BrowseResult, record: dict[str, Any]
    ) -> BrowseResult:
        ciphertext, _ = await self.encryption.encrypt_with_user_key(
            result.model_dump_json(), record["vault_key_id"]
        )
        if not ciphertext:
            raise RuntimeError("Browser result encryption failed.")
        ok, _ = await self.db.create_item(
            "browser_runs",
            {
                "id": result.run_id,
                "session_id": result.session_id,
                "owner_hash": owner_hash(record["user_id"]),
                "vault_key_id": record["vault_key_id"],
                "encrypted_payload": ciphertext,
                "expires_at": int(time.time()) + IDLE_DELETE_SECONDS,
            },
            admin_required=True,
        )
        if not ok:
            return await self.load_result(result.run_id, record["user_id"])
        return result

    @asynccontextmanager
    async def lease(
        self, session_id: str, *, wait_seconds: float = 25
    ) -> AsyncIterator[None]:
        redis = await self.cache.client
        key = "web_browse:lease:" + session_id
        token = str(uuid.uuid4())
        deadline = time.monotonic() + wait_seconds
        while not await redis.set(key, token, nx=True, ex=180):
            if time.monotonic() > deadline:
                raise HTTPException(
                    409, "The browser is busy; wait for the current operation."
                )
            await asyncio.sleep(0.1)
        try:
            yield
        finally:
            await redis.eval(
                "if redis.call('get',KEYS[1]) == ARGV[1] then return redis.call('del',KEYS[1]) else return 0 end",
                1,
                key,
                token,
            )

    async def load(
        self, session_id: str, user_id: str | None, chat_id: str | None = None
    ) -> dict[str, Any]:
        params = {"filter[id][_eq]": session_id, "limit": 1, "fields": "*"}
        if user_id:
            params["filter[owner_hash][_eq]"] = owner_hash(user_id)
        rows = await self.db.get_items(
            COLLECTION,
            params=params,
            no_cache=True,
            admin_required=True,
            raise_on_error=True,
        )
        if not rows:
            raise HTTPException(404, "Browser session is unavailable.")
        row = rows[0]
        text = await self.encryption.decrypt_with_user_key(
            row["encrypted_payload"], row["vault_key_id"]
        )
        if not text:
            raise HTTPException(409, "Browser state could not be restored.")
        record = json.loads(text)
        if (user_id and record["user_id"] != user_id) or (
            chat_id and record["chat_id"] != chat_id
        ):
            raise HTTPException(404, "Browser session is unavailable.")
        record["_version"] = row.get("version", 1)
        return record

    async def save(self, record: dict[str, Any], *, create: bool = False) -> None:
        version = record.get("_version", 0)
        plain = {k: v for k, v in record.items() if not k.startswith("_")}
        ciphertext, _ = await self.encryption.encrypt_with_user_key(
            json.dumps(plain), record["vault_key_id"]
        )
        if not ciphertext:
            raise RuntimeError("Browser state encryption failed.")
        row = {
            "owner_hash": owner_hash(record["user_id"]),
            "vault_key_id": record["vault_key_id"],
            "encrypted_payload": ciphertext,
            "status": record["status"],
            "last_activity": int(record["last_activity"]),
            "expires_at": int(record["last_activity"]) + IDLE_DELETE_SECONDS,
            "version": version + 1,
            "needs_reconciliation": bool(
                record.get("reservation") or record.get("pending_calls")
            ),
        }
        if create:
            ok, result = await self.db.create_item(
                COLLECTION, {"id": record["session_id"], **row}, admin_required=True
            )
            if not ok:
                raise RuntimeError("Browser session persistence failed.")
        else:
            result = await self.db.update_item_if_version(
                COLLECTION,
                record["session_id"],
                row,
                version,
                owner_hash_field="owner_hash",
                owner_hash=owner_hash(record["user_id"]),
                admin_required=True,
            )
            if not result or result.get("version") != version + 1:
                raise HTTPException(
                    409, "Browser state changed; refresh before continuing."
                )
        record["_version"] = version + 1


class BrowseService:
    def __init__(
        self,
        *,
        app: Any,
        directus: Any,
        encryption: Any,
        cache: Any,
        secrets_manager: Any,
        driver: Any = None,
        models_factory: Any = BrowserModels,
    ) -> None:
        self.app = app
        self.store = BrowseStore(directus, encryption, cache)
        self.secrets = secrets_manager
        self.driver = driver
        self.models_factory = models_factory

    async def browser(self) -> E2BBrowser:
        if self.driver is None:
            self.driver = E2BBrowser(await get_e2b_api_key_async(self.secrets))
        return self.driver

    async def claim_slot(self, record: dict[str, Any]) -> None:
        async with self.store.lease("owner:" + owner_hash(record["user_id"])):
            rows = await self.store.db.get_items(
                COLLECTION,
                params={
                    "filter[owner_hash][_eq]": owner_hash(record["user_id"]),
                    "filter[status][_in]": "ai,user",
                    "filter[id][_neq]": record["session_id"],
                    "fields": "id",
                    "limit": 3,
                },
                no_cache=True,
                admin_required=True,
                raise_on_error=True,
            )
            if len(rows) >= 3:
                raise HTTPException(
                    409, "Three browsers are already active; pause or close one first."
                )
            record["status"] = "ai"
            record["last_activity"] = time.time()
            await self.store.save(record)

    async def reserve(self, record: dict[str, Any]) -> None:
        if record.get("settlement"):
            await self.settle(record)
        if record.get("accounting_pending"):
            raise HTTPException(
                409, "Browser usage is awaiting reconciliation; start a new session."
            )
        if record.get("reservation") and record.get("reservation_admitted"):
            return
        operation = record.get("reservation") or str(uuid.uuid4())
        remaining = record["max_credits"] - record.get("charged_credits", 0)
        if remaining <= 0:
            raise BrowseBudgetExceeded("The browser spending limit was reached.")
        # A crash after wallet admission must still leave a recoverable operation identity.
        record["reservation"] = operation
        await self.store.save(record)
        try:
            await self.app._make_internal_api_request(
                "POST",
                "/internal/billing/reserve",
                payload={
                    "user_id": record["user_id"],
                    "user_id_hash": owner_hash(record["user_id"]),
                    "idempotency_key": operation,
                    "quoted_credits": remaining,
                    "app_id": "web",
                    "skill_id": "browse",
                },
            )
        except HTTPException as exc:
            if exc.status_code < 500:
                record["reservation"] = None
                record["reservation_admitted"] = False
                record["status"] = "paused"
                await self.store.save(record)
            raise
        record["reservation_admitted"] = True
        await self.store.save(record)

    def runtime_cost(
        self, record: dict[str, Any], *, stop_at: float | None = None
    ) -> Decimal:
        p = record.get("provider") or {}
        rate = Decimal(p.get("cpu_count", 0)) * Decimal("0.000014") + Decimal(
            p.get("memory_mb", 0)
        ) / 1024 * Decimal("0.0000045")
        start = p.get("running_since")
        elapsed = (
            max(
                0,
                min(stop_at or time.time(), p.get("provider_deadline", time.time()))
                - start,
            )
            if start
            else 0
        )
        return (
            Decimal(record.get("runtime_cost_usd", "0")) + Decimal(str(elapsed)) * rate
        )

    def total_cost(self, record: dict[str, Any]) -> Decimal:
        return self.runtime_cost(record) + Decimal(
            record.get("inference_cost_usd", "0")
        )

    def remaining_usd(self, record: dict[str, Any]) -> Decimal:
        return Decimal(record["max_credits"]) / 2000 - self.total_cost(record)

    async def keep_running(
        self, record: dict[str, Any], reserved_usd: Decimal = Decimal(0)
    ) -> None:
        p = record["provider"]
        rate = Decimal(p["cpu_count"]) * Decimal("0.000014") + Decimal(
            p["memory_mb"]
        ) / 1024 * Decimal("0.0000045")
        available = self.remaining_usd(record) - reserved_usd
        seconds = min(120, int(available / rate) - 2)
        if seconds < 5:
            raise BrowseBudgetExceeded(
                "The remaining session budget cannot cover the next browser operation."
            )
        if abs(p.get("provider_deadline", 0) - (time.time() + seconds)) > 15:
            record["runtime_intent"] = {
                "kind": "timeout",
                "at": time.time(),
                "deadline": time.time() + seconds,
            }
            await self.store.save(record)
            await (await self.browser()).keep_running(p, seconds=seconds)
            record.pop("runtime_intent", None)
            await self.store.save(record)

    async def resume_compute(self, record: dict[str, Any]) -> None:
        record["runtime_intent"] = {
            "kind": "resume",
            "at": time.time(),
            "deadline": time.time() + 120,
        }
        await self.store.save(record)

        async def resumed(provider: dict[str, Any]) -> None:
            record["provider"] = provider
            record.pop("runtime_intent", None)
            await self.store.save(record)

        await (await self.browser()).resume(record["provider"], on_resumed=resumed)

    async def settle(self, record: dict[str, Any]) -> None:
        reservation = record.get("reservation")
        if (
            not reservation
            or record.get("accounting_pending")
            or record.get("pending_calls")
        ):
            return
        if not record.get("settlement"):
            total = max(
                record.get("charged_credits", 0),
                charged_credits(self.total_cost(record)),
            )
            record["settlement"] = {
                "total": total,
                "delta": max(0, total - record.get("charged_credits", 0)),
                "supplier_cost_usd": str(self.total_cost(record)),
            }
            await self.store.save(record)
        intent = record["settlement"]
        delta = intent["delta"]
        if delta:
            charge = await self.app.charge_user_credits(
                user_id=record["user_id"],
                user_id_hash=owner_hash(record["user_id"]),
                credits_to_charge=delta,
                skill_id="browse",
                app_id="web",
                idempotency_key=reservation,
                api_key_hash=(record.get("billing_actor") or {}).get("api_key_hash"),
                device_hash=(record.get("billing_actor") or {}).get("device_hash"),
                usage_details={
                    "browser_session_id": record["session_id"],
                    "supplier_cost_usd": intent["supplier_cost_usd"],
                    "multiplier": 2,
                    "chat_id": record["chat_id"],
                },
            )
            # The charge atomically settles its reservation. An outbox receipt
            # is still pending; retain the exact intent and hold for retry.
            if (
                charge.get("state") != "committed"
                or charge.get("charged_credits") != delta
            ):
                raise HTTPException(503, "Browser billing settlement is pending.")
        else:
            # No additional metered cost remains to charge in this window.
            await self.app._make_internal_api_request(
                "POST",
                "/internal/billing/reservation/release",
                payload={
                    "subject_kind": "personal",
                    "user_id": record["user_id"],
                    "user_id_hash": owner_hash(record["user_id"]),
                    "idempotency_key": reservation,
                    "reason": "definite_no_cost",
                },
            )
        record["charged_credits"] = intent["total"]
        record.pop("settlement", None)
        record["reservation"] = None
        record["reservation_admitted"] = False
        await self.store.save(record)

    async def pause(self, record: dict[str, Any]) -> None:
        if record.get("runtime_intent") or record.get("startup_intent"):
            record["accounting_pending"] = True
        if record.get("provider") and record["status"] not in (
            "paused",
            "closed",
            "expired",
        ):
            driver = await self.browser()
            # E2B's management API does not wake an already auto-paused VM.
            # An unreachable browser RPC must not prevent pausing paid compute.
            if not record["provider"].get("deleted"):
                await driver.pause(record["provider"])
            record["runtime_cost_usd"] = str(self.runtime_cost(record))
            record["provider"]["running_since"] = None
        record["status"] = "paused"
        record["active_run"] = None
        await self.settle(record)
        await self.store.save(record)

    async def expire(self, record: dict[str, Any], status: str = "expired") -> None:
        if record.get("provider"):
            if (
                record.get("accounting_pending")
                or record.get("runtime_intent")
                or record.get("pending_calls")
            ):
                # Closing removes credentials and live state, but must not erase
                # the content-free resource identity needed to reconcile a hold.
                record["unresolved_resource_receipt"] = {
                    key: record["provider"].get(key)
                    for key in (
                        "sandbox_id",
                        "cpu_count",
                        "memory_mb",
                        "created_at",
                        "running_since",
                        "provider_deadline",
                    )
                }
            if not record["provider"].get("deleted"):
                await (await self.browser()).kill(record["provider"])
            record["runtime_cost_usd"] = str(self.runtime_cost(record))
            record["provider"] = None
        record["status"] = status
        record["active_run"] = None
        await self.settle(record)
        # Browser credentials and private live state are removed. Saved chat results have independent retention.
        record.pop("latest_observation", None)
        record.pop("last_result", None)
        await self.store.save(record)

    async def ensure_live(self, record: dict[str, Any]) -> None:
        if session_lifecycle(record, time.time()) in ("closed", "expired"):
            if record["status"] not in ("closed", "expired"):
                await self.expire(record)
            raise HTTPException(410, "This browser session has expired.")

    async def run(
        self,
        request: BrowseRequest,
        *,
        user_id: str,
        chat_id: str,
        message_id: str,
        vault_key_id: str,
        billing_actor: dict[str, Any] | None = None,
        budget_check: Callable[[int], Awaitable[None]] | None = None,
        prepare_only: bool = False,
        prepared_run_id: str | None = None,
    ) -> BrowseResult | BrowseJob:
        if not user_id or not chat_id or not message_id or not vault_key_id:
            raise HTTPException(401, "An authenticated chat is required for Browse.")
        job = browse_identity(request, user_id, chat_id, message_id)
        run_id, session_id = job.run_id, job.session_id
        prepared = False
        started = time.monotonic()
        stage_times = {
            "startup_seconds": 0.0,
            "observation_seconds": 0.0,
            "action_seconds": 0.0,
        }
        async with self.store.lease(session_id):
            try:
                record = await self.store.load(session_id, user_id, chat_id)
            except HTTPException as exc:
                if request.session_id or exc.status_code != 404:
                    raise
                if not request.start_url:
                    raise HTTPException(422, "A new browser needs a starting URL.")
                record = {
                    "session_id": session_id,
                    "user_id": user_id,
                    "chat_id": chat_id,
                    "vault_key_id": vault_key_id,
                    "status": "paused",
                    "last_activity": time.time(),
                    "active_run": None,
                    "completed_runs": [],
                    "max_credits": request.max_credits,
                    "charged_credits": 0,
                    "runtime_cost_usd": "0",
                    "inference_cost_usd": "0",
                    "private_account": False,
                    "sign_in_origins": [],
                    "provider": None,
                    "pending_calls": {},
                    "model_calls": [],
                }
                await self.store.save(record, create=True)
            try:
                saved = await self.store.load_result(run_id, user_id)
            except HTTPException as exc:
                if exc.status_code != 404:
                    raise
            else:
                return (
                    job.model_copy(update={"dispatch_required": False})
                    if prepare_only
                    else saved
                )
            await self.ensure_live(record)
            if request.session_id and request.max_credits < record["max_credits"]:
                # Never accept a tighter requested cap while spending against a
                # previously authorized, larger window. Changing a session cap
                # requires closing it and explicitly starting another session.
                raise HTTPException(
                    409,
                    "This session has a higher established spending cap. Close it and start a new session to use a lower cap.",
                )
            if record.get("last_result", {}).get("run_id") == run_id:
                return (
                    job.model_copy(update={"dispatch_required": False})
                    if prepare_only
                    else BrowseResult.model_validate(record["last_result"])
                )
            if run_id in record.get("completed_runs", []):
                raise HTTPException(
                    409, "This browser run was already executed; use its saved result."
                )
            if (
                record.get("active_run") == run_id
                and record.get("queued_run") == run_id
            ):
                if prepare_only:
                    return job
                if prepared_run_id == run_id:
                    prepared = True
                    record.pop("queued_run", None)
                else:
                    raise HTTPException(
                        409, "The browser run is queued for its worker."
                    )
            if (record.get("active_run") and not prepared) or record[
                "status"
            ] == "user":
                raise HTTPException(409, "The browser is busy or under your control.")
            if prepared_run_id is not None and not prepared:
                raise HTTPException(
                    409, "This queued browser run was stopped or replaced."
                )
            if len(record["completed_runs"]) >= 64:
                raise HTTPException(409, "Start a new session after sixty-four runs.")
            if record.get("pending_calls"):
                raise HTTPException(
                    409, "The previous browser operation needs usage reconciliation."
                )
            if request.session_id and (
                not record.get("provider") or record["provider"].get("deleted")
            ):
                raise HTTPException(
                    410,
                    "This browser is unavailable; start a new Browse request without its session_id.",
                )
            provider = record.get("provider") or {}
            if (
                provider.get("running_since") is not None
                and provider.get("provider_deadline", 0) <= time.time()
            ):
                # The native idle timeout can pause compute before our sweeper
                # updates the record. Confirm/settle that window before replacing
                # last_activity and admitting the owner's paid resume.
                await self.pause(record)
            # Hold the complete user-authorized cap; credits are debited only on settlement.
            await self.claim_slot(record)
            if not record.get("reservation"):
                if budget_check:
                    await budget_check(
                        record["max_credits"] - record["charged_credits"]
                    )
                record["billing_actor"] = billing_actor
            await self.reserve(record)
            record.update(
                active_run=run_id,
                active_deadline=time.time() + request.timeout_seconds + 100,
                last_activity=time.time(),
                task=request.task,
                request=request.model_dump(),
                status="ai",
            )
            if prepare_only:
                record["queued_run"] = run_id
                record["queued_at"] = time.time()
            await self.store.save(record)

        if prepare_only:
            return job

        async def before_attempt(model: str, host: str, bound: Decimal) -> str:
            async with self.store.lease(session_id):
                current = await self.store.load(session_id, user_id, chat_id)
                if current["status"] != "ai" or current.get("active_run") != run_id:
                    raise BrowseControlChanged()
                if current.get("accounting_pending"):
                    raise BrowserModelError("Browser usage needs reconciliation.")
                other = sum(
                    (
                        Decimal(c["bound_usd"])
                        for c in current.get("pending_calls", {}).values()
                    ),
                    Decimal(0),
                )
                await self.keep_running(current, reserved_usd=other + bound)
                call_id = str(uuid.uuid4())
                current.setdefault("pending_calls", {})[call_id] = {
                    "model": model,
                    "host": host,
                    "bound_usd": str(bound),
                    "run_id": run_id,
                }
                await self.store.save(current)
                return call_id

        async def after_attempt(call_id: str, attempt: dict[str, Any]) -> None:
            async with self.store.lease(session_id):
                current = await self.store.load(session_id, user_id, chat_id)
                if call_id not in current.get("pending_calls", {}):
                    return
                if attempt.get("complete"):
                    current["pending_calls"].pop(call_id)
                    current["inference_cost_usd"] = str(
                        Decimal(current["inference_cost_usd"])
                        + Decimal(attempt["cost_usd"])
                    )
                else:
                    current["accounting_pending"] = True
                current.setdefault("model_calls", []).append(
                    {"call_id": call_id, "run_id": run_id, **attempt}
                )
                current["model_calls"] = current["model_calls"][-512:]
                await self.store.save(current)
                if current["status"] in ("closed", "expired", "paused"):
                    await self.settle(current)

        models = self.models_factory(
            self.secrets,
            private_account=record["private_account"],
            before_attempt=before_attempt,
            after_attempt=after_attempt,
        )
        history = []
        observation = {}
        status, reason = "budget_exceeded", "The browser action limit was reached."
        data = None
        checked_observations = {}
        no_progress = 0
        prior = None
        phase = "startup"
        failure = {}
        try:
            startup_started = time.monotonic()
            driver = await self.browser()
            async with asyncio.timeout(90):
                async with self.store.lease(session_id):
                    record = await self.store.load(session_id, user_id, chat_id)
                    if not record.get("provider"):
                        # The first desktop allocation is bounded to 2 CPU / 4 GiB / 120s.
                        if self.remaining_usd(record) < Decimal("0.0056"):
                            raise BrowseBudgetExceeded(
                                "The spending limit cannot cover browser startup."
                            )

                        validator = getattr(driver, "validate_creation", None)
                        if validator:
                            validator()

                        async def created(provider: dict[str, Any]) -> None:
                            record["provider"] = provider
                            record.pop("startup_intent", None)
                            await self.store.save(record)

                        try:
                            provisioning_started = time.monotonic()
                            if pool_size():
                                async with asyncio.timeout(5):
                                    claimed = await BrowsePool(
                                        self.store, driver
                                    ).claim(session_id, created)
                                    if claimed is None:
                                        raise BrowserAdmissionRejected(
                                            "Prepared browser capacity is temporarily unavailable. Please try again shortly."
                                        )
                                    await self.resume_compute(record)
                                    checked = await driver.rpc(
                                        record["provider"],
                                        {
                                            "operation": "control",
                                            "mode": "ai",
                                            "check_ready": True,
                                            "require_pristine": True,
                                        },
                                    )
                                    if checked.get("pristine") is not True:
                                        raise BrowserUnavailable(
                                            "The blank browser could not be verified."
                                        )
                                    record["provider"]["pool_verified"] = True
                                    await self.store.save(record)
                            else:
                                record["startup_intent"] = {"at": time.time()}
                                await self.store.save(record)
                                await driver.create(
                                    session_id=session_id,
                                    owner=owner_hash(user_id),
                                    on_created=created,
                                )
                            stage_times["provisioning_seconds"] = round(
                                time.monotonic() - provisioning_started, 3
                            )
                        except BrowserAdmissionRejected:
                            record.pop("startup_intent", None)
                            await self.store.save(record)
                            raise
                        navigation_started = time.monotonic()
                        await driver.rpc(
                            record["provider"],
                            {"operation": "navigate", "url": request.start_url},
                        )
                        stage_times["initial_navigation_seconds"] = round(
                            time.monotonic() - navigation_started, 3
                        )
                    elif record["provider"].get("deleted"):
                        raise BrowserUnavailable(
                            "The browser was closed during startup."
                        )
                    elif record["provider"].get("running_since") is None:
                        # Admission is checked before E2B's explicit, paid resume.
                        if self.remaining_usd(record) < Decimal("0.0056"):
                            raise BrowseBudgetExceeded(
                                "The spending limit cannot cover a resumed browser."
                            )
                        await self.resume_compute(record)
                    await self.keep_running(record)
                    await driver.rpc(
                        record["provider"], {"operation": "control", "mode": "ai"}
                    )
                    await self.store.save(record)

            stage_times["startup_seconds"] = round(
                time.monotonic() - startup_started, 3
            )

            async with asyncio.timeout(request.timeout_seconds):
                for _ in range(request.max_steps):
                    async with self.store.lease(session_id):
                        record = await self.store.load(session_id, user_id, chat_id)
                        if (
                            record["status"] != "ai"
                            or record.get("active_run") != run_id
                        ):
                            raise BrowseControlChanged()
                        await self.keep_running(record)
                        with private_inference_logging():
                            phase = "observe"
                            observation_started = time.monotonic()
                            observation = await driver.rpc(
                                record["provider"], {"operation": "observe"}
                            )
                            stage_times["observation_seconds"] += (
                                time.monotonic() - observation_started
                            )
                        from backend.core.api.app.utils.text_sanitization import (
                            sanitize_text_payload_for_ascii_smuggling,
                        )

                        observation, _ = sanitize_text_payload_for_ascii_smuggling(
                            observation, include_stats=True
                        )
                        record["latest_observation"] = observation
                        await self.store.save(record)
                    if observation.get("blocked_reason"):
                        status, reason = "blocked", observation["blocked_reason"]
                        break
                    if observation.get("has_private_input"):
                        status, reason = (
                            "needs_user",
                            "Review the sign-in notice and sign in privately using the browser controls.",
                        )
                        break
                    fingerprint = hashlib.sha256(
                        json.dumps(
                            {
                                k: observation.get(k)
                                for k in ("url", "controls", "tables")
                            },
                            sort_keys=True,
                        ).encode()
                    ).hexdigest()
                    no_progress = no_progress + 1 if fingerprint == prior else 0
                    prior = fingerprint
                    if no_progress >= 3:
                        status, reason = (
                            "needs_user",
                            "Repeated actions made no observable progress.",
                        )
                        break
                    # No execution lease is held during inference. Take control can invalidate
                    # the observation immediately; stale decisions are checked again before input.
                    with private_inference_logging():
                        phase = "decide"
                        action = await models.choose(observation, request.task, history)
                    if action["kind"] == "blocked":
                        status, reason = (
                            "needs_user",
                            action.get(
                                "reason", "The browser needs your help to continue."
                            ),
                        )
                        break
                    if action["kind"] == "done":
                        with private_inference_logging():
                            effective_schema = request.output_schema or {
                                "type": "object"
                            }
                            extraction_context = {
                                "purpose": "extract",
                                "goal": request.task,
                                "output_schema": effective_schema,
                                "private_account": record["private_account"],
                                "observed_page": {
                                    **{
                                        k: observation.get(k)
                                        for k in (
                                            "url",
                                            "title",
                                            "tables",
                                            "links",
                                        )
                                    },
                                    "text": observation.get(
                                        "document_text",
                                        observation.get("text", ""),
                                    ),
                                },
                            }
                            # One repair can recover an incomplete answer from
                            # already observed evidence. It never navigates,
                            # relaxes verification or invents missing facts.
                            for extraction_attempt in range(2):
                                phase = "extract"
                                extracted = await models.generate(extraction_context)
                                data = (
                                    extracted.get("data")
                                    if isinstance(extracted, dict)
                                    else None
                                )
                                if (
                                    extraction_attempt
                                    and data
                                    == extraction_context["correction"][
                                        "previous_candidate"
                                    ]
                                ):
                                    # An unchanged answer cannot seek a
                                    # different stochastic verifier verdict.
                                    break
                                phase = "verify"
                                verified = await models.verify(
                                    request.task, observation, data
                                )
                                if (
                                    verified
                                    or data is None
                                    or extracted.get("needs_user")
                                    or extraction_attempt == 1
                                ):
                                    break
                                extraction_context["correction"] = {
                                    "previous_candidate": data,
                                    "verification": dict(
                                        getattr(models, "verification", {})
                                    ),
                                    "instruction": "The previous candidate failed independent completion checks. Compare every part of the goal with the observed page and correct omissions or unsupported claims using only that evidence. Preserve relevant qualifications and caveats. If the requested facts are unavailable, return needs_user rather than guessing.",
                                }
                        if verified:
                            status, reason = (
                                ("no_results", "The page reported no matching results.")
                                if getattr(models, "no_results", False)
                                else ("completed", None)
                            )
                            validator = Draft202012Validator(effective_schema)
                            if status == "no_results" and not validator.is_valid(data):
                                data = None  # An empty search cannot satisfy a schema demanding records.
                            elif status == "completed":
                                validator.validate(data)
                        else:
                            status, reason = (
                                "needs_user",
                                "The observed page does not establish every requested result.",
                            )
                        break
                    async with self.store.lease(session_id):
                        record = await self.store.load(session_id, user_id, chat_id)
                        if (
                            record["status"] != "ai"
                            or record.get("active_run") != run_id
                        ):
                            raise BrowseControlChanged()
                        # Journal the intention before crossing the irreversible input boundary.
                        action_id = str(uuid.uuid4())
                        record["pending_action"] = {
                            "id": action_id,
                            "run_id": run_id,
                            "kind": action["kind"],
                            "observation_id": observation["observation_id"],
                        }
                        await self.store.save(record)
                        with private_inference_logging():
                            phase = "act"
                            action_started = time.monotonic()
                            await driver.rpc(
                                record["provider"],
                                {
                                    "operation": "act",
                                    "observation_id": observation["observation_id"],
                                    **action,
                                },
                            )
                            stage_times["action_seconds"] += (
                                time.monotonic() - action_started
                            )
                        history.append(
                            {"kind": action["kind"], "target": action.get("target")}
                        )
                        record["last_action"] = {
                            **record.pop("pending_action"),
                            "outcome": "executed",
                        }
                        if action["kind"] != "wait" and fingerprint != record.get(
                            "last_progress_fingerprint"
                        ):
                            record["last_activity"] = time.time()
                            record["last_progress_fingerprint"] = fingerprint
                        await self.store.save(record)
                if status in ("completed", "no_results"):
                    with private_inference_logging():
                        phase = "scan"
                        checked = await models.sanitize_external(
                            {
                                "data": data,
                                "observations": {
                                    **{
                                        k: observation.get(k)
                                        for k in ("url", "title", "tables", "links")
                                    },
                                    "text": observation.get(
                                        "document_text", observation.get("text", "")
                                    ),
                                },
                            },
                            self.store.cache,
                        )
                    data = checked["data"]
                    checked_observations = checked["observations"]
                    if request.output_schema and data is not None:
                        Draft202012Validator(request.output_schema).validate(data)
        except BrowseControlChanged:
            status, reason = (
                "needs_user",
                "Browser control changed; pending AI input was discarded.",
            )
        except BrowseBudgetExceeded as exc:
            status, reason = "budget_exceeded", str(exc)
        except TimeoutError:
            status, reason = "budget_exceeded", "The browser time limit was reached."
        except asyncio.CancelledError:
            status, reason = "cancelled", "The browser request was cancelled."
            raise
        except StrictSafetyUnavailable:
            status, reason = (
                "needs_user",
                "The page could not be safely checked. Take control to continue.",
            )
        except (BrowserModelError, BrowserUnavailable) as exc:
            failure = {"error_kind": type(exc).__name__, "error_phase": phase}
            if isinstance(getattr(exc, "status_code", None), int):
                failure["rpc_status_code"] = exc.status_code
            status, reason = (
                "failed",
                str(exc)
                if isinstance(exc, BrowserAdmissionRejected)
                else "The browser or decision provider could not complete this task.",
            )
        except Exception:
            status, reason = (
                "failed",
                "The browser could not produce a verified result matching the requested data.",
            )
        finally:
            async with self.store.lease(session_id):
                record = await self.store.load(session_id, user_id, chat_id)
                if record.get("active_run") == run_id:
                    record["active_run"] = None
                if record.get("pending_action"):
                    status, reason = (
                        "needs_user",
                        "An action outcome is uncertain; review the page before continuing.",
                    )
                if (
                    record.get("pending_calls")
                    or record.get("startup_intent")
                    or record.get("runtime_intent")
                ):
                    record["accounting_pending"] = True
                    status, reason = (
                        "failed",
                        "Browser usage is awaiting reconciliation.",
                    )
                if (record.get("provider") or {}).get("pool_assigned") and not record[
                    "provider"
                ].get("pool_verified"):
                    # No model, viewer or manual input may see a failed initial
                    # pristine-state check. This VM is destroyed, never recycled.
                    await self.expire(record, "closed")
                if record["status"] == "user":
                    status, reason = "needs_user", "You have control of this browser."
                if record["status"] in ("closed", "expired"):
                    status, reason = "cancelled", "This browser session is closed."
                if status in ("completed", "no_results"):
                    record["last_activity"] = time.time()
                else:
                    data = None  # Rejected extraction cannot expose proposed facts as observed data.
                if status in ("budget_exceeded", "failed", "cancelled") and record[
                    "status"
                ] not in ("user", "closed", "expired"):
                    await self.pause(record)
                record["completed_runs"].append(run_id)
                metrics = {
                    "total_seconds": round(time.monotonic() - started, 3),
                    "steps": len(history),
                    "model_calls": models.attempts,
                    "supplier_cost_usd": str(self.total_cost(record)),
                    "accrued_credits": charged_credits(self.total_cost(record)),
                    "charged_credits": record["charged_credits"],
                    "accounting_pending": bool(record.get("accounting_pending")),
                    "runtime_cost_usd": str(self.runtime_cost(record)),
                    "inference_cost_usd": record["inference_cost_usd"],
                    "verification": getattr(models, "verification", {}),
                    **failure,
                    **{k: round(v, 3) for k, v in stage_times.items()},
                }
                result = BrowseResult(
                    session_id=session_id,
                    run_id=run_id,
                    status=status,
                    reason=reason,
                    url=observation.get("url", ""),
                    title=checked_observations.get("title", "Browse"),
                    data=data,
                    sources=[
                        {
                            "url": observation["url"],
                            "title": checked_observations.get("title", ""),
                        }
                    ]
                    if observation.get("url")
                    else [],
                    screenshot_base64=observation.get("screenshot"),
                    observations=checked_observations
                    if status in ("completed", "no_results")
                    else {},
                    screenshot_ref={
                        "storage": "encrypted_result",
                        "field": "screenshot_base64",
                        "run_id": run_id,
                    }
                    if observation.get("screenshot")
                    else None,
                    metrics=metrics,
                )
                result = await self.store.save_result(result, record)
                record["last_result"] = result.model_dump()
                await self.store.save(record)
        return result

    async def finish_failed_job(
        self, session_id: str, run_id: str, user_id: str, chat_id: str
    ) -> BrowseResult:
        """Terminalize an admitted worker error without starting or repeating work."""
        async with self.store.lease(session_id):
            record = await self.store.load(session_id, user_id, chat_id)
            try:
                return await self.store.load_result(run_id, user_id)
            except HTTPException as exc:
                if exc.status_code != 404:
                    raise
            cancelled = record["status"] in ("paused", "closed", "expired") or (
                record.get("active_run") != run_id
            )
            if record.get("active_run") == run_id:
                record["active_run"] = None
                record.pop("queued_run", None)
                if (
                    record.get("pending_calls")
                    or record.get("startup_intent")
                    or record.get("runtime_intent")
                ):
                    record["accounting_pending"] = True
                if record["status"] == "ai":
                    await self.pause(record)
            result = BrowseResult(
                session_id=session_id,
                run_id=run_id,
                status="cancelled" if cancelled else "failed",
                reason="The queued browser run was stopped or is no longer available."
                if cancelled
                else "The browser worker could not finish this run.",
                metrics={
                    "supplier_cost_usd": str(self.total_cost(record)),
                    "charged_credits": record.get("charged_credits", 0),
                    "accounting_pending": bool(record.get("accounting_pending")),
                },
            )
            result = await self.store.save_result(result, record)
            if run_id not in record["completed_runs"]:
                record["completed_runs"].append(run_id)
            if not record.get("active_run"):
                record["last_result"] = result.model_dump()
            await self.store.save(record)
            return result

    async def control(
        self, session_id: str, user_id: str, command: BrowseControl
    ) -> dict[str, Any]:
        async with self.store.lease(session_id):
            record = await self.store.load(session_id, user_id)
            await self.ensure_live(record)
            driver = await self.browser()
            op = command.operation
            if (
                op not in ("close", "stop")
                and (record.get("provider") or {}).get("pool_assigned")
                and not record["provider"].get("pool_verified")
            ):
                raise HTTPException(
                    409, "The browser is still completing its ownership checks."
                )
            if op == "close":
                await self.expire(record, "closed")
            elif op == "stop":
                await self.pause(record)
            elif op in ("resume", "take_control", "sign_in"):
                if not record.get("provider") or record["provider"].get("deleted"):
                    raise HTTPException(409, "No live browser is available.")
                if op == "sign_in":
                    # Validate against the live page before granting consent or paid work.
                    if record["status"] != "user":
                        raise HTTPException(409, "Take control before signing in.")
                    metadata = await driver.rpc(
                        record["provider"], {"operation": "metadata"}
                    )
                    origin = metadata["origin"]
                    if command.sign_in_origin != origin:
                        raise HTTPException(
                            409, "The sign-in site changed; review the notice again."
                        )
                was_paused = record["status"] == "paused"
                if was_paused and self.remaining_usd(record) < Decimal("0.0056"):
                    raise HTTPException(
                        402, "The spending limit cannot cover a resumed browser."
                    )
                if was_paused:
                    await self.claim_slot(record)
                await self.reserve(record)
                if was_paused:
                    await self.resume_compute(record)
                mode = "ai" if op == "resume" else "user"
                await driver.rpc(
                    record["provider"], {"operation": "control", "mode": mode}
                )
                record["status"] = mode
                record["active_run"] = None
                record["last_activity"] = time.time()
                if op == "sign_in":
                    await driver.rpc(
                        record["provider"],
                        {"operation": "sign_in_consent", "origin": origin},
                    )
                    record["sign_in_origins"] = list(
                        set(record["sign_in_origins"] + [origin])
                    )
                    record["private_account"] = True
                record.pop(
                    "pending_action", None
                )  # User reviewed the uncertain state before explicit handoff.
                await self.keep_running(record)
                await self.store.save(record)
            elif op == "input":
                if record["status"] != "user" or not command.action:
                    raise HTTPException(
                        409, "Take control before entering browser input."
                    )
                if self.remaining_usd(record) < Decimal("0.0005"):
                    await self.pause(record)
                    raise HTTPException(402, "The browser spending limit was reached.")
                with private_inference_logging():
                    reply = await driver.rpc(
                        record["provider"],
                        {
                            **command.action.model_dump(exclude_none=True),
                            "operation": "manual",
                        },
                    )
                if reply.get("needs_sign_in_consent"):
                    return {
                        **self.public_state(record),
                        "needs_sign_in_consent": True,
                        "sign_in_origin": reply["origin"],
                    }
                record["last_activity"] = time.time()
                await self.keep_running(record)
                await self.store.save(record)
            return self.public_state(record)

    def public_state(self, record: dict[str, Any]) -> dict[str, Any]:
        return {
            "session_id": record["session_id"],
            "status": record["status"],
            "chat_id": record["chat_id"],
            "task": record.get("task", ""),
            "url": (record.get("latest_observation") or {}).get("url", ""),
            "sign_in_notice": SIGN_IN_NOTICE,
            "sign_in_origins": record.get("sign_in_origins", []),
            "accounting_pending": bool(record.get("accounting_pending")),
            "expires_at": record["last_activity"] + IDLE_DELETE_SECONDS,
            "max_credits": record["max_credits"],
            "accrued_credits": charged_credits(self.total_cost(record)),
            "charged_credits": record.get("charged_credits", 0),
        }

    async def state(self, session_id: str, user_id: str) -> dict[str, Any]:
        async with self.store.lease(session_id):
            record = await self.store.load(session_id, user_id)
            await self.ensure_live(record)
            if (
                record["status"] not in ("paused", "closed", "expired")
                and record.get("provider")
                and record["provider"].get("provider_deadline", 0) < time.time()
            ):
                await self.pause(record)
            return self.public_state(record)

    async def frame(self, session_id: str, user_id: str) -> bytes:
        import base64

        await self.state(session_id, user_id)
        record = await self.store.load(session_id, user_id)
        if not record.get("provider"):
            raise HTTPException(
                404, "The browser has not produced its first frame yet."
            )
        if record["provider"].get("pool_assigned") and not record["provider"].get(
            "pool_verified"
        ):
            raise HTTPException(
                409, "The browser is still completing its ownership checks."
            )
        if record["status"] == "paused":
            image = (record.get("latest_observation") or {}).get("screenshot")
        else:
            with private_inference_logging():
                image = (
                    await (await self.browser()).rpc(
                        record["provider"], {"operation": "frame"}
                    )
                ).get("image")
        if not image:
            raise HTTPException(404, "No browser frame is available.")
        return base64.b64decode(image, validate=True)

    async def sweep(self) -> int:
        now = int(time.time())
        expired_results = await self.store.db.get_items(
            "browser_runs",
            params={
                "filter[expires_at][_lte]": now,
                "fields": "id",
                "limit": 100,
                "sort": "expires_at",
            },
            no_cache=True,
            admin_required=True,
            raise_on_error=True,
        )
        if expired_results and not await self.store.db.bulk_delete_items(
            "browser_runs", [r["id"] for r in expired_results]
        ):
            logger.warning("Expired browser result cleanup requires retry.")
        # Query each cleanup class independently. Old unresolved reservations
        # must not monopolize a combined limit and starve expired credentials.
        filters = [
            {"status": {"_nin": ["closed", "expired"]}, "expires_at": {"_lte": now}},
            {
                "status": {"_nin": ["closed", "expired", "paused"]},
                "last_activity": {"_lte": now - 120},
            },
            {
                "status": {"_in": ["closed", "expired", "paused"]},
                "needs_reconciliation": {"_eq": True},
            },
        ]
        by_id = {}
        for due in filters:
            batch = await self.store.db.get_items(
                COLLECTION,
                params={
                    "filter": json.dumps(due),
                    "fields": "id",
                    "sort": "expires_at",
                    "limit": 100,
                },
                no_cache=True,
                admin_required=True,
                raise_on_error=True,
            )
            by_id.update((row["id"], row) for row in batch)
        rows = list(by_id.values())
        count = 0
        for row in rows:
            try:
                async with self.store.lease(row["id"]):
                    record = await self.store.load(row["id"], None)
                    if (
                        record.get("active_run")
                        and record.get("active_deadline", 0) < time.time()
                    ):
                        record["active_run"] = None
                        if record.get("pending_calls"):
                            record["accounting_pending"] = True
                    state = session_lifecycle(record, time.time())
                    if state == "expired":
                        await self.expire(record)
                        count += 1
                    elif state == "paused" and record["status"] != "paused":
                        await self.pause(record)
                        count += 1
                    elif record["status"] in ("closed", "expired", "paused"):
                        await self.settle(record)
            except Exception:
                # One failed provider/persistence operation cannot starve other owners' cleanup.
                logger.warning("Browser cleanup requires retry for an owned session.")
        try:
            if "E2B_BROWSE_POOL_SIZE" in os.environ:
                count += await BrowsePool(self.store, await self.browser()).sweep()
            count += await self.sweep_orphans()
        except Exception:
            logger.warning("Browser provider inventory requires a cleanup retry.")
        return count

    async def sweep_orphans(self) -> int:
        """Reconcile create-response crashes without resuming any remote machine."""
        driver = await self.browser()
        if not hasattr(driver, "inventory_page"):
            return 0
        redis = await self.store.cache.client
        cursor_key = "web_browse:inventory_cursor:" + driver.scope
        cursor = await redis.get(cursor_key)
        if isinstance(cursor, bytes):
            cursor = cursor.decode()
        machines, next_cursor = await driver.inventory_page(cursor)
        count = 0
        for info in machines:
            try:
                if info.metadata.get("openmates_owner_hash") == owner_hash(
                    "platform-blank-pool:" + driver.scope
                ):
                    pool = BrowsePool(self.store, driver)
                    if await pool.retain_native(info):
                        continue
                    if time.time() - info.started_at.timestamp() >= 180:
                        await driver.kill({"sandbox_id": info.sandbox_id})
                        count += 1
                    continue
                session_id = str(uuid.UUID(info.metadata["openmates_browser_session"]))
                if time.time() - info.started_at.timestamp() < 180:
                    continue
                async with self.store.lease(session_id):
                    rows = await self.store.db.get_items(
                        COLLECTION,
                        params={
                            "filter[id][_eq]": session_id,
                            "fields": "id,expires_at,owner_hash",
                            "limit": 1,
                        },
                        no_cache=True,
                        admin_required=True,
                        raise_on_error=True,
                    )
                    record = None
                    if rows and rows[0]["expires_at"] > time.time():
                        record = await self.store.load(session_id, None)
                        if (record.get("provider") or {}).get(
                            "sandbox_id"
                        ) == info.sandbox_id:
                            continue
                    # Missing/expired rows and unmatched handles cannot preserve a
                    # paid browser or an indefinitely paused credential snapshot.
                    await driver.kill({"sandbox_id": info.sandbox_id})
                    count += 1
                    if record is not None and not record.get("provider"):
                        end = min(
                            time.time(),
                            info.end_at.timestamp(),
                            info.started_at.timestamp() + 120,
                        )
                        rate = Decimal(info.cpu_count) * Decimal("0.000014") + Decimal(
                            info.memory_mb
                        ) / 1024 * Decimal("0.0000045")
                        record["runtime_cost_usd"] = str(
                            Decimal(record["runtime_cost_usd"])
                            + Decimal(str(max(0, end - info.started_at.timestamp())))
                            * rate
                        )
                        record["status"] = "paused"
                        record["active_run"] = None
                        record.pop("startup_intent", None)
                        record["accounting_pending"] = bool(record.get("pending_calls"))
                        await self.store.save(record)
                        await self.settle(record)
            except Exception:
                logger.warning("An orphan browser requires a cleanup retry.")
        if next_cursor:
            await redis.set(cursor_key, next_cursor, ex=86400)
        else:
            await redis.delete(cursor_key)
        return count
