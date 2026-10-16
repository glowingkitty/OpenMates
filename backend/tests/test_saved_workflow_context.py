"""Discovery shortlists only saved authorized IDs and never invokes a graph."""
from types import SimpleNamespace

from backend.apps.workflows.skills.saved_workflow_context import saved_workflow_metadata, load_selected_saved_workflows
from backend.core.api.app.services.workflow_models import WorkflowLifecycle, WorkflowStatus
from backend.core.api.app.services.workflow_service import WorkflowService


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


# contract-test: supporting surface=rest_api assertions=workflows.chat.metadata-warmup
def test_discovery_fetches_only_bounded_metadata_blobs_in_existing_order():
    class Cipher:
        requires_vault_key_id = False
        def decrypt_json(self, blob, key):
            return blob["plain"]
    class Repository:
        def __init__(self):
            self.requested = []
        def list_workflows(self, user, team_id=None):
            assert user == "alice" and team_id is None
            return [{"id": str(index), "encrypted_title_ref": f"title-{index}",
                     "encrypted_description_ref": f"description-{index}",
                     "enabled": index == 24, "next_run_at": 1 if index == 24 else None,
                     "status": "active" if index == 24 else "disabled", "lifecycle": "persisted",
                     "updated_at": index, "current_version_id": f"version-{index}"}
                    for index in range(25)]
        def project_workflow_next_runs(self, records):
            return records
        def get_encrypted_blobs(self, refs):
            self.requested = refs
            return {ref: {"plain": ref} for ref in refs}
    repository = Repository()
    service = WorkflowService(repository=repository, payload_cipher=Cipher())
    rows = service.list_discovery_metadata("alice")
    assert len(rows) == 20
    assert rows[0]["workflow_id"] == "24"  # enabled scheduled workflow keeps priority
    assert len(repository.requested) == 40  # two metadata refs per candidate
    assert "title-0" not in repository.requested
    assert all("graph" not in row for row in rows)
    original_get = repository.get_encrypted_blobs
    def one_missing_blob(refs):
        result = original_get(refs)
        result.pop("title-24")
        return result
    repository.get_encrypted_blobs = one_missing_blob
    remaining = service.list_discovery_metadata("alice")
    assert len(remaining) == 19
    assert remaining[0]["workflow_id"] == "23"
