"""Stable shared sidecar/highlight/subchat pages with explicit oversized reads."""

import pytest

from backend.core.api.app.services.shared_auxiliary_window import (
    shared_auxiliary_by_id, shared_auxiliary_window,
)


class FakeDirectus:
    def __init__(self, rows):
        self.rows = rows
        self.limits = []

    async def get_items(self, collection, params, **_kwargs):
        self.limits.append(params["limit"])
        scope = params["filter"]
        scope_field = "parent_id" if collection == "chats" else "chat_id"
        selected = [row for row in self.rows if row.get(scope_field) == scope[scope_field]["_eq"]]
        if "id" in scope:
            selected = [row for row in selected if row["id"] == scope["id"]["_eq"]]
        if "_or" in scope:
            timestamp_field = "updated_at" if collection in {"code_run_outputs", "notebook_run_outputs"} else "created_at"
            boundary = scope["_or"][0][timestamp_field]["_lt"]
            boundary_id = scope["_or"][1]["_and"][1]["id"]["_lt"]
            selected = [row for row in selected if (row[timestamp_field], row["id"]) < (boundary, boundary_id)]
        timestamp_field = "updated_at" if collection in {"code_run_outputs", "notebook_run_outputs"} else "created_at"
        return sorted(selected, key=lambda row: (row[timestamp_field], row["id"]), reverse=True)[:params["limit"]]


# contract-test: direct surface=rest_api assertions=storage.cold.discoverable-bounded,storage.cold.shared-team-authorized
@pytest.mark.anyio
async def test_shared_auxiliary_pages_advance_with_compound_cursor():
    rows = [{"id": f"row-{index:03}", "chat_id": "shared", "created_at": index // 2,
             "encrypted_payload": "cipher"} for index in range(25)]
    directus = FakeDirectus(rows)
    first = await shared_auxiliary_window(directus, chat_id="shared", kind="message_highlights")
    assert len(first["items"]) == 20
    assert first["has_more_before"] is True
    second = await shared_auxiliary_window(
        directus, chat_id="shared", kind="message_highlights",
        before_timestamp=first["start_cursor"]["timestamp"], before_id=first["start_cursor"]["id"],
    )
    assert len(second["items"]) == 5
    assert set(row["id"] for row in first["items"]).isdisjoint(row["id"] for row in second["items"])
    assert directus.limits == [21, 21]


# contract-test: direct surface=rest_api assertions=storage.cold.discoverable-bounded,storage.cold.shared-team-authorized
@pytest.mark.anyio
async def test_shared_large_sidecar_is_selected_exactly():
    rows = [{"id": "large", "chat_id": "shared", "updated_at": 10,
             "encrypted_payload": "x" * 150_000}]
    directus = FakeDirectus(rows)
    page = await shared_auxiliary_window(directus, chat_id="shared", kind="code_run_outputs")
    assert page["items"] == []
    assert page["oversized_id"] == "large"
    assert page["has_more_before"] is True
    exact = await shared_auxiliary_by_id(directus, chat_id="shared", kind="code_run_outputs", record_id="large")
    assert exact and exact["id"] == "large"
    assert await shared_auxiliary_by_id(directus, chat_id="other", kind="code_run_outputs", record_id="large") is None


# contract-test: direct surface=rest_api assertions=storage.cold.discoverable-bounded,storage.cold.shared-team-authorized
@pytest.mark.anyio
async def test_shared_subchat_field_fallback_preserves_directus_failures():
    class UnavailableDirectus:
        async def get_items(self, collection, *, params, raise_on_error, return_none_on_403, **_kwargs):
            assert raise_on_error is True
            assert return_none_on_403 is True
            raise RuntimeError("Directus unavailable")

    directus = UnavailableDirectus()
    with pytest.raises(RuntimeError, match="Directus unavailable"):
        await shared_auxiliary_window(directus, chat_id="shared", kind="sub_chats")
    with pytest.raises(RuntimeError, match="Directus unavailable"):
        await shared_auxiliary_by_id(directus, chat_id="shared", kind="sub_chats", record_id="child-1")
