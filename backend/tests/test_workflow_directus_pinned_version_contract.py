# backend/tests/test_workflow_directus_pinned_version_contract.py
#
# Directus persistence contract for the immutable workflow version rows used by
# runtime acceptance transactions. The current workflow pointer is published
# only after the matching version row exists.
#
# Spec: docs/specs/workflows-v1/spec.yml

from __future__ import annotations

from backend.core.api.app.services.workflow_service import DirectusWorkflowRepository
from backend.tests.test_workflows_models import FakeDirectusClient, rain_graph
from backend.tests.workflow_test_utils import workflow_service


def test_directus_workflow_persists_the_version_pinned_by_runtime_acceptance() -> None:
    repository = DirectusWorkflowRepository(base_url="http://directus.test", token="test-token")
    client = FakeDirectusClient()
    repository._client = client
    service = workflow_service(repository=repository)

    workflow = service.create_workflow("alice", "Daily rain alert", rain_graph())

    versions = client.collections["workflow_versions"]
    assert len(versions) == 1
    version = next(iter(versions.values()))
    assert version["version_id"] == workflow.current_version_id
    assert version["workflow_id"] == workflow.id
    assert version["hashed_user_id"] == repository.workflow_owner_hash("alice")
    assert set(version["graph_json"]) == {"encrypted_graph_ref"}
    assert version["encrypted_graph_secrets"] == version["graph_json"]["encrypted_graph_ref"]
    assert "Berlin" not in str(version)

    stored_trigger = next(iter(client.collections["workflow_triggers"].values()))
    public_trigger = repository.get_trigger_for_workflow(workflow.id, "alice")
    assert stored_trigger["owner_user_id"] == "alice"
    assert public_trigger is not None
    assert "owner_user_id" not in public_trigger
