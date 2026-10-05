"""Portable Workflow file import and binding security contracts."""

from __future__ import annotations

import ast
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.core.api.app.routes.auth_routes.auth_dependencies import _enforce_api_key_route_policy
from backend.core.api.app.services.workflow_file_service import (
    WorkflowFileDocument, WorkflowFileImportError, WorkflowFileService, WorkflowFileTooLargeError,
)
from backend.core.api.app.services.workflow_service import (
    InMemoryWorkflowRepository,
    WorkflowBindingRequirementsUnresolvedError,
    WorkflowBindingRequirementUnresolvedError,
)
from backend.core.api.app.services.workflow_models import WorkflowNodeType, validate_workflow_composition_refs, validate_workflow_readiness
from backend.tests.workflow_test_utils import workflow_service


WORKFLOWS_PATH = Path(__file__).resolve().parents[2] / "backend/core/api/app/routes/workflows.py"


def _route(name: str, namespace: dict):
    function = next(item for item in ast.parse(WORKFLOWS_PATH.read_text()).body
                    if isinstance(item, ast.AsyncFunctionDef) and item.name == name)
    function.decorator_list = []
    function.args.defaults = []
    function.args.kw_defaults = [None for _ in function.args.kw_defaults]
    for arg in function.args.args:
        arg.annotation = None
    function.returns = None
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])), str(WORKFLOWS_PATH), "exec"), namespace)
    return namespace[name]


def _validation_helper(name: str, namespace: dict):
    """Compile the actual route validation helper, preserving its defaults/body."""
    function = next(item for item in ast.parse(WORKFLOWS_PATH.read_text()).body
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == name)
    function.decorator_list = []
    for arg in [*function.args.args, *function.args.kwonlyargs]:
        arg.annotation = None
    function.returns = None
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])), str(WORKFLOWS_PATH), "exec"), namespace)
    return namespace[name]


def portable_file() -> dict:
    return {
        "format": "openmates-workflow",
        "format_version": 1,
        "workflow": {
            "title": "Daily forecast",
            "description": "A portable definition",
            "run_content_retention": "none",
            "graph": {
                "version": 2,
                "trigger_node_id": "step_1",
                "nodes": [
                    {"id": "step_1", "type": "schedule_trigger", "config": {"schedule": {"type": "daily", "time": "07:00", "timezone": "UTC"}}, "ui": {"x": 1}},
                    {"id": "step_2", "type": "app_skill_action", "config": {"app_id": "weather", "skill_id": "forecast", "input": {"location": "Berlin"}}, "input_mapping": {"trigger": "$nodes.step_1.output.triggered"}},
                    {"id": "step_3", "type": "send_chat_message", "config": {"message": "{{steps.step_2.temperature}}", "destination_required": True, "blocks": [{"id": "block_1", "source": "$nodes.step_2.output.forecast"}]}, "ui": {"note": "{{steps.step_2.temperature}}"}},
                ],
                "edges": [{"from": "step_1", "to": "step_2"}, {"from": "step_2", "to": "step_3"}],
                "variables": {"location": "Berlin", "step_2": "An authored variable name", "token_count": 10,
                              "credential_help": "Ask the user to connect", "output_summary": "Weather"},
                "limits": {"max_runs": 10},
                "ui_layout": {"step_1": {"x": 1, "step_2": {"x": 9}}, "step_2": {"x": 2}, "step_3": {"x": 3}},
            },
        },
        "binding_requirements": [
            {"type": "schedule", "node_id": "step_1"},
            {"type": "app_skill", "node_id": "step_2", "app_id": "weather", "skill_id": "forecast"},
            {"type": "chat_destination", "node_id": "step_3"},
        ],
    }


def service_pair():
    runtime = workflow_service(repository=InMemoryWorkflowRepository())
    return WorkflowFileService(runtime), runtime


