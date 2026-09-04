# backend/tests/test_workflow_ui_identity.py
#
# Contract tests for encrypted Workflow category/icon identity metadata.
# These tests cover deterministic graph-first assignment, bounded classifier
# input, legacy fallbacks, and preprocessing-log redaction before UI work.
# Spec: docs/specs/workflows-ui-contract/spec.yml

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from backend.core.api.app.services.workflow_models import WorkflowGraph, WorkflowSummary
from backend.core.api.app.services.workflow_service import InMemoryWorkflowRepository
from backend.tests.workflow_test_utils import workflow_service


def _manual_graph() -> dict[str, Any]:
    return {
        "version": 1,
        "trigger_node_id": "manual",
        "nodes": [{"id": "manual", "type": "manual_trigger", "config": {}}],
        "edges": [],
    }


def _weather_graph() -> dict[str, Any]:
    return {
        "version": 1,
        "trigger_node_id": "manual",
        "nodes": [
            {"id": "manual", "type": "manual_trigger", "config": {}},
            {
                "id": "weather",
                "type": "app_skill_action",
                "config": {
                    "app_id": "weather",
                    "skill_id": "forecast",
                    "input": {"location": "Private home address", "days": 1},
                    "credential": "must-not-leave-workflow-boundary",
                },
            },
        ],
        "edges": [{"from": "manual", "to": "weather"}],
    }


# contract-test: direct surface=rest_api assertions=workflows-ui.identity.automatic-category-icon
def test_workflow_models_expose_category_and_icon() -> None:
    assert "category" in WorkflowSummary.model_fields
    assert "icon" in WorkflowSummary.model_fields


# contract-test: direct surface=rest_api assertions=workflows-ui.identity.automatic-category-icon,workflows-ui.workspace.title-first-draft
def test_workflow_identity_round_trips_only_through_encrypted_refs() -> None:
    repository = InMemoryWorkflowRepository()
    service = workflow_service(repository=repository)

    workflow = service.create_workflow(
        "alice",
        "Review source changes",
        _manual_graph(),
        category="software_development",
        icon="code",
    )
    record = repository.workflows[workflow.id]

    assert workflow.category == "software_development"
    assert workflow.icon == "code"
    assert record["encrypted_category_ref"]
    assert record["encrypted_icon_ref"]
    assert "category" not in record
    assert "icon" not in record
    assert "software_development" not in repr(record)


# contract-test: direct surface=rest_api assertions=workflows-ui.identity.automatic-category-icon
def test_legacy_workflow_without_identity_hydrates_stable_fallbacks() -> None:
    repository = InMemoryWorkflowRepository()
    service = workflow_service(repository=repository)
    created = service.create_workflow("alice", "Legacy workflow", _manual_graph())

    record = repository.workflows[created.id]
    record.pop("encrypted_category_ref", None)
    record.pop("encrypted_icon_ref", None)

    hydrated = service.get_workflow(created.id, "alice")

    assert hydrated.category == "general_knowledge"
    assert hydrated.icon == "help-circle"


# contract-test: direct surface=rest_api assertions=workflows-ui.identity.automatic-category-icon
def test_direct_service_creation_uses_deterministic_app_identity() -> None:
    service = workflow_service()

    workflow = service.create_workflow("alice", "Daily weather check", _weather_graph())

    assert workflow.category == "science"
    assert workflow.icon == "cloud-rain"


# contract-test: direct surface=rest_api assertions=workflows-ui.identity.automatic-category-icon
@pytest.mark.asyncio
async def test_graph_first_identity_skips_classifier_for_known_app_skill() -> None:
    from backend.core.api.app.services.workflow_identity_service import WorkflowIdentityService

    classifier_calls: list[dict[str, Any]] = []

    async def classifier(payload: dict[str, Any]) -> dict[str, str]:
        classifier_calls.append(payload)
        return {"category": "general_knowledge", "icon": "help-circle"}

    identity = await WorkflowIdentityService(classifier=classifier).resolve(
        title="Daily weather check",
        description=None,
        graph=WorkflowGraph.model_validate(_weather_graph()),
    )

    assert identity.category == "science"
    assert identity.icon == "cloud-rain"
    assert classifier_calls == []


# contract-test: direct surface=rest_api assertions=workflows-ui.identity.automatic-category-icon
@pytest.mark.asyncio
async def test_ambiguous_identity_classifier_receives_no_node_inputs_or_credentials() -> None:
    from backend.core.api.app.services.workflow_identity_service import WorkflowIdentityService

    classifier_payloads: list[dict[str, Any]] = []

    async def classifier(payload: dict[str, Any]) -> dict[str, str]:
        classifier_payloads.append(payload)
        return {"category": "not_a_category", "icon": "not-an-icon"}

    identity = await WorkflowIdentityService(classifier=classifier).resolve(
        title="Private weekly routine",
        description="A short private description",
        graph=WorkflowGraph.model_validate(_manual_graph()),
    )

    assert classifier_payloads == [
        {
            "title": "Private weekly routine",
            "description": "A short private description",
            "node_types": ["manual_trigger"],
            "app_skills": [],
        }
    ]
    assert identity.category == "general_knowledge"
    assert identity.icon == "help-circle"


# contract-test: supporting surface=rest_api assertions=workflows-ui.identity.automatic-category-icon
def test_preprocessing_development_log_redacts_workflow_identity_fields() -> None:
    source = (
        Path(__file__).resolve().parents[2]
        / "backend/apps/ai/utils/llm_utils.py"
    ).read_text(encoding="utf-8")

    assert '"category" in sanitized_args' in source
    assert '"icon" in sanitized_args' in source or '"icon_names" in sanitized_args' in source
