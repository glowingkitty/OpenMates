# backend/apps/ai/processing/workspace_ask_planner.py
#
# Transient workspace ask planners. These helpers call the existing structured
# LLM preprocessing utility and return plaintext proposals only to the current
# authenticated request, so clients can encrypt task, plan, and project payloads
# before durable writes.
#
# Spec: docs/specs/workspace-change-history/spec.yml

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.apps.ai.processing.task_proposals import TaskProposal, sanitize_task_proposals
from backend.core.api.app.services.workflow_models import WorkflowGraph, WorkflowNodeType
from backend.core.api.app.utils.secrets_manager import SecretsManager


logger = logging.getLogger(__name__)

WORKSPACE_ASK_MODEL_ID = "mistral/mistral-small-2506"
DEEPSEEK_V4_FLASH_FALLBACK = "deepseek/deepseek-v4-flash"
WORKSPACE_ASK_MAX_DESCRIPTIONS = 5
WORKSPACE_ASK_VALID_TASK_AREAS = {"code", "math", "creative", "instruction", "general"}
WORKSPACE_ASK_SAFE_NODE_TYPES = {
    WorkflowNodeType.SCHEDULE_TRIGGER.value,
    WorkflowNodeType.MANUAL_TRIGGER.value,
    WorkflowNodeType.EVENT_TRIGGER.value,
    WorkflowNodeType.APP_SKILL_ACTION.value,
    WorkflowNodeType.DECISION.value,
    WorkflowNodeType.REPEAT.value,
    WorkflowNodeType.CREATE_CHAT_REPORT.value,
    WorkflowNodeType.START_NEW_CHAT.value,
    WorkflowNodeType.SEND_NOTIFICATION.value,
    WorkflowNodeType.SEND_EMAIL_NOTIFICATION.value,
    WorkflowNodeType.ASK_USER.value,
    WorkflowNodeType.WAIT.value,
    WorkflowNodeType.END.value,
}
WORKSPACE_ASK_DEFAULT_WORKFLOW_NODE_TYPES = [
    WorkflowNodeType.MANUAL_TRIGGER.value,
    WorkflowNodeType.SEND_NOTIFICATION.value,
    WorkflowNodeType.END.value,
]


class WorkspaceAskPlanningError(RuntimeError):
    """Raised when an inference-backed ask planner cannot produce a valid proposal."""


