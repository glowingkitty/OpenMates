"""Account-scoped saved workflow library contracts for the Apps workspace."""

from copy import deepcopy

from backend.core.api.app.services.workflow_service import InMemoryWorkflowRepository, _hash_team_id
from backend.tests.test_workflows_models import rain_graph
from backend.tests.workflow_test_utils import workflow_service


def _graph_with_apps(*app_ids: str) -> dict:
    graph = deepcopy(rain_graph())
    graph["nodes"][1]["config"]["app_id"] = app_ids[0]
    previous = "email"
    for index, app_id in enumerate(app_ids[1:], start=1):
        node_id = f"extra-skill-{index}"
        graph["nodes"].append({
            "id": node_id, "type": "app_skill_action",
            "config": {"app_id": app_id, "skill_id": "other", "input": {}},
        })
        graph["edges"].append({"from": previous, "to": node_id})
        previous = node_id
    return graph


# contract-test: supporting surface=rest_api assertions=apps.library.workflows-account-related
def test_app_library_filters_current_encrypted_graph_and_pages_saved_unrun_workflows() -> None:
    repository = InMemoryWorkflowRepository()
    service = workflow_service(repository=repository)
    first = service.create_workflow("alice", "Two Audio skills", _graph_with_apps("audio", "audio"))
    second = service.create_workflow("alice", "One Audio skill", _graph_with_apps("audio"))
    service.create_workflow("alice", "Other app", _graph_with_apps("weather"))
    service.create_workflow("alice", "Temporary Audio", _graph_with_apps("audio"), lifecycle="temporary")
    service.create_workflow("bob", "Bob Audio", _graph_with_apps("audio"))

    first_page, has_more = service.list_workflows_page("alice", app_id="audio", limit=1)
    second_page, second_has_more = service.list_workflows_page("alice", app_id="audio", offset=1, limit=1)

    assert {first_page[0].id, second_page[0].id} == {first.id, second.id}
    assert has_more is True
    assert second_has_more is False
    assert first_page[0].last_run_status is None
    assert second_page[0].last_run_status is None
    assert len(service.list_workflows("alice")) == 3  # Legacy callers still get an unpaginated list.
    assert "app_id" not in str(repository.workflows)


# contract-test: supporting surface=rest_api assertions=apps.library.workflows-account-related
def test_app_library_keeps_personal_and_team_rows_separate() -> None:
    repository = InMemoryWorkflowRepository()
    service = workflow_service(repository=repository)
    personal = service.create_workflow("alice", "Personal Audio", _graph_with_apps("audio"))
    team = service.create_workflow("alice", "Team Audio", _graph_with_apps("audio"))
    team_record = repository.workflows[team.id]
    team_record["hashed_team_id"] = _hash_team_id("studio")
    repository.save_workflow(team_record)

    personal_page, _ = service.list_workflows_page("alice", app_id="audio")
    team_page, _ = service.list_workflows_page("alice", team_id="studio", app_id="audio")
    other_team_page, _ = service.list_workflows_page("alice", team_id="other", app_id="audio")

    assert [item.id for item in personal_page] == [personal.id]
    assert [item.id for item in team_page] == [team.id]
    assert other_team_page == []
