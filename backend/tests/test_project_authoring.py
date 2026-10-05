"""Project-only recommendation, authoring and encrypted-save boundaries."""
from __future__ import annotations

import asyncio
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from fastapi import Request

import pytest

from backend.core.api.app.services.project_authoring_service import (
    FocusAuthorResult, ProjectAuthoringService, ProjectFocusDocument,
)
from backend.core.api.app.services.project_recommendation_service import (
    ProjectAuthoringAccess, ProjectCatalogEntry, ProjectRecommendationService,
)
from backend.core.api.app.services.project_write_authorization_service import ProjectWriteAuthorizationError
from backend.shared.providers.typesafe.models import DecisionResponse

HISTORY = [{"role": "user", "content": "Sensitive conversation example: improve reusable daily review."}]
DOCUMENT = {"name": "Daily review", "description": "Review this Project's work", "when_to_use": "During daily review",
            "instructions": "Review pending work. Ask for priorities.", "phases": []}


# contract-test: supporting surface=rest_api assertions=focus-modes.project-authoring-persistence,focus-modes.phases
def test_authored_focus_phase_schema_matches_runtime_and_unphased_markdown_omits_phase_metadata():
    from backend.apps.ai.processing.focus_phases import parse_project_phase_focus
    from backend.shared.python_utils.focus_mode_skill_loader import _split_frontmatter_and_body
    unphased = ProjectFocusDocument.model_validate(DOCUMENT)
    metadata, _ = _split_frontmatter_and_body(unphased.markdown(), "Project focus")
    assert "phases" not in metadata and "phases_version" not in metadata
    assert parse_project_phase_focus(unphased.markdown(), "project-focus:test:item") is None

    phased = ProjectFocusDocument.model_validate({**DOCUMENT, "phases_version": 1, "phases": [{
        "id": "verify", "title": "Verify", "instructions": "Check the source revision.",
        "requirements": [{"id": "source_checked", "type": "semantic",
                          "text": "The source revision was checked."}],
    }]})
    parsed = parse_project_phase_focus(phased.markdown(), "project-focus:test:item")
    assert parsed.phases[0].title == "Verify"
    assert parsed.phases[0].requirements[0].id == "source_checked"
    schema = FocusAuthorResult.model_json_schema()
    assert "ProjectFocusPhase" not in schema.get("$defs", {})
    assert "title" in schema["$defs"]["FocusPhaseDefinition"]["properties"]
    with pytest.raises(ValueError):
        ProjectFocusDocument.model_validate({**DOCUMENT, "phases": [{
            "id": "verify", "name": "Old phase", "instructions": "Check.",
        }]})
    with pytest.raises(ValueError):
        ProjectFocusDocument.model_validate({**DOCUMENT, "phases_version": True,
                                             "phases": [phase.model_dump() for phase in phased.phases]})


class Cache:
    def __init__(self):
        self.values = {}
        self.claims = {}

    @property
    async def client(self):
        return self

    async def get(self, key):
        return deepcopy(self.values.get(key))

    async def set(self, key, value, *, ttl=None, nx=False, ex=None):
        if nx:
            if key in self.claims:
                return False
            self.claims[key] = value
        else:
            self.values[key] = deepcopy(value)
        return True

    async def incr(self, key):
        self.claims[key] = self.claims.get(key, 0) + 1
        return self.claims[key]

    async def expire(self, key, seconds):
        return True

    async def delete(self, key):
        self.values.pop(key, None)
        self.claims.pop(key, None)


