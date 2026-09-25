# backend/core/api/app/services/workflow_runner.py
#
# Deterministic Workflows V1 runner for validated server-side workflow graphs.
# V1 executes a deliberately small safe node set while preserving per-node run
# records that every client can inspect.
#
# Spec: docs/specs/workflows-v1/spec.yml

from __future__ import annotations

import hashlib
import time
import uuid
from typing import Any

from starlette.concurrency import run_in_threadpool

from backend.core.api.app.services.workflow_action_adapter import WorkflowActionAdapter, WorkflowActionExecutionError
from backend.core.api.app.services.workflow_app_skill_adapter import WorkflowAppSkillAdapter, WorkflowSkillBillingError
from backend.core.api.app.services.workflow_ai_service import WorkflowAiService, render_bounded_ask_ai_prompt
from backend.core.api.app.services.workflow_models import (
    WorkflowDetail,
    WorkflowNode,
    WorkflowNodeRun,
    WorkflowNodeRunStatus,
    WorkflowNodeType,
    WorkflowRunDetail,
    WorkflowRunStatus,
)
from backend.core.api.app.services.workflow_service import WorkflowService
from backend.core.api.app.services.workflow_template_expressions import resolve_workflow_path, resolve_workflow_template
from backend.shared.python_utils.billing_utils import BillingError, ensure_credit_headroom