# contract-test: direct surface=rest_api assertions=workflows.portability.definition-roundtrip,workflows.portability.disabled-validated-import feature=feature.workflows@7
def test_file_import_preserves_authoring_graph_and_remaps_all_references() -> None:
    file_service, runtime = service_pair()
    document, graph = file_service.validate_document(portable_file())
    imported = file_service.import_document("bob", document, graph)
    source = portable_file()["workflow"]["graph"]
    ids = [node.id for node in imported.graph.nodes]
    assert set(ids).isdisjoint({"step_1", "step_2", "step_3"})
    assert imported.graph.trigger_node_id == ids[0]
    assert [(edge.from_node, edge.to_node) for edge in imported.graph.edges] == [(ids[0], ids[1]), (ids[1], ids[2])]
    assert imported.graph.nodes[1].input_mapping["trigger"] == f"$nodes.{ids[0]}.output.triggered"
    assert imported.graph.nodes[2].config["message"] == "{{steps." + ids[1] + ".temperature}}"
    assert imported.graph.nodes[2].config["blocks"][0]["source"] == f"$nodes.{ids[1]}.output.forecast"
    assert imported.graph.nodes[2].ui["note"] == "{{steps." + ids[1] + ".temperature}}"
    assert set(imported.graph.ui_layout) == set(ids)
    assert imported.graph.ui_layout[ids[0]] == {"x": 1, "step_2": {"x": 9}}
    assert imported.graph.ui_layout[ids[1]] == {"x": 2}
    assert imported.graph.ui_layout[ids[2]] == {"x": 3}
    assert imported.graph.variables == source["variables"]
    assert imported.graph.limits == source["limits"]
    assert imported.run_content_retention.value == "none"
    assert imported.enabled is False and imported.status.value == "disabled" and imported.source == "import"
    assert len(imported.binding_requirements) == 3 and imported.completed_binding_requirements == []
    assert runtime.repository.workflows[imported.id]["binding_requirements"] == imported.binding_requirements
    assert runtime.list_runs(imported.id, "bob") == []
    assert runtime.list_workflows("alice") == []
    assert "Daily forecast" not in str(runtime.repository.workflows[imported.id])


@pytest.mark.parametrize("mutate", [
    lambda data: data.update(format_version=2),
    lambda data: data["workflow"].update(source_chat_id="sender-chat"),
    lambda data: data["workflow"].update(title="   "),
    lambda data: data["workflow"]["graph"]["nodes"][1]["config"].update(access_token="private"),
    lambda data: data["workflow"]["graph"]["nodes"][2]["config"].update(chat_id="sender-chat"),
    lambda data: data["workflow"]["graph"].update(owner_id="sender"),
    lambda data: data["binding_requirements"].append({"type": "app_skill", "node_id": "made-up", "app_id": "weather", "skill_id": "forecast"}),
    lambda data: data["binding_requirements"][1].update(skill_id="other"),
    lambda data: data["workflow"]["graph"]["nodes"][2]["config"].update(message="{{steps.missing.value}}"),
    lambda data: data["workflow"]["graph"]["edges"].append({"from": "step_2", "to": "missing"}),
])
# contract-test: direct surface=rest_api assertions=workflows.portability.private-content-boundary,workflows.portability.disabled-validated-import feature=feature.workflows@7
def test_invalid_file_is_rejected_before_any_persistence(mutate) -> None:
    file_service, runtime = service_pair()
    data = portable_file()
    mutate(data)
    with pytest.raises((WorkflowFileImportError, ValueError)):
        file_service.validate_document(data)
    assert runtime.repository.workflows == {}
    assert runtime.repository.encrypted_blobs == {}


# contract-test: direct surface=rest_api assertions=workflows.portability.private-content-boundary feature=feature.workflows@7
@pytest.mark.parametrize("field", ["weather_api_key", "customAccessToken", "provider_secret", "admin_password", "client_secret"])
def test_scoped_credential_field_names_are_rejected_without_overblocking_ordinary_keys(field: str) -> None:
    file_service, runtime = service_pair()
    data = portable_file()
    data["workflow"]["graph"]["nodes"][1]["config"]["input"][field] = "private"
    with pytest.raises(WorkflowFileImportError, match="private or runtime field"):
        file_service.validate_document(data)
    assert runtime.repository.workflows == {}


# contract-test: direct surface=rest_api assertions=workflows.portability.private-content-boundary feature=feature.workflows@7
@pytest.mark.parametrize("field", ["cookie", "vault", "encrypted_graph_ref", "last_run_at", "encrypted_payload"])
def test_exact_runtime_and_private_fields_match_shared_file_validator(field: str) -> None:
    file_service, runtime = service_pair()
    data = portable_file()
    data["workflow"]["graph"]["nodes"][1]["config"]["input"][field] = "private"
    with pytest.raises(WorkflowFileImportError, match="private or runtime field"):
        file_service.validate_document(data)
    assert runtime.repository.workflows == {}


