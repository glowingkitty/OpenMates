# backend/core/api/app/services/workflow_runner.py
#
# Deterministic Workflows V1 runner for validated server-side workflow graphs.
# V1 executes a deliberately small safe node set while preserving per-node run
# records that every client can inspect.
#
# Spec: docs/specs/workflows-v1/spec.yml

from __future__ import annotations

import time
import uuid
from typing import Any

from starlette.concurrency import run_in_threadpool

from backend.core.api.app.services.workflow_action_adapter import WorkflowActionAdapter, WorkflowActionExecutionError
from backend.core.api.app.services.workflow_app_skill_adapter import WorkflowAppSkillAdapter
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
from backend.core.api.app.services.workflow_template_expressions import resolve_workflow_template


class WorkflowRunner:
    def __init__(
        self,
        workflow_service: WorkflowService,
        app_skill_adapter: WorkflowAppSkillAdapter | None = None,
        action_adapter: WorkflowActionAdapter | None = None,
    ) -> None:
        self.workflow_service = workflow_service
        self.app_skill_adapter = app_skill_adapter or WorkflowAppSkillAdapter()
        self.action_adapter = action_adapter or WorkflowActionAdapter()

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
        started_at = int(time.time())
        context: dict[str, Any] = {"trigger": input_payload or {}, "nodes": {}}
        node_runs: list[WorkflowNodeRun] = []

        nodes_by_id = {node.id: node for node in workflow.graph.nodes}
        outgoing_edges: dict[str, list[Any]] = {}
        for edge in workflow.graph.edges:
            outgoing_edges.setdefault(edge.from_node, []).append(edge)

        current_node_id: str | None = workflow.graph.trigger_node_id
        visited_count = 0
        max_nodes = int(workflow.graph.limits.get("max_nodes", max(len(workflow.graph.nodes), 1) * 2))

        while current_node_id is not None:
            if accepted_run and await run_in_threadpool(self.workflow_service.is_run_cancellation_requested, workflow.id, run_id, user_id):
                return await self._save_cancelled_run(run_id, workflow.id, version_id, trigger_type, started_at, node_runs, context, user_id, vault_key_id)
            visited_count += 1
            if visited_count > max_nodes:
                raise ValueError("Workflow execution exceeded max_nodes")
            node = nodes_by_id[current_node_id]
            node_run = await self._run_node(run_id, workflow.id, node, context, user_id)
            node_runs.append(node_run)
            context["nodes"][node.id] = {"output": node_run.output_summary, "status": node_run.status.value}
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
                    error_summary=node_run.error_summary,
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
                    node_runs=node_runs,
                    output_summary=context,
                )
                return await run_in_threadpool(self.workflow_service.save_run, user_id, run, vault_key_id)
            current_node_id = self._next_node_id(node, node_run.output_summary, outgoing_edges)

        run = WorkflowRunDetail(
            id=run_id,
            workflow_id=workflow.id,
            version_id=version_id,
            trigger_type=trigger_type,
            status=WorkflowRunStatus.COMPLETED,
            started_at=started_at,
            finished_at=int(time.time()),
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
        context: dict[str, Any] = {"trigger": {"step_test": True}, "nodes": {}}
        node_run = await self._run_node(run_id, workflow.id, node, context, user_id)
        context["nodes"][node.id] = {"output": node_run.output_summary, "status": node_run.status.value}
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
            error_summary=node_run.error_summary,
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
            node_runs=node_runs,
            output_summary=context,
        )
        return await run_in_threadpool(self.workflow_service.save_run, user_id, run, vault_key_id)

    def _next_node_id(self, node: WorkflowNode, output: dict[str, Any], outgoing_edges: dict[str, list[Any]]) -> str | None:
        candidates = outgoing_edges.get(node.id, [])
        if not candidates:
            return None
        if node.type == WorkflowNodeType.DECISION:
            branch = output.get("branch")
            for edge in candidates:
                if edge.branch == branch or (branch == "yes" and edge.branch == "true") or (branch == "no" and edge.branch == "false"):
                    return edge.to_node
            return None
        for edge in candidates:
            if edge.branch is None:
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
        if node.type == WorkflowNodeType.DECISION:
            matched = _evaluate_predicate(node.config["predicate"], context)
            return {"matched": matched, "branch": "yes" if matched else "no"}
        if node.type == WorkflowNodeType.REPEAT:
            return _execute_repeat_control(node, context)
        if node.type == WorkflowNodeType.WAIT:
            return {"waited": True, "seconds": node.config.get("seconds"), "until": node.config.get("until")}
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
        request = _resolve_template(node.config.get("input") or {}, context)
        request.update(_resolve_template(node.input_mapping, context))
        return await self.app_skill_adapter.execute(app_id, skill_id, request)


def _evaluate_predicate(predicate: dict[str, Any], context: dict[str, Any]) -> bool:
    op = predicate["op"]
    if op == "and":
        return all(_evaluate_predicate(item, context) for item in predicate["conditions"])
    if op == "or":
        return any(_evaluate_predicate(item, context) for item in predicate["conditions"])
    if op == "not":
        return not _evaluate_predicate(predicate["condition"], context)

    left = _resolve_value(predicate.get("left"), context)
    if op == "exists":
        return left is not None
    right = predicate.get("right")
    if op == "eq":
        return left == right
    if op == "neq":
        return left != right
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
    value: Any = context.get("nodes", {})
    for part in parts:
        if isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value


def _resolve_template(value: Any, context: dict[str, Any]) -> Any:
    return resolve_workflow_template(value, context)