class WorkflowRunner:
    def __init__(
        self,
        workflow_service: WorkflowService,
        app_skill_adapter: WorkflowAppSkillAdapter | None = None,
        action_adapter: WorkflowActionAdapter | None = None,
        ai_service: WorkflowAiService | None = None,
    ) -> None:
        self.workflow_service = workflow_service
        self.app_skill_adapter = app_skill_adapter or WorkflowAppSkillAdapter()
        self.action_adapter = action_adapter or WorkflowActionAdapter(workflow_service=workflow_service)
        self.ai_service = ai_service or WorkflowAiService(
            secrets_manager=getattr(self.app_skill_adapter, "secrets_manager", None),
            cache_service=getattr(self.app_skill_adapter, "cache_service", None),
        )

    async def run_workflow(
        self,
        workflow: WorkflowDetail,
        user_id: str,
        vault_key_id: str | None = None,
        trigger_type: str = "manual",
        input_payload: dict[str, Any] | None = None,
        run_id: str | None = None,
        version_id: str | None = None,
    ) -> WorkflowRunDetail:
        self.workflow_service.validate_manual_run_input(workflow, input_payload)
        if trigger_type in {"manual", "test"} and (run_id is None or version_id is None):
            raise ValueError("Manual and test workflow runs must be accepted before execution")
        if run_id is not None and not version_id:
            raise ValueError("Accepted workflow runs require a pinned version_id")
        accepted_run = run_id is not None
        run_id = run_id or str(uuid.uuid4())
        version_id = version_id or workflow.current_version_id
        reusable_ai_outputs: dict[str, tuple[dict[str, Any], int]] = {}
        if accepted_run:
            try:
                previous = await run_in_threadpool(
                    self.workflow_service.get_run,
                    workflow.id,
                    run_id,
                    user_id,
                    vault_key_id,
                )
                reusable_ai_outputs = {
                    item.node_id: (dict(item.output_summary), item.credit_cost)
                    for item in previous.node_runs
                    if item.status == WorkflowNodeRunStatus.COMPLETED
                    and (
                        (
                            item.node_type == WorkflowNodeType.CHECK
                            and item.output_summary.get("decision_path")
                        )
                        or (
                            item.node_type == WorkflowNodeType.APP_SKILL_ACTION
                            and item.output_summary.get("app_id") == "ai"
                            and item.output_summary.get("skill_id") == "ask"
                            and isinstance(item.output_summary.get("answer"), str)
                        )
                    )
                }
            except Exception:
                # A newly accepted run may not have a readable content checkpoint yet.
                reusable_ai_outputs = {}
        started_at = int(time.time())
        trigger_node = next((n for n in workflow.graph.nodes if n.id == workflow.graph.trigger_node_id), None)
        context: dict[str, Any] = {"trigger": input_payload or {}, "nodes": {}, "workflow": {
            "workflow_id": workflow.id, "run_id": run_id, "started_at": started_at,
            "timezone": ((trigger_node.config.get("schedule") or {}).get("timezone") or trigger_node.config.get("timezone") or "UTC") if trigger_node else "UTC",
        }}
        node_runs: list[WorkflowNodeRun] = []

        nodes_by_id = {node.id: node for node in workflow.graph.nodes}
        outgoing_edges: dict[str, list[Any]] = {}
        for edge in workflow.graph.edges:
            outgoing_edges.setdefault(edge.from_node, []).append(edge)

        incoming = {edge.to_node for edge in workflow.graph.edges}
        roots = [node.id for node in workflow.graph.nodes if node.id not in incoming]
        current_node_id: str | None = workflow.graph.trigger_node_id or (roots[0] if len(roots) == 1 else None)
        if current_node_id is None:
            raise ValueError("Workflow requires a single executable starting step")
        continuations: list[str] = []
        visited_count = 0
        max_nodes = int(workflow.graph.limits.get("max_nodes", max(len(workflow.graph.nodes), 1) * 2))

        while current_node_id is not None:
            if accepted_run and await run_in_threadpool(self.workflow_service.is_run_cancellation_requested, workflow.id, run_id, user_id):
                return await self._save_cancelled_run(run_id, workflow.id, version_id, trigger_type, started_at, node_runs, context, user_id, vault_key_id)
            visited_count += 1
            if visited_count > max_nodes:
                raise ValueError("Workflow execution exceeded max_nodes")
            if continuations and current_node_id == continuations[-1]:
                continuations.pop()
            node = nodes_by_id[current_node_id]
            context["workflow"]["node_id"] = node.id
            # Persist a checkpoint before executing a side effect or making a reservation.
            progress = WorkflowRunDetail(id=run_id, workflow_id=workflow.id, version_id=version_id,
                trigger_type=trigger_type, status=WorkflowRunStatus.RUNNING, started_at=started_at,
                cost_summary=_workflow_cost_summary(node_runs),
                node_runs=[*node_runs, WorkflowNodeRun(
                    id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"workflow:{run_id}:{node.id}:node-run")),
                    run_id=run_id, workflow_id=workflow.id, node_id=node.id, node_type=node.type,
                    status=WorkflowNodeRunStatus.RUNNING, started_at=int(time.time()))], output_summary=context)
            await run_in_threadpool(self.workflow_service.save_run, user_id, progress, vault_key_id)
            reusable = reusable_ai_outputs.get(node.id)
            if reusable is not None:
                reusable_output, reusable_credit_cost = reusable
                node_run = WorkflowNodeRun(
                    id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"workflow:{run_id}:{node.id}:node-run")),
                    run_id=run_id,
                    workflow_id=workflow.id,
                    node_id=node.id,
                    node_type=node.type,
                    status=WorkflowNodeRunStatus.COMPLETED,
                    started_at=int(time.time()),
                    finished_at=int(time.time()),
                    output_summary=reusable_output,
                    credit_cost=reusable_credit_cost,
                )
            else:
                node_run = await self._run_node(run_id, workflow.id, node, context, user_id)
            node_runs.append(node_run)
            context["nodes"][node.id] = {"output": node_run.output_summary, "status": node_run.status.value, "app_id": node.config.get("app_id"), "skill_id": node.config.get("skill_id")}
            if accepted_run and await run_in_threadpool(self.workflow_service.is_run_cancellation_requested, workflow.id, run_id, user_id):
                return await self._save_cancelled_run(run_id, workflow.id, version_id, trigger_type, started_at, node_runs, context, user_id, vault_key_id)
            if node_run.status == WorkflowNodeRunStatus.FAILED:
                run = WorkflowRunDetail(
                    id=run_id,
                    workflow_id=workflow.id,
                    version_id=version_id,
                    trigger_type=trigger_type,
                    status=WorkflowRunStatus.FAILED,
                    started_at=started_at,
                    finished_at=int(time.time()),
                    error_summary=f"Step failed ({node_run.error_code or 'execution_error'})" if node_run.error_summary else None,
                    cost_summary=_workflow_cost_summary(node_runs),
                    node_runs=node_runs,
                    output_summary=context,
                )
                return await run_in_threadpool(self.workflow_service.save_run, user_id, run, vault_key_id)
            if node_run.output_summary.get("wait_for_user_input"):
                run = WorkflowRunDetail(
                    id=run_id,
                    workflow_id=workflow.id,
                    version_id=version_id,
                    trigger_type=trigger_type,
                    status=WorkflowRunStatus.WAITING,
                    started_at=started_at,
                    cost_summary=_workflow_cost_summary(node_runs),
                    node_runs=node_runs,
                    output_summary=context,
                )
                return await run_in_threadpool(self.workflow_service.save_run, user_id, run, vault_key_id)
            next_node_id = self._next_node_id(node, node_run.output_summary, outgoing_edges)
            if node.type.value in {"check", "decision"}:
                continuation = next((edge.to_node for edge in outgoing_edges.get(node.id, []) if edge.branch in {None, "default"}), None)
                if continuation and next_node_id != continuation:
                    continuations.append(continuation)
            current_node_id = next_node_id or (continuations.pop() if continuations else None)

        run = WorkflowRunDetail(
            id=run_id,
            workflow_id=workflow.id,
            version_id=version_id,
            trigger_type=trigger_type,
            status=WorkflowRunStatus.COMPLETED,
            started_at=started_at,
            finished_at=int(time.time()),
            cost_summary=_workflow_cost_summary(node_runs),
            node_runs=node_runs,
            output_summary=context,
        )
        return await run_in_threadpool(self.workflow_service.save_run, user_id, run, vault_key_id)

    async def run_step_test(
        self,
        workflow: WorkflowDetail,
        user_id: str,
        node_id: str,
        *,
        input_override: dict[str, Any] | None = None,
        vault_key_id: str | None = None,
        upstream_outputs: dict[str, dict[str, Any]] | None = None,
    ) -> WorkflowRunDetail:
        """Execute one selected action/control as a real inspectable step-test run."""
        node = next((item for item in workflow.graph.nodes if item.id == node_id), None)
        if node is None:
            raise ValueError(f"Workflow step not found: {node_id}")
        if input_override:
            node = node.model_copy(deep=True)
            if node.type == WorkflowNodeType.APP_SKILL_ACTION:
                node.config["input"] = {**dict(node.config.get("input") or {}), **input_override}
            else:
                node.config.update(input_override)
        run_id = str(uuid.uuid4())
        started_at = int(time.time())
        if node.type.value in {"send_chat_message", "start_new_chat", "create_chat_report"}:
            raise ValueError("Send message supports preview; use a full run for actual delivery")
        trigger_node = next((n for n in workflow.graph.nodes if n.id == workflow.graph.trigger_node_id), None)
        context: dict[str, Any] = {"trigger": {"step_test": True},
            "nodes": {key: {"output": value} for key, value in (upstream_outputs or {}).items()},
            "workflow": {"workflow_id": workflow.id, "run_id": run_id, "node_id": node.id,
                         "started_at": started_at, "step_test": True,
                         "timezone": ((trigger_node.config.get("schedule") or {}).get("timezone") or trigger_node.config.get("timezone") or "UTC") if trigger_node else "UTC"}}
        node_run = await self._run_node(run_id, workflow.id, node, context, user_id)
        context["nodes"][node.id] = {"output": node_run.output_summary, "status": node_run.status.value, "app_id": node.config.get("app_id"), "skill_id": node.config.get("skill_id")}
        status = WorkflowRunStatus.FAILED if node_run.status == WorkflowNodeRunStatus.FAILED else WorkflowRunStatus.COMPLETED
        if node_run.output_summary.get("wait_for_user_input"):
            status = WorkflowRunStatus.WAITING
        run = WorkflowRunDetail(
            id=run_id,
            workflow_id=workflow.id,
            version_id=workflow.current_version_id,
            trigger_type="step_test",
            status=status,
            started_at=started_at,
            finished_at=None if status == WorkflowRunStatus.WAITING else int(time.time()),
            error_summary=f"Step failed ({node_run.error_code or 'execution_error'})" if node_run.error_summary else None,
            cost_summary=_workflow_cost_summary([node_run]),
            node_runs=[node_run],
            output_summary=context,
        )
        return await run_in_threadpool(self.workflow_service.save_run, user_id, run, vault_key_id)

    async def _save_cancelled_run(
        self,
        run_id: str,
        workflow_id: str,
        version_id: str,
        trigger_type: str,
        started_at: int,
        node_runs: list[WorkflowNodeRun],
        context: dict[str, Any],
        user_id: str,
        vault_key_id: str | None,
    ) -> WorkflowRunDetail:
        """Finish cooperatively after a checkpoint without changing a started call."""
        now = int(time.time())
        run = WorkflowRunDetail(
            id=run_id,
            workflow_id=workflow_id,
            version_id=version_id,
            trigger_type=trigger_type,
            status=WorkflowRunStatus.CANCELLED,
            started_at=started_at,
            finished_at=now,
            cancellation_requested_at=now,
            cancelled_at=now,
            cost_summary=_workflow_cost_summary(node_runs),
            node_runs=node_runs,
            output_summary=context,
        )
        return await run_in_threadpool(self.workflow_service.save_run, user_id, run, vault_key_id)

    def _next_node_id(self, node: WorkflowNode, output: dict[str, Any], outgoing_edges: dict[str, list[Any]]) -> str | None:
        candidates = outgoing_edges.get(node.id, [])
        if not candidates:
            return None
        if node.type.value in {"decision", "check"}:
            branch = output.get("branch")
            for edge in candidates:
                if edge.branch == branch or (branch == "yes" and edge.branch == "true") or (branch == "no" and edge.branch == "false"):
                    return edge.to_node
            return next((edge.to_node for edge in candidates if edge.branch in {None, "default"}), None)
        for edge in candidates:
            if edge.branch in {None, "default"}:
                return edge.to_node
        return candidates[0].to_node

    async def _run_node(
        self,
        run_id: str,
        workflow_id: str,
        node: WorkflowNode,
        context: dict[str, Any],
        user_id: str,
    ) -> WorkflowNodeRun:
        started_at = int(time.time())
        try:
            output = await self._execute_node(node, context, user_id)
            credit_cost = output.pop("_workflow_credit_cost", 0)
            if not isinstance(credit_cost, int) or credit_cost < 0:
                raise WorkflowSkillBillingError("WORKFLOW_BILLING_INVALID_RECEIPT", "Workflow billing receipt is invalid")
            return WorkflowNodeRun(
                id=str(uuid.uuid4()),
                run_id=run_id,
                workflow_id=workflow_id,
                node_id=node.id,
                node_type=node.type,
                status=WorkflowNodeRunStatus.SKIPPED if output.get("skipped") else WorkflowNodeRunStatus.COMPLETED,
                started_at=started_at,
                finished_at=int(time.time()),
                skipped_reason=output.get("skipped_reason"),
                input_summary=node.input_mapping,
                output_summary=output,
                credit_cost=credit_cost,
            )
        except WorkflowActionExecutionError as exc:
            return WorkflowNodeRun(
                id=str(uuid.uuid4()),
                run_id=run_id,
                workflow_id=workflow_id,
                node_id=node.id,
                node_type=node.type,
                status=WorkflowNodeRunStatus.FAILED,
                started_at=started_at,
                finished_at=int(time.time()),
                error_code=exc.code,
                error_summary=str(exc),
                input_summary=node.input_mapping,
            )
        except WorkflowSkillBillingError as exc:
            return WorkflowNodeRun(
                id=str(uuid.uuid4()),
                run_id=run_id,
                workflow_id=workflow_id,
                node_id=node.id,
                node_type=node.type,
                status=WorkflowNodeRunStatus.FAILED,
                started_at=started_at,
                finished_at=int(time.time()),
                error_code=exc.code,
                error_summary=str(exc),
                input_summary=node.input_mapping,
            )
        except Exception as exc:
            return WorkflowNodeRun(
                id=str(uuid.uuid4()),
                run_id=run_id,
                workflow_id=workflow_id,
                node_id=node.id,
                node_type=node.type,
                status=WorkflowNodeRunStatus.FAILED,
                started_at=started_at,
                finished_at=int(time.time()),
                error_code=exc.__class__.__name__,
                error_summary=str(exc),
                input_summary=node.input_mapping,
            )

    async def _execute_node(self, node: WorkflowNode, context: dict[str, Any], user_id: str) -> dict[str, Any]:
        if node.type in {WorkflowNodeType.SCHEDULE_TRIGGER, WorkflowNodeType.MANUAL_TRIGGER}:
            return {"triggered": True, "trigger": node.type.value}
        if node.type == WorkflowNodeType.APP_SKILL_ACTION:
            return await self._execute_app_skill(node, context, user_id)
        if node.type.value in {"decision", "check"}:
            if node.type == WorkflowNodeType.CHECK and node.config.get("mode", "exact") == "ai":
                await _precheck_workflow_ai_check(user_id)
                selected_inputs = [
                    {
                        "reference": reference,
                        "label": reference.split(".output.", 1)[-1].replace("_", " "),
                        "value": _resolve_template(reference, context),
                    }
                    for reference in node.config["selected_inputs"]
                ]
                result = await self.ai_service.evaluate_check(
                    question=node.config["question"],
                    selected_inputs=selected_inputs,
                )
                credit_cost = await _charge_workflow_ai_check(
                    user_id=user_id,
                    context=context,
                    node_id=node.id,
                    decision_path=result.decision_path,
                )
                matched = True if result.outcome == "true" else False if result.outcome == "false" else None
                return {
                    "matched": matched,
                    "branch": result.outcome,
                    "question": node.config["question"],
                    "projected_inputs": selected_inputs,
                    "confidence_band": result.confidence_band,
                    "decision_path": result.decision_path,
                    "unsure_reason": result.unsure_reason,
                    "_workflow_credit_cost": credit_cost,
                }
            matched = _evaluate_predicate(node.config["predicate"], context)
            return {"matched": matched, "branch": "yes" if matched else "no"}
        if node.type == WorkflowNodeType.REPEAT:
            return _execute_repeat_control(node, context)
        if node.type == WorkflowNodeType.WAIT:
            return {"waited": True, "seconds": node.config.get("seconds"), "until": node.config.get("until")}
        if node.type.value == "send_chat_message":
            return await self.action_adapter.send_chat_message(node.config, context, user_id)
        if node.type == WorkflowNodeType.CREATE_CHAT_REPORT:
            return await self.action_adapter.create_chat_report(_resolve_template(node.config, context), context, user_id)
        if node.type == WorkflowNodeType.START_NEW_CHAT:
            return await self.action_adapter.start_new_chat(_resolve_template(node.config, context), context, user_id)
        if node.type == WorkflowNodeType.ASK_USER:
            return await self.action_adapter.ask_for_user_input(_resolve_template(node.config, context), context, user_id)
        if node.type in {WorkflowNodeType.SEND_NOTIFICATION, WorkflowNodeType.SEND_EMAIL_NOTIFICATION}:
            return await self.action_adapter.send_notification(_resolve_template(node.config, context), node.type.value, user_id)
        if node.type == WorkflowNodeType.END:
            return {"ended": True}
        return {"skipped": True, "skipped_reason": f"node_type_{node.type.value}_not_executable"}

    async def _execute_app_skill(self, node: WorkflowNode, context: dict[str, Any], user_id: str) -> dict[str, Any]:
        app_id = node.config["app_id"]
        skill_id = node.config["skill_id"]
        binding_ref = node.config.get("binding_ref")
        if binding_ref is not None:
            revalidate_binding = getattr(self.app_skill_adapter, "revalidate_binding", None)
            if not callable(revalidate_binding):
                raise PermissionError("Workflow provider binding revalidation is unavailable")
            await revalidate_binding(binding_ref, user_id, app_id, skill_id)
        authored_input = node.config.get("input") or {}
        if app_id == "ai" and skill_id == "ask":
            prompt = authored_input.get("prompt") if isinstance(authored_input, dict) else None
            if not isinstance(prompt, str):
                raise WorkflowActionExecutionError("WORKFLOW_AI_ASK_INVALID", "Ask AI requires an instruction")
            request = {"prompt": render_bounded_ask_ai_prompt(prompt, context)}
        else:
            request = _resolve_template(authored_input, context)
        request.update(_resolve_template(node.input_mapping, context))
        from backend.core.api.app.services.workflow_runtime_values import resolve_workflow_runtime_values
        execution = context.get("workflow") or {}
        request = resolve_workflow_runtime_values(request, now=execution.get("started_at"), timezone=execution.get("timezone") or "UTC")
        output = await self.app_skill_adapter.execute(
            app_id,
            skill_id,
            request,
            user_id=user_id,
            billing_context={
                "workflow_id": execution.get("workflow_id"),
                "run_id": execution.get("run_id"),
                "node_id": node.id,
                "source": "workflow_test" if execution.get("step_test") else "workflow",
            },
        )
        if output.get("error"):
            raise WorkflowActionExecutionError("WORKFLOW_SKILL_FAILED", "The selected app skill could not complete this step")
        return output


