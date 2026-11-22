# backend/tests/test_carried_reply_references.py
#
# A continuation rewrites the assistant reply from empty; the earlier streams'
# cards are re-emitted first (ids only), so earlier steps stay visible.

import asyncio
import json

from backend.apps.ai.processing.carried_reply_references import (
    MAX_CARRIED_REFERENCES,
    extract_reply_references,
    load_reply_references,
    reference_block,
    reference_embed_id,
    reply_references_key,
    store_reply_references,
)


class FakeCache:
    def __init__(self):
        self.values = {}
        self.ttls = {}

    async def set(self, key, value, ttl=None):
        self.values[key] = json.loads(json.dumps(value))
        self.ttls[key] = ttl
        return True

    async def get(self, key):
        return self.values.get(key)


def _fence(payload):
    return f"```json\n{json.dumps(payload)}\n```"


RUN = {"type": "app_skill_use", "embed_id": "run-1", "app_id": "code", "skill_id": "run", "query": "secret words"}
READ = {"type": "app_skill_use", "embed_id": "read-1", "app_id": "projects", "skill_id": "read"}


# contract-test: supporting surface=rest_api assertions=projects.agentic.earlier-steps-stay
def test_extracts_ids_only_in_order_and_deduplicated():
    text = f"Starting.\n\n{_fence(READ)}\n\nThen I ran it.\n\n{_fence(RUN)}\n\n{_fence(READ)}\n\n```json\nnot json\n```"
    references = extract_reply_references(text)
    assert [r["embed_id"] for r in references] == ["read-1", "run-1"]
    # Only the reference ids cross the boundary, never user-visible text such as a query.
    assert references[1] == {"type": "app_skill_use", "embed_id": "run-1", "app_id": "code", "skill_id": "run"}


# contract-test: supporting surface=rest_api assertions=projects.agentic.earlier-steps-stay
def test_refuses_references_without_ids_or_with_unsafe_values():
    text = "\n".join([
        _fence({"type": "app_skill_use"}),
        _fence({"embed_id": "x"}),
        _fence({"type": "code", "embed_id": "has spaces and\nnewline"}),
        _fence({"type": "code", "embed_id": "ok-1", "app_id": 7}),
    ])
    assert extract_reply_references(text) == [{"type": "code", "embed_id": "ok-1"}]


# contract-test: supporting surface=rest_api assertions=projects.agentic.earlier-steps-stay
def test_store_then_load_round_trip_with_short_ttl():
    cache = FakeCache()
    ids = {"user_id": "u1", "chat_id": "c1", "message_id": "m1"}
    asyncio.run(store_reply_references(cache, text=f"{_fence(RUN)}\nDone.", **ids))
    key = reply_references_key("u1", "c1", "m1")
    assert cache.ttls[key] and cache.ttls[key] <= 2 * 60 * 60
    assert asyncio.run(load_reply_references(cache, **ids)) == [
        {"type": "app_skill_use", "embed_id": "run-1", "app_id": "code", "skill_id": "run"}]
    # Another reply of the same chat starts empty.
    assert asyncio.run(load_reply_references(cache, user_id="u1", chat_id="c1", message_id="m2")) == []


# contract-test: supporting surface=rest_api assertions=projects.agentic.earlier-steps-stay
def test_load_cleans_tampered_cache_entries_and_caps_the_list():
    cache = FakeCache()
    key = reply_references_key("u1", "c1", "m1")
    cache.values[key] = [{"type": "code", "embed_id": f"e{i}", "content": "x"} for i in range(MAX_CARRIED_REFERENCES + 5)]
    cache.values[key].insert(0, "not a dict")
    loaded = asyncio.run(load_reply_references(cache, user_id="u1", chat_id="c1", message_id="m1"))
    assert len(loaded) == MAX_CARRIED_REFERENCES
    assert all(set(r) == {"type", "embed_id"} for r in loaded)


# contract-test: supporting surface=rest_api assertions=projects.agentic.earlier-steps-stay
def test_reference_block_round_trips_through_extraction():
    block = reference_block({"type": "app_skill_use", "embed_id": "run-1", "app_id": "code", "skill_id": "run"})
    assert extract_reply_references(block)[0]["embed_id"] == "run-1"
    assert reference_embed_id(json.dumps(RUN)) == "run-1"
    assert reference_embed_id("not json") is None
