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

from backend.core.api.app.services import workflow_app_skill_adapter
from backend.core.api.app.services.workflow_app_skill_adapter import WorkflowAppSkillAdapter


class FakeRegistry:
    def __init__(self, response: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.response = response or {"choices": [{"message": {"content": "Workflow AI OK"}}]}

    async def dispatch_skill(self, app_id: str, skill_id: str, request: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((app_id, skill_id, request))
        return self.response


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


@pytest.mark.anyio
async def test_generic_output_normalization_exposes_artifact_and_task_ids() -> None:
    registry = FakeRegistry(
        response={
            "status": "processing",
            "task_ids": ["task-1"],
            "embed_ids": ["embed-1"],
            "provider": "ExampleProvider",
        }
    )
    adapter = WorkflowAppSkillAdapter(registry=registry)

    result = await adapter.execute("images", "generate", {"requests": [{"prompt": "blue circle"}]})

    assert result["summary"] == "images:generate completed"
    assert result["provider"] == "ExampleProvider"
    assert result["artifact_ids"] == ["embed-1"]
    assert result["task_ids"] == ["task-1"]


@pytest.mark.anyio
async def test_workflow_strips_prompt_injection_opt_out_and_still_sanitizes_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = FakeRegistry(response={"results": [{"description": "external workflow output"}]})
    captured_contexts: list[Any] = []

    async def fake_safety(result: dict[str, Any], context: Any) -> dict[str, Any]:
        captured_contexts.append(context)
        return result

    monkeypatch.setattr(workflow_app_skill_adapter, "sanitize_app_skill_output", fake_safety)
    adapter = WorkflowAppSkillAdapter(registry=registry)

    await adapter.execute(
        "news",
        "search",
        {
            "requests": [{"query": "AI news"}],
            "security": {"prompt_injection_protection": "disabled"},
        },
        user_id="alice",
    )

    assert "security" not in registry.calls[0][2]
    assert captured_contexts[0].surface == "workflow"
    assert captured_contexts[0].external_data is True
    assert captured_contexts[0].request_body["security"] == {"prompt_injection_protection": "disabled"}