class PlanProposal(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(default="", max_length=2_000)
    goal: str = Field(default="", max_length=2_000)


class ProjectProposal(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2_000)
    icon: str = Field(default="folder", max_length=80)
    color: str = Field(default="default", max_length=80)


class WorkspaceAskPreprocessingResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    can_proceed: bool = False
    rejection_reason: str | None = Field(default=None, max_length=500)
    namespace: Literal["tasks", "plans", "projects", "workflows"]
    operation: Literal["create", "update", "delete", "archive", "restore", "link", "unlink", "status", "unknown"] = "create"
    target_resolution_strategy: Literal["none", "single_existing_object", "multi_existing_object", "requires_clarification"] = "none"
    complexity: Literal["simple", "medium", "complex"] = "simple"
    task_area: str = Field(default="instruction", max_length=40)
    user_unhappy: bool = False
    china_model_sensitive: bool = True
    requires_main_processor: bool = True
    needed_fields: list[str] = Field(default_factory=list, max_length=24)
    selected_capability_ids: list[str] = Field(default_factory=list, max_length=12)
    built_in_nodes: list[str] = Field(default_factory=list, max_length=12)
    candidate_title: str | None = Field(default=None, max_length=200)
    ambiguity: list[dict[str, Any]] = Field(default_factory=list, max_length=10)
    selected_main_llm_model_id: str | None = None
    selected_secondary_model_id: str | None = None
    selected_fallback_model_id: str | None = None
    model_selection_reason: str | None = None
    filtered_cn_models: bool = False


WorkspaceAskIntentFrame = WorkspaceAskPreprocessingResult


class WorkspaceAskPipelineResult(BaseModel):
    proposal: Any
    processing: dict[str, Any] = Field(default_factory=dict)


WorkspaceLlmCaller = Callable[..., Awaitable[dict[str, Any]]]


class WorkflowStepProposal(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    body: str = Field(default="", max_length=500)


class WorkflowProposal(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2_000)
    enabled: bool = False
    steps: list[WorkflowStepProposal] = Field(default_factory=list, max_length=5)


async def plan_task_ask(instruction: str, secrets_manager: SecretsManager) -> list[TaskProposal]:
    return (await run_task_ask_pipeline(instruction, secrets_manager)).proposal


async def plan_plan_ask(instruction: str, secrets_manager: SecretsManager) -> PlanProposal:
    return (await run_plan_ask_pipeline(instruction, secrets_manager)).proposal


async def plan_project_ask(instruction: str, secrets_manager: SecretsManager) -> ProjectProposal:
    return (await run_project_ask_pipeline(instruction, secrets_manager)).proposal


async def plan_workflow_ask(instruction: str, secrets_manager: SecretsManager) -> dict[str, Any]:
    return (await run_workflow_ask_pipeline(instruction, secrets_manager)).proposal


async def run_task_ask_pipeline(
    instruction: str,
    secrets_manager: SecretsManager,
    *,
    llm_caller: WorkspaceLlmCaller | None = None,
    model_selector: Any | None = None,
) -> WorkspaceAskPipelineResult:
    frame = await _build_intent_frame("tasks", instruction, secrets_manager, llm_caller=llm_caller)
    _raise_for_blocking_ambiguity(frame)
    selection = await _select_workspace_model(frame, model_selector)
    frame = _frame_with_model_selection(frame, selection)
    if frame.requires_main_processor is False and frame.candidate_title:
        proposals = sanitize_task_proposals([{"title": frame.candidate_title, "status": "todo", "assignee_type": "user"}], "workspace-ask-tasks")
    else:
        args = await _call_workspace_llm(
            task_id="workspace-ask-tasks-main",
            model_id=selection.primary_model_id,
            instruction=instruction,
            tool_definition=_task_main_tool(),
            secrets_manager=secrets_manager,
            llm_caller=llm_caller,
            fallback_models=_selection_fallbacks(selection),
            dynamic_context={"intent_frame": frame.model_dump(mode="json")},
        )
        proposals = sanitize_task_proposals(args.get("tasks") or args.get("task_proposals") or [], "workspace-ask-tasks-main")
    if not proposals:
        raise WorkspaceAskPlanningError("main processor returned no valid task proposals")
    proposals = await _describe_tasks(proposals, instruction, secrets_manager, llm_caller=llm_caller)
    return WorkspaceAskPipelineResult(proposal=proposals, processing=_processing_metadata(frame, selection))


async def run_plan_ask_pipeline(
    instruction: str,
    secrets_manager: SecretsManager,
    *,
    llm_caller: WorkspaceLlmCaller | None = None,
    model_selector: Any | None = None,
) -> WorkspaceAskPipelineResult:
    frame = await _build_intent_frame("plans", instruction, secrets_manager, llm_caller=llm_caller)
    _raise_for_blocking_ambiguity(frame)
    selection = await _select_workspace_model(frame, model_selector)
    frame = _frame_with_model_selection(frame, selection)
    args = await _call_workspace_llm(
        task_id="workspace-ask-plans-main",
        model_id=selection.primary_model_id,
        instruction=instruction,
        tool_definition=_plan_main_tool(),
        secrets_manager=secrets_manager,
        llm_caller=llm_caller,
        fallback_models=_selection_fallbacks(selection),
        dynamic_context={"intent_frame": frame.model_dump(mode="json")},
    )
    proposal = _validate(PlanProposal, args.get("plan") if isinstance(args.get("plan"), dict) else args, "plan")
    proposal = await _describe_plan(proposal, instruction, secrets_manager, llm_caller=llm_caller)
    return WorkspaceAskPipelineResult(proposal=proposal, processing=_processing_metadata(frame, selection))


async def run_project_ask_pipeline(
    instruction: str,
    secrets_manager: SecretsManager,
    *,
    llm_caller: WorkspaceLlmCaller | None = None,
    model_selector: Any | None = None,
) -> WorkspaceAskPipelineResult:
    frame = await _build_intent_frame("projects", instruction, secrets_manager, llm_caller=llm_caller)
    _raise_for_blocking_ambiguity(frame)
    selection = await _select_workspace_model(frame, model_selector)
    frame = _frame_with_model_selection(frame, selection)
    args = await _call_workspace_llm(
        task_id="workspace-ask-projects-main",
        model_id=selection.primary_model_id,
        instruction=instruction,
        tool_definition=_project_main_tool(),
        secrets_manager=secrets_manager,
        llm_caller=llm_caller,
        fallback_models=_selection_fallbacks(selection),
        dynamic_context={"intent_frame": frame.model_dump(mode="json")},
    )
    proposal = _validate(ProjectProposal, args.get("project") if isinstance(args.get("project"), dict) else args, "project")
    proposal = await _describe_project(proposal, instruction, secrets_manager, llm_caller=llm_caller)
    return WorkspaceAskPipelineResult(proposal=proposal, processing=_processing_metadata(frame, selection))


async def run_workflow_ask_pipeline(
    instruction: str,
    secrets_manager: SecretsManager,
    *,
    llm_caller: WorkspaceLlmCaller | None = None,
    model_selector: Any | None = None,
    capability_registry: Any | None = None,
) -> WorkspaceAskPipelineResult:
    capability_context = _workflow_capability_context(capability_registry)
    frame = await _build_intent_frame(
        "workflows",
        instruction,
        secrets_manager,
        llm_caller=llm_caller,
        dynamic_context=capability_context["compact"],
    )
    _raise_for_blocking_ambiguity(frame)
    selection = await _select_workspace_model(frame, model_selector)
    frame = _frame_with_model_selection(frame, selection)
    selected_context = _selected_workflow_capability_context(frame, capability_context)
    args = await _call_workspace_llm(
        task_id="workspace-ask-workflows-main",
        model_id=selection.primary_model_id,
        instruction=instruction,
        tool_definition=_workflow_main_tool(),
        secrets_manager=secrets_manager,
        llm_caller=llm_caller,
        fallback_models=_selection_fallbacks(selection),
        dynamic_context={"intent_frame": frame.model_dump(mode="json"), **selected_context},
    )
    proposal = _workflow_proposal_from_main(
        args,
        {item["id"] for item in selected_context["selected_capabilities"]},
        set(selected_context["built_in_nodes"]),
    )
    proposal = await _describe_workflow(proposal, instruction, secrets_manager, llm_caller=llm_caller)
    processing = _processing_metadata(frame, selection)
    processing["filtered_unknown_capability_ids"] = selected_context["filtered_unknown_capability_ids"]
    processing["selected_capability_ids"] = [item["id"] for item in selected_context["selected_capabilities"]]
    return WorkspaceAskPipelineResult(proposal=proposal, processing=processing)


async def _call_planner(*, task_id: str, namespace: str, instruction: str, tool_definition: dict[str, Any], secrets_manager: SecretsManager) -> dict[str, Any]:
    # Backward-compatible wrapper for old tests and any un-migrated callers.
    return await _call_workspace_llm(
        task_id=task_id,
        model_id=WORKSPACE_ASK_MODEL_ID,
        instruction=instruction,
        tool_definition=tool_definition,
        secrets_manager=secrets_manager,
        dynamic_context={"namespace": namespace},
    )


async def _call_workspace_llm(
    *,
    task_id: str,
    model_id: str,
    instruction: str,
    tool_definition: dict[str, Any],
    secrets_manager: SecretsManager,
    llm_caller: WorkspaceLlmCaller | None = None,
    fallback_models: list[str] | None = None,
    dynamic_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if llm_caller is not None:
        result = await llm_caller(
            task_id=task_id,
            model_id=model_id,
            instruction=instruction,
            tool_definition=tool_definition,
            secrets_manager=secrets_manager,
            fallback_models=fallback_models or [],
            dynamic_context=dynamic_context,
        )
        if not isinstance(result, dict):
            raise WorkspaceAskPlanningError("LLM caller returned invalid arguments")
        return result

    from backend.apps.ai.utils.llm_utils import call_preprocessing_llm, resolve_fallback_servers_from_provider_config

    messages = [
        {"role": "system", "content": "You are a precise OpenMates workspace processor. Return only structured tool arguments."},
        {"role": "user", "content": f"Process this workspace ask instruction:\n\n{instruction}"},
    ]
    if dynamic_context:
        messages.insert(1, {"role": "system", "content": f"Context JSON:\n{_json(dynamic_context)}"})
    fallbacks = fallback_models or _with_deepseek_utility_fallback(resolve_fallback_servers_from_provider_config(model_id))
    result = await call_preprocessing_llm(
        task_id=task_id,
        model_id=model_id,
        message_history=messages,
        tool_definition=tool_definition,
        secrets_manager=secrets_manager,
        user_app_settings_and_memories_metadata=None,
        dynamic_context=None,
        fallback_models=fallbacks,
    )
    if result.error_message:
        raise WorkspaceAskPlanningError(result.error_message)
    if not isinstance(result.arguments, dict):
        raise WorkspaceAskPlanningError("LLM returned no tool arguments")
    logger.info("[%s] workspace ask pipeline returned structured arguments", task_id)
    return result.arguments


async def _build_intent_frame(
    namespace: Literal["tasks", "plans", "projects", "workflows"],
    instruction: str,
    secrets_manager: SecretsManager,
    *,
    llm_caller: WorkspaceLlmCaller | None = None,
    dynamic_context: dict[str, Any] | None = None,
) -> WorkspaceAskIntentFrame:
    args = await _call_workspace_llm(
        task_id=f"workspace-ask-{namespace}-preprocessor",
        model_id=WORKSPACE_ASK_MODEL_ID,
        instruction=instruction,
        tool_definition=_intent_frame_tool(namespace),
        secrets_manager=secrets_manager,
        llm_caller=llm_caller,
        dynamic_context=dynamic_context,
    )
    try:
        return _normalize_preprocessing_result(WorkspaceAskPreprocessingResult.model_validate({"namespace": namespace, **args}))
    except ValidationError as exc:
        raise WorkspaceAskPlanningError("LLM returned invalid workspace ask preprocessing result") from exc


async def _select_workspace_model(frame: WorkspaceAskIntentFrame, model_selector: Any | None) -> Any:
    selector = model_selector
    if selector is None:
        from backend.apps.ai.utils.model_selector import get_model_selector

        selector = await get_model_selector()
    complexity = "complex" if frame.complexity in {"medium", "complex"} else "simple"
    return selector.select_models(
        task_area=frame.task_area,
        complexity=complexity,
        china_related=frame.china_model_sensitive,
        user_unhappy=frame.user_unhappy,
        log_prefix=f"[workspace-ask-{frame.namespace}] ",
    )


def _normalize_preprocessing_result(frame: WorkspaceAskPreprocessingResult) -> WorkspaceAskPreprocessingResult:
    updates: dict[str, Any] = {}
    if frame.task_area not in WORKSPACE_ASK_VALID_TASK_AREAS:
        updates["task_area"] = "general"
    if frame.namespace != "workflows":
        updates["selected_capability_ids"] = []
        updates["built_in_nodes"] = []
    if not isinstance(frame.user_unhappy, bool):
        updates["user_unhappy"] = False
    if not isinstance(frame.china_model_sensitive, bool):
        updates["china_model_sensitive"] = True
    return frame.model_copy(update=updates) if updates else frame


def _frame_with_model_selection(frame: WorkspaceAskIntentFrame, selection: Any) -> WorkspaceAskIntentFrame:
    return frame.model_copy(update={
        "selected_main_llm_model_id": getattr(selection, "primary_model_id", None),
        "selected_secondary_model_id": getattr(selection, "secondary_model_id", None),
        "selected_fallback_model_id": getattr(selection, "fallback_model_id", None),
        "model_selection_reason": getattr(selection, "selection_reason", ""),
        "filtered_cn_models": bool(getattr(selection, "filtered_cn_models", False)),
    })


def _raise_for_blocking_ambiguity(frame: WorkspaceAskIntentFrame) -> None:
    if not frame.can_proceed:
        raise WorkspaceAskPlanningError(frame.rejection_reason or "clarification required before applying workspace ask")
    if any(item.get("severity") == "blocking" for item in frame.ambiguity):
        raise WorkspaceAskPlanningError("clarification required before applying workspace ask")
    if frame.operation in {"delete", "archive"}:
        raise WorkspaceAskPlanningError("clarification required before destructive workspace ask")
    if frame.target_resolution_strategy == "requires_clarification":
        raise WorkspaceAskPlanningError("clarification required before applying workspace ask")


def _selection_fallbacks(selection: Any) -> list[str]:
    return [value for value in (getattr(selection, "secondary_model_id", None), getattr(selection, "fallback_model_id", None)) if isinstance(value, str) and value]


def _processing_metadata(frame: WorkspaceAskIntentFrame, selection: Any) -> dict[str, Any]:
    preprocessing_result = frame.model_dump(mode="json")
    return {
        "intent_frame": preprocessing_result,
        "preprocessing_result": preprocessing_result,
        "model_selection": {
            "primary_model_id": getattr(selection, "primary_model_id", None),
            "secondary_model_id": getattr(selection, "secondary_model_id", None),
            "fallback_model_id": getattr(selection, "fallback_model_id", None),
            "selection_reason": getattr(selection, "selection_reason", ""),
            "filtered_cn_models": bool(getattr(selection, "filtered_cn_models", False)),
        },
        "repair_attempted": False,
        "description_model_id": WORKSPACE_ASK_MODEL_ID,
    }


def _intent_frame_tool(namespace: str) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "can_proceed": {"type": "boolean"},
        "rejection_reason": {"type": "string"},
        "operation": {"type": "string", "enum": ["create", "update", "delete", "archive", "restore", "link", "unlink", "status", "unknown"]},
        "target_resolution_strategy": {"type": "string", "enum": ["none", "single_existing_object", "multi_existing_object", "requires_clarification"]},
        "complexity": {"type": "string", "enum": ["simple", "medium", "complex"]},
        "task_area": {"type": "string", "enum": sorted(WORKSPACE_ASK_VALID_TASK_AREAS)},
        "user_unhappy": {"type": "boolean"},
        "china_model_sensitive": {"type": "boolean"},
        "requires_main_processor": {"type": "boolean"},
        "needed_fields": {"type": "array", "items": {"type": "string"}},
        "candidate_title": {"type": "string"},
        "ambiguity": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "field": {"type": "string"},
                    "severity": {"type": "string", "enum": ["recoverable", "blocking"]},
                    "reason": {"type": "string"},
                },
                "required": ["field", "severity", "reason"],
            },
        },
    }
    if namespace == "workflows":
        properties["selected_capability_ids"] = {"type": "array", "items": {"type": "string"}}
        properties["built_in_nodes"] = {"type": "array", "items": {"type": "string", "enum": sorted(WORKSPACE_ASK_SAFE_NODE_TYPES)}}
    return _tool(
        "build_workspace_ask_intent_frame",
        (
            f"Classify this {namespace} workspace ask request. Return routing, safety, complexity, "
            "model-selection hints, needed context, and ambiguity only. "
            "Use can_proceed=false for unsafe or under-specified destructive/modification requests. "
            "Do not create final user-visible task, plan, project, or workflow content."
        ),
        properties,
        ["can_proceed", "operation", "complexity", "task_area", "china_model_sensitive", "requires_main_processor"],
    )


