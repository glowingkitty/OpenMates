"""draft_only workflow authoring: validate and return a draft, persist no Workflow.

Plan: docs/plans/chat-recommendations/plan.yml (D-8, workflow panel).
Run: python3 scripts/heavy_slot.py run -- python3 -m pytest backend/tests/test_workflow_input_draft_only.py -v
"""

from __future__ import annotations

from backend.tests.runtime_import_stubs import install_code_route_import_stubs

install_code_route_import_stubs()

import pytest  # noqa: E402

from backend.core.api.app.routes.workflows import WorkflowInputStartRequest  # noqa: E402
from backend.core.api.app.services.workflow_input_service import WorkflowInputService  # noqa: E402
from backend.tests.test_workflow_input_sessions import QueuePlanner  # noqa: E402
from backend.tests.test_workflows_models import rain_graph  # noqa: E402
from backend.tests.workflow_test_utils import workflow_service  # noqa: E402


# contract-test: supporting surface=rest_api assertions=app-memories.suggestions.post-processor,workflows-ui.authoring.composer-and-preview
def test_request_field_defaults_false_and_is_accepted() -> None:
    assert WorkflowInputStartRequest(text="Create a workflow").draft_only is False
    assert WorkflowInputStartRequest(text="Create a workflow", draft_only=True).draft_only is True


# contract-test: supporting surface=rest_api assertions=app-memories.suggestions.post-processor,workflows-ui.authoring.composer-and-preview
def test_draft_only_create_returns_draft_and_persists_nothing() -> None:
    service = workflow_service()
    events: list[dict] = []
    input_service = WorkflowInputService(
        workflow_service=service,
        planner=QueuePlanner([{"action": "create_workflow", "title": "Weekly CFP alert", "description": "Alert", "graph": rain_graph()}]),
    )
    result = input_service.start(user_id="alice", text="Create a CFP alert", draft_only=True, on_event=events.append)
    assert result.status == "draft"
    assert result.preview_workflow is not None and result.preview_workflow.title == "Weekly CFP alert"
    assert result.preview_workflow.graph is not None
    assert result.workflow is None
    assert service.list_workflows("alice") == []
    assert {"type": "progress", "phase": "validating"} in events
    assert not any(event.get("phase") == "saving" for event in events)


# contract-test: supporting surface=rest_api assertions=app-memories.suggestions.post-processor,workflows-ui.authoring.composer-and-preview
def test_draft_only_update_returns_new_graph_without_saving() -> None:
    service = workflow_service()
    original = service.create_workflow("alice", "Rain", rain_graph(), enabled=False)
    input_service = WorkflowInputService(
        workflow_service=service,
        planner=QueuePlanner([{"action": "update_workflow", "workflow_id": original.id, "title": "Rain renamed", "graph": rain_graph()}]),
    )
    result = input_service.start(user_id="alice", text="Rename it", selected_workflow_id=original.id, draft_only=True)
    assert result.status == "draft"
    assert result.preview_workflow is not None and result.preview_workflow.id == original.id
    assert result.preview_workflow.title == "Rain renamed"
    stored = service.get_workflow(original.id, "alice")
    assert stored.title == "Rain" and stored.version == original.version


# contract-test: supporting surface=rest_api assertions=app-memories.suggestions.post-processor,workflows-ui.authoring.composer-and-preview
def test_default_false_still_saves() -> None:
    service = workflow_service()
    input_service = WorkflowInputService(
        workflow_service=service,
        planner=QueuePlanner([{"action": "create_workflow", "title": "Saved rain", "graph": rain_graph()}]),
    )
    result = input_service.start(user_id="alice", text="Create a rain workflow")
    assert result.status == "executed"
    assert [item.title for item in service.list_workflows("alice")] == ["Saved rain"]


# contract-test: supporting surface=rest_api assertions=app-memories.suggestions.post-processor,workflows-ui.authoring.composer-and-preview
def test_draft_only_partial_plan_is_not_saved() -> None:
    service = workflow_service()
    input_service = WorkflowInputService(
        workflow_service=service,
        planner=QueuePlanner([{"action": "partial", "reason": "provider_error", "notice": "Stopped early.", "operations": []}]),
    )
    result = input_service.start(user_id="alice", text="Create something", draft_only=True)
    assert result.status != "executed"
    assert service.list_workflows("alice") == []


@pytest.mark.parametrize("draft_only", [True, False])
# contract-test: supporting surface=rest_api assertions=app-memories.suggestions.post-processor,workflows-ui.authoring.composer-and-preview
def test_clarification_unchanged_by_draft_only(draft_only: bool) -> None:
    service = workflow_service()
    input_service = WorkflowInputService(
        workflow_service=service,
        planner=QueuePlanner([{"action": "needs_clarification", "message": "Which city?"}]),
    )
    result = input_service.start(user_id="alice", text="Weather alert", draft_only=draft_only)
    assert result.status == "needs_clarification"
