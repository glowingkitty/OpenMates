"""Selected-folder canonical writes preserve file/workflow conflict guards."""
import hashlib

import pytest
import yaml

from backend.core.api.app.services.workflow_remote_file_service import WorkflowRemoteFileBinding, WorkflowRemoteFileService
from backend.tests.test_workflow_file_import import portable_file, service_pair


def setup():
    files, runtime = service_pair()
    document, graph = files.validate_document(portable_file())
    workflow = files.import_document("alice", document, graph)
    return workflow, runtime


# contract-test: supporting surface=rest_api assertions=workflows.portability.remote-project-save,workflows.portability.private-content-boundary
@pytest.mark.asyncio
async def test_canonical_remote_create_and_later_update_use_exact_bound_path_and_base():
    workflow, runtime = setup()
    calls = []
    async def execute(operation, arguments, context):
        assert context["_proposed_binding"].file_path == arguments["path"]
        assert context["_proposed_binding"].workflow_version_id == workflow.current_version_id
        if operation == "create_file":
            assert context["_proposed_binding"].base_hash == hashlib.sha256(arguments["content"].encode()).hexdigest()
        calls.append((operation, arguments))
        return {"status": "completed"}
    service = WorkflowRemoteFileService(runtime, execute)
    context = {"project_id": "project", "source_id": "source", "chat_id": "chat"}
    first = await service.persist(user_id="alice", workflow_id=workflow.id,
        expected_workflow_version_id=workflow.current_version_id,
        binding=WorkflowRemoteFileBinding("project", "source", "automation"), source_write_context=context)
    assert first["status"] == "saved"
    operation, arguments = calls[0]
    assert operation == "create_file" and arguments["expected_base"] is None
    assert arguments["path"] == "automation/daily_forecast.workflow.yml"
    content = arguments["content"]
    parsed = yaml.safe_load(content)
    assert parsed["format"] == "openmates-workflow"
    assert parsed["workflow"]["graph"]["nodes"][0]["id"] == "step_1"
    assert workflow.id not in content and workflow.current_version_id not in content
    assert first["binding"].base_hash == hashlib.sha256(content.encode()).hexdigest()
    second = await service.persist(user_id="alice", workflow_id=workflow.id,
        expected_workflow_version_id=workflow.current_version_id,
        binding=first["binding"], source_write_context=context)
    assert second["status"] == "saved"
    assert calls[1][0] == "update_file" and calls[1][1]["expected_base"] == first["binding"].base_hash
    assert calls[1][1]["path"] == arguments["path"]


# contract-test: supporting surface=rest_api assertions=workflows.portability.remote-project-save
@pytest.mark.asyncio
@pytest.mark.parametrize("receipt,status", [({"status": "waiting_for_executor"}, "pending"), ({"status": "conflict"}, "conflict"), ({"status": "failed"}, "failed")])
async def test_proposals_pending_denials_and_conflicts_never_claim_file_saved(receipt, status):
    workflow, runtime = setup()
    async def execute(*args): return receipt
    binding = WorkflowRemoteFileBinding("project", "source", "automation")
    result = await WorkflowRemoteFileService(runtime, execute).persist(user_id="alice", workflow_id=workflow.id,
        expected_workflow_version_id=workflow.current_version_id, binding=binding,
        source_write_context={"project_id": "project", "source_id": "source", "chat_id": "chat"})
    assert result["status"] == status and result["binding"] == binding
    assert runtime.get_workflow(workflow.id, "alice").id == workflow.id


# contract-test: supporting surface=rest_api assertions=workflows.portability.remote-project-save
@pytest.mark.asyncio
async def test_stale_definition_and_escaped_folder_do_not_write():
    workflow, runtime = setup()
    async def execute(*args): raise AssertionError("must not write")
    service = WorkflowRemoteFileService(runtime, execute)
    context = {"project_id": "project", "source_id": "source", "chat_id": "chat"}
    result = await service.persist(user_id="alice", workflow_id=workflow.id, expected_workflow_version_id="stale",
        binding=WorkflowRemoteFileBinding("project", "source", "automation"), source_write_context=context)
    assert result["status"] == "conflict"
    with pytest.raises(ValueError, match="invalid_workflow_folder"):
        await service.persist(user_id="alice", workflow_id=workflow.id, expected_workflow_version_id=workflow.current_version_id,
            binding=WorkflowRemoteFileBinding("project", "source", "../outside"), source_write_context=context)