def _task_main_tool() -> dict[str, Any]:
    return _tool(
        "draft_workspace_tasks",
        "Create final task drafts from the intent frame. Do not invent tasks beyond the user request.",
        {
            "tasks": {
                "type": "array",
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                        "status": {"type": "string", "enum": ["backlog", "todo", "in_progress", "blocked", "done"]},
                        "assignee_type": {"type": "string", "enum": ["user", "ai"]},
                    },
                    "required": ["title"],
                },
            }
        },
        ["tasks"],
    )


def _plan_main_tool() -> dict[str, Any]:
    return _tool(
        "draft_workspace_plan",
        "Create one final plan draft from the intent frame.",
        {
            "plan": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "goal": {"type": "string"},
                },
                "required": ["title", "summary", "goal"],
            }
        },
        ["plan"],
    )


def _project_main_tool() -> dict[str, Any]:
    return _tool(
        "draft_workspace_project",
        "Create one final project draft from the intent frame.",
        {
            "project": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "icon": {"type": "string"},
                    "color": {"type": "string"},
                },
                "required": ["name", "description"],
            }
        },
        ["project"],
    )


def _workflow_main_tool() -> dict[str, Any]:
    return _tool(
        "draft_workspace_workflow",
        "Create one final workflow draft using only loaded built-in nodes and selected real capabilities.",
        {
            "title": {"type": "string"},
            "description": {"type": "string"},
            "enabled": {"type": "boolean"},
            "graph": _workflow_graph_tool_schema(),
        },
        ["title", "description", "enabled", "graph"],
    )


