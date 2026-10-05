"""Discovery shortlists only saved authorized IDs and never invokes a graph."""
from types import SimpleNamespace

from backend.apps.workflows.skills.saved_workflow_context import saved_workflow_metadata, load_selected_saved_workflows
from backend.core.api.app.services.workflow_models import WorkflowLifecycle, WorkflowStatus


def summary(identity, lifecycle=WorkflowLifecycle.PERSISTED):
    return SimpleNamespace(id=identity, title=identity, description="Useful", enabled=False,
        status=WorkflowStatus.DISABLED, lifecycle=lifecycle, current_version_id="v1",
        graph=SimpleNamespace(model_dump=lambda **kw: {"nodes": [{"config": {"api_key": "private", "location": "Berlin"}}]}), binding_requirements=[])


# contract-test: supporting surface=rest_api assertions=workflows.chat.relevance-discovery
def test_shortlisting_uses_metadata_and_loading_rechecks_owner_scope_and_version():
    class Service:
        def list_workflows(self, user, key, **kw):
            assert user == "alice" and kw == {"team_id": None}
            return [summary("saved"), summary("temporary", WorkflowLifecycle.TEMPORARY), summary("unrelated")]
        def get_workflow(self, identity, user, key, **kw):
            assert identity == "saved" and user == "alice"
            return summary(identity)
    service = Service()
    candidates = saved_workflow_metadata(service, "alice", authorized_workflow_ids=["saved", "temporary"])
    assert [item["workflow_id"] for item in candidates] == ["saved"]
    assert "graph" not in candidates[0]
    result = load_selected_saved_workflows(service, "alice", ["invented", "saved", "saved"], candidates)
    assert len(result) == 1
    assert result[0]["graph"]["nodes"][0]["config"] == {"location": "Berlin"}
    assert result[0]["invocation_tool"] == "workflows.run"
    candidates[0]["current_version_id"] = "stale"
    assert load_selected_saved_workflows(service, "alice", ["saved"], candidates) == []
