"""Cursor and key-scope checks for ciphertext-only public Plan/Task pages."""
import hashlib

import pytest

from backend.core.api.app.services.shared_plan_task_window import (
    shared_plan_task_by_id, shared_plan_task_key_window, shared_plan_task_window,
)


CHAT = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class Directus:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    async def get_items(self, collection, *, params, **kwargs):
        assert kwargs == {"admin_required": True, "no_cache": True, "raise_on_error": True}
        self.calls.append((collection, params))
        rows = list(self.rows.get(collection, []))
        def matches(row, conditions):
            for field, predicate in conditions.items():
                if field == "_or":
                    if not any(matches(row, term) for term in predicate):
                        return False
                elif field == "_and":
                    if not all(matches(row, term) for term in predicate):
                        return False
                else:
                    value = row.get(field)
                    for operation, bound in predicate.items():
                        if operation == "_eq" and value != bound:
                            return False
                        if operation == "_in" and value not in bound:
                            return False
                        if operation == "_lt" and not value < bound:
                            return False
                        if operation == "_gt" and not value > bound:
                            return False
            return True
        rows = [row for row in rows if matches(row, params["filter"])]
        sort = params.get("sort")
        if sort:
            for field in reversed(sort if isinstance(sort, list) else [sort]):
                descending = field.startswith("-")
                rows.sort(key=lambda row: row[field.lstrip("-")], reverse=descending)
        return rows[:params["limit"]]


def plan(index, *, chat=CHAT, title="cipher"):
    plan_id = f"plan-{index:03}"
    return {"plan_id": plan_id, "primary_chat_id": chat,
            "hashed_primary_chat_id": digest(chat), "updated_at": index,
            "status": "active", "encrypted_title": title}


def wrapper(index, *, chat=CHAT, key_type="chat"):
    return {"id": f"wrapper-{index:03}", "hashed_plan_id": digest(f"plan-{index:03}"),
            "hashed_chat_id": digest(chat), "key_type": key_type,
            "encrypted_plan_key": "wrapped-cipher"}


# contract-test: direct surface=rest_api assertions=storage.cold.discoverable-bounded,storage.cold.shared-team-authorized
@pytest.mark.asyncio
async def test_plan_pages_use_stable_cursor_and_chat_only_wrappers():
    directus = Directus({"user_plans": [*(plan(i) for i in range(1, 24)), plan(99, chat=OTHER)],
                        "user_plan_key_wrappers": [*(wrapper(i) for i in range(1, 24)),
                                                   wrapper(23, chat=OTHER), wrapper(22, key_type="master")]})
    first = await shared_plan_task_window(directus, chat_id=CHAT, kind="plans")
    assert [item["plan_id"] for item in first["items"]] == [f"plan-{i:03}" for i in range(4, 24)]
    assert first["has_more_before"] is True
    assert first["start_cursor"] == {"timestamp": 4, "id": "plan-004"}
    assert len(first["key_wrappers"]) == 20
    assert all(row["key_type"] == "chat" and row["hashed_chat_id"] == digest(CHAT)
               for row in first["key_wrappers"])
    second = await shared_plan_task_window(directus, chat_id=CHAT, kind="plans",
                                           before_timestamp=4, before_id="plan-004")
    assert [item["plan_id"] for item in second["items"]] == ["plan-001", "plan-002", "plan-003"]
    assert second["has_more_before"] is False


# contract-test: direct surface=rest_api assertions=storage.cold.discoverable-bounded,storage.cold.shared-team-authorized
@pytest.mark.asyncio
async def test_oversized_row_requires_exact_read_and_key_scope_is_revalidated():
    directus = Directus({"user_plans": [plan(1, title="x" * (129 * 1024))],
                        "user_plan_key_wrappers": [wrapper(1)]})
    first = await shared_plan_task_window(directus, chat_id=CHAT, kind="plans")
    assert first["items"] == [] and first["oversized_id"] == "plan-001"
    assert first["has_more_before"] is True and first["start_cursor"] is None
    exact = await shared_plan_task_by_id(directus, chat_id=CHAT, kind="plans", record_id="plan-001")
    assert exact["item"]["plan_id"] == "plan-001"
    assert len(exact["key_wrappers"]) == 1
    with pytest.raises(ValueError, match="outside this chat"):
        await shared_plan_task_key_window(directus, chat_id=OTHER, kind="plans", item_ids=["plan-001"])
    with pytest.raises(ValueError, match="Incomplete"):
        await shared_plan_task_window(directus, chat_id=CHAT, kind="plans", before_timestamp=1)