def _workflow_graph_tool_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "version": {"type": "integer", "enum": [1]},
            "trigger_node_id": {"type": "string"},
            "nodes": {
                "type": "array",
                "minItems": 2,
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "type": {"type": "string", "enum": sorted(WORKSPACE_ASK_SAFE_NODE_TYPES)},
                        "title": {"type": "string"},
                        "config": {"type": "object"},
                    },
                    "required": ["id", "type", "title"],
                },
            },
            "edges": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"from": {"type": "string"}, "to": {"type": "string"}},
                    "required": ["from", "to"],
                },
            },
        },
        "required": ["version", "trigger_node_id", "nodes", "edges"],
    }


def _description_tool(namespace: str, count: int) -> dict[str, Any]:
    if namespace == "tasks":
        return _tool(
            "generate_workspace_task_descriptions",
            "Generate concise task descriptions from final validated task data. Return exactly one description per task.",
            {"descriptions": {"type": "array", "minItems": count, "maxItems": count, "items": {"type": "string"}}},
            ["descriptions"],
        )
    return _tool(
        f"generate_workspace_{namespace}_description",
        f"Generate one concise {namespace[:-1] if namespace.endswith('s') else namespace} description from final validated data.",
        {"description": {"type": "string"}},
        ["description"],
    )


