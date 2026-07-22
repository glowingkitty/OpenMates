# backend/tests/test_workspace_ask_pipeline.py
#
# Workspace ask AI-pipeline contract tests.
# These tests protect the intended preprocessor -> model selector -> selected
# main processor -> deterministic postprocessor -> description-generator flow
# without calling external model providers.

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.apps.ai.processing import workspace_ask_planner as planner


class FakeModelSelector:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def select_models(self, **kwargs):
        self.calls.append(kwargs)
        complexity = kwargs.get("complexity")
        return SimpleNamespace(
            primary_model_id="google/gemini-3.6-flash" if complexity == "complex" else "google/gemini-3-flash-preview",
            secondary_model_id="anthropic/claude-haiku-4-5-20251001",
            fallback_model_id="anthropic/claude-sonnet-4-6",
            selection_reason=f"fake selector complexity={complexity}",
            filtered_cn_models=False,
        )


class FakeCapabilityRegistry:
    def list_capabilities(self, user_id=None):
        del user_id
        return [
            SimpleNamespace(
                id="tasks.create",
                title="tasks.create",
                type="app_skill",
                metadata={
                    "app_id": "tasks",
                    "skill_id": "create",
                    "input_schema": {"type": "object", "properties": {"tasks": {"type": "array"}}},
                    "output_schema": {"type": "object", "properties": {"task_ids": {"type": "array"}}},
                    "workflow": {"available": True, "effect": "chat_write"},
                },
            ),
            SimpleNamespace(
                id="web.search",
                title="web.search",
                type="app_skill",
                metadata={
                    "app_id": "web",
                    "skill_id": "search",
                    "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}},
                    "output_schema": {"type": "object", "properties": {"results": {"type": "array"}}},
                    "workflow": {"available": True, "effect": "read"},
                },
            ),
            SimpleNamespace(
                id="slack.send_message",
                title="slack.send_message",
                type="app_skill",
                enabled=False,
                metadata={"app_id": "slack", "skill_id": "send_message", "workflow": {"available": False}},
            ),
        ]


@pytest.mark.asyncio
async def test_task_pipeline_uses_preprocessor_selected_main_model_and_description_generator() -> None:
    calls: list[dict] = []

    async def fake_llm(**kwargs):
        calls.append(kwargs)
        task_id = kwargs["task_id"]
        if task_id.endswith("-preprocessor"):
            preprocessor_properties = kwargs["tool_definition"]["function"]["parameters"]["properties"]
            assert "can_proceed" in preprocessor_properties
            assert "selected_capability_ids" not in preprocessor_properties
            assert "built_in_nodes" not in preprocessor_properties
            return {
                "namespace": "tasks",
                "can_proceed": True,
                "operation": "create",
                "complexity": "medium",
                "task_area": "instruction",
                "user_unhappy": True,
                "china_model_sensitive": True,
                "requires_main_processor": True,
                "needed_fields": ["title", "description", "status", "assignee_type"],
                "selected_capability_ids": ["fake.workflow.capability"],
                "ambiguity": [],
            }
        if task_id.endswith("-main"):
            assert kwargs["model_id"] == "google/gemini-3.6-flash"
            return {
                "tasks": [
                    {"title": "Draft QA checklist", "description": "", "status": "todo", "assignee_type": "user"},
                    {"title": "Verify rollback commands", "description": "", "status": "todo", "assignee_type": "user"},
                ]
            }
        if task_id.endswith("-description"):
            return {"descriptions": ["Draft checks for release readiness.", "Confirm rollback commands work."]}
        raise AssertionError(task_id)

    selector = FakeModelSelector()
    result = await planner.run_task_ask_pipeline(
        "Plan release validation tasks",
        object(),
        llm_caller=fake_llm,
        model_selector=selector,
    )

    assert [proposal.title for proposal in result.proposal] == ["Draft QA checklist", "Verify rollback commands"]
    assert [proposal.description for proposal in result.proposal] == ["Draft checks for release readiness.", "Confirm rollback commands work."]
    assert result.processing["intent_frame"]["complexity"] == "medium"
    assert result.processing["intent_frame"]["selected_capability_ids"] == []
    assert result.processing["preprocessing_result"]["user_unhappy"] is True
    assert result.processing["model_selection"]["primary_model_id"] == "google/gemini-3.6-flash"
    assert result.processing["intent_frame"]["selected_main_llm_model_id"] == "google/gemini-3.6-flash"
    assert selector.calls[0]["task_area"] == "instruction"
    assert selector.calls[0]["china_related"] is True
    assert selector.calls[0]["user_unhappy"] is True
    assert [call["task_id"] for call in calls] == [
        "workspace-ask-tasks-preprocessor",
        "workspace-ask-tasks-main",
        "workspace-ask-tasks-description",
    ]
    selector_call = calls[1]["dynamic_context"]["intent_frame"]
    assert selector_call["task_area"] == "instruction"
    assert selector_call["china_model_sensitive"] is True