def _evaluate_predicate(predicate: dict[str, Any], context: dict[str, Any]) -> bool:
    op = predicate["op"]
    if op == "and":
        return all(_evaluate_predicate(item, context) for item in predicate["conditions"])
    if op == "or":
        return any(_evaluate_predicate(item, context) for item in predicate["conditions"])
    if op == "not":
        return not _evaluate_predicate(predicate["condition"], context)

    left = _resolve_template(predicate.get("left"), context)
    if op == "exists":
        return left is not None
    right = _resolve_template(predicate.get("right"), context)
    if op == "eq":
        return left == right
    if op == "neq":
        return left != right
    if op in {"gt", "gte", "lt", "lte"} and (left is None or right is None):
        return False
    if op == "gt":
        return left > right
    if op == "gte":
        return left >= right
    if op == "lt":
        return left < right
    if op == "lte":
        return left <= right
    if op == "contains":
        return right in left if left is not None else False
    if op == "starts_with":
        return str(left).startswith(str(right))
    return False


def _workflow_cost_summary(node_runs: list[WorkflowNodeRun]) -> dict[str, int]:
    credits = sum(node.credit_cost for node in node_runs)
    return {"credits": credits} if credits > 0 else {}


async def _precheck_workflow_ai_check(user_id: str) -> None:
    try:
        await ensure_credit_headroom(
            user_id=user_id,
            estimated_credits=1,
            operation_name="workflow AI Check",
            log_prefix="[WorkflowAiCheckBilling]",
        )
    except BillingError as exc:
        raise WorkflowSkillBillingError(
            "INSUFFICIENT_CREDITS",
            "Insufficient credits for this workflow AI Check",
        ) from exc


