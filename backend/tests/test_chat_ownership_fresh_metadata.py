"""A same-request Directus row may satisfy chat ownership without a second read."""

import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.services.directus.chat_methods import ChatMethods


CHAT_ID = "11111111-1111-4111-8111-111111111111"
USER_ID = "owner-1"
OWNER_HASH = hashlib.sha256(USER_ID.encode()).hexdigest()


# contract-test: supporting surface=rest_api assertions=chats.message.identity-idempotent
@pytest.mark.asyncio
async def test_metadata_source_is_uncached_directus_row_with_identity_and_owner_fields():
    get_items = AsyncMock(return_value=[{
        "id": CHAT_ID, "hashed_user_id": OWNER_HASH, "chat_visibility": None,
    }])
    methods = ChatMethods(SimpleNamespace(get_items=get_items))
    row = await methods.get_chat_metadata(CHAT_ID)
    assert row == {"id": CHAT_ID, "hashed_user_id": OWNER_HASH, "chat_visibility": None}
    args, kwargs = get_items.await_args
    assert args == ("chats",)
    assert kwargs["no_cache"] is True
    assert kwargs["params"]["filter[id][_eq]"] == CHAT_ID
    assert {"id", "hashed_user_id", "chat_visibility"} <= set(kwargs["params"]["fields"].split(","))


def chat_methods():
    cache = SimpleNamespace(
        check_chat_exists_for_user=AsyncMock(return_value=True),
        is_user_cache_primed=AsyncMock(return_value=True),
    )
    methods = ChatMethods(SimpleNamespace(cache=cache))
    methods.get_chat_metadata = AsyncMock(return_value={"id": CHAT_ID, "hashed_user_id": OWNER_HASH})
    return methods, cache


# contract-test: supporting surface=rest_api assertions=chats.message.identity-idempotent
@pytest.mark.asyncio
async def test_fresh_same_chat_row_authorizes_owner_without_second_read():
    methods, cache = chat_methods()
    assert await methods.check_chat_ownership(
        CHAT_ID, USER_ID,
        authoritative_metadata={"id": CHAT_ID, "hashed_user_id": OWNER_HASH},
    )
    methods.get_chat_metadata.assert_not_awaited()
    cache.check_chat_exists_for_user.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=chats.message.identity-idempotent
@pytest.mark.asyncio
@pytest.mark.parametrize("row", [
    {"id": "22222222-2222-4222-8222-222222222222", "hashed_user_id": OWNER_HASH},
    {"id": CHAT_ID, "hashed_user_id": hashlib.sha256(b"other-owner").hexdigest()},
    {"id": CHAT_ID},
    {"id": CHAT_ID, "hashed_user_id": OWNER_HASH, "chat_visibility": "direct"},
])
async def test_fresh_row_fails_closed_for_wrong_chat_owner_or_direct_chat(row):
    methods, cache = chat_methods()
    assert not await methods.check_chat_ownership(CHAT_ID, USER_ID, authoritative_metadata=row)
    methods.get_chat_metadata.assert_not_awaited()
    cache.check_chat_exists_for_user.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=chats.message.identity-idempotent
@pytest.mark.asyncio
async def test_callers_without_fresh_row_keep_authoritative_fetch():
    methods, _cache = chat_methods()
    assert await methods.check_chat_ownership(CHAT_ID, USER_ID)
    methods.get_chat_metadata.assert_awaited_once_with(CHAT_ID, admin_required=True)
