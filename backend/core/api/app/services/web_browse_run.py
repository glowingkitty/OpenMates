"""Browse v2 run loop: one start call, planner steps, the evidence ledger and the answer.

`BrowseService.run` owns admission, identity, replay and the final saved result
with settlement. `BrowseRun.execute` owns everything in between:

1. Startup: pool claim or create, then one `start` RPC (navigation, settle and
   the first observation). An existing session resumes and calls `observe`.
2. Steps: one planner call, one Jev gate call, code-checked notes into the
   ledger, then one `step` RPC for the planned batch under the session lease
   with a pending-action journal entry.
3. Finish: one extraction from the ledger plus the current page, code leaf
   matching, one Jev verification and, when needed, a partial answer that
   lists the `missing` paths. Output safety scanning runs last.

The run never holds the session lease during model calls; take-over is
detected by reloading the record before any input crosses to the browser.
Exceptions propagate to `BrowseService.run`, which maps them to statuses.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
import hashlib
import json
import time
from typing import Any, TYPE_CHECKING
import uuid

from jsonschema import Draft202012Validator

from backend.core.api.app.services.web_browse_evidence import (
    accept_notes,
    check_answer,
    extraction_context,
    page_text,
    partial_answer,
)
from backend.core.api.app.services.web_browse_pool import BrowsePool, pool_size
from backend.shared.providers.browser_planner import BLOCK_REASONS, control_index
from backend.shared.providers.e2b_browser import (
    BrowserAdmissionRejected,
    BrowserUnavailable,
)
from backend.shared.python_schemas.web_browse import owner_hash
from backend.shared.python_utils.private_inference_logging import (
    private_inference_logging,
)

if TYPE_CHECKING:
    from backend.core.api.app.services.web_browse_service import BrowseService
    from backend.shared.python_schemas.web_browse import BrowseRequest

RUNTIME_PROTOCOL = "preboot-v2"
STEP_HISTORY = 80
START_TIMINGS = ("ready", "pristine", "navigate", "settle", "observe")
PARTIAL_REASON = (
    "Partial result: some requested values could not be confirmed on the visited "
    "pages and are listed as missing."
)


class BrowseBudgetExceeded(RuntimeError):
    pass


class BrowseControlChanged(RuntimeError):
    pass


class BrowserRuntimeOutdated(BrowserUnavailable):
    """The VM runs a runtime without the `start`/`step` protocol."""


def require_protocol(reply: dict[str, Any]) -> None:
    if reply.get("runtime_protocol") != RUNTIME_PROTOCOL:
        raise BrowserRuntimeOutdated(
            "This browser runs an outdated runtime; start a new Browse session."
        )


def fingerprint(observation: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                **{k: observation.get(k) for k in ("url", "controls", "tables")},
                # Scrolling is progress: it moves the planner's document excerpt.
                "y": (observation.get("scroll") or {}).get("y"),
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()


class BrowseRun:
    """One admitted run between admission and the final result."""

    def __init__(
        self,
        service: "BrowseService",
        request: "BrowseRequest",
        *,
        run_id: str,
        session_id: str,
        user_id: str,
        chat_id: str,
        models: Any,
        private_account: bool,
    ) -> None:
        self.service = service
        self.request = request
        self.run_id = run_id
        self.session_id = session_id
        self.user_id = user_id
        self.chat_id = chat_id
        self.models = models
        self.private_account = private_account
        self.schema = request.output_schema or {"type": "object"}
        self.started = time.monotonic()
        self.store_started = service.store.elapsed
        # Outputs read by BrowseService.run's final block.
        self.status = "budget_exceeded"
        self.reason: str | None = "The browser action limit was reached."
        self.data: Any = None
        self.missing: list[str] = []
        self.sources: list[dict[str, Any]] = []
        self.observation: dict[str, Any] = {}
        self.checked_observations: dict[str, Any] = {}
        self.phase = "startup"
        # Loop state.
        self.ledger: list[dict[str, Any]] = []
        self.history: list[dict[str, Any]] = []
        self.pages: set[str] = set()
        self.executed = 0
        self.planner_steps = 0
        self.rejected_notes = 0
        self.dropped_notes = 0
        self.no_progress = 0
        self.prior: str | None = None
        self.stage: dict[str, float] = {
            "startup_seconds": 0.0,
            "start_rpc_seconds": 0.0,
            "planner_seconds": 0.0,
            "gate_seconds": 0.0,
            "step_rpc_seconds": 0.0,
            "extract_seconds": 0.0,
            "verify_seconds": 0.0,
        }

    @property
    def store(self) -> Any:
        return self.service.store

    async def load(self) -> dict[str, Any]:
        return await self.store.load(self.session_id, self.user_id, self.chat_id)

    async def load_active(self) -> dict[str, Any]:
        record = await self.load()
        if record["status"] != "ai" or record.get("active_run") != self.run_id:
            raise BrowseControlChanged()
        return record

    def finish(self, status: str, reason: str | None) -> bool:
        self.status, self.reason = status, reason
        return True

    def metrics(self) -> dict[str, Any]:
        return {
            "steps": self.executed,
            "planner_steps": self.planner_steps,
            "rejected_notes": self.rejected_notes,
            "dropped_notes": self.dropped_notes,
            "pages_visited": len(self.pages),
            "evidence_notes": sum(len(p["notes"]) for p in self.ledger),
            "store_seconds": self.store.elapsed - self.store_started,
            **self.stage,
        }

    async def execute(self) -> None:
        driver = await self.service.browser()
        await self.startup(driver)
        async with asyncio.timeout(self.request.timeout_seconds):
            for _ in range(self.request.max_steps):
                if await self.step(driver):
                    break
            if self.status in ("completed", "no_results"):
                await self.scan()

    # Startup -----------------------------------------------------------------

    async def startup(self, driver: Any) -> None:
        started = time.monotonic()
        async with asyncio.timeout(90):
            async with self.store.lease(self.session_id):
                record = await self.load()
                self.ledger = list(record.get("evidence") or [])
                if not record.get("provider"):
                    observation = await self.provision(record, driver)
                elif record["provider"].get("deleted"):
                    raise BrowserUnavailable("The browser was closed during startup.")
                else:
                    observation = await self.reopen(record, driver)
                await self.service.keep_running(record)
                self.adopt(record, observation)
                self.stage["first_observation_seconds"] = time.monotonic() - started
                record["phase"] = "working"
                await self.store.save(record)
        self.stage["startup_seconds"] = time.monotonic() - started

    async def provision(self, record: dict[str, Any], driver: Any) -> dict[str, Any]:
        # The first desktop allocation is bounded to 2 CPU / 4 GiB / 120s.
        if self.service.remaining_usd(record) < Decimal("0.0056"):
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

        pooled = bool(pool_size())
        provisioning = time.monotonic()
        try:
            if pooled:
                async with asyncio.timeout(5):
                    claim_started = time.monotonic()
                    claimed = await BrowsePool(self.store, driver).claim(
                        self.session_id, created
                    )
                    self.stage["pool_claim_seconds"] = time.monotonic() - claim_started
                    if claimed is None:
                        raise BrowserAdmissionRejected(
                            "Prepared browser capacity is temporarily unavailable. Please try again shortly."
                        )
                    resume_started = time.monotonic()
                    await self.service.resume_compute(record)
                    self.stage["resume_seconds"] = time.monotonic() - resume_started
            else:
                record["startup_intent"] = {"at": time.time()}
                await self.store.save(record)
                await driver.create(
                    session_id=self.session_id,
                    owner=owner_hash(self.user_id),
                    on_created=created,
                )
        except BrowserAdmissionRejected:
            record.pop("startup_intent", None)
            await self.store.save(record)
            raise
        self.stage["provisioning_seconds"] = time.monotonic() - provisioning
        reply = await self.start_rpc(driver, record, require_pristine=pooled)
        if pooled:
            # No model, viewer or manual input may see a VM whose blank state
            # was not proven inside the same start call.
            if reply.get("pristine") is not True:
                raise BrowserUnavailable("The blank browser could not be verified.")
            record["provider"]["pool_verified"] = True
        observation = reply.get("observation")
        if not isinstance(observation, dict):
            raise BrowserUnavailable("The browser did not return an observation.")
        return observation

    async def start_rpc(
        self, driver: Any, record: dict[str, Any], *, require_pristine: bool
    ) -> dict[str, Any]:
        started = time.monotonic()
        with private_inference_logging():
            reply = await driver.rpc(
                record["provider"],
                {
                    "operation": "start",
                    "url": self.request.start_url,
                    "require_pristine": require_pristine,
                },
            )
        self.stage["start_rpc_seconds"] = time.monotonic() - started
        require_protocol(reply)
        timings = reply.get("timings") or {}
        for key in START_TIMINGS:
            if isinstance(timings.get(key), (int, float)):
                self.stage[f"start_{key}_seconds"] = float(timings[key])
        return reply

    async def reopen(self, record: dict[str, Any], driver: Any) -> dict[str, Any]:
        if record["provider"].get("running_since") is None:
            # Admission is checked before E2B's explicit, paid resume.
            if self.service.remaining_usd(record) < Decimal("0.0056"):
                raise BrowseBudgetExceeded(
                    "The spending limit cannot cover a resumed browser."
                )
            await self.service.resume_compute(record)
        await self.service.keep_running(record)
        started = time.monotonic()
        require_protocol(
            await driver.rpc(record["provider"], {"operation": "control", "mode": "ai"})
        )
        with private_inference_logging():
            observation = await driver.rpc(
                record["provider"], {"operation": "observe", "screenshot": True}
            )
        self.stage["start_rpc_seconds"] = time.monotonic() - started
        return observation

    def adopt(self, record: dict[str, Any], observation: dict[str, Any]) -> None:
        """Clean and store the newest observation; the screenshot is kept once."""
        from backend.core.api.app.utils.text_sanitization import (
            sanitize_text_payload_for_ascii_smuggling,
        )

        observation = {k: v for k, v in observation.items() if k != "_rpc_timings"}
        observation, _ = sanitize_text_payload_for_ascii_smuggling(
            observation, include_stats=True
        )
        self.observation = observation
        if observation.get("url"):
            self.pages.add(observation["url"])
        record["latest_observation"] = observation

    # Steps -------------------------------------------------------------------

    async def step(self, driver: Any) -> bool:
        """Run one planner step; True when the run reached its outcome."""
        observation = self.observation
        if observation.get("blocked_reason"):
            return self.finish("blocked", observation["blocked_reason"])
        if observation.get("has_private_input"):
            return self.finish(
                "needs_user",
                "Review the sign-in notice and sign in privately using the browser controls.",
            )
        current = fingerprint(observation)
        self.no_progress = self.no_progress + 1 if current == self.prior else 0
        self.prior = current
        if self.no_progress >= 3:
            return self.finish(
                "needs_user", "Repeated actions made no observable progress."
            )
        self.planner_steps += 1
        # No execution lease is held during inference. Take control can
        # invalidate the observation; control is checked again before input.
        with private_inference_logging():
            self.phase = "plan"
            started = time.monotonic()
            plan = await self.models.plan(
                task=self.request.task,
                output_schema=self.schema,
                observation=observation,
                ledger=self.ledger,
                history=self.history,
            )
            self.stage["planner_seconds"] += time.monotonic() - started
        if plan["blocked"]:
            return self.finish("needs_user", BLOCK_REASONS[plan["blocked"]])
        with private_inference_logging():
            self.phase = "gate"
            started = time.monotonic()
            denial = await self.models.gate(
                self.request.task, observation, plan["actions"]
            )
            self.stage["gate_seconds"] += time.monotonic() - started
        if denial:
            return self.finish("needs_user", denial)
        notes = accept_notes(self.ledger, observation, plan["notes"])
        self.rejected_notes += notes.rejected
        self.dropped_notes += notes.dropped
        if plan["done"]:
            await self.answer()
            return True
        return await self.act(driver, plan["actions"], current)

    def record_steps(
        self, record: dict[str, Any], actions: list[dict[str, Any]]
    ) -> None:
        """Viewer step list: target labels only, never typed text."""
        controls = control_index(self.observation)
        count = record.get("step_count", 0)
        steps = record.setdefault("steps", [])
        for action in actions:
            count += 1
            label = controls.get(str(action.get("target")), {}).get("label") or ""
            steps.append(
                {
                    "n": count,
                    "kind": action["kind"],
                    "label": str(label)[:80],
                    "url": self.observation.get("url", ""),
                    "at": time.time(),
                }
            )
        record["steps"] = steps[-STEP_HISTORY:]
        record["step_count"] = count

    async def act(
        self, driver: Any, actions: list[dict[str, Any]], current: str
    ) -> bool:
        async with self.store.lease(self.session_id):
            record = await self.load_active()
            await self.service.keep_running(record)
            # Journal the batch before crossing the irreversible input boundary.
            record["pending_action"] = {
                "id": str(uuid.uuid4()),
                "run_id": self.run_id,
                "kinds": [a["kind"] for a in actions],
                "observation_id": self.observation["observation_id"],
            }
            record["evidence"] = self.ledger
            self.record_steps(record, actions)
            await self.store.save(record)
            with private_inference_logging():
                self.phase = "step"
                started = time.monotonic()
                reply = await driver.rpc(
                    record["provider"],
                    {
                        "operation": "step",
                        "observation_id": self.observation["observation_id"],
                        "actions": actions,
                        "screenshot": True,
                    },
                )
                self.stage["step_rpc_seconds"] += time.monotonic() - started
            results = reply.get("results")
            if (
                not isinstance(results, list)
                or not isinstance(reply.get("observation"), dict)
                or any(
                    not isinstance(r, dict) or r.get("outcome") == "uncertain"
                    for r in results
                )
            ):
                # The journal stays; the final block reports the uncertain input.
                return self.finish(
                    "needs_user",
                    "An action outcome is uncertain; review the page before continuing.",
                )
            outcomes = [r.get("outcome") for r in results]
            self.history.extend(
                {
                    "kind": r.get("kind"),
                    "target": r.get("target"),
                    "outcome": r.get("outcome"),
                }
                for r in results
            )
            self.history = self.history[-8:]
            self.executed += outcomes.count("executed")
            self.adopt(record, reply["observation"])
            record["last_action"] = {
                **record.pop("pending_action"),
                "outcomes": outcomes,
            }
            progressed = any(
                r.get("outcome") == "executed" and r.get("kind") != "wait"
                for r in results
            )
            if progressed and current != record.get("last_progress_fingerprint"):
                record["last_activity"] = time.time()
                record["last_progress_fingerprint"] = current
            await self.store.save(record)
        return False

    # Answer ------------------------------------------------------------------

    async def answer(self) -> None:
        """Extract once, verify once, and fall back to a code-matched partial answer."""
        self.phase = "extract"
        async with self.store.lease(self.session_id):
            record = await self.load_active()
            record["phase"] = "finishing"
            record["evidence"] = self.ledger
            await self.store.save(record)
        observation = self.observation
        with private_inference_logging():
            started = time.monotonic()
            extracted = await self.models.generate(
                extraction_context(
                    task=self.request.task,
                    schema=self.schema,
                    ledger=self.ledger,
                    observation=observation,
                    private_account=self.private_account,
                )
            )
            self.stage["extract_seconds"] += time.monotonic() - started
            data = extracted.get("data") if isinstance(extracted, dict) else None
            self.phase = "verify"
            started = time.monotonic()
            verified = await self.models.verify(
                self.request.task, observation, data, evidence=self.ledger
            )
            self.stage["verify_seconds"] += time.monotonic() - started
        check = check_answer(data, self.schema, self.ledger, observation)
        validator = Draft202012Validator(self.schema)
        if verified:
            if getattr(self.models, "no_results", False):
                self.finish("no_results", "The page reported no matching results.")
                # An empty search cannot satisfy a schema demanding records.
                self.data = data if validator.is_valid(data) else None
            else:
                validator.validate(data)
                self.finish("completed", None)
                self.data = data
            self.sources = check.sources
            return
        interaction = getattr(self.models, "verification", {}).get(
            "interaction_score", 0.0
        )
        if (
            data is not None
            and interaction >= 0.95
            and partial_answer(check, self.schema)
        ):
            self.finish("completed", PARTIAL_REASON)
            self.data = check.pruned
            self.missing = check.missing
            self.sources = check.sources
            return
        self.finish(
            "needs_user", "The observed pages do not establish every requested result."
        )

    async def scan(self) -> None:
        """Mandatory output safety on returned data, sources and observations."""
        with private_inference_logging():
            self.phase = "scan"
            checked = await self.models.sanitize_external(
                {
                    "data": self.data,
                    "missing": self.missing,
                    "sources": self.sources,
                    "observations": {
                        **{
                            k: self.observation.get(k)
                            for k in ("url", "title", "tables", "links")
                        },
                        "text": page_text(self.observation),
                    },
                },
                self.store.cache,
            )
        self.data = checked["data"]
        self.missing = checked["missing"]
        self.sources = checked["sources"]
        self.checked_observations = checked["observations"]
        if self.request.output_schema and self.data is not None:
            Draft202012Validator(self.request.output_schema).validate(self.data)
