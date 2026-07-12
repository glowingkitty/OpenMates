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

from backend.core.api.app.services.workflow_action_adapter import WorkflowActionAdapter
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
        if run_id is not None and not version_id:
            raise ValueError("Accepted workflow runs require a pinned version_id")
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
            visited_count += 1
            if visited_count > max_nodes:
                raise ValueError("Workflow execution exceeded max_nodes")
            node = nodes_by_id[current_node_id]
            node_run = await self._run_node(run_id, workflow.id, node, context, user_id)
            node_runs.append(node_run)
            context["nodes"][node.id] = {"output": node_run.output_summary, "status": node_run.status.value}
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

    def _next_node_id(self, node: WorkflowNode, output: dict[str, Any], outgoing_edges: dict[str, list[Any]]) -> str | None:
        candidates = outgoing_edges.get(node.id, [])
        if not candidates:
            return None
        if node.type == WorkflowNodeType.DECISION:
            branch = output.get("branch")
            for edge in candidates:
                if edge.branch == branch:
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
            return {"configured": True, "max_iterations": node.config["max_iterations"], "skipped": True, "skipped_reason": "repeat_execution_not_enabled_in_this_slice"}
        if node.type == WorkflowNodeType.CREATE_CHAT_REPORT:
            return await self.action_adapter.create_chat_report(node.config, context)
        if node.type == WorkflowNodeType.START_NEW_CHAT:
            return await self.action_adapter.start_new_chat(node.config, context)
        if node.type in {WorkflowNodeType.SEND_NOTIFICATION, WorkflowNodeType.SEND_EMAIL_NOTIFICATION}:
            return await self.action_adapter.send_notification(node.config, node.type.value)
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
    if isinstance(value, str):
        return _resolve_value(value, context)
    if isinstance(value, list):
        return [_resolve_template(item, context) for item in value]
    if isinstance(value, dict):
        return {key: _resolve_template(item, context) for key, item in value.items()}
    return value