def _workflow_capability_context(capability_registry: Any | None) -> dict[str, Any]:
    registry = capability_registry
    if registry is None:
        from backend.core.api.app.services.workflow_capability_registry import WorkflowCapabilityRegistry

        registry = WorkflowCapabilityRegistry()
    capabilities = []
    for capability in registry.list_capabilities(user_id=None):
        if _value(capability, "enabled") is False:
            continue
        capability_id = str(_value(capability, "id") or "").strip()
        if not capability_id:
            continue
        metadata = _as_dict(_value(capability, "metadata"))
        capabilities.append(
            {
                "id": capability_id,
                "title": str(_value(capability, "title") or capability_id),
                "app_id": str(metadata.get("app_id") or capability_id.split(".", 1)[0]),
                "skill_id": str(metadata.get("skill_id") or capability_id.split(".", 1)[-1]),
                "hint": _capability_hint(metadata),
                "input_schema": metadata.get("input_schema") if isinstance(metadata.get("input_schema"), Mapping) else {},
                "output_schema": metadata.get("output_schema") if isinstance(metadata.get("output_schema"), Mapping) else {},
                "workflow": metadata.get("workflow") if isinstance(metadata.get("workflow"), Mapping) else {},
            }
        )
    return {
        "capabilities": capabilities,
        "compact": {
            "available_capability_ids": [item["id"] for item in capabilities],
            "capability_hints": [{"id": item["id"], "title": item["title"], "hint": item["hint"]} for item in capabilities],
            "built_in_nodes": sorted(WORKSPACE_ASK_SAFE_NODE_TYPES),
            "capability_id_rule": "Use only capability IDs from available_capability_ids. Do not invent external app skills.",
        },
    }