class Access:
    def __init__(self):
        self.revision = "revision-1"
        self.denied = False
        self.loaded = []
        self.directus = SimpleNamespace(embed=SimpleNamespace(
            get_embed_by_id=AsyncMock(return_value={"encrypted_content": "ciphertext", "version_number": 1}),
            get_embeds_by_hashed_embed_ids=AsyncMock(return_value=[{"version_number": 1}])), get_items=AsyncMock())
        self.item = {"target_id_hash": hashlib.sha256(b"embed-1").hexdigest()}
        self.detail = SimpleNamespace(id="workflow-1", version=2, current_version_id="wf-version-2",
            model_dump=lambda **_: {"id": "workflow-1", "graph": {"nodes": [{"type": "ai_check"}]}, "version": 2})

    async def require_context(self, *args, **kwargs):
        if self.denied:
            raise ProjectWriteAuthorizationError("PROJECT_NOT_FOUND", status_code=404)
        return [{"project_item_id": "workflow-item", "item_type": "workflow", "target_id_hash": hashlib.sha256(b"workflow-1").hexdigest(),
                 "updated_at": 1, "encrypted_metadata": "prior-ciphertext"}]

    async def require_target(self, **kwargs):
        if self.denied:
            raise ProjectWriteAuthorizationError("PROJECT_NOT_FOUND", status_code=404)
        self.loaded.append((kwargs["kind"], kwargs["target_id"]))
        return self.revision, self.detail if kwargs["kind"] == "workflow" else self.item


class Jev:
    def __init__(self, values):
        self.values = list(values)
        self.calls = []

    async def evaluate(self, **kwargs):
        self.calls.append(kwargs)
        result = self.values.pop(0)
        return DecisionResponse(model="typesafe/jev-1.13", answers={
            key: {"type": "noul", "noul": value} for key, value in result.items()})


async def permit(cache, service, turn="turn-1"):
    await cache.set(service.response_key("owner", "chat", turn), {"project_id": "project", "team_id": None})


def catalog(kind="focus"):
    return [ProjectCatalogEntry(kind=kind, id="focus-1" if kind == "focus" else "workflow-1",
                                title="Inactive daily review", summary="Daily reusable review", revision="revision-1")]


# contract-test: direct surface=rest_api assertions=focus-modes.project-recommendation-catalog,focus-modes.project-recommendation-full-assessment
@pytest.mark.asyncio
async def test_catalog_then_selected_focus_inspection_never_authors_or_activates():
    cache, access = Cache(), Access()
    jev = Jev([{"candidate_0": 1, "create_focus": 0}, {"useful_update": 1}])
    service = ProjectRecommendationService(access=access, cache=cache, jev=jev)
    await permit(cache, service)
    proposals = await service.assess(user_id="owner", chat_id="chat", project_id="project", catalog=catalog(),
                                     history=HISTORY, message_id="turn-1")
    assert [proposal["action"] for proposal in proposals] == ["inspect"]
    assert len(jev.calls) == 1
    assert "instructions" not in json.dumps(jev.calls[0]["state"]["catalog"])
    assert "Inactive" in jev.calls[0]["state"]["catalog"][0]["title"]
    update = await service.inspect_focus(user_id="owner", project_id="project", assessment_id=proposals[0]["recommendation_id"],
                                         history=HISTORY, document=DOCUMENT)
    assert update["action"] == "update"
    assert jev.calls[1]["state"]["target"] == DOCUMENT
    repeated = await service.inspect_focus(user_id="owner", project_id="project", assessment_id=proposals[0]["recommendation_id"],
                                           history=HISTORY, document=DOCUMENT)
    assert repeated == update and len(jev.calls) == 2
    assert "Sensitive conversation" not in json.dumps(cache.values)


# contract-test: direct surface=rest_api assertions=focus-modes.project-recommendation-catalog,workflows.project.update-recommendation
@pytest.mark.asyncio
async def test_create_first_pass_and_uncertain_full_graph_does_not_show_update():
    cache, access = Cache(), Access()
    jev = Jev([{"candidate_0": 1, "create_focus": 1}, {"useful_update": .5}])
    service = ProjectRecommendationService(access=access, cache=cache, jev=jev)
    await permit(cache, service)
    proposals = await service.assess(user_id="owner", chat_id="chat", project_id="project", catalog=catalog("workflow"),
                                     history=HISTORY, message_id="turn-1")
    assert [proposal["action"] for proposal in proposals] == ["create"]
    assert "graph" in jev.calls[1]["state"]["target"]
    assert len(jev.calls) == 2