@pytest.mark.asyncio
async def test_workflow_pipeline_filters_unknown_capabilities_before_main_processor() -> None:
    calls: list[dict] = []

    async def fake_llm(**kwargs):
        calls.append(kwargs)
        task_id = kwargs["task_id"]
        if task_id.endswith("-preprocessor"):
            compact_context = kwargs["dynamic_context"]
            assert "tasks.create" in compact_context["available_capability_ids"]
            assert "slack.send_message" not in compact_context["available_capability_ids"]
            return {
                "namespace": "workflows",
                "can_proceed": True,
                "operation": "create",
                "complexity": "complex",
                "task_area": "instruction",
                "china_model_sensitive": False,
                "requires_main_processor": True,
                "selected_capability_ids": ["tasks.create", "slack.send_message"],
                "built_in_nodes": ["manual_trigger", "app_skill_action", "send_notification", "end"],
                "ambiguity": [],
            }
        if task_id.endswith("-main"):
            assert kwargs["model_id"] == "google/gemini-3.6-flash"
            graph_schema = kwargs["tool_definition"]["function"]["parameters"]["properties"]["graph"]
            assert graph_schema["required"] == ["version", "trigger_node_id", "nodes", "edges"]
            detailed_context = kwargs["dynamic_context"]
            assert [item["id"] for item in detailed_context["selected_capabilities"]] == ["tasks.create"]
            assert "slack.send_message" in detailed_context["filtered_unknown_capability_ids"]
            assert detailed_context["built_in_nodes"] == ["manual_trigger", "app_skill_action", "send_notification", "end"]
            return {
                "title": "Manual Release Review",
                "description": "",
                "enabled": False,
                "graph": {
                    "version": 1,
                    "trigger_node_id": "manual-trigger",
                    "nodes": [
                        {"id": "manual-trigger", "type": "manual_trigger", "title": "Manual trigger"},
                        {"id": "notify-user", "type": "send_notification", "title": "Notify user", "config": {"title": "Review", "body": "Review release risk."}},
                        {"id": "end", "type": "end", "title": "End"},
                    ],
                    "edges": [{"from": "manual-trigger", "to": "notify-user"}, {"from": "notify-user", "to": "end"}],
                },
            }
        if task_id.endswith("-description"):
            return {"description": "Prompts the user to review release risk before shipping."}
        raise AssertionError(task_id)

    result = await planner.run_workflow_ask_pipeline(
        "Notify me about risky PRs using Slack",
        object(),
        llm_caller=fake_llm,
        model_selector=FakeModelSelector(),
        capability_registry=FakeCapabilityRegistry(),
    )

    assert result.proposal["title"] == "Manual Release Review"
    assert result.proposal["description"] == "Prompts the user to review release risk before shipping."
    assert result.processing["filtered_unknown_capability_ids"] == ["slack.send_message"]
    assert result.processing["model_selection"]["primary_model_id"] == "google/gemini-3.6-flash"


@pytest.mark.asyncio
async def test_workflow_pipeline_rejects_unselected_built_in_nodes() -> None:
    async def fake_llm(**kwargs):
        task_id = kwargs["task_id"]
        if task_id.endswith("-preprocessor"):
            return {
                "namespace": "workflows",
                "can_proceed": True,
                "operation": "create",
                "complexity": "medium",
                "task_area": "instruction",
                "china_model_sensitive": False,
                "requires_main_processor": True,
                "selected_capability_ids": [],
                "built_in_nodes": ["manual_trigger", "custom_code", "end"],
                "ambiguity": [],
            }
        if task_id.endswith("-main"):
            assert kwargs["dynamic_context"]["built_in_nodes"] == ["manual_trigger", "end"]
            return {
                "title": "Wait before review",
                "description": "",
                "enabled": False,
                "graph": {
                    "version": 1,
                    "trigger_node_id": "manual-trigger",
                    "nodes": [
                        {"id": "manual-trigger", "type": "manual_trigger", "title": "Manual trigger"},
                        {"id": "wait", "type": "wait", "title": "Wait"},
                        {"id": "end", "type": "end", "title": "End"},
                    ],
                    "edges": [{"from": "manual-trigger", "to": "wait"}, {"from": "wait", "to": "end"}],
                },
            }
        raise AssertionError(task_id)

    with pytest.raises(planner.WorkspaceAskPlanningError, match="unselected workflow node type"):
        await planner.run_workflow_ask_pipeline(
            "Create a manual wait workflow",
            object(),
            llm_caller=fake_llm,
            model_selector=FakeModelSelector(),
            capability_registry=FakeCapabilityRegistry(),
        )


