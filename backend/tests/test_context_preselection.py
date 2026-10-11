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


# contract-test: supporting surface=rest_api assertions=workflows.chat.metadata-warmup
@pytest.mark.asyncio
async def test_workflow_discovery_uses_shared_cache_and_falls_back_on_cache_error(monkeypatch):
    from backend.apps.workflows.skills import saved_workflow_context
    request = SimpleNamespace(user_id="alice", team_id=None)
    cached = [{"workflow_id": "wf", "current_version_id": "v1"}]
    service = object()
    expire = AsyncMock(return_value=True)
    class Cache:
        @property
        async def client(self):
            return SimpleNamespace(expire=expire)
    cache = Cache()
    monkeypatch.setattr(context_preselection, "_workflow_service", AsyncMock(return_value=(service, "vault")))
    cache_read = AsyncMock(return_value=cached)
    cache_write = AsyncMock()
    monkeypatch.setattr(context_preselection, "_cached_workflow_metadata", cache_read)
    monkeypatch.setattr(context_preselection, "_save_workflow_metadata", cache_write)
    versioned_key = AsyncMock(return_value="key")
    monkeypatch.setattr(context_preselection, "_versioned_workflow_metadata_key", versioned_key)
    discovery_calls = []
    monkeypatch.setattr(saved_workflow_context, "saved_workflow_metadata",
                        lambda *args, **kwargs: discovery_calls.append(args) or cached)
    assert await context_preselection.discover_workflow_metadata(request, cache) == cached
    assert discovery_calls == []
    expire.assert_awaited_once_with("key", 7200)
    assert request._workflow_metadata_discovery_complete is True
    cache_read.side_effect = RuntimeError("cache unavailable")
    assert await context_preselection.discover_workflow_metadata(request, cache) == cached
    assert len(discovery_calls) == 1
    cache_write.assert_awaited_once()
    versioned_key.side_effect = RuntimeError("epoch cache unavailable")
    assert await context_preselection.discover_workflow_metadata(request, cache) == cached
    assert len(discovery_calls) == 2
    cache_write.assert_awaited_once()  # no write into an unknown cache generation


# contract-test: supporting surface=rest_api assertions=workflows.chat.metadata-warmup
def test_workflow_cache_epoch_scopes_personal_and_team_authoring():
    from backend.core.api.app.services.workflow_service import _hash_owner_id, _hash_team_id
    personal = context_preselection._workflow_metadata_epoch_key("alice", None)
    team = context_preselection._workflow_metadata_epoch_key("alice", "team-id")
    assert personal == f"workflow:discovery:epoch:v2:{_hash_owner_id('alice')}"
    assert team == f"workflow:discovery:epoch:v2:{_hash_team_id('team-id')}"
    assert team == context_preselection._workflow_metadata_epoch_key("bob", "team-id")
    assert personal != team


# contract-test: supporting surface=rest_api assertions=rules.selection.focus-aware,workflows.chat.relevance-discovery
@pytest.mark.asyncio
async def test_empty_selection_does_not_reload_unselected_private_catalogues(monkeypatch):
    rules = AsyncMock(side_effect=AssertionError("no Rule body was selected"))
    workflows = AsyncMock(side_effect=AssertionError("no Workflow was selected"))
    monkeypatch.setattr(context_preselection, "_rules", rules)
    monkeypatch.setattr(context_preselection, "_workflow_service", workflows)
    request = SimpleNamespace(user_id="alice", team_id=None)
    assert await context_preselection.reload_preselected_rules(request, None, None, [], []) == []
    assert await context_preselection.reload_preselected_workflows(request, None, []) == []
    rules.assert_not_awaited()
    workflows.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=rules.selection.focus-aware,workflows.chat.metadata-warmup
@pytest.mark.asyncio
async def test_failed_discovery_is_not_confirmed_empty(monkeypatch):
    request = SimpleNamespace(user_id="alice", team_id=None)
    monkeypatch.setattr(context_preselection, "_rules", AsyncMock(side_effect=RuntimeError("offline")))
    assert await context_preselection.discover_rule_metadata(request, None, None, []) == []
    assert request._rule_metadata_discovery_complete is False
    monkeypatch.setattr(context_preselection, "_workflow_service", AsyncMock(return_value=None))
    assert await context_preselection.discover_workflow_metadata(request, None) == []
    assert request._workflow_metadata_discovery_complete is False


# contract-test: supporting surface=rest_api assertions=workflows.chat.metadata-warmup
@pytest.mark.asyncio
async def test_workflow_cache_generation_change_forces_discovery_without_stale_publish(monkeypatch):
    from backend.apps.workflows.skills import saved_workflow_context
    request = SimpleNamespace(user_id="alice", team_id=None)
    monkeypatch.setattr(context_preselection, "_workflow_service", AsyncMock(return_value=(object(), "vault")))
    keys = iter(["before", "after", "after"])
    monkeypatch.setattr(context_preselection, "_versioned_workflow_metadata_key", AsyncMock(side_effect=lambda *args: next(keys)))
    monkeypatch.setattr(context_preselection, "_cached_workflow_metadata", AsyncMock(return_value=[{"workflow_id": "removed"}]))
    fresh = [{"workflow_id": "new", "current_version_id": "v2"}]
    monkeypatch.setattr(saved_workflow_context, "saved_workflow_metadata", lambda *args, **kwargs: fresh)
    save = AsyncMock()
    monkeypatch.setattr(context_preselection, "_save_workflow_metadata", save)
    assert await context_preselection.discover_workflow_metadata(request, object()) == fresh
    assert request._workflow_metadata_discovery_complete is True
    save.assert_not_awaited()