# contract-test: direct surface=rest_api assertions=focus-modes.project-recommendation-catalog,focus-modes.project-recommendation-full-assessment
@pytest.mark.asyncio
async def test_likely_metadata_match_requires_stronger_full_definition_update():
    cache, access = Cache(), Access()
    jev = Jev([{"candidate_0": .8, "create_focus": .89}, {"useful_update": .8}])
    service = ProjectRecommendationService(access=access, cache=cache, jev=jev)
    await permit(cache, service)
    proposals = await service.assess(user_id="owner", chat_id="chat", project_id="project", catalog=catalog(),
                                     history=HISTORY, message_id="turn-1")
    assert [proposal["action"] for proposal in proposals] == ["inspect"]
    update = await service.inspect_focus(user_id="owner", project_id="project",
        assessment_id=proposals[0]["recommendation_id"], history=HISTORY, document=DOCUMENT)
    assert update is None
    assert len(jev.calls) == 2
    assert "Sensitive conversation" not in json.dumps(cache.values)


# contract-test: direct surface=rest_api assertions=focus-modes.project-recommendation-catalog
@pytest.mark.asyncio
async def test_catalog_questions_scope_selection_to_individual_definitions():
    cache, access = Cache(), Access()
    entries = [*catalog(), ProjectCatalogEntry(kind="focus", id="unrelated-focus", title="Music practice",
        summary="Compose music", revision="revision-1")]
    jev = Jev([{"candidate_0": .8, "candidate_1": .1, "create_focus": 0}])
    service = ProjectRecommendationService(access=access, cache=cache, jev=jev)
    await permit(cache, service)
    proposals = await service.assess(user_id="owner", chat_id="chat", project_id="project", catalog=entries,
                                     history=HISTORY, message_id="turn-1")
    assert [proposal["target_id"] for proposal in proposals] == ["focus-1"]
    questions = jev.calls[0]["questions"]
    assert "catalog[0]" in questions["candidate_0"]["instructions"]
    assert "catalog[1]" in questions["candidate_1"]["instructions"]


# contract-test: direct surface=rest_api assertions=focus-modes.project-recommendation-full-assessment
@pytest.mark.asyncio
async def test_unselected_focus_never_loads_and_stale_inspection_fails_closed():
    cache, access = Cache(), Access()
    service = ProjectRecommendationService(access=access, cache=cache, jev=Jev([{"candidate_0": 0, "create_focus": 0}]))
    await permit(cache, service)
    load = AsyncMock()
    assert await service.assess(user_id="owner", chat_id="chat", project_id="project", catalog=catalog(),
                               history=HISTORY, load_full=load, message_id="turn-1") == []
    load.assert_not_called()
    token = await service._issue("owner", "chat", "project", None, "focus", "inspect", "focus-1", "revision-1")
    access.revision = "revision-2"
    with pytest.raises(ProjectWriteAuthorizationError, match="REVISION_CONFLICT"):
        await service.inspect_focus(user_id="owner", project_id="project", assessment_id=token["recommendation_id"],
                                    history=HISTORY, document=DOCUMENT)