def _selected_workflow_capability_context(frame: WorkspaceAskIntentFrame, context: dict[str, Any]) -> dict[str, Any]:
    by_id = {item["id"]: item for item in context["capabilities"]}
    selected = [by_id[item] for item in frame.selected_capability_ids if item in by_id]
    filtered = [item for item in frame.selected_capability_ids if item not in by_id]
    built_in_nodes = _selected_workflow_node_types(frame, has_selected_capabilities=bool(selected))
    return {
        "selected_capabilities": selected,
        "filtered_unknown_capability_ids": filtered,
        "built_in_nodes": built_in_nodes,
        "node_type_rule": "Use only these built_in_nodes plus selected_capabilities. If no selected_capabilities are listed, do not emit app_skill_action nodes.",
    }


def _selected_workflow_node_types(frame: WorkspaceAskIntentFrame, *, has_selected_capabilities: bool) -> list[str]:
    selected = [node_type for node_type in frame.built_in_nodes if node_type in WORKSPACE_ASK_SAFE_NODE_TYPES]
    if not selected:
        selected = list(WORKSPACE_ASK_DEFAULT_WORKFLOW_NODE_TYPES)
    for required_node in (WorkflowNodeType.MANUAL_TRIGGER.value, WorkflowNodeType.END.value):
        if required_node not in selected:
            selected.append(required_node)
    if has_selected_capabilities and WorkflowNodeType.APP_SKILL_ACTION.value not in selected:
        selected.append(WorkflowNodeType.APP_SKILL_ACTION.value)
    if not has_selected_capabilities:
        selected = [node_type for node_type in selected if node_type != WorkflowNodeType.APP_SKILL_ACTION.value]
    return list(dict.fromkeys(selected))


