"""Chat search grants from approved Memory references."""
import asyncio

from backend.shared.python_utils.memory_chat_grants import (
    MAX_APPROVED_SEARCH_CHATS, approved_search_chat_ids, is_chat_searchable,
)

APPROVED = [{"app_id": "memory", "item_key": "m1", "content": "---\ntitle: T\n---\nbody"}]


def _grant(raw, entries=APPROVED, requested=("memory:m1",), owned=None):
    async def is_owned(chat_id):
        return owned is None or chat_id in owned
    return asyncio.run(approved_search_chat_ids(
        raw, entries=entries, requested_keys=requested, current_chat_id="current", is_owned=is_owned))


# contract-test: direct surface=rest_api assertions=app-memories.references.embeds-and-chats
def test_approved_response_for_requested_memory_grants_only_listed_owned_chats():
    assert _grant(["a", "b", "stranger"], owned={"a", "b"}) == ["a", "b"]
    assert is_chat_searchable(["a", "b"], "a")
    assert not is_chat_searchable(["a", "b"], "other")  # no other chat becomes searchable
    assert not is_chat_searchable(None, "a")


# contract-test: direct surface=rest_api assertions=app-memories.references.embeds-and-chats
def test_response_without_requested_memory_or_rejection_grants_nothing():
    assert _grant(["a"], entries=[]) == []
    assert _grant(["a"], entries=[{"app_id": "memory", "item_key": "unrequested", "content": "x"}]) == []
    assert _grant(["a"], entries=[{"app_id": "code", "item_key": "m1", "content": "x"}]) == []
    assert _grant(["a"], requested=("memory-other",)) == []


# contract-test: direct surface=rest_api assertions=app-memories.references.embeds-and-chats
def test_grant_is_capped_deduplicated_and_excludes_current_chat():
    raw = ["current", "a", "a", 7, ""] + [f"c{i}" for i in range(30)]
    granted = _grant(raw)
    assert len(granted) == MAX_APPROVED_SEARCH_CHATS
    assert "current" not in granted and granted.count("a") == 1
    assert _grant("not-a-list") == []
