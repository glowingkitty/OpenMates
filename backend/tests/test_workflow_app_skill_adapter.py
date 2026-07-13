# backend/tests/test_workflow_app_skill_adapter.py
#
# Contract tests for Workflow app-skill request adaptation before dispatching to
# the shared SkillRegistry. These tests protect YAML Workflow shorthand shapes
# from leaking into app-specific schemas that expect API-native request bodies.
#
# Spec: docs/specs/workflows-cli-runtime/spec.yml

from __future__ import annotations

from typing import Any

import pytest

from backend.core.api.app.services.workflow_app_skill_adapter import WorkflowAppSkillAdapter


class FakeRegistry:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def dispatch_skill(self, app_id: str, skill_id: str, request: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((app_id, skill_id, request))
        return {"choices": [{"message": {"content": "Workflow AI OK"}}]}


@pytest.mark.anyio
async def test_ai_ask_workflow_prompt_is_adapted_to_openai_messages_with_owner_context() -> None:
    registry = FakeRegistry()
    adapter = WorkflowAppSkillAdapter(registry=registry)

    result = await adapter.execute(
        "ai",
        "ask",
        {"prompt": "Reply with exactly: Workflow AI OK", "conversation": "e2e-local", "temperature": 0},
        user_id="alice",
    )

    assert registry.calls == [
        (
            "ai",
            "ask",
            {
                "conversation": "e2e-local",
                "temperature": 0,
                "messages": [{"role": "user", "content": "Reply with exactly: Workflow AI OK"}],
                "_user_id": "alice",
                "_external_request": True,
            },
        )
    ]
    assert result["raw"] == {"choices": [{"message": {"content": "Workflow AI OK"}}]}


@pytest.mark.anyio
async def test_ai_ask_preserves_openai_messages_shape() -> None:
    registry = FakeRegistry()
    adapter = WorkflowAppSkillAdapter(registry=registry)

    await adapter.execute(
        "ai",
        "ask",
        {"messages": [{"role": "system", "content": "Keep it short"}], "model": "auto"},
        user_id="alice",
    )

    assert registry.calls[0][2] == {
        "messages": [{"role": "system", "content": "Keep it short"}],
        "model": "auto",
        "_user_id": "alice",
        "_external_request": True,
    }