def _capability_hint(metadata: dict[str, Any]) -> str:
    workflow = metadata.get("workflow") if isinstance(metadata.get("workflow"), Mapping) else {}
    pieces = [str(workflow.get("effect") or "").strip(), str(workflow.get("execution_mode") or "").strip()]
    return " ".join(piece for piece in pieces if piece)


def _workflow_proposal_from_main(args: dict[str, Any], allowed_capability_ids: set[str] | None = None, allowed_node_types: set[str] | None = None) -> dict[str, Any]:
    raw = args.get("workflow") if isinstance(args.get("workflow"), dict) else args
    if not isinstance(raw, dict):
        raise WorkspaceAskPlanningError("main processor returned invalid workflow proposal")
    graph_raw = raw.get("graph")
    if not _looks_like_workflow_graph(graph_raw):
        proposal = _validate(WorkflowProposal, raw, "workflow")
        graph_raw = _workflow_graph(proposal).model_dump(mode="json", by_alias=True)
    if allowed_capability_ids is not None or allowed_node_types is not None:
        _reject_raw_unselected_workflow_nodes(graph_raw, allowed_capability_ids or set(), allowed_node_types or WORKSPACE_ASK_SAFE_NODE_TYPES)
    try:
        graph_model = WorkflowGraph.model_validate(graph_raw)
    except (ValidationError, ValueError) as exc:
        raise WorkspaceAskPlanningError("main processor returned invalid workflow graph") from exc
    if allowed_capability_ids is not None or allowed_node_types is not None:
        _reject_unselected_workflow_nodes(graph_model, allowed_capability_ids or set(), allowed_node_types or WORKSPACE_ASK_SAFE_NODE_TYPES)
    graph = graph_model.model_dump(mode="json", by_alias=True)
    title = _clean_text(raw.get("title"), max_length=200) or "Untitled workflow"
    description = _clean_text(raw.get("description"), max_length=2_000) or ""
    return {"title": title, "description": description, "enabled": bool(raw.get("enabled", False)), "graph": graph}


def _looks_like_workflow_graph(value: Any) -> bool:
    return isinstance(value, dict) and isinstance(value.get("nodes"), list) and isinstance(value.get("trigger_node_id"), str)


def _reject_unselected_workflow_nodes(graph: WorkflowGraph, allowed_capability_ids: set[str], allowed_node_types: set[str]) -> None:
    for node in graph.nodes:
        _reject_unselected_workflow_node(str(node.type.value), _as_dict(node.config), allowed_capability_ids, allowed_node_types)


def _reject_raw_unselected_workflow_nodes(graph: Any, allowed_capability_ids: set[str], allowed_node_types: set[str]) -> None:
    if not isinstance(graph, dict) or not isinstance(graph.get("nodes"), list):
        return
    for node in graph["nodes"]:
        if not isinstance(node, dict):
            continue
        _reject_unselected_workflow_node(str(node.get("type") or ""), _as_dict(node.get("config")), allowed_capability_ids, allowed_node_types)


def _reject_unselected_workflow_node(node_type: str, config: dict[str, Any], allowed_capability_ids: set[str], allowed_node_types: set[str]) -> None:
    if node_type == WorkflowNodeType.APP_SKILL_ACTION.value:
        app_id = str(config.get("app_id") or "").strip()
        skill_id = str(config.get("skill_id") or "").strip()
        if f"{app_id}.{skill_id}" not in allowed_capability_ids:
            raise WorkspaceAskPlanningError("main processor returned an unselected workflow capability")
    if node_type not in allowed_node_types:
        raise WorkspaceAskPlanningError("main processor returned an unselected workflow node type")