async def _charge_workflow_ai_check(
    *,
    user_id: str,
    context: dict[str, Any],
    node_id: str,
    decision_path: str,
) -> int:
    """Settle one normal AI credit once a provider returned a usable decision."""
    if decision_path not in {"bounded_decision_primary", "structured_generative_fallback"}:
        return 0
    execution = context.get("workflow") or {}
    workflow_id = execution.get("workflow_id")
    run_id = execution.get("run_id")
    source = "workflow_test" if execution.get("step_test") else "workflow"
    if not all(isinstance(value, str) and value for value in (workflow_id, run_id, node_id)):
        raise WorkflowSkillBillingError(
            "WORKFLOW_BILLING_INVALID_CONTEXT",
            "Workflow AI Check billing context is invalid",
        )
    operation_id = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"openmates:workflow-billing:{workflow_id}:{run_id}:{node_id}:ai:workflow-check:0",
        )
    )
    model_used = (
        "typesafe/jev-1.13"
        if decision_path == "bounded_decision_primary"
        else "google/gemini-3.8-flash"
    )
    try:
        from backend.core.api.app.routes import apps_api

        charge_result = await apps_api.charge_credits_via_internal_api(
            user_id=user_id,
            user_id_hash=hashlib.sha256(user_id.encode()).hexdigest(),
            credits=1,
            app_id="ai",
            skill_id="workflow-check",
            usage_details={
                "source": source,
                "units_processed": 1,
                "model_used": model_used,
                "server_provider": "OpenRouter" if decision_path == "bounded_decision_primary" else "Google",
                "server_region": "global" if decision_path == "bounded_decision_primary" else "US",
                "decision_path": decision_path,
                "operation_id": operation_id,
            },
            idempotency_key=operation_id,
            raise_on_error=True,
        )
        actual_credits = charge_result.get("charged_credits") if isinstance(charge_result, dict) else None
        if not isinstance(actual_credits, int) or actual_credits < 0:
            raise RuntimeError("Billing response did not include charged credits")
        return actual_credits
    except WorkflowSkillBillingError:
        raise
    except Exception as exc:
        response = getattr(exc, "response", None)
        code = "INSUFFICIENT_CREDITS" if getattr(response, "status_code", None) == 402 else "WORKFLOW_BILLING_UNAVAILABLE"
        message = (
            "Insufficient credits for this workflow AI Check"
            if code == "INSUFFICIENT_CREDITS"
            else "Workflow AI Check billing could not be completed"
        )
        raise WorkflowSkillBillingError(code, message) from exc


def _execute_repeat_control(node: WorkflowNode, context: dict[str, Any]) -> dict[str, Any]:
    config = node.config
    mode = config.get("mode") or "repeat"
    max_iterations = int(config.get("max_iterations") or 1)
    if mode == "for_every":
        items = _resolve_template(config.get("items"), context)
        if not isinstance(items, list):
            items = []
        iterations = min(len(items), max_iterations)
        return {"mode": mode, "iterations": iterations, "truncated": len(items) > max_iterations}
    if mode == "repeat_until":
        condition = config.get("condition")
        matched = _evaluate_predicate(condition, context) if isinstance(condition, dict) else False
        return {"mode": mode, "matched": matched, "iterations": 0 if matched else max_iterations}
    return {"mode": mode, "configured": True, "max_iterations": max_iterations}


def _resolve_value(reference: Any, context: dict[str, Any]) -> Any:
    if not isinstance(reference, str) or not reference.startswith("$nodes."):
        return reference
    parts = reference.removeprefix("$nodes.").split(".")
    return resolve_workflow_path(context.get("nodes", {}), parts)


def _resolve_template(value: Any, context: dict[str, Any]) -> Any:
    return resolve_workflow_template(value, context)
