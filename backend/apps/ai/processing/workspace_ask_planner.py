# backend/apps/ai/processing/workspace_ask_planner.py
#
# Transient workspace ask planners. These helpers call the existing structured
# LLM preprocessing utility and return plaintext proposals only to the current
# authenticated request, so clients can encrypt task, plan, and project payloads
# before durable writes.
#
# Spec: docs/specs/workspace-change-history/spec.yml

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from backend.apps.ai.processing.task_proposals import TaskProposal, sanitize_task_proposals
from backend.core.api.app.services.workflow_models import WorkflowGraph
from backend.core.api.app.utils.secrets_manager import SecretsManager


logger = logging.getLogger(__name__)

WORKSPACE_ASK_MODEL_ID = "mistral/mistral-small-2506"
DEEPSEEK_V4_FLASH_FALLBACK = "deepseek/deepseek-v4-flash"


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


class WorkflowStepProposal(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    body: str = Field(default="", max_length=500)


class WorkflowProposal(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2_000)
    enabled: bool = False
    steps: list[WorkflowStepProposal] = Field(default_factory=list, max_length=5)


async def plan_task_ask(instruction: str, secrets_manager: SecretsManager) -> list[TaskProposal]:
    args = await _call_planner(
        task_id="workspace-ask-tasks",
        namespace="tasks",
        instruction=instruction,
        tool_definition=_tool(
            "plan_workspace_tasks",
            "Extract concrete task creates from the user instruction. Return only tasks the user explicitly asked for.",
            {
                "task_proposals": {
                    "type": "array",
                    "maxItems": 3,
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string", "description": "Concise task title, max 12 words."},
                            "description": {"type": "string", "description": "Optional extra context from the instruction."},
                            "status": {"type": "string", "enum": ["backlog", "todo", "in_progress", "blocked", "done"]},
                            "assignee_type": {"type": "string", "enum": ["user", "ai"]},
                        },
                        "required": ["title"],
                    },
                }
            },
            ["task_proposals"],
        ),
        secrets_manager=secrets_manager,
    )
    proposals = sanitize_task_proposals(args.get("task_proposals", []), "workspace-ask-tasks")
    if not proposals:
        raise WorkspaceAskPlanningError("LLM returned no valid task proposals")
    return proposals


async def plan_plan_ask(instruction: str, secrets_manager: SecretsManager) -> PlanProposal:
    args = await _call_planner(
        task_id="workspace-ask-plans",
        namespace="plans",
        instruction=instruction,
        tool_definition=_tool(
            "plan_workspace_plan",
            "Turn the user instruction into one concise plan create proposal.",
            {
                "title": {"type": "string", "description": "Short plan title."},
                "summary": {"type": "string", "description": "One sentence summary."},
                "goal": {"type": "string", "description": "The intended outcome of the plan."},
            },
            ["title", "summary", "goal"],
        ),
        secrets_manager=secrets_manager,
    )
    return _validate(PlanProposal, args, "plan")


async def plan_project_ask(instruction: str, secrets_manager: SecretsManager) -> ProjectProposal:
    args = await _call_planner(
        task_id="workspace-ask-projects",
        namespace="projects",
        instruction=instruction,
        tool_definition=_tool(
            "plan_workspace_project",
            "Turn the user instruction into one project create proposal.",
            {
                "name": {"type": "string", "description": "Short project name."},
                "description": {"type": "string", "description": "Optional project description."},
                "icon": {"type": "string", "description": "Simple icon keyword such as folder, rocket, book, briefcase."},
                "color": {"type": "string", "description": "Simple color keyword or default."},
            },
            ["name", "description"],
        ),
        secrets_manager=secrets_manager,
    )
    return _validate(ProjectProposal, args, "project")


async def plan_workflow_ask(instruction: str, secrets_manager: SecretsManager) -> dict[str, Any]:
    args = await _call_planner(
        task_id="workspace-ask-workflows",
        namespace="workflows",
        instruction=instruction,
        tool_definition=_tool(
            "plan_workspace_workflow",
            "Turn the user instruction into one simple workflow create proposal. Use steps for user-visible notifications or checks.",
            {
                "title": {"type": "string", "description": "Short workflow title."},
                "description": {"type": "string", "description": "One sentence workflow description."},
                "enabled": {"type": "boolean", "description": "Whether the workflow should start enabled."},
                "steps": {
                    "type": "array",
                    "maxItems": 5,
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string", "description": "Step title."},
                            "body": {"type": "string", "description": "Notification or action body."},
                        },
                        "required": ["title"],
                    },
                },
            },
            ["title", "description"],
        ),
        secrets_manager=secrets_manager,
    )
    proposal = _validate(WorkflowProposal, args, "workflow")
    return {
        "title": proposal.title,
        "description": proposal.description,
        "enabled": proposal.enabled,
        "graph": _workflow_graph(proposal).model_dump(mode="json", by_alias=True),
    }


async def _call_planner(*, task_id: str, namespace: str, instruction: str, tool_definition: dict[str, Any], secrets_manager: SecretsManager) -> dict[str, Any]:
    from backend.apps.ai.utils.llm_utils import call_preprocessing_llm, resolve_fallback_servers_from_provider_config

    messages = [
        {"role": "system", "content": "You are a precise OpenMates workspace planner. Return only structured tool arguments."},
        {"role": "user", "content": f"Plan a {namespace} ask request from this instruction:\n\n{instruction}"},
    ]
    fallbacks = _with_deepseek_utility_fallback(resolve_fallback_servers_from_provider_config(WORKSPACE_ASK_MODEL_ID))
    result = await call_preprocessing_llm(
        task_id=task_id,
        model_id=WORKSPACE_ASK_MODEL_ID,
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
    logger.info("[%s] workspace ask planner returned structured arguments", task_id)
    return result.arguments


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