async def _describe_tasks(
    proposals: list[TaskProposal],
    instruction: str,
    secrets_manager: SecretsManager,
    *,
    llm_caller: WorkspaceLlmCaller | None,
) -> list[TaskProposal]:
    missing_indexes = [index for index, proposal in enumerate(proposals) if not proposal.description]
    if not missing_indexes:
        return proposals
    try:
        args = await _call_workspace_llm(
            task_id="workspace-ask-tasks-description",
            model_id=WORKSPACE_ASK_MODEL_ID,
            instruction=instruction,
            tool_definition=_description_tool("tasks", len(proposals)),
            secrets_manager=secrets_manager,
            llm_caller=llm_caller,
            dynamic_context={"tasks": [proposal.model_dump() for proposal in proposals]},
        )
    except WorkspaceAskPlanningError:
        return proposals
    descriptions = args.get("descriptions")
    if not isinstance(descriptions, list):
        return proposals
    updated: list[TaskProposal] = []
    for index, proposal in enumerate(proposals):
        description = proposal.description or _clean_text(descriptions[index] if index < len(descriptions) else None, max_length=2_000)
        updated.append(proposal.model_copy(update={"description": description}))
    return updated


async def _describe_plan(
    proposal: PlanProposal,
    instruction: str,
    secrets_manager: SecretsManager,
    *,
    llm_caller: WorkspaceLlmCaller | None,
) -> PlanProposal:
    if proposal.summary:
        return proposal
    description = await _single_description("plans", proposal.model_dump(), instruction, secrets_manager, llm_caller)
    return proposal.model_copy(update={"summary": description or proposal.summary})


async def _describe_project(
    proposal: ProjectProposal,
    instruction: str,
    secrets_manager: SecretsManager,
    *,
    llm_caller: WorkspaceLlmCaller | None,
) -> ProjectProposal:
    if proposal.description:
        return proposal
    description = await _single_description("projects", proposal.model_dump(), instruction, secrets_manager, llm_caller)
    return proposal.model_copy(update={"description": description or proposal.description})


async def _describe_workflow(
    proposal: dict[str, Any],
    instruction: str,
    secrets_manager: SecretsManager,
    *,
    llm_caller: WorkspaceLlmCaller | None,
) -> dict[str, Any]:
    if proposal.get("description"):
        return proposal
    description = await _single_description("workflows", proposal, instruction, secrets_manager, llm_caller)
    return {**proposal, "description": description or proposal.get("description") or ""}


async def _single_description(namespace: str, final_data: dict[str, Any], instruction: str, secrets_manager: SecretsManager, llm_caller: WorkspaceLlmCaller | None) -> str | None:
    try:
        args = await _call_workspace_llm(
            task_id=f"workspace-ask-{namespace}-description",
            model_id=WORKSPACE_ASK_MODEL_ID,
            instruction=instruction,
            tool_definition=_description_tool(namespace, 1),
            secrets_manager=secrets_manager,
            llm_caller=llm_caller,
            dynamic_context={"final_validated_data": final_data},
        )
    except WorkspaceAskPlanningError:
        return None
    return _clean_text(args.get("description"), max_length=2_000)


def _value(item: Any, key: str) -> Any:
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key, None)


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _clean_text(value: Any, *, max_length: int) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned[:max_length] if cleaned else None


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _with_deepseek_utility_fallback(fallbacks: list[str]) -> list[str]:
    return [DEEPSEEK_V4_FLASH_FALLBACK] + [fallback for fallback in fallbacks if fallback != DEEPSEEK_V4_FLASH_FALLBACK]


def _tool(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


def _validate(model: type[BaseModel], value: dict[str, Any], label: str) -> Any:
    try:
        return model.model_validate(value)
    except ValidationError as exc:
        raise WorkspaceAskPlanningError(f"LLM returned invalid {label} proposal") from exc


def _workflow_graph(proposal: WorkflowProposal) -> WorkflowGraph:
    steps = proposal.steps or [WorkflowStepProposal(title=proposal.title, body=proposal.description)]
    nodes: list[dict[str, Any]] = [{"id": "manual-trigger", "type": "manual_trigger", "title": "Manual trigger"}]
    edges: list[dict[str, str]] = []
    previous = "manual-trigger"
    for index, step in enumerate(steps[:5], start=1):
        node_id = f"notify-{index}"
        nodes.append({
            "id": node_id,
            "type": "send_notification",
            "title": step.title,
            "config": {"title": step.title, "body": step.body or proposal.description or step.title},
        })
        edges.append({"from": previous, "to": node_id})
        previous = node_id
    nodes.append({"id": "end", "type": "end", "title": "End"})
    edges.append({"from": previous, "to": "end"})
    return WorkflowGraph(version=1, trigger_node_id="manual-trigger", nodes=nodes, edges=edges)