# contract-test: direct surface=rest_api assertions=workflows.portability.disabled-validated-import feature=feature.workflows@7
@pytest.mark.parametrize("variant,error", [
    ("bytes", WorkflowFileTooLargeError),
    ("items", WorkflowFileTooLargeError),
    ("depth", WorkflowFileImportError),
])
def test_untrusted_document_complexity_is_bounded_before_recursive_validation(variant: str, error: type[Exception]) -> None:
    file_service, runtime = service_pair()
    data = portable_file()
    if variant == "bytes":
        data["workflow"]["graph"]["variables"]["large"] = "x" * 1_048_577
    elif variant == "items":
        data["workflow"]["graph"]["variables"]["large"] = list(range(50_001))
    else:
        nested = {}
        root = nested
        for _ in range(65):
            child = {}
            nested["child"] = child
            nested = child
        data["workflow"]["graph"]["variables"]["nested"] = root
    with pytest.raises(error):
        file_service.validate_document(data)
    assert runtime.repository.workflows == {}


# contract-test: direct surface=rest_api assertions=workflows.portability.definition-roundtrip,workflows.portability.disabled-validated-import feature=feature.workflows@7
def test_blank_draft_with_no_trigger_imports_and_title_collision_creates_new_id() -> None:
    file_service, runtime = service_pair()
    data = portable_file()
    data["workflow"]["graph"] = {"version": 2, "trigger_node_id": None, "nodes": [], "edges": [], "variables": {}, "limits": {}, "ui_layout": {}}
    data["binding_requirements"] = []
    document, graph = file_service.validate_document(data)
    first = file_service.import_document("bob", document, graph)
    second = file_service.import_document("bob", document, graph)
    assert first.id != second.id and first.title == second.title
    assert first.graph.nodes == [] and first.graph.trigger_node_id is None
    assert runtime.list_workflows("bob")[0].id in {first.id, second.id}


# contract-test: direct surface=rest_api assertions=workflows.portability.disabled-validated-import feature=feature.workflows@7
def test_import_binding_gate_and_explicit_chat_completion() -> None:
    file_service, runtime = service_pair()
    document, graph = file_service.validate_document(portable_file())
    imported = file_service.import_document("bob", document, graph)
    chat_node = imported.graph.nodes[2]
    with pytest.raises(WorkflowBindingRequirementsUnresolvedError):
        runtime.ensure_import_bindings_resolved(imported.id, "bob")
    with pytest.raises(WorkflowBindingRequirementUnresolvedError, match="CHAT_DESTINATION_NOT_SAVED"):
        runtime.complete_chat_destination_binding(imported.id, "bob", chat_node.id, chat_id="owned-chat")
    updated_graph = imported.graph.model_dump(mode="json", by_alias=True)
    updated_graph["nodes"][2]["config"]["chat_id"] = "owned-chat"
    runtime.update_workflow(imported.id, "bob", graph=updated_graph)
    completed = runtime.complete_chat_destination_binding(imported.id, "bob", chat_node.id, chat_id="owned-chat")
    assert completed == {"type": "chat_destination", "node_id": chat_node.id}
    reloaded = runtime.get_workflow(imported.id, "bob")
    assert reloaded.graph.nodes[2].config["chat_id"] == "owned-chat"
    assert "destination_required" not in reloaded.graph.nodes[2].config
    assert completed in reloaded.completed_binding_requirements
    assert len(reloaded.binding_requirements) == 3


