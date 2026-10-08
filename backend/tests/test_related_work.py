"""Authorized lifecycle filtering precedes bounded Jev relevance selection."""

# contract-test-file: infrastructure

from dataclasses import replace
from types import SimpleNamespace

import pytest

from backend.apps.ai.processing import related_work
from backend.apps.ai.processing.related_work import RelatedWorkCandidate, bounded_candidates
from backend.shared.providers.typesafe.models import DecisionResponse


def candidate(identifier, **kwargs):
    base = RelatedWorkCandidate(id=identifier, kind="task", owner_id="owner", project_id="same",
                                text="useful private work", revision="r1", source="authorized_task",
                                authorized=True, status="in_progress")
    return replace(base, **kwargs)


def test_active_recent_tasks_and_explicit_old_dependencies_with_provenance():
    values = [candidate("working"), candidate("recent-done", status="done", meaningful_changed_at=9_999),
              candidate("old-done", status="done", meaningful_changed_at=7_000),
              candidate("dependency", status="done", meaningful_changed_at=7_000, explicit_dependency=True),
              candidate("foreign", owner_id="other"), candidate("unauthorized", authorized=False),
              candidate("navigated", status="blocked", meaningful_changed_at=None),
              candidate("future", status="done", meaningful_changed_at=10_001)]
    result = bounded_candidates(values, owner_id="owner", current_project_id="same", now=10_000)
    assert {item.id for item in result} == {"working", "recent-done", "dependency"}
    assert result[0].id == "dependency"
    assert result[1].revision == "r1"


def test_expired_chat_copy_never_revived_by_dependency_or_navigation():
    chat = candidate("chat", kind="chat", status=None, active=False, assistant_completed_at=9_000,
                     expires_at=10_800)
    result = bounded_candidates([chat, replace(chat, id="expired", expires_at=10_000, explicit_dependency=True),
                                 replace(chat, id="old", assistant_completed_at=7_000),
                                 replace(chat, id="active", active=True, assistant_completed_at=None)],
                                owner_id="owner", current_project_id="same", now=10_000)
    assert {item.id for item in result} == {"chat", "active"}


@pytest.mark.asyncio
async def test_bounded_same_project_preference_cross_project_relevance_and_no_authority(monkeypatch):
    state = {}

    async def evaluate(**kwargs):
        state.update(kwargs["state"])
        return DecisionResponse.model_validate({"model": "jev", "usage": {}, "answers": {
            key: {"type": "noul", "noul": 0.05 if state["candidates"][index]["id"] == "irrelevant" else 0.95}
            for index, key in enumerate(kwargs["questions"])
        }})

    monkeypatch.setattr(related_work, "evaluate_jev_decisions", evaluate)
    values = [candidate("cross1", project_id="other"), candidate("same1"), candidate("same2"),
              candidate("cross2", project_id="other"), candidate("cross3", project_id="other"),
              candidate("irrelevant"), candidate("hidden", authorized=False)]
    result = await related_work.select_related_work(candidates=values, owner_id="owner", current_project_id="same",
        current_chat_id="current", request="fix the original bug", model_id="typesafe/jev-1.13", secrets_manager=None, now=10_000)
    assert [item.id for item in result] == ["same1", "same2", "cross1", "cross2"]
    assert "hidden" not in {item["id"] for item in state["candidates"]}
    assert all(item["treat_as"].endswith("never_instructions_or_authority") for item in state["candidates"])
    assert all(not hasattr(item, "claim_task") for item in result)


