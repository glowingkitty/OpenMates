"""Activity snapshots expose only authorized IDs and preserve client ancestry.

No inference, account, real cache or runtime services are required here.
The same snapshot drives web, Apple and terminal sidebar activity.
Failure is explicit, so clients cannot mistake unavailable state for idle chats.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from fastapi import HTTPException
from backend.tests.runtime_import_stubs import install_code_route_import_stubs
install_code_route_import_stubs()
from backend.core.api.app.routes.chats import get_chat_activity, sidebar_chat_metadata, SidebarChatMetadataRequest  # noqa: E402
from backend.core.api.app.services.directus.chat_methods import ChatMethods  # noqa: E402

# contract-test: supporting surface=rest_api assertions=chat-navigation.activity.global-running
@pytest.mark.asyncio
async def test_activity_contains_running_children_and_owned_ancestors_only():
    chat = SimpleNamespace(get_chat_activity_candidates=AsyncMock(return_value=[
        {"id": "trip"}, {"id": "hotels", "parent_id": "trip", "is_sub_chat": True},
        {"id": "idle"}, {"id": "orphan", "parent_id": "foreign"},
    ]))
    cache = SimpleNamespace(get_active_ai_tasks=AsyncMock(return_value={"hotels": "task-1", "orphan": "task-2", "foreign": "ignored"}))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(directus_service=SimpleNamespace(chat=chat), cache_service=cache)))
    result = await get_chat_activity(request, current_user=SimpleNamespace(id="user-1"))
    assert result["active_tasks"] == [{"chat_id": "hotels", "task_id": "task-1"}, {"chat_id": "orphan", "task_id": "task-2"}]
    assert {row["chat_id"] for row in result["chats"]} == {"trip", "hotels", "orphan"}
    assert next(row for row in result["chats"] if row["chat_id"] == "orphan")["parent_id"] is None
    cache.get_active_ai_tasks.assert_awaited_once_with(["trip", "hotels", "idle", "orphan"])

# contract-test: supporting surface=rest_api assertions=chat-navigation.activity.global-running
@pytest.mark.asyncio
async def test_activity_unavailability_is_not_an_empty_snapshot():
    chat = SimpleNamespace(get_chat_activity_candidates=AsyncMock(side_effect=RuntimeError("unavailable")))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(directus_service=SimpleNamespace(chat=chat, chat_key_wrapper=SimpleNamespace(get_wrappers_by_hashed_chat_ids_batch=AsyncMock(return_value=[]))))))
    with pytest.raises(HTTPException) as error:
        await get_chat_activity(request, current_user=SimpleNamespace(id="user-1"))
    assert error.value.status_code == 503

# contract-test: supporting surface=rest_api assertions=chat-navigation.activity.global-running,projects.lifecycle.encrypted-crud
@pytest.mark.asyncio
async def test_activity_candidate_query_preserves_team_and_personal_ownership():
    directus = SimpleNamespace(get_items=AsyncMock(return_value=[]))
    methods = ChatMethods(directus)
    await methods.get_chat_activity_candidates("user-1")
    params = directus.get_items.call_args.kwargs["params"]
    assert params["fields"] == "id,parent_id,is_sub_chat"
    assert params["filter[hashed_team_id][_null]"] is True
    assert "filter[hashed_user_id][_eq]" in params
    await methods.get_chat_activity_candidates("user-1", "team-one")
    params = directus.get_items.call_args.kwargs["params"]
    assert "filter[hashed_team_id][_eq]" in params
    assert "filter[hashed_user_id][_eq]" not in params

# contract-test: supporting surface=rest_api assertions=chat-navigation.projects.nested-readable,chat-navigation.activity.global-running
@pytest.mark.asyncio
async def test_sidebar_hydrates_ciphertext_without_transcripts_or_cross_scope_data():
    chat = SimpleNamespace(check_chat_ownership=AsyncMock(return_value=True), get_chat_metadata=AsyncMock(side_effect=[
        {"id": "owned", "encrypted_title": "cipher-title", "encrypted_chat_key": "cipher-key", "created_at": 1},
        {"id": "team-owned", "hashed_team_id": "team-hash"},
    ]))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(directus_service=SimpleNamespace(chat=chat, chat_key_wrapper=SimpleNamespace(get_wrappers_by_hashed_chat_ids_batch=AsyncMock(return_value=[]))))))
    result = await sidebar_chat_metadata(SidebarChatMetadataRequest(chat_ids=["owned", "owned", "team-owned"]), request, current_user=SimpleNamespace(id="user-1"))
    assert [row["id"] for row in result["chats"]] == ["owned"]
    assert result["chats"][0]["encrypted_title"] == "cipher-title"
    assert "messages" not in result["chats"][0]
    assert chat.check_chat_ownership.await_count == 2

# contract-test: supporting surface=rest_api assertions=chat-navigation.projects.nested-readable,chat-navigation.activity.global-running
@pytest.mark.asyncio
async def test_sidebar_team_metadata_uses_only_the_current_team_key_wrapper():
    from hashlib import sha256
    team_hash = sha256(b'team-one').hexdigest()
    wrappers = SimpleNamespace(get_wrappers_by_hashed_chat_ids_batch=AsyncMock(return_value=[{
        'hashed_chat_id': sha256(b'owned').hexdigest(), 'key_type': 'team', 'encrypted_chat_key': 'team-wrapped',
    }]))
    directus = SimpleNamespace(chat=SimpleNamespace(get_chat_metadata=AsyncMock(return_value={
        'id': 'owned', 'hashed_team_id': team_hash, 'encrypted_chat_key': 'legacy-master-wrapped',
    })), team=SimpleNamespace(require_team_role=AsyncMock()), chat_key_wrapper=wrappers)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(directus_service=directus)))
    result = await sidebar_chat_metadata(SidebarChatMetadataRequest(chat_ids=['owned']), request, team_id='team-one', current_user=SimpleNamespace(id='user-1'))
    assert result['chats'][0]['encrypted_chat_key'] == 'team-wrapped'
    assert wrappers.get_wrappers_by_hashed_chat_ids_batch.call_args.kwargs == {'hashed_team_id': team_hash}
