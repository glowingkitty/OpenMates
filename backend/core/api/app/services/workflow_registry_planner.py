"""Owner-scoped, registry-derived natural language workflow authoring.

Jev selects candidate skills/controls and existing targets. Gemini streams
validated semantic nodes, with one corrective continuation if needed. The
compiler owns graph wiring and saveable partial drafts. This module never
persists or executes a model response.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import time
from dataclasses import replace
from typing import Any

import httpx

from backend.core.api.app.services.workflow_authoring_compiler import (
    FlatAuthoringAccumulator, compile_authoring_plan,
)
from backend.core.api.app.services.workflow_authoring_billing import (
    GEMINI_MODEL, MeteredJevClient, WorkflowAuthoringBilling,
)
from backend.core.api.app.services.workflow_authoring_preselection import (
    JEV_INPUT_PRICE, WorkflowAuthoringPreselector, WorkflowPreselection,
)
from backend.core.api.app.services.workflow_capability_registry import WorkflowCapabilityRegistry
from backend.core.api.app.services.workflow_gemini_authoring import (
    GOOGLE_SECRET_PATH, WorkflowAuthoringProviderError, WorkflowAuthoringStopped, WorkflowGeminiAuthor,
)
from backend.core.api.app.utils.secrets_manager import SecretsManager
from backend.shared.providers.typesafe.client import (
    OPENROUTER_SECRET_KEY, OPENROUTER_SECRET_PATH, DecisionProviderError, JevDecisionClient,
)
from backend.shared.providers.typesafe.models import NoulAnswer

MAX_WORKFLOWS = 8
CLARIFICATION = "I could not build a valid workflow for every part of this request. Let's clarify the details in chat."
PARTIAL_FAILURE = "The AI could not finish this workflow after a correction attempt. Your validated changes were saved and the workflow is disabled. Ask for a specific update or edit it manually."
PARTIAL_STOPPED = "Generation stopped. Your validated changes were saved and the workflow is disabled."
_PROVIDER_CACHE_KEYS = (f"{GOOGLE_SECRET_PATH}/api_key", f"{OPENROUTER_SECRET_PATH}/{OPENROUTER_SECRET_KEY}")
_VALIDATION_KEYWORDS = frozenset({
    "type", "enum", "required", "additionalProperties", "anyOf", "oneOf", "allOf",
    "format", "pattern", "minimum", "maximum", "minItems", "maxItems", "minLength", "maxLength",
})
_PLAN_FAILURE_CODES = {
    "Not every requested workflow was authored": "workflow_count_mismatch",
    "An actionable request cannot become an empty or clarification plan": "empty_actionable_plan",
    "Unknown or repeated workflow update target": "invalid_update_target",
    "Requested conditional control was omitted": "check_mode_omitted",
    "Mixed request omitted an operation": "mixed_operation_omitted",
    "A selected workflow edit was omitted": "update_target_omitted",
    "Create requires a title and description": "header_metadata",
    "Create requires a supported icon": "header_icon",
    "Correction must preserve the accepted workflow header": "retry_header_changed",
    "Correction must preserve accepted workflow nodes": "retry_node_changed",
}


class _UnclearWorkflowRequest(ValueError):
    """Jev, rather than a constructor failure, determined that input is unclear."""


class _AuthoringCancelled(Exception):
    """Stop planning while retaining only the server-validated prefix."""


def _dump(value: Any) -> dict[str, Any]:
    return value.model_dump(mode="json", by_alias=True) if hasattr(value, "model_dump") else dict(value)


class WorkflowRegistryPlanner:
    requires_workflow_overview = False
    requires_workflow_lookup = True
    atomic_authoring = True

    def __init__(self, *, secrets_manager: Any, workflow_service: Any = None,
                 jev_client: Any = None, author: Any = None,
                 registry: WorkflowCapabilityRegistry | None = None,
                 preselection_mode: str = "direct") -> None:
        self.secrets_manager = secrets_manager
        self.workflow_service = workflow_service
        self.registry = registry or WorkflowCapabilityRegistry()
        self.jev_client = jev_client
        self.author = author
        self.preselection_mode = preselection_mode

    def plan(self, *, text: str, context: dict[str, Any]) -> dict[str, Any]:
        return asyncio.run(self._isolated_plan(text, context))

    async def _isolated_plan(self, text: str, context: dict[str, Any]) -> dict[str, Any]:
        manager = self.secrets_manager
        owns_manager = isinstance(manager, SecretsManager) and self.jev_client is None and self.author is None
        if owns_manager:
            manager = object.__new__(SecretsManager)
            SecretsManager.__init__(manager)
            manager.vault_token = self.secrets_manager.vault_token
            # Each thread needs its own async HTTP clients, but cached provider
            # credentials and their existing expiry do not depend on a loop.
            manager._token_valid_until = self.secrets_manager._token_valid_until
            for key in _PROVIDER_CACHE_KEYS:
                cached = self.secrets_manager._secrets_cache.get(key)
                if cached and cached["expires"] > asyncio.get_running_loop().time():
                    manager._secrets_cache[key] = dict(cached)
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(45.0, connect=5.0)) as client:
                jev = self.jev_client or JevDecisionClient(secrets_manager=manager, http_client=client,
                                                          timeout_seconds=3.0, max_retries=0)
                author = self.author or WorkflowGeminiAuthor(manager, client)
                return await self._plan(text, context, jev, author)
        finally:
            if owns_manager:
                if manager.vault_token == self.secrets_manager.vault_token:
                    for key in _PROVIDER_CACHE_KEYS:
                        cached = manager._secrets_cache.get(key)
                        if cached and cached["expires"] > asyncio.get_running_loop().time():
                            current = self.secrets_manager._secrets_cache.get(key)
                            if current is None or cached["expires"] > current["expires"]:
                                self.secrets_manager._secrets_cache[key] = dict(cached)
                await manager.aclose()

    async def _emit(self, context: dict[str, Any], event: dict[str, Any]) -> None:
        callback = context.get("_on_component")
        if callable(callback):
            result = callback(event)
            if inspect.isawaitable(result):
                await result

    async def _targets(self, text: str, context: dict[str, Any], selection: WorkflowPreselection,
                       jev: Any, metrics: dict[str, Any]) -> dict[str, dict[str, Any]]:
        selected = context.get("selected_workflow")
        targets = {selected["id"]: selected} if isinstance(selected, dict) else {}
        if selection.operation in {"create", "clarify"}:
            return {}
        if targets and selection.operation != "mixed":
            return targets
        loader = context.get("_load_workflows")
        summaries = await asyncio.to_thread(loader) if callable(loader) else context.get("workflows", [])
        overview = [_dump(item) for item in summaries]
        if not overview:
            return targets
        if len(overview) > 120:
            raise ValueError("Workflow target search needs clarification")
        questions = {item["id"]: {"type": "noul", "instructions":
                     "Is this existing workflow explicitly an edit target of the request? "
                     "New workflows are not existing targets. Select all requested edit targets, "
                     "but do not select similar unrelated workflows."} for item in overview}
        started = time.perf_counter()
        decision_call = jev.evaluate(state={"request": text, "implicit_target_id": (selected or {}).get("id"),
                                            "existing_workflows": [{"id": item["id"], "title": item.get("title"),
                                                                     "description": item.get("description")}
                                                                    for item in overview]}, questions=questions)
        response = (await decision_call if isinstance(jev, MeteredJevClient)
                    else await asyncio.wait_for(decision_call, timeout=3.2))
        metrics["target_selection_seconds"] = round(time.perf_counter() - started, 3)
        metrics["jev_calls"] += 1
        metrics["estimated_cost_usd"] += response.usage.input_tokens * JEV_INPUT_PRICE
        ids = []
        for item in overview:
            answer = response.answers.get(item["id"])
            if not isinstance(answer, NoulAnswer):
                raise DecisionProviderError("Missing workflow target decision")
            if answer.noul >= 0.75:
                ids.append(item["id"])
            elif answer.noul >= 0.35:
                raise _UnclearWorkflowRequest("Ambiguous workflow target")
        if not ids or len(ids) > MAX_WORKFLOWS:
            raise _UnclearWorkflowRequest("Workflow targets require clarification")
        load_detail = context.get("_load_workflow")
        if not callable(load_detail):
            raise ValueError("Owned workflow lookup is unavailable")
        details = await asyncio.gather(*(asyncio.to_thread(load_detail, identifier) for identifier in ids))
        return {identifier: _dump(detail) for identifier, detail in zip(ids, details)}

    @staticmethod
    def _stopped(context: dict[str, Any]) -> bool:
        callback = context.get("_should_stop")
        return bool(callback()) if callable(callback) else False

    @staticmethod
    def _flat_nodes(steps: list[dict[str, Any]], parent: str | None = None,
                    branch: str | None = None) -> list[dict[str, Any]]:
        """Adapt retained compact fixtures/contracts to the node transport."""
        result = []
        encoded_fields = ("input", "predicate", "question", "selected_inputs", "prompt", "message", "blocks")
        if not isinstance(steps, list):
            raise ValueError("Workflow steps must be a list")
        for item in steps:
            if not isinstance(item, dict):
                raise ValueError("Workflow step must be an object")
            record = {key: value for key, value in item.items()
                      if key in {"kind", "id", "capability", "mode", "title"}}
            if parent is not None:
                record.update(parent_check_id=parent, branch=branch)
            for key in encoded_fields:
                if key in item:
                    record[f"{key}_json"] = json.dumps(item[key], ensure_ascii=False, separators=(",", ":"))
            result.append(record)
            if item.get("kind") == "check":
                for child_branch in ("yes", "no", "unsure"):
                    result.extend(WorkflowRegistryPlanner._flat_nodes(item.get(child_branch) or [],
                                                                       item.get("id"), child_branch))
        return result

    async def _checkpoint(self, context: dict[str, Any], index: int,
                          accumulator: FlatAuthoringAccumulator, preview: dict[str, Any] | None) -> None:
        if preview is None:
            return
        header = accumulator.header or {}
        checkpoint = {"workflow_index": index, "operation": header.get("operation"),
                      "graph": preview["graph"], "accepted_node_count": len(accumulator.records),
                      "accepted_node_id": (accumulator.records[-1]["id"] if accumulator.records
                                           else preview["graph"].get("trigger_node_id")),
                      "metadata": {key: preview.get(key) for key in
                                   ("title", "description", "category", "icon", "workflow_id", "assumptions")}}
        if header.get("operation") == "update" and accumulator.selected_workflow:
            checkpoint["metadata"]["expected_record_version"] = accumulator.selected_workflow.get("version")
        callback = context.get("_on_checkpoint")
        if callable(callback):
            result = callback(checkpoint)
            if inspect.isawaitable(result):
                await result
        else:
            await self._emit(context, {"type": "preview", **checkpoint, "provisional": True})

    @staticmethod
    def _finalize(accumulators: dict[int, FlatAuthoringAccumulator], selection: WorkflowPreselection,
                  targets: dict[str, dict[str, Any]]) -> dict[str, Any]:
        if not accumulators or sorted(accumulators) != list(range(len(accumulators))):
            raise ValueError("Not every requested workflow was authored")
        if selection.workflow_count is not None and len(accumulators) != selection.workflow_count:
            raise ValueError("Not every requested workflow was authored")
        plans = []
        seen_updates: set[str] = set()
        for accumulator in accumulators.values():
            compiled = accumulator.compile_final()
            if compiled["action"] not in {"create_workflow", "update_workflow"}:
                raise ValueError("An actionable request cannot become an empty or clarification plan")
            if compiled["action"] == "update_workflow":
                identifier = compiled["workflow_id"]
                if identifier in seen_updates or identifier not in targets:
                    raise ValueError("Unknown or repeated workflow update target")
                seen_updates.add(identifier)
                compiled["expected_record_version"] = targets[identifier]["version"]
            plans.append(compiled)
        actual_modes = {node.get("config", {}).get("mode") for item in plans
                        for node in item["graph"]["nodes"] if node["type"] == "check"}
        required_modes = ({"exact", "ai"} if selection.check_mode == "both"
                          else {selection.check_mode} - {"none"})
        if not required_modes.issubset(actual_modes):
            raise ValueError("Requested conditional control was omitted")
        kinds = {item["action"] for item in plans}
        if selection.operation == "mixed" and kinds != {"create_workflow", "update_workflow"}:
            raise ValueError("Mixed request omitted an operation")
        if targets and seen_updates != set(targets):
            raise ValueError("A selected workflow edit was omitted")
        return plans[0] if len(plans) == 1 else {"action": "batch", "operations": plans}

    @staticmethod
    def _partial(accumulators: dict[int, FlatAuthoringAccumulator], reason: str) -> dict[str, Any]:
        operations = []
        for accumulator in accumulators.values():
            # Acceptance guarantees the prefix can be saved. If an unrelated
            # edit changed this workflow meanwhile, the persistence CAS still
            # rejects the whole transition rather than overwriting newer work.
            if accumulator.header and accumulator.header.get("operation") in {"create", "update"}:
                operation = accumulator.compile_partial()
                operation.pop("partial", None)
                operations.append(operation)
        return {"action": "partial", "reason": reason,
                "notice": PARTIAL_STOPPED if reason == "stopped" else PARTIAL_FAILURE,
                "operations": operations}

    async def _plan(self, text: str, context: dict[str, Any], jev: Any, author: Any) -> dict[str, Any]:
        started = time.perf_counter()
        metrics: dict[str, Any] = {"jev_calls": 0, "gemini_calls": 0, "estimated_cost_usd": 0.0,
                                   "generation_attempts": [], "cost_estimate_complete": True}
        user_id = context.get("_billing_user_id")
        session_id = context.get("_billing_session_id")
        billing = (WorkflowAuthoringBilling(user_id=user_id, session_id=session_id)
                   if isinstance(user_id, str) and isinstance(session_id, str) else None)
        metered_jev = MeteredJevClient(jev, billing) if billing is not None else jev
        targets: dict[str, dict[str, Any]] = {}
        accumulators: dict[int, FlatAuthoringAccumulator] = {}
        timezone = context.get("timezone") or "UTC"

        def finish(plan: dict[str, Any]) -> dict[str, Any]:
            metrics["total_seconds"] = round(time.perf_counter() - started, 3)
            if billing is not None:
                metrics["jev_calls"] = max(metrics["jev_calls"], metered_jev.call_count)
                if not billing.usage_complete:
                    metrics["cost_estimate_complete"] = False
                metrics["billing"] = {"credits_charged": sum(item["credits_charged"] for item in billing.entries),
                                      "usage_complete": billing.usage_complete,
                                      "entries": billing.entries}
            plan["_authoring_metrics"] = metrics
            if targets:
                plan["_authoring_before"] = targets
            return plan

        try:
            if not text.strip() or len(text) > 16_000:
                raise ValueError("Invalid workflow instruction length")
            await self._emit(context, {"type": "progress", "phase": "planning"})
            selector = WorkflowAuthoringPreselector(jev_client=metered_jev, registry=self.registry,
                                                   mode=self.preselection_mode)
            try:
                selection_call = selector.select(text, timezone=timezone,
                                                 selected_workflow=context.get("selected_workflow"))
                # The real Jev client enforces its own provider timeout. A
                # planner-wide deadline must not cancel ledger settlement.
                selection = (await selection_call if billing is not None
                             else await asyncio.wait_for(selection_call, timeout=3.2))
                metrics.update(selection.metrics)
                if selection.request_clarity == "title_only":
                    if context.get("selected_workflow") or len(text.strip()) > 200 or len(text.split()) > 24:
                        raise ValueError("A title-only draft must be a short new-workflow request")
                    return finish(compile_authoring_plan({"operation": "draft", "title": text.strip()},
                                                         selection, timezone))
                if (selection.request_clarity == "confusing" or selection.operation == "clarify"
                        or selection.workflow_count is None):
                    raise _UnclearWorkflowRequest("Jev determined that the workflow request needs clarification")
                # Let the client choose its single-workflow editor before the
                # first validated header arrives. A known multi-workflow batch
                # stays on the workspace while each preview streams.
                await self._emit(context, {"type": "progress", "phase": "planning",
                                           "operation": selection.operation,
                                           "workflow_count": selection.workflow_count})
                targets = await self._targets(text, context, selection, metered_jev, metrics)
            except (DecisionProviderError, TimeoutError):
                capabilities = [cap for cap in self.registry.list_capabilities() if cap.enabled]
                selection = WorkflowPreselection(capabilities, "unknown", "none", True, {}, {})
                metrics["jev_unavailable"] = True
                metrics["cost_estimate_complete"] = False
                selected = context.get("selected_workflow")
                if isinstance(selected, dict):
                    targets[selected["id"]] = selected
                else:
                    loader = context.get("_load_workflows")
                    summaries = await asyncio.to_thread(loader) if callable(loader) else []
                    context = {**context, "_fallback_overview": [_dump(item) for item in summaries][:120]}
            candidates = {cap.id: cap for cap in selection.capabilities}
            for target in targets.values():
                for node in (target.get("graph") or {}).get("nodes", []):
                    config = node.get("config") or {}
                    if node.get("type") == "app_skill_action":
                        identifier = config.get("capability_id") or f"{config.get('app_id')}.{config.get('skill_id')}"
                        cap = self.registry.get_capability(identifier)
                        if not cap.enabled:
                            raise ValueError("Existing workflow capability is unavailable")
                        candidates[identifier] = cap
            selection = replace(selection, capabilities=list(candidates.values()))
            existing = ({"workflows": list(targets.values())} if len(targets) > 1
                        else next(iter(targets.values())) if targets else None)
            if context.get("_fallback_overview"):
                existing = {"selected_workflows": list(targets.values()),
                            "workflow_overview": context["_fallback_overview"]}
            correction = None
            for attempt in range(2):
                if self._stopped(context):
                    return finish(self._partial(accumulators, "stopped"))
                frozen = {index: accumulator.flat_snapshot() for index, accumulator in accumulators.items()}
                seen_this_attempt: set[tuple[int, str]] = set()
                usage = None

                async def accept(component: dict[str, Any], *, replay: bool = False) -> None:
                    if self._stopped(context):
                        raise _AuthoringCancelled()
                    index = component.get("workflow_index", 0)
                    if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < MAX_WORKFLOWS:
                        raise ValueError("Workflow component index is invalid")
                    kind = component.get("type")
                    if kind == "header":
                        header = component.get("header")
                        if not isinstance(header, dict) or header.get("operation") not in {"create", "update"}:
                            raise ValueError("Gemini must author an actionable workflow; only Jev may request clarification")
                        if selection.operation in {"create", "update"} and header["operation"] != selection.operation:
                            raise ValueError("Authored operation does not match requested routing")
                        target = targets.get(header.get("workflow_id"))
                        if header["operation"] == "update" and target is None and metrics.get("jev_unavailable"):
                            identifier = header.get("workflow_id")
                            allowed_ids = {item["id"] for item in context.get("_fallback_overview", [])}
                            if identifier in allowed_ids and callable(context.get("_load_workflow")):
                                target = _dump(await asyncio.to_thread(context["_load_workflow"], identifier))
                                targets[identifier] = target
                        if header["operation"] == "update" and target is None:
                            raise ValueError("Unknown workflow update target")
                        if index in accumulators:
                            if accumulators[index].header != header:
                                raise ValueError("Correction must preserve the accepted workflow header")
                            return
                        if index != len(accumulators):
                            raise ValueError("Workflow headers must arrive in order")
                        if any(item.header and item.header.get("operation") == "update"
                               and item.header.get("workflow_id") == header.get("workflow_id")
                               for item in accumulators.values()) and header["operation"] == "update":
                            raise ValueError("Repeated workflow update target")
                        per_workflow = replace(selection, operation=header["operation"], check_mode="none")
                        accumulator = FlatAuthoringAccumulator(per_workflow, timezone, target)
                        preview = accumulator.accept_header(header)
                        accumulators[index] = accumulator
                        await self._checkpoint(context, index, accumulator, preview)
                    elif kind == "node":
                        if index not in accumulators:
                            raise ValueError("Workflow node arrived before its header")
                        node = component.get("node")
                        if not isinstance(node, dict):
                            raise ValueError("Workflow node must be an object")
                        identity = (index, node.get("id"))
                        if identity in seen_this_attempt and not replay:
                            raise ValueError("A workflow node was repeated in one response")
                        seen_this_attempt.add(identity)
                        existing_node = next((item for item in accumulators[index].records if item.get("id") == node.get("id")), None)
                        if existing_node is not None:
                            frozen_nodes = (frozen.get(index) or {}).get("nodes", [])
                            equivalent = existing_node == node
                            if replay and not equivalent:
                                # The transport returns the compact tree after
                                # callbacks. Re-encoding its validated JSON fields
                                # may change whitespace, but cannot edit a prefix.
                                def decoded(record: dict[str, Any]) -> dict[str, Any]:
                                    return {key: json.loads(value) if key.endswith("_json") else value
                                            for key, value in record.items()}
                                equivalent = decoded(existing_node) == decoded(node)
                            if equivalent and (replay or node in frozen_nodes):
                                return
                            raise ValueError("Correction must preserve accepted workflow nodes")
                        preview = accumulators[index].accept_node(node)
                        await self._checkpoint(context, index, accumulators[index], preview)
                    elif "plan" in component:
                        await ingest(component["plan"], index, replay=True)
                    else:
                        raise ValueError("Unknown workflow component")

                async def ingest(raw: dict[str, Any], index: int, *, replay: bool = True) -> None:
                    if not isinstance(raw, dict):
                        raise ValueError("Invalid workflow plan envelope")
                    header = {key: value for key, value in raw.items() if key != "steps"}
                    await accept({"type": "header", "workflow_index": index, "header": header}, replay=replay)
                    for node in self._flat_nodes(raw.get("steps") or []):
                        await accept({"type": "node", "workflow_index": index, "node": node}, replay=replay)

                if billing is not None:
                    await billing.precheck(model=GEMINI_MODEL)
                metrics["gemini_calls"] += 1
                try:
                    kwargs = {"text": text, "selection": selection, "timezone": timezone,
                              "selected_workflow": existing, "on_plan_component": accept,
                              "should_stop": lambda: self._stopped(context)}
                    if correction is not None:
                        kwargs.update(correction=correction,
                                      accepted_prefixes=[frozen[index] for index in sorted(frozen)])
                    raw, usage = await author.generate(**kwargs)
                    # Transport adapters retain the compact return contract for
                    # CLI benchmarks and callers without a streaming callback.
                    if not isinstance(raw, dict):
                        raise ValueError("Invalid workflow response envelope")
                    if "workflows" in raw:
                        if (set(raw) != {"workflows"} or not isinstance(raw["workflows"], list)
                                or not 1 <= len(raw["workflows"]) <= MAX_WORKFLOWS):
                            raise ValueError("Invalid flat workflow batch envelope")
                        for index, workflow in enumerate(raw["workflows"]):
                            if (not isinstance(workflow, dict) or set(workflow) != {"header", "nodes"}
                                    or not isinstance(workflow["nodes"], list)):
                                raise ValueError("Invalid flat workflow record")
                            await accept({"type": "header", "workflow_index": index,
                                          "header": workflow["header"]}, replay=True)
                            for node in workflow["nodes"]:
                                await accept({"type": "node", "workflow_index": index, "node": node}, replay=True)
                    else:
                        operations = raw.get("operations", [raw])
                        if ("operations" in raw and set(raw) != {"operations"}) or not isinstance(operations, list):
                            raise ValueError("Invalid compact workflow batch envelope")
                        if not 1 <= len(operations) <= MAX_WORKFLOWS:
                            raise ValueError("Invalid compact workflow batch size")
                        for index, item in enumerate(operations):
                            await ingest(item, index)
                    await self._emit(context, {"type": "progress", "phase": "validating"})
                    plan = self._finalize(accumulators, selection, targets)
                except _AuthoringCancelled as exc:
                    usage = getattr(exc, "metrics", None)
                    metrics["cost_estimate_complete"] = False
                    return finish(self._partial(accumulators, "stopped"))
                except (ValueError, WorkflowAuthoringProviderError) as exc:
                    usage = dict(usage or getattr(exc, "metrics", None) or {})
                    if isinstance(exc, WorkflowAuthoringProviderError):
                        # Early stream termination may report only usage seen
                        # before the rejected node, rather than final billing.
                        metrics["cost_estimate_complete"] = False
                    if isinstance(exc, WorkflowAuthoringStopped) or self._stopped(context):
                        return finish(self._partial(accumulators, "stopped"))
                    correction = (getattr(exc, "validation_error", None) or str(exc))[:600]
                    metrics["last_failure_stage"] = "authoring_validation"
                    # Keep diagnostics useful without persisting the private
                    # correction text or a provider response. Provider codes
                    # are constants; ValueError messages may contain user data.
                    reason_code = (getattr(exc, "code", None)
                                   or _PLAN_FAILURE_CODES.get(str(exc), "plan_validation"))
                    usage["failure_reason_code"] = reason_code
                    metrics["last_failure_reason_code"] = reason_code
                    validation_code = getattr(exc, "validation_code", None)
                    if validation_code:
                        usage["validation_code"] = validation_code
                        metrics["last_validation_code"] = validation_code
                    validation_path = getattr(exc, "validation_path", None)
                    if validation_path:
                        usage["validation_path"] = validation_path
                        metrics["last_validation_path"] = validation_path
                    validation_keyword = getattr(exc, "validation_keyword", None)
                    if isinstance(validation_keyword, str) and validation_keyword in _VALIDATION_KEYWORDS:
                        usage["validation_keyword"] = validation_keyword
                        metrics["last_validation_keyword"] = validation_keyword
                    if attempt == 0:
                        await self._emit(context, {"type": "progress", "phase": "retrying_node", "attempt": 2})
                        continue
                    plan = self._partial(accumulators, "provider_error")
                finally:
                    if billing is not None:
                        await billing.settle(model=GEMINI_MODEL,
                                             provider_step=f"gemini:{attempt}", usage=usage)
                        if not billing.usage_complete:
                            metrics["cost_estimate_complete"] = False
                        if "billing" in metrics:
                            metrics["billing"]["credits_charged"] = sum(
                                item["credits_charged"] for item in billing.entries)
                            metrics["billing"]["usage_complete"] = billing.usage_complete
                    if usage is not None:
                        metrics["generation_attempts"].append(usage)
                        metrics["generation"] = usage
                        cost = usage.get("estimated_cost_usd")
                        if isinstance(cost, (int, float)):
                            metrics["estimated_cost_usd"] = round(metrics["estimated_cost_usd"] + cost, 8)
                        else:
                            metrics["cost_estimate_complete"] = False
                return finish(plan)
        except _UnclearWorkflowRequest:
            return finish({"action": "needs_clarification", "message": CLARIFICATION})
        except (ValueError, DecisionProviderError):
            # System/constructor errors are not evidence that the user's request
            # is confusing. Surface a failed/partial result, never open a chat.
            return finish(self._partial(accumulators, "provider_error"))
        return finish(self._partial(accumulators, "provider_error"))