@pytest.mark.asyncio
async def test_workflow_pipeline_rejects_unselected_app_skill_nodes() -> None:
    async def fake_llm(**kwargs):
        task_id = kwargs["task_id"]
        if task_id.endswith("-preprocessor"):
            return {
                "namespace": "workflows",
                "can_proceed": True,
                "operation": "create",
                "complexity": "complex",
                "task_area": "instruction",
                "china_model_sensitive": False,
                "requires_main_processor": True,
                "selected_capability_ids": [],
                "ambiguity": [],
            }
        if task_id.endswith("-main"):
            return {
                "title": "Slack release alert",
                "description": "",
                "enabled": False,
                "graph": {
                    "version": 1,
                    "trigger_node_id": "manual-trigger",
                    "nodes": [
                        {"id": "manual-trigger", "type": "manual_trigger", "title": "Manual trigger"},
                        {"id": "slack", "type": "app_skill_action", "title": "Send Slack", "config": {"app_id": "slack", "skill_id": "send_message"}},
                        {"id": "end", "type": "end", "title": "End"},
                    ],
                    "edges": [{"from": "manual-trigger", "to": "slack"}, {"from": "slack", "to": "end"}],
                },
            }
        raise AssertionError(task_id)

    with pytest.raises(planner.WorkspaceAskPlanningError, match="unselected workflow capability"):
        await planner.run_workflow_ask_pipeline(
            "Send a Slack release alert",
            object(),
            llm_caller=fake_llm,
            model_selector=FakeModelSelector(),
            capability_registry=FakeCapabilityRegistry(),
        )


@pytest.mark.asyncio
async def test_workflow_pipeline_repairs_empty_graph_to_manual_notification() -> None:
    async def fake_llm(**kwargs):
        task_id = kwargs["task_id"]
        if task_id.endswith("-preprocessor"):
            return {
                "namespace": "workflows",
                "can_proceed": True,
                "operation": "create",
                "complexity": "medium",
                "task_area": "instruction",
                "china_model_sensitive": False,
                "requires_main_processor": True,
                "selected_capability_ids": [],
                "ambiguity": [],
            }
        if task_id.endswith("-main"):
            return {
                "title": "Manual Release Review",
                "description": "Review release evidence before shipping.",
                "enabled": False,
                "graph": {},
            }
        raise AssertionError(task_id)

    result = await planner.run_workflow_ask_pipeline(
        "Create a manual release review workflow",
        object(),
        llm_caller=fake_llm,
        model_selector=FakeModelSelector(),
        capability_registry=FakeCapabilityRegistry(),
    )

    graph = result.proposal["graph"]
    assert result.proposal["title"] == "Manual Release Review"
    assert graph["trigger_node_id"] == "manual-trigger"
    assert [node["type"] for node in graph["nodes"]] == ["manual_trigger", "send_notification", "end"]


@pytest.mark.asyncio
async def test_ambiguous_destructive_request_fails_before_main_processor() -> None:
    calls: list[str] = []

    async def fake_llm(**kwargs):
        calls.append(kwargs["task_id"])
        return {
            "namespace": "tasks",
            "operation": "delete",
            "complexity": "medium",
            "requires_main_processor": False,
            "ambiguity": [{"field": "target", "severity": "blocking", "reason": "No task target specified"}],
        }

    with pytest.raises(planner.WorkspaceAskPlanningError, match="clarification"):
        await planner.run_task_ask_pipeline(
            "Clean up old tasks",
            object(),
            llm_caller=fake_llm,
            model_selector=FakeModelSelector(),
        )

    assert calls == ["workspace-ask-tasks-preprocessor"]
