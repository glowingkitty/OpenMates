"""Initial single-call shortlists never substitute newer private bodies."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.apps.ai.processing import context_preselection
from backend.tests.test_rule_context import guide


# contract-test: supporting surface=rest_api assertions=rules.selection.focus-aware
@pytest.mark.asyncio
async def test_rules_reload_exact_revision_and_fresh_selected_mate_catalog(monkeypatch):
    current = guide()
    other = guide("app:code:other")
    catalog = AsyncMock(return_value=[current])
    monkeypatch.setattr(context_preselection, "_rules", catalog)
    snapshots = [{"id": current.id, "revision": current.revision},
                 {"id": other.id, "revision": other.revision}]
    request = SimpleNamespace()
    selected = await context_preselection.reload_preselected_rules(request, None, None, ["code"], snapshots)
    assert selected == [current]
    catalog.assert_awaited_once_with(request, None, None, ["code"])
    catalog.return_value = [current.model_copy(update={"revision": "b" * 64})]
    assert await context_preselection.reload_preselected_rules(request, None, None, ["code"], snapshots) == []


# contract-test: supporting surface=rest_api assertions=rules.ownership.encrypted-custom
@pytest.mark.asyncio
async def test_discovery_contains_no_rule_body_and_reload_after_revocation_is_empty(monkeypatch):
    current = guide("project-rule", source="project", app_id=None, project_id="p1")
    catalog = AsyncMock(return_value=[current])
    monkeypatch.setattr(context_preselection, "_rules", catalog)
    request = SimpleNamespace()
    metadata = await context_preselection.discover_rule_metadata(request, None, None, ["code"])
    assert metadata[0]["revision"] == current.revision
    assert "body" not in metadata[0]
    catalog.return_value = []
    assert await context_preselection.reload_preselected_rules(request, None, None, ["code"], metadata) == []


# contract-test: supporting surface=rest_api assertions=rules.ownership.encrypted-custom
@pytest.mark.asyncio
async def test_authorized_project_guide_survives_bounded_app_rule_catalog(monkeypatch):
    app_rules = [guide(f"app:code:rule-{index}") for index in range(30)]
    project_rule = guide("project-guide", source="project", app_id=None, project_id="p1")
    monkeypatch.setattr(context_preselection, "_rules", AsyncMock(return_value=[*app_rules, project_rule]))
    metadata = await context_preselection.discover_rule_metadata(
        SimpleNamespace(), None, None, ["code"],
    )
    assert len(metadata) == context_preselection.MAX_RULE_CANDIDATES
    assert metadata[0]["id"] == "project-guide"
    assert {row["id"] for row in metadata[1:]} == {rule.id for rule in app_rules[:23]}


# contract-test: supporting surface=rest_api assertions=workflows.chat.relevance-discovery
@pytest.mark.asyncio
async def test_workflow_reload_rejects_changed_version_before_graph_loading(monkeypatch):
    from backend.apps.workflows.skills import saved_workflow_context
    service = object()
    monkeypatch.setattr(context_preselection, "_workflow_service", AsyncMock(return_value=(service, "vault")))
    monkeypatch.setattr(saved_workflow_context, "saved_workflow_metadata", lambda *a, **k: [
        {"workflow_id": "wf", "current_version_id": "new", "title": "fresh"}])
    captured = []
    monkeypatch.setattr(saved_workflow_context, "load_selected_saved_workflows",
                        lambda *a, **k: captured.extend(a[2]) or [])
    request = SimpleNamespace(user_id="user", team_id=None)
    assert await context_preselection.reload_preselected_workflows(request, None,
        [{"workflow_id": "wf", "current_version_id": "old"}]) == []
    assert captured == []
