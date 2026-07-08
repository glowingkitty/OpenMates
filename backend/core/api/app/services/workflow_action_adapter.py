# backend/core/api/app/services/workflow_action_adapter.py
#
# Workflow platform action adapter.
# Centralizes OpenMates-native side effects so the runner does not hardcode
# notification, report, or chat behavior. Production callers can replace the
# default recorder with real services while tests assert adapter boundaries.
#
# Spec: docs/specs/workflows-v1/spec.yml

from __future__ import annotations

import uuid
from typing import Any


class WorkflowActionAdapter:
    """Execute OpenMates platform action nodes for workflow runs."""

    def __init__(self) -> None:
        self.actions: list[dict[str, Any]] = []

    async def create_chat_report(self, config: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        action = {
            "type": "create_chat_report",
            "report_id": str(uuid.uuid4()),
            "summary": config.get("summary") or "Workflow report created",
            "source_nodes": list((context.get("nodes") or {}).keys()),
        }
        self.actions.append(action)
        return action

    async def start_new_chat(self, config: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        action = {
            "type": "start_new_chat",
            "chat_id": str(uuid.uuid4()),
            "title": config.get("title") or "Workflow chat",
            "message": config.get("message") or "",
        }
        self.actions.append(action)
        return action

    async def send_notification(self, config: dict[str, Any], channel: str) -> dict[str, Any]:
        action = {
            "type": channel,
            "queued": True,
            "channel": channel,
            "title": config.get("title"),
            "body": config.get("body"),
        }
        self.actions.append(action)
        return action
