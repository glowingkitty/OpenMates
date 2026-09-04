# backend/core/api/app/services/workflow_identity_service.py
#
# Resolves privacy-sensitive Workflow category and icon metadata.
# Known app skills map deterministically; ambiguous graphs may use one bounded
# structured preprocessing call containing no node inputs, credentials, or runs.
# Invalid or unavailable classification always returns stable safe defaults.
# Spec: docs/specs/workflows-ui-contract/spec.yml

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from backend.core.api.app.services.workflow_models import WorkflowGraph, WorkflowNodeType


logger = logging.getLogger(__name__)

DEFAULT_WORKFLOW_CATEGORY = "general_knowledge"
DEFAULT_WORKFLOW_ICON = "help-circle"
WORKFLOW_IDENTITY_MODEL_ID = "mistral/mistral-small-2506"
WORKFLOW_IDENTITY_CONFIG_PATH = Path(__file__).resolve().parents[4] / "shared/config/workflow_identity.json"

WorkflowIdentityClassifier = Callable[[dict[str, Any]], Awaitable[dict[str, Any] | None]]


class WorkflowIdentity(BaseModel):
    category: str
    icon: str


def _load_identity_config() -> dict[str, Any]:
    return json.loads(WORKFLOW_IDENTITY_CONFIG_PATH.read_text(encoding="utf-8"))


WORKFLOW_IDENTITY_CONFIG = _load_identity_config()
WORKFLOW_CATEGORIES = WORKFLOW_IDENTITY_CONFIG["categories"]
WORKFLOW_ALLOWED_ICONS = frozenset(WORKFLOW_IDENTITY_CONFIG["allowed_icons"])

APP_IDENTITIES: dict[str, WorkflowIdentity] = {
    "code": WorkflowIdentity(category="software_development", icon="code"),
    "design": WorkflowIdentity(category="design", icon="palette"),
    "finance": WorkflowIdentity(category="finance", icon="dollar-sign"),
    "health": WorkflowIdentity(category="medical_health", icon="heart"),
    "medical": WorkflowIdentity(category="medical_health", icon="heart"),
    "news": WorkflowIdentity(category="general_knowledge", icon="newspaper"),
    "weather": WorkflowIdentity(category="science", icon="cloud-rain"),
}


def normalize_workflow_identity(category: Any, icon: Any) -> WorkflowIdentity:
    normalized_category = category.strip() if isinstance(category, str) else ""
    if normalized_category not in WORKFLOW_CATEGORIES:
        return WorkflowIdentity(category=DEFAULT_WORKFLOW_CATEGORY, icon=DEFAULT_WORKFLOW_ICON)

    normalized_icon = icon.strip() if isinstance(icon, str) else ""
    if normalized_icon not in WORKFLOW_ALLOWED_ICONS:
        normalized_icon = str(WORKFLOW_CATEGORIES[normalized_category]["fallback_icon"])
    return WorkflowIdentity(category=normalized_category, icon=normalized_icon)


def resolve_deterministic_workflow_identity(graph: WorkflowGraph) -> WorkflowIdentity | None:
    for node in graph.nodes:
        if node.type != WorkflowNodeType.APP_SKILL_ACTION:
            continue
        app_id = node.config.get("app_id")
        if isinstance(app_id, str) and app_id in APP_IDENTITIES:
            return APP_IDENTITIES[app_id]
    return None


class WorkflowIdentityService:
    def __init__(self, classifier: WorkflowIdentityClassifier | None = None) -> None:
        self.classifier = classifier

    async def resolve(
        self,
        *,
        title: str,
        description: str | None,
        graph: WorkflowGraph,
    ) -> WorkflowIdentity:
        deterministic = resolve_deterministic_workflow_identity(graph)
        if deterministic is not None:
            return deterministic
        if self.classifier is None:
            logger.info("Workflow identity used deterministic fallback because classification is unavailable")
            return normalize_workflow_identity(None, None)

        payload = self._classifier_payload(title, description, graph)
        try:
            classified = await self.classifier(payload)
        except Exception as exc:
            logger.warning("Workflow identity classification failed; using deterministic fallback", extra={"error_type": type(exc).__name__})
            return normalize_workflow_identity(None, None)
        if not isinstance(classified, dict):
            logger.warning("Workflow identity classification returned no structured result; using deterministic fallback")
            return normalize_workflow_identity(None, None)
        return normalize_workflow_identity(classified.get("category"), classified.get("icon"))

    @staticmethod
    def _classifier_payload(title: str, description: str | None, graph: WorkflowGraph) -> dict[str, Any]:
        app_skills = sorted({
            f"{node.config.get('app_id')}.{node.config.get('skill_id')}"
            for node in graph.nodes
            if node.type == WorkflowNodeType.APP_SKILL_ACTION
            and isinstance(node.config.get("app_id"), str)
            and isinstance(node.config.get("skill_id"), str)
        })
        return {
            "title": title,
            "description": description,
            "node_types": [node.type.value for node in graph.nodes],
            "app_skills": app_skills,
        }


def build_preprocessing_workflow_classifier(secrets_manager: Any) -> WorkflowIdentityClassifier:
    async def classify(payload: dict[str, Any]) -> dict[str, Any] | None:
        from backend.apps.ai.utils.llm_utils import (
            call_preprocessing_llm,
            resolve_fallback_servers_from_provider_config,
        )

        tool_definition = {
            "type": "function",
            "function": {
                "name": "classify_workflow_identity",
                "description": "Choose one supported category and one relevant icon for a Workflow.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "category": {"type": "string", "enum": sorted(WORKFLOW_CATEGORIES)},
                        "icon": {"type": "string", "enum": sorted(WORKFLOW_ALLOWED_ICONS)},
                    },
                    "required": ["category", "icon"],
                    "additionalProperties": False,
                },
            },
        }
        result = await call_preprocessing_llm(
            task_id="workflow-identity",
            model_id=WORKFLOW_IDENTITY_MODEL_ID,
            message_history=[
                {"role": "system", "content": "Return only structured Workflow identity tool arguments."},
                {"role": "user", "content": json.dumps(payload, sort_keys=True, ensure_ascii=True)},
            ],
            tool_definition=tool_definition,
            secrets_manager=secrets_manager,
            user_app_settings_and_memories_metadata=None,
            dynamic_context=None,
            fallback_models=resolve_fallback_servers_from_provider_config(WORKFLOW_IDENTITY_MODEL_ID)[:1],
        )
        if result.error_message:
            raise RuntimeError(result.error_message)
        return result.arguments

    return classify
