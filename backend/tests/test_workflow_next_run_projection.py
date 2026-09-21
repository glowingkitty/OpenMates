"""The UI's next-run time follows scheduler state, not stale workflow JSON."""
from backend.core.api.app.services.workflow_service import InMemoryWorkflowRepository, DirectusWorkflowRepository
from backend.core.api.app.services.workflow_trigger_projection import project_workflow_next_runs
from backend.tests.workflow_test_utils import workflow_service


def scheduled_graph():
    return {"version": 1, "trigger_node_id": "trigger", "nodes": [
        {"id": "trigger", "type": "schedule_trigger", "config": {"schedule": {"type": "daily", "time": "09:00", "timezone": "Europe/Berlin"}}},
        {"id": "send", "type": "start_new_chat", "config": {"title": "Daily", "message": "Daily"}},
    ], "edges": [{"from": "trigger", "to": "send"}]}


# contract-test: supporting surface=rest_api assertions=workflows.execution.lifecycle-visible,workflows.surface.semantic-parity
def test_detail_and_list_project_advanced_trigger_without_mutating_workflow_json():
    repository = InMemoryWorkflowRepository()
    service = workflow_service(repository=repository)
    workflow = service.create_workflow("alice", "Daily", scheduled_graph(), enabled=True)
    previous = repository.get_workflow(workflow.id, "alice")["next_run_at"]
    trigger = repository.get_trigger_for_workflow(workflow.id, "alice")
    advanced = previous + 86400
    repository.update_trigger_next_run(trigger["trigger_id"], advanced, updated_at=advanced - 100)
    assert service.get_workflow(workflow.id, "alice").next_run_at == advanced
    assert service.list_workflows("alice")[0].next_run_at == advanced
    assert repository.get_workflow(workflow.id, "alice")["next_run_at"] == previous
    repository.update_trigger_next_run(trigger["trigger_id"], 0, updated_at=advanced)
    assert service.get_workflow(workflow.id, "alice").next_run_at is None
    repository.triggers.clear()
    assert service.list_workflows("alice")[0].next_run_at is None


# contract-test: supporting surface=rest_api assertions=workflows.execution.lifecycle-visible,workflows.surface.semantic-parity
def test_projection_rejects_other_owner_and_disabled_schedule():
    record = {"id": "workflow", "owner_hash": "alice-hash", "enabled": True, "next_run_at": 1}
    trigger = {"workflow_id": "workflow", "hashed_user_id": "bob-hash", "enabled": True, "next_run_at": 2000}
    assert project_workflow_next_runs([record], [trigger])[0]["next_run_at"] is None
    trigger["hashed_user_id"] = "alice-hash"
    trigger["enabled"] = False
    assert project_workflow_next_runs([record], [trigger])[0]["next_run_at"] is None


# contract-test: supporting surface=rest_api assertions=workflows.execution.lifecycle-visible,workflows.surface.semantic-parity
def test_directus_projection_batches_authorized_workflow_ids(monkeypatch):
    repository = object.__new__(DirectusWorkflowRepository)
    calls = []
    def get_items(collection, filters, **kwargs):
        calls.append((collection, filters, kwargs))
        return [{"workflow_id": "workflow", "hashed_user_id": "alice-hash", "enabled": True, "next_run_at": 2000}]
    monkeypatch.setattr(repository, "_get_items", get_items)
    result = repository.project_workflow_next_runs([{"id": "workflow", "owner_hash": "alice-hash", "enabled": True}])
    assert result[0]["next_run_at"] == 2000
    assert calls == [("workflow_triggers", {"_and": [{"workflow_id": {"_in": ["workflow"]}}, {"hashed_user_id": {"_in": ["alice-hash"]}}]}, {"limit": -1})]
