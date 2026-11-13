"""Browse v2 run loop: one start call, planner steps, the evidence ledger and the answer.

`BrowseService.run` owns admission, identity, replay and the final saved result
with settlement. `BrowseRun.execute` owns everything in between:

1. Startup: pool claim or create, then one `start` RPC (navigation, settle and
   the first observation). An existing session resumes and calls `observe`.
2. Steps: one planner call, one Jev gate call, code-checked notes into the
   ledger, then one `step` RPC for the planned batch under the session lease
   with a pending-action journal entry.
3. Finish: one extraction from the ledger plus the current page, code leaf
   matching, one Jev verification with the run's interaction history and,
   when Jev does not accept but code matched part of the answer, one
   text-helper review of the pruned answer. A grounded review with finished
   interactions completes the run, partially with `missing` paths when
   something was pruned or the review found the answer incomplete. Output
   safety scanning runs last.

The ledger and viewer steps of a session carry over only to a run with the
same task text (a continuation after needs_user or take-over); a new task on
the session starts with an empty ledger.

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
from jsonschema.exceptions import best_match

from backend.core.api.app.services.web_browse_evidence import (
    accept_notes,
    check_answer,
    coerce_numbers,
    drop_invalid,
    extraction_context,
    json_type,
    page_text,
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
# Fixed rejection reasons of the browser runtime (`STEP_DENIED` and the robots
# refusal); any other detail text is dropped before the planner sees it.
SCHEMA_ERROR_KEYWORDS = frozenset(
    {
        "type",
        "required",
        "minItems",
        "maxItems",
        "minLength",
        "maxLength",
        "enum",
        "const",
        "pattern",
        "format",
        "additionalProperties",
        "minimum",
        "maximum",
        "anyOf",
        "oneOf",
    }
)
REJECTION_DETAILS = frozenset(
    {"Target is stale, hidden or covered", "Crawler access denied"}
)
START_TIMINGS = ("ready", "pristine", "navigate", "settle", "observe")
PARTIAL_REASON = (
    "Partial result: the visited pages do not establish every requested value; "
    "values that could not be confirmed are listed as missing."
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


def task_hash(task: str) -> str:
    """Binds a saved ledger to the task text that produced it."""
    return hashlib.sha256(task.encode()).hexdigest()


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
        # Ordered run-level trail of executed steps; never typed text.
        self.trail: list[dict[str, Any]] = []
        self.pages: dict[str, None] = {}
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
                digest = task_hash(self.request.task)
                if record.get("evidence_task") != digest:
                    # A different task never inherits another task's evidence.
                    for key in ("evidence", "steps", "step_count"):
                        record.pop(key, None)
                    record["evidence_task"] = digest
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
            self.pages.setdefault(observation["url"])
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
        self.rejected_notes += notes.rejected + plan.get("malformed_notes", 0)
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
            controls = control_index(self.observation)
            for r in results:
                if r.get("outcome") == "executed":
                    label = controls.get(str(r.get("target")), {}).get("label") or ""
                    self.trail.append(
                        {
                            "kind": r.get("kind"),
                            "label": str(label)[:80],
                            "url": self.observation.get("url", ""),
                        }
                    )
            self.trail = self.trail[-STEP_HISTORY:]
            self.history.extend(
                {
                    "kind": r.get("kind"),
                    "target": r.get("target"),
                    "outcome": r.get("outcome"),
                    # Only fixed runtime reasons reach the planner, e.g. a click
                    # refused because an overlay covers its target.
                    **(
                        {"detail": r["detail"]}
                        if r.get("detail") in REJECTION_DETAILS
                        else {}
                    ),
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

    def interaction_history(self) -> dict[str, Any]:
        return {"steps": list(self.trail), "visited_urls": list(self.pages)}

    async def answer(self) -> None:
        """Extract once, verify with Jev, then review a code-matched answer once."""
        self.phase = "extract"
        async with self.store.lease(self.session_id):
            record = await self.load_active()
            record["phase"] = "finishing"
            record["evidence"] = self.ledger
            await self.store.save(record)
        observation = self.observation
        history = self.interaction_history()
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
            data = coerce_numbers(data, self.schema)
            self.phase = "verify"
            started = time.monotonic()
            verified = await self.models.verify(
                self.request.task,
                observation,
                data,
                evidence=self.ledger,
                history=history,
            )
            self.stage["verify_seconds"] += time.monotonic() - started
        check = check_answer(data, self.schema, self.ledger, observation)
        validator = Draft202012Validator(self.schema)
        pruned_valid = data is not None and validator.is_valid(check.pruned)
        dropped: list[str] = []
        if data is not None and not pruned_valid:
            # Content-free diagnosis before repair: a fixed JSON Schema keyword
            # and the JSON type of the offending value, never schema or answer text.
            error = best_match(validator.iter_errors(check.pruned))
            keyword = error.validator if error is not None else None
            instance = json_type(error.instance) if error is not None else "other"
            repaired, removed = drop_invalid(check.pruned, validator)
            if repaired is not None and validator.is_valid(repaired):
                check.pruned = repaired
                dropped = removed
                check.missing = [*check.missing, *dropped]
        # Content-free counts that show which check decided the outcome.
        verification = getattr(self.models, "verification", None)
        if isinstance(verification, dict):
            verification.update(
                answer_extracted=float(data is not None),
                answer_matched_values=float(check.matched),
                answer_unmatched_values=float(len(check.unmatched)),
                answer_pruned_valid=float(pruned_valid),
                answer_schema_dropped=float(len(dropped)),
            )
            if data is not None and not pruned_valid:
                verification["answer_schema_error"] = (
                    keyword if keyword in SCHEMA_ERROR_KEYWORDS else "other"
                )
                verification["answer_schema_error_instance"] = instance
        no_results = getattr(self.models, "no_results", False)
        # A verified answer that breaks its schema goes through the repaired,
        # reviewed path below instead of failing the run.
        if verified and (no_results or validator.is_valid(data)):
            if no_results:
                self.finish("no_results", "The page reported no matching results.")
                # An empty search cannot satisfy a schema demanding records.
                self.data = data if validator.is_valid(data) else None
            else:
                self.finish("completed", None)
                self.data = data
            self.sources = check.sources
            return
        if data is None or check.matched == 0 or not validator.is_valid(check.pruned):
            self.finish(
                "needs_user",
                "The observed pages do not establish every requested result.",
            )
            return
        # Only the code-matched (pruned) answer is ever reviewed or returned.
        with private_inference_logging():
            self.phase = "review"
            started = time.monotonic()
            verdict = await self.models.review(
                self.request.task,
                observation,
                check.pruned,
                evidence=self.ledger,
                history=history,
            )
            self.stage["verify_seconds"] += time.monotonic() - started
        if not (verdict["grounded"] and verdict["interaction_complete"]):
            self.finish(
                "needs_user",
                "The observed pages do not establish every requested result.",
            )
            return
        full = verdict["answer_complete"] and not check.missing
        self.finish("completed", None if full else PARTIAL_REASON)
        self.data = check.pruned
        self.missing = check.missing
        self.sources = check.sources

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
                            for k in ("url", "title", "tables")
                        },
                        # Same bound as extraction: the nearest links, not every
                        # link the runtime collected for source verification.
                        "links": (self.observation.get("links") or [])[:100],
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