# contract-test: direct surface=rest_api assertions=focus-modes.project-authoring-click,focus-modes.project-authoring-persistence,notifications.project-authoring.result-route
@pytest.mark.asyncio
async def test_only_click_authors_once_and_ready_requires_owned_encrypted_saved_result():
    cache, access = Cache(), Access()
    recommendation = ProjectRecommendationService(access=access, cache=cache, jev=None)
    token = await recommendation._issue("owner", "chat", "project", None, "focus", "create", None, None)
    author = SimpleNamespace(author=AsyncMock(return_value=FocusAuthorResult(status="authored", document=ProjectFocusDocument(**DOCUMENT))))
    notifications = SimpleNamespace(store_and_publish=AsyncMock())
    service = ProjectAuthoringService(access=access, cache=cache, workflow_input=None, focus_author=author, notifications=notifications)
    assert author.author.await_count == 0
    first = await service.start(user_id="owner", project_id="project", recommendation_id=token["recommendation_id"], expected_revision=None, history=HISTORY)
    second = await service.start(user_id="owner", project_id="project", recommendation_id=token["recommendation_id"], expected_revision=None, history=HISTORY)
    assert first["job_id"] == second["job_id"]
    await asyncio.gather(*service._tasks)
    assert author.author.await_count == 1
    job = await service.get(user_id="owner", project_id="project", job_id=first["job_id"])
    assert job["status"] == "needs_save" and job["draft"]["markdown"].startswith("---\n")
    assert "Sensitive conversation" not in json.dumps(cache.values)
    notifications.store_and_publish.assert_not_called()
    access.directus.get_items.return_value = [{"operation_id": job["draft"]["save_operation_id"], "embed_id": "embed-1", "committed_revision": 1,
        "expected_revision": 0, "actor_user_hash": hashlib.sha256(b"owner").hexdigest(),
        "hashed_project_id": hashlib.sha256(b"project").hexdigest(), "hashed_chat_id": hashlib.sha256(b"chat").hexdigest(),
        "hashed_team_id": None, "created_at": job["created_at"]}]
    ready = await service.acknowledge_focus_save(user_id="owner", project_id="project", job_id=first["job_id"],
        project_item_id=job["result_id"], embed_id="embed-1", saved_revision="revision-1", expected_revision=None,
        save_operation_id=job["draft"]["save_operation_id"])
    assert ready["status"] == "ready"
    await service.acknowledge_focus_save(user_id="owner", project_id="project", job_id=first["job_id"],
        project_item_id=job["result_id"], embed_id="embed-1", saved_revision="revision-1", expected_revision=None,
        save_operation_id=job["draft"]["save_operation_id"])
    notifications.store_and_publish.assert_awaited_once()
    event = notifications.store_and_publish.call_args.args[0]
    assert event.routing["project_id"] == "project" and event.routing["embed_id"] == "embed-1"
    assert DOCUMENT["instructions"] not in event.model_dump_json()


# contract-test: direct surface=rest_api assertions=focus-modes.project-authoring-persistence
@pytest.mark.asyncio
async def test_cross_owner_revocation_and_revisions_reject_click():
    cache, access = Cache(), Access()
    recommendation = ProjectRecommendationService(access=access, cache=cache, jev=None)
    token = await recommendation._issue("owner", "chat", "project", None, "focus", "update", "focus-1", "revision-1")
    service = ProjectAuthoringService(access=access, cache=cache, workflow_input=None, focus_author=SimpleNamespace(author=AsyncMock()))
    with pytest.raises(ProjectWriteAuthorizationError, match="EXPIRED"):
        await service.start(user_id="other", project_id="project", recommendation_id=token["recommendation_id"], expected_revision="revision-1", history=HISTORY, target=DOCUMENT)
    access.revision = "revision-2"
    with pytest.raises(ProjectWriteAuthorizationError, match="REVISION_CONFLICT"):
        await service.start(user_id="owner", project_id="project", recommendation_id=token["recommendation_id"], expected_revision="revision-1", history=HISTORY, target=DOCUMENT)
    access.denied = True
    with pytest.raises(ProjectWriteAuthorizationError, match="PROJECT_NOT_FOUND"):
        await service.start(user_id="owner", project_id="project", recommendation_id=token["recommendation_id"], expected_revision="revision-1", history=HISTORY, target=DOCUMENT)
    service.focus_author.author.assert_not_called()