# contract-test: direct surface=rest_api assertions=workflows.portability.disabled-validated-import feature=feature.workflows@7
@pytest.mark.anyio
async def test_file_route_returns_binding_review_and_chat_route_rejects_unowned_target() -> None:
    file_service, runtime = service_pair()
    del file_service
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    user = SimpleNamespace(id="bob", vault_key_id=None)
    from starlette.concurrency import run_in_threadpool

    async def no_ask_ai(*_args):
        return []

    def handle(exc):
        if isinstance(exc, WorkflowBindingRequirementUnresolvedError):
            raise HTTPException(status_code=409, detail=exc.reason) from exc
        raise exc

    namespace = {"WorkflowFileService": WorkflowFileService, "run_in_threadpool": run_in_threadpool,
                 "_validate_workflow_ask_ai_nodes": no_ask_ai, "_handle_workflow_error": handle,
                 "WorkflowBindingRequirementUnresolvedError": WorkflowBindingRequirementUnresolvedError,
                 "WorkflowNodeType": WorkflowNodeType,
                 "validate_workflow_composition_refs": validate_workflow_composition_refs,
                 "validate_workflow_readiness": validate_workflow_readiness,
                 "get_workflow_ai_service": lambda _request: SimpleNamespace()}
    _validation_helper("_prevalidate_paid_workflow_save", namespace)
    _validation_helper("_validate_workflow_ai_check_nodes", namespace)
    import_route = _route("import_workflow_file", namespace)
    complete_route = _route("complete_workflow_template_binding", namespace)
    response = await import_route(request, WorkflowFileDocument.model_validate(portable_file()), user, runtime)
    imported = response["workflow"]
    assert imported["binding_requirements"] and imported["completed_binding_requirements"] == []
    assert response["warnings"] == []
    chat_node = imported["graph"]["nodes"][2]
    graph = deepcopy(imported["graph"])
    graph["nodes"][2]["config"]["chat_id"] = "somebody-elses-chat"
    runtime.update_workflow(imported["id"], "bob", graph=graph)
    directus = SimpleNamespace(chat=SimpleNamespace(check_chat_ownership=lambda *_args: _false()))
    with pytest.raises(HTTPException) as exc:
        await complete_route(
            imported["id"], SimpleNamespace(type="chat_destination", node_id=chat_node["id"], chat_id="somebody-elses-chat", new_chat=False),
            request, user, runtime, directus,
        )
    assert exc.value.status_code == 409
    assert runtime.get_workflow(imported["id"], "bob").completed_binding_requirements == []

    directus.chat.check_chat_ownership = lambda *_args: _true()
    accepted = await complete_route(
        imported["id"], SimpleNamespace(type="chat_destination", node_id=chat_node["id"], chat_id="somebody-elses-chat", new_chat=False),
        request, user, runtime, directus,
    )
    assert accepted["completed"] is True
    assert accepted["workflow"]["completed_binding_requirements"] == [accepted["binding_requirement"]]
    assert "destination_required" not in accepted["workflow"]["graph"]["nodes"][2]["config"]


async def _false() -> bool:
    return False


async def _true() -> bool:
    return True


# contract-test: direct surface=rest_api assertions=workflows.portability.disabled-validated-import feature=feature.workflows@7
def test_new_chat_requires_explicit_title_and_selection() -> None:
    file_service, runtime = service_pair()
    document, graph = file_service.validate_document(portable_file())
    imported = file_service.import_document("bob", document, graph)
    chat_node = imported.graph.nodes[2]
    with pytest.raises(WorkflowBindingRequirementUnresolvedError, match="NEW_CHAT_DESTINATION_NOT_SAVED"):
        runtime.complete_chat_destination_binding(imported.id, "bob", chat_node.id, new_chat=True)
    updated = imported.graph.model_dump(mode="json", by_alias=True)
    updated["nodes"][2]["config"]["title"] = "My new forecast chat"
    runtime.update_workflow(imported.id, "bob", graph=updated)
    completed = runtime.complete_chat_destination_binding(imported.id, "bob", chat_node.id, new_chat=True)
    assert completed["type"] == "chat_destination"
    assert runtime.get_workflow(imported.id, "bob").graph.nodes[2].config["title"] == "My new forecast chat"


# contract-test: direct surface=rest_api assertions=workflows.portability.disabled-validated-import feature=feature.workflows@7
def test_changed_app_skill_cannot_complete_the_original_binding() -> None:
    file_service, runtime = service_pair()
    document, graph = file_service.validate_document(portable_file())
    imported = file_service.import_document("bob", document, graph)
    app_node = imported.graph.nodes[1]
    changed = imported.graph.model_dump(mode="json", by_alias=True)
    changed["nodes"][1]["config"]["skill_id"] = "different"
    runtime.update_workflow(imported.id, "bob", graph=changed)
    available = SimpleNamespace(is_skill_available=lambda *_args: True)
    with pytest.raises(WorkflowBindingRequirementUnresolvedError, match="APP_SKILL_CHANGED"):
        runtime.validate_app_skill_binding_requirement(imported.id, "bob", app_node.id, available)


# contract-test: direct surface=rest_api assertions=workflows.portability.private-content-boundary feature=feature.workflows@7
def test_file_import_requires_create_scope_for_approved_api_key_device() -> None:
    request = SimpleNamespace(method="POST", url=SimpleNamespace(path="/v1/workflows/file-import"), headers={})
    approved = {"device_hash": "device", "api_key_metadata": {"full_access": False, "scopes": {"workflows": ["workflow:create"]}}}
    _enforce_api_key_route_policy(request, approved)
    approved["api_key_metadata"]["scopes"]["workflows"] = ["workflow:write"]
    with pytest.raises(HTTPException) as exc:
        _enforce_api_key_route_policy(request, approved)
    assert exc.value.detail == {"error": "missing_scope", "missing_scope": "workflow:create"}
