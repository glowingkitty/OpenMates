# backend/tests/test_workflow_core_ui_contract.py
#
# Contract tests for core workflow editor and list behavior.
#
# These cases use the in-memory workflow repository and test payload cipher.
#
# Spec: docs/specs/workflows-v1/spec.yml

from backend.core.api.app.services.workflow_models import WorkflowStatus
from backend.core.api.app.services.workflow_service import InMemoryWorkflowRepository
from backend.tests.workflow_test_utils import workflow_service


def manual_title_draft_graph() -> dict:
    return {
        "version": 1,
        "trigger_node_id": "manual",
        "nodes": [{"id": "manual", "type": "manual_trigger", "config": {}}],
        "edges": [],
    }


def scheduled_title_draft_graph() -> dict:
    return {
        "version": 1,
        "trigger_node_id": "schedule",
        "nodes": [
            {
                "id": "schedule",
                "type": "schedule_trigger",
                "config": {"schedule": {"type": "daily", "time": "09:00", "timezone": "UTC"}},
            }
        ],
        "edges": [],
    }


def test_title_only_manual_draft_is_persisted_disabled_with_exact_title() -> None:
    repository = InMemoryWorkflowRepository()
    service = workflow_service(repository=repository)

    workflow = service.create_workflow("alice", "Plan weekly review", manual_title_draft_graph())
    record = repository.workflows[workflow.id]

    assert workflow.title == "Plan weekly review"
    assert workflow.enabled is False
    assert workflow.status == WorkflowStatus.DISABLED
    assert record["enabled"] is False
    assert record["status"] == WorkflowStatus.DISABLED.value
    assert [node.type.value for node in workflow.graph.nodes] == ["manual_trigger"]
    assert workflow.graph.edges == []


def test_workflow_description_round_trips_without_plaintext_record_storage() -> None:
    repository = InMemoryWorkflowRepository()
    service = workflow_service(repository=repository)

    workflow = service.create_workflow(
        "alice",
        "Plan weekly review",
        manual_title_draft_graph(),
        description="Review priorities every Friday.",
    )
    updated = service.update_workflow(
        workflow.id,
        "alice",
        description="Review priorities and decisions every Friday.",
    )
    record = repository.workflows[workflow.id]

    assert updated.description == "Review priorities and decisions every Friday."
    assert "encrypted_description_ref" in record
    assert "description" not in record


def test_workflow_list_prioritizes_next_scheduled_runs_then_recent_remaining_entries() -> None:
    repository = InMemoryWorkflowRepository()
    service = workflow_service(repository=repository)
    scheduled_later = service.create_workflow("alice", "Scheduled later", scheduled_title_draft_graph(), enabled=True)
    scheduled_earlier = service.create_workflow("alice", "Scheduled earlier", scheduled_title_draft_graph(), enabled=True)
    disabled = service.create_workflow("alice", "Disabled", scheduled_title_draft_graph())
    draft = service.create_workflow("alice", "Draft", manual_title_draft_graph())
    manual = service.create_workflow("alice", "Manual", manual_title_draft_graph(), enabled=True)

    repository.workflows[scheduled_later.id].update({"next_run_at": 300, "updated_at": 10})
    repository.workflows[scheduled_earlier.id].update({"next_run_at": 100, "updated_at": 20})
    repository.workflows[disabled.id]["updated_at"] = 400
    repository.workflows[draft.id].update({"status": WorkflowStatus.DRAFT.value, "updated_at": 300})
    repository.workflows[manual.id]["updated_at"] = 200

    workflows = service.list_workflows("alice")

    assert [workflow.id for workflow in workflows] == [
        scheduled_earlier.id,
        scheduled_later.id,
        disabled.id,
        draft.id,
        manual.id,
    ]