# contract-test: direct surface=rest_api assertions=workflows.project.update-authoring,notifications.project-authoring.result-route
@pytest.mark.asyncio
@pytest.mark.parametrize("result_status,partial,remote_status,expected", [
    ("executed", None, None, "ready"), ("executed", "provider_error", None, "partial"),
    ("needs_clarification", None, None, "needs_input"), ("executed", None, "pending", "pending_file"),
    ("executed", None, "conflict", "conflict"),
])
async def test_workflow_reuses_existing_pipeline_without_history_in_job_and_only_complete_save_notifies(result_status, partial, remote_status, expected):
    cache, access = Cache(), Access()
    access.revision = "1"
    recommendation = ProjectRecommendationService(access=access, cache=cache, jev=None)
    token = await recommendation._issue("owner", "chat", "project", None, "workflow", "update", "workflow-1", "1")
    calls = []
    def start(**kwargs):
        calls.append(kwargs)
        access.revision = "2"
        return SimpleNamespace(session_id="input-session", status=result_status, partial_reason=partial, error_code=None,
                               workflow=access.detail, message="Which daily time?")
    notifications = SimpleNamespace(store_and_publish=AsyncMock())
    remote = SimpleNamespace(persist=AsyncMock(return_value={"status": remote_status})) if remote_status else None
    service = ProjectAuthoringService(access=access, cache=cache, workflow_input=SimpleNamespace(start=start), focus_author=None,
                                      notifications=notifications, remote_files=remote)
    job = await service.start(user_id="owner", project_id="project", recommendation_id=token["recommendation_id"], expected_revision="1", history=HISTORY,
                              remote_binding=SimpleNamespace(project_id="project", source_id="source") if remote else None)
    await asyncio.gather(*service._tasks)
    status = await service.get(user_id="owner", project_id="project", job_id=job["job_id"])
    assert status["status"] == expected
    assert calls[0]["expected_workflow_version"] == 1
    assert calls[0]["transient_context"]["history"] == HISTORY
    assert "Sensitive conversation" not in calls[0]["text"] and "Sensitive conversation" not in json.dumps(cache.values)
    assert notifications.store_and_publish.await_count == (1 if expected == "ready" else 0)


# contract-test: direct surface=rest_api assertions=focus-modes.project-authoring-click
@pytest.mark.asyncio
async def test_assessment_needs_completed_response_and_per_user_budget():
    cache, access = Cache(), Access()
    jev = Jev([{"create_focus": 0}] * 9)
    service = ProjectRecommendationService(access=access, cache=cache, jev=jev)
    with pytest.raises(ProjectWriteAuthorizationError, match="RESPONSE_UNAVAILABLE"):
        await service.assess(user_id="owner", chat_id="chat", project_id="project", catalog=[], history=HISTORY, message_id="missing")
    for index in range(8):
        await permit(cache, service, str(index))
        await service.assess(user_id="owner", chat_id="chat", project_id="project", catalog=[], history=HISTORY, message_id=str(index))
    await permit(cache, service, "ninth")
    with pytest.raises(ProjectWriteAuthorizationError) as denied:
        await service.assess(user_id="owner", chat_id="chat", project_id="project", catalog=[], history=HISTORY, message_id="ninth")
    assert denied.value.status_code == 429 and len(jev.calls) == 8


# contract-test: supporting surface=rest_api assertions=focus-modes.project-authoring-click,focus-modes.project-authoring-persistence
def test_routes_use_approved_first_party_auth_limits_and_no_public_allowlist_change():
    source = (Path(__file__).resolve().parents[1] / "core/api/app/routes/project_authoring.py").read_text()
    assert "get_current_user_or_api_key" in source and "Depends(ensure_projects_enabled)" in source
    lines = source.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("@router."):
            assert lines[index + 1].startswith("@limiter.limit(")