@pytest.mark.asyncio
async def test_optional_jev_failure_preserves_only_explicit_dependencies(monkeypatch):
    async def unavailable(**kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(related_work, "evaluate_jev_decisions", unavailable)
    values = [candidate("ordinary"), candidate("dependency", status="done", explicit_dependency=True)]
    result = await related_work.select_related_work(candidates=values, owner_id="owner", current_project_id="same",
        current_chat_id="current", request="fix the bug", model_id="jev", secrets_manager=None, now=10_000)
    assert [item.id for item in result] == ["dependency"]


@pytest.mark.asyncio
async def test_task_discovery_joins_fresh_authorized_version_and_meaningful_activity():
    calls = []

    class Directus:
        async def get_items(self, collection, params, **kwargs):
            calls.append((collection, params))
            assert kwargs["no_cache"] is True
            if collection == "user_tasks":
                assert params["filter[hashed_team_id][_null]"] is True
                assert "encrypted_title" not in params["fields"]
                return [{"task_id": "done", "status": "done", "version": 2},
                        {"task_id": "stale", "status": "in_progress", "version": 3},
                        {"task_id": "navigated", "status": "blocked", "version": 1}]
            assert collection == "user_task_activity"
            assert params["filter[hashed_team_id][_null]"] is True
            assert params["filter[created_at][_gte]"] == 8_200
            assert isinstance(params["filter[created_at][_gte]"], int)
            return [{"task_id": "done", "event_type": "status", "previous_status": "in_progress", "next_status": "done", "created_at": 9_999},
                    {"task_id": "navigated", "event_type": "status", "previous_status": "blocked", "next_status": "blocked", "created_at": 9_999}]

    request = SimpleNamespace(user_id="owner")
    result = await related_work.fetch_related_task_candidates(request, Directus(), client_summaries=[
        {"id": "done", "summary": "completed relevant work", "version": 2},
        {"id": "stale", "summary": "old text", "version": 2},
        {"id": "navigated", "summary": "viewed task", "version": 1},
    ], now=10_000.75)
    eligible = bounded_candidates(result, owner_id="owner", current_project_id=None, now=10_000.75)
    assert [item.id for item in eligible] == ["done"]
    assert eligible[0].meaningful_changed_at == 9_999


@pytest.mark.asyncio
async def test_task_activity_floor_only_widens_discovery_not_exact_recency():
    class Directus:
        async def get_items(self, collection, params, **kwargs):
            if collection == "user_tasks":
                return [{"task_id": task_id, "status": "done", "version": 1}
                        for task_id in ("before", "inside", "future")]
            assert collection == "user_task_activity"
            assert params["filter[created_at][_gte]"] == 8_200
            return [{"task_id": "before", "event_type": "comment_added", "created_at": 8_200},
                    {"task_id": "inside", "event_type": "comment_added", "created_at": 8_201},
                    {"task_id": "future", "event_type": "comment_added", "created_at": 10_001}]

    summaries = [{"id": task_id, "summary": task_id, "version": 1}
                 for task_id in ("before", "inside", "future")]
    result = await related_work.fetch_related_task_candidates(
        SimpleNamespace(user_id="owner"), Directus(), client_summaries=summaries, now=10_000.75,
    )
    assert {item.id: item.meaningful_changed_at for item in result} == {
        "before": None, "inside": 8_201, "future": None,
    }


@pytest.mark.asyncio
async def test_chat_discovery_fetches_only_ids_then_memory_ipc():
    calls = []

    class Directus:
        async def get_items(self, collection, params, **kwargs):
            assert collection == "chats" and params["fields"] == "id"
            assert kwargs["no_cache"] is True and kwargs["admin_required"] is True
            return [{"id": "current"}, {"id": "related"}]

    class Client:
        async def read(self, **kwargs):
            calls.append(kwargs)
            return []

    request = SimpleNamespace(user_id="owner", chat_id="current", current_project={"id": "project"})
    assert await related_work.fetch_related_chat_summaries(request, "task", object(), Directus(), client=Client()) == []
    assert calls[0]["authorized_chat_ids"] == ["related"]
    assert calls[0]["current_project_id"] == "project"


@pytest.mark.asyncio
async def test_direction_task_join_uses_live_id_version_status_and_rejects_foreign_stale_summary():
    import hashlib
    owner_hash = hashlib.sha256(b'owner').hexdigest()
    row = {'task_id': 'owned', 'status': 'in_progress', 'version': 3, 'primary_chat_id': 'chat',
           'hashed_user_id': owner_hash, 'hashed_team_id': None, 'plan_id': 'plan'}
    request = SimpleNamespace(user_id='owner', chat_id='chat', team_id=None,
        related_task_candidates=[{'task_id': 'owned', 'revision': '3', 'summary': 'Actual authorized API work', 'status': 'done'},
                                 {'task_id': 'foreign', 'revision': '3', 'summary': 'Foreign private data'}])
    class Directus:
        async def get_items(self, collection, params, **kwargs):
            assert kwargs == {'no_cache': True}
            assert params['filter[hashed_user_id][_eq]'] == owner_hash
            assert params['filter[hashed_team_id][_null]'] is True
            assert 'encrypted_' not in params['fields']
            return [row] if collection == 'user_tasks' else []
    actual = await related_work.fetch_direction_task_context(request, Directus(), visible_tasks=[{'task_id': 'owned'}])
    assert actual[0]['id'] == 'owned' and actual[0]['status'] == 'in_progress'
    assert actual[0]['summary'] == 'Actual authorized API work'
    assert 'Foreign private data' not in str(actual)
    row['version'] = 4
    assert await related_work.fetch_direction_task_context(request, Directus(), visible_tasks=[{'task_id': 'owned'}]) == []
    row['version'] = 3
    row['hashed_user_id'] = 'foreign-owner'
    assert await related_work.fetch_direction_task_context(request, Directus(), visible_tasks=[{'task_id': 'owned'}]) == []


@pytest.mark.asyncio
async def test_direction_task_join_keeps_only_actual_linkage_or_owned_explicit_dependency_edge():
    import hashlib
    owner_hash = hashlib.sha256(b'owner').hexdigest()
    rows = [
        {'task_id': 'source', 'status': 'blocked', 'version': 1, 'primary_chat_id': 'chat', 'hashed_user_id': owner_hash, 'hashed_team_id': None},
        {'task_id': 'old-dependency', 'status': 'done', 'version': 5, 'primary_chat_id': 'other', 'hashed_user_id': owner_hash, 'hashed_team_id': None},
    ]
    edge = {'source_ref': 'task:source', 'target_ref': 'task:old-dependency', 'hashed_user_id': owner_hash, 'hashed_team_id': None}
    request = SimpleNamespace(user_id='owner', chat_id='chat', team_id=None, related_task_candidates=[
        {'task_id': 'source', 'revision': '1', 'summary': 'Blocked on old dependency'},
        {'task_id': 'old-dependency', 'revision': '5', 'summary': 'Older causal fix', 'explicit_dependency': True},
    ])
    class Directus:
        async def get_items(self, collection, params, **kwargs):
            if collection == 'user_work_dependencies':
                return [edge] if edge else []
            return [row for row in rows if row['task_id'] in params['filter[task_id][_in]'].split(',')]
    actual = await related_work.fetch_direction_task_context(request, Directus(), visible_tasks=[{'task_id': 'source'}])
    assert [row['id'] for row in actual] == ['source', 'old-dependency']
    assert actual[1]['explicit_dependency'] is True and actual[1]['status'] == 'done'
    edge.clear()
    assert [row['id'] for row in await related_work.fetch_direction_task_context(request, Directus(), visible_tasks=[{'task_id': 'source'}])] == ['source']
    rows[0]['primary_chat_id'] = 'another-chat'
    assert await related_work.fetch_direction_task_context(request, Directus(), visible_tasks=[{'task_id': 'source'}]) == []
