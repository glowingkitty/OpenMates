"""Keep private chat origins out of shared Team workflow responses.

The workflow record retains source_chat_id for internal bookkeeping.
Every public Team summary, detail, and version projection must omit it,
because an explicitly shared workflow can originate in a private Team DM.
Personal workflow projections retain their existing source-chat behavior.
"""

from backend.core.api.app.services.workflow_service import InMemoryWorkflowRepository
from backend.tests.workflow_test_utils import workflow_service


GRAPH = {"version": 2, "trigger_node_id": None, "nodes": [], "edges": []}
PRIVATE_CHAT_ID = "00000000-0000-0000-0000-000000000001"


# contract-test: supporting surface=rest_api assertions=teams.direct-chat.participant-isolation,teams.context.full-switch-local
def test_team_workflow_omits_source_chat_from_all_projections_but_retains_internal_origin():
    repository = InMemoryWorkflowRepository()
    service = workflow_service(repository=repository)
    created = service.create_workflow(
        "alice", "Shared result", GRAPH, team_id="team-a", source_chat_id=PRIVATE_CHAT_ID,
    )
    assert repository.workflows[created.id]["source_chat_id"] == PRIVATE_CHAT_ID
    assert created.source_chat_id is None
    assert service.list_workflows("bob", team_id="team-a")[0].source_chat_id is None
    assert service.list_workflows_page("bob", team_id="team-a")[0][0].source_chat_id is None
    assert service.get_workflow(created.id, "bob", team_id="team-a").source_chat_id is None
    assert service.get_workflow_version(
        created.id, "bob", created.current_version_id, team_id="team-a",
    ).source_chat_id is None


# contract-test: supporting surface=rest_api assertions=workflows.access.boundaries
def test_personal_workflow_preserves_source_chat_projection():
    service = workflow_service(repository=InMemoryWorkflowRepository())
    created = service.create_workflow("alice", "Personal result", GRAPH, source_chat_id=PRIVATE_CHAT_ID)
    assert created.source_chat_id == PRIVATE_CHAT_ID
    assert service.list_workflows("alice")[0].source_chat_id == PRIVATE_CHAT_ID