# contract-test: direct surface=rest_api assertions=focus-modes.project-authoring-click,workflows.project.update-authoring
def test_first_party_api_rejects_anonymous_developer_and_revoked_access_and_binds_current_turn():
    from backend.tests.runtime_import_stubs import install_code_route_import_stubs
    install_code_route_import_stubs()
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient
    from backend.core.api.app.models.user import User
    from backend.core.api.app.routes import project_authoring as routes
    from backend.core.api.app.routes.auth_routes.auth_dependencies import _enforce_api_key_route_policy
    from backend.core.api.app.services.limiter import limiter

    path = "/v1/projects/project/authoring/recommend"
    with pytest.raises(HTTPException) as developer:
        _enforce_api_key_route_policy(SimpleNamespace(method="POST", url=SimpleNamespace(path=path)),
                                     {"api_key_metadata": {"full_access": True}})
    assert developer.value.status_code == 403
    _enforce_api_key_route_policy(SimpleNamespace(method="POST", url=SimpleNamespace(path=path)),
                                 {"device_hash": "approved", "api_key_metadata": {"full_access": True}})

    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(routes.router)
    async def authorized(request: Request):
        if request.headers.get("authorization") != "Bearer owner":
            raise HTTPException(401)
        return User(id="owner", username="owner", vault_key_id="vault")
    app.dependency_overrides[routes.get_current_user_or_api_key] = authorized
    app.dependency_overrides[routes.ensure_projects_enabled] = lambda: None
    assess = AsyncMock(side_effect=ProjectWriteAuthorizationError("PROJECT_NOT_FOUND", status_code=404))
    app.dependency_overrides[routes.get_recommendations] = lambda: SimpleNamespace(assess=assess)
    client = TestClient(app)
    body = {"chat_id": "chat", "message_id": "current-user-turn", "catalog": [], "history": HISTORY}
    assert client.post(path, json=body).status_code == 401
    assess.assert_not_called()
    denied = client.post(path, json=body, headers={"authorization": "Bearer owner"})
    assert denied.status_code == 404 and denied.json()["detail"] == "PROJECT_NOT_FOUND"
    assert assess.call_args.kwargs["message_id"] == "current-user-turn"
    assert client.post(path, json={key: value for key, value in body.items() if key != "message_id"},
                       headers={"authorization": "Bearer owner"}).status_code == 422


# contract-test: direct surface=rest_api assertions=workflows.project.update-authoring
def test_input_pipeline_scope_authority_and_transient_history_do_not_change_persisted_input():
    from backend.core.api.app.services.workflow_input_service import WorkflowInputService, _session_private_state
    from backend.tests.workflow_test_utils import workflow_service
    from backend.tests.test_workflows_models import rain_graph
    workflows = workflow_service()
    graph = rain_graph()
    original = workflows.create_workflow("owner", "Daily review", graph)
    seen = []
    class Planner:
        requires_workflow_overview = False
        def plan(self, *, text, context):
            seen.append((text, context["_transient_authoring_context"]["history"]))
            return {"action": "update_workflow", "workflow_id": original.id, "title": "Updated daily review"}
    calls = []
    service = WorkflowInputService(workflow_service=workflows, planner=Planner())
    result = service.start(user_id="owner", text="Update selected Workflow.", selected_workflow_id=original.id,
                           expected_workflow_version=original.version,
                           transient_context={"history": HISTORY, "_authorize_commit": lambda: calls.append("authorized")})
    assert result.status == "executed" and calls == ["authorized"]
    assert seen == [("Update selected Workflow.", HISTORY)]
    assert "Sensitive conversation" not in json.dumps(_session_private_state(service._sessions[result.session_id]))
    assert "_transient_authoring_context" not in service._sessions[result.session_id]

    class WrongTarget:
        requires_workflow_overview = False
        def plan(self, **kwargs):
            return {"action": "create_workflow", "title": "Unrequested copy", "graph": graph}
    service.planner = WrongTarget()
    before = workflows.get_workflow(original.id, "owner")
    rejected = service.start(user_id="owner", text="Update selected Workflow.", selected_workflow_id=original.id,
                             expected_workflow_version=before.version)
    assert rejected.status == "failed" and len(workflows.repository.workflows) == 1
    assert workflows.get_workflow(original.id, "owner").version == before.version


# contract-test: direct surface=rest_api assertions=workflows.project.update-recommendation
@pytest.mark.asyncio
async def test_team_owned_workflow_is_excluded_before_button_but_personal_link_remains_editable():
    cache = Cache()
    rows = [{"project_item_id": "item-" + identity, "item_type": "workflow",
             "target_id_hash": hashlib.sha256(identity.encode()).hexdigest()} for identity in ("team-workflow", "personal-workflow")]
    def get_record(identity, user_id):
        return {"version": 1} if identity == "personal-workflow" else None

    detail = SimpleNamespace(version=1, model_dump=lambda **_: {"id": "personal-workflow", "graph": {"nodes": []}})
    def get_full(identity, user_id, key):
        return detail
    workflow = SimpleNamespace(ensure_enabled=lambda: None, repository=SimpleNamespace(get_workflow=get_record), get_workflow=get_full)
    access = ProjectAuthoringAccess(SimpleNamespace(project=SimpleNamespace(list_items=AsyncMock(return_value=rows))), cache, workflow)
    access.authorization._require_project_access = AsyncMock(return_value=({}, None))
    access.require_context = AsyncMock(return_value=rows)
    jev = Jev([{"candidate_0": 1, "create_focus": 0}, {"useful_update": 1}])
    service = ProjectRecommendationService(access=access, cache=cache, jev=jev)
    await cache.set(service.response_key("owner", "chat", "turn"), {"project_id": "project", "team_id": "team"})
    proposed = await service.assess(user_id="owner", chat_id="chat", project_id="project", team_id="team", message_id="turn", history=HISTORY,
        catalog=[ProjectCatalogEntry(kind="workflow", id=identity, title=identity, revision="1") for identity in ("team-workflow", "personal-workflow")])
    assert [row["target_id"] for row in proposed] == ["personal-workflow"]
    assert [row["id"] for row in jev.calls[0]["state"]["catalog"]] == ["personal-workflow"]


# contract-test: direct surface=rest_api assertions=focus-modes.project-authoring-persistence,notifications.project-authoring.result-route
@pytest.mark.asyncio
async def test_focus_save_cannot_claim_ready_without_its_atomic_commit_receipt():
    cache, access = Cache(), Access()
    author = SimpleNamespace(author=AsyncMock(return_value={"status": "authored", "document": DOCUMENT}))
    notifications = SimpleNamespace(store_and_publish=AsyncMock())
    service = ProjectAuthoringService(access=access, cache=cache, workflow_input=None, focus_author=author, notifications=notifications)
    token = await ProjectRecommendationService(access=access, cache=cache, jev=None)._issue("owner", "chat", "project", None, "focus", "create", None, None)
    job = await service.start(user_id="owner", project_id="project", recommendation_id=token["recommendation_id"], expected_revision=None, history=HISTORY)
    await asyncio.gather(*service._tasks)
    current = await service.get(user_id="owner", project_id="project", job_id=job["job_id"])
    access.directus.get_items.return_value = []
    with pytest.raises(ProjectWriteAuthorizationError, match="SAVE_PROOF_REQUIRED"):
        await service.acknowledge_focus_save(user_id="owner", project_id="project", job_id=job["job_id"],
            project_item_id=current["result_id"], embed_id="embed-1", saved_revision="revision-1", expected_revision=None,
            save_operation_id=current["draft"]["save_operation_id"])
    notifications.store_and_publish.assert_not_called()


# contract-test: direct surface=rest_api assertions=workflows.project.update-authoring,notifications.project-authoring.result-route
@pytest.mark.asyncio
async def test_remote_workflow_needs_actual_file_completion_and_encrypted_binding_before_ready(monkeypatch):
    import backend.core.api.app.services.project_authoring_service as module
    from backend.core.api.app.services.project_recommendation_service import project_item_revision
    cache, access = Cache(), Access()
    access.revision = "1"
    token = await ProjectRecommendationService(access=access, cache=cache, jev=None)._issue(
        "owner", "chat", "project", None, "workflow", "update", "workflow-1", "1")
    def start(**kwargs):
        access.revision = "2"
        return SimpleNamespace(session_id="session", status="executed", partial_reason=None, workflow=access.detail)
    binding = {"project_id": "project", "source_id": "source", "folder_path": "workflows", "file_path": "workflows/Daily.workflow.yml",
               "base_hash": hashlib.sha256(b"canonical-yaml").hexdigest(), "saved_content": "canonical-yaml", "workflow_version_id": "wf-version-2"}
    notifications = SimpleNamespace(store_and_publish=AsyncMock())
    service = ProjectAuthoringService(access=access, cache=cache, workflow_input=SimpleNamespace(start=start), focus_author=None,
        notifications=notifications, remote_files=SimpleNamespace(persist=AsyncMock(return_value={"status": "pending", "operation_id": "file-operation", "proposed_binding": binding})))
    started = await service.start(user_id="owner", project_id="project", recommendation_id=token["recommendation_id"],
        expected_revision="1", history=HISTORY, remote_binding=SimpleNamespace(project_id="project", source_id="source"))
    await asyncio.gather(*service._tasks)
    job = await service.get(user_id="owner", project_id="project", job_id=started["job_id"])
    assert job["status"] == "pending_file"
    operation = {"continuation_task_id": "project-authoring:" + job["job_id"], "project_id": "project", "source_id": "source",
                 "state": "COMPLETED", "result_status": "completed"}
    monkeypatch.setattr(module, "ProjectFileOperationService", lambda _: SimpleNamespace(get_job=AsyncMock(return_value=operation)))
    completed = await service.settle_file_operation(user_id="owner", operation_id="file-operation")
    assert completed["status"] == "needs_binding_save"
    notifications.store_and_publish.assert_not_called()
    item = {"project_item_id": "workflow-item", "encrypted_metadata": "new-binding-ciphertext", "updated_at": 2}
    access.directus.project = SimpleNamespace(get_item=AsyncMock(return_value=item))
    ready = await service.acknowledge_workflow_binding(user_id="owner", project_id="project", job_id=job["job_id"],
        project_item_id="workflow-item", saved_item_revision=project_item_revision(item), workflow_version_id="wf-version-2")
    assert ready["status"] == "ready"
    notifications.store_and_publish.assert_awaited_once()


# contract-test: supporting surface=rest_api assertions=focus-modes.project-authoring-persistence
@pytest.mark.asyncio
async def test_team_authoring_ledger_prechecks_and_charges_team_without_personal_fallback(monkeypatch):
    import sys
    from backend.core.api.app.services import workflow_authoring_billing as module
    personal = AsyncMock()
    team = AsyncMock()
    charged = AsyncMock(return_value={"charged_credits": 3})
    monkeypatch.setattr(module, "ensure_credit_headroom", personal)
    monkeypatch.setattr(module, "calculate_total_credits", lambda **_: 3)
    monkeypatch.setitem(sys.modules, "backend.core.api.app.routes.apps_api", SimpleNamespace(charge_credits_via_internal_api=charged))
    billing = module.WorkflowAuthoringBilling(user_id="owner", session_id="job", app_id="ai", skill_id="project-focus-author",
        team_id="team", team_precheck=team, config_manager=SimpleNamespace())
    billing._pricing = lambda _: {}
    await billing.precheck(model=module.GEMINI_MODEL)
    await billing.settle(model=module.GEMINI_MODEL, provider_step="author", usage={"input_tokens": 10, "output_tokens": 10})
    team.assert_awaited_once_with("team", "owner")
    personal.assert_not_called()
    assert charged.call_args.kwargs["team_id"] == "team"
    team.side_effect = module.WorkflowAuthoringBillingError("INSUFFICIENT_CREDITS")
    with pytest.raises(module.WorkflowAuthoringBillingError, match="INSUFFICIENT_CREDITS"):
        await billing.precheck(model=module.GEMINI_MODEL)
    assert charged.await_count == 1
