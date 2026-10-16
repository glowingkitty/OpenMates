"""Legacy complete responses cannot truncate at Directus's default page size."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from backend.core.api.app.services.scoped_directus_pagination import read_complete_scoped_records
from backend.core.api.app.services.directus.chat_methods import ChatMethods
from backend.core.api.app.services.directus.embed_methods import EmbedMethods


# contract-test: supporting surface=rest_api assertions=storage.export.persisted-bounded-complete
@pytest.mark.asyncio
async def test_complete_collection_crosses_default_limit_without_unbounded_sql_reads():
    rows = [{"id": f"row-{number:04d}", "encrypted_content": f"cipher-{number}"} for number in range(121)]
    calls = []

    async def read(_collection, *, params, **options):
        calls.append((params, options))
        assert params["filter[hashed_chat_id][_eq]"] == "authorized-chat-hash"
        excluded = params.get("filter[id][_nin]", [])
        assert "filter[id][_gt]" not in params
        return [row for row in rows if row["id"] not in excluded][:params["limit"]]

    actual = await read_complete_scoped_records(
        SimpleNamespace(get_items=read), "embeds",
        params={"filter[hashed_chat_id][_eq]": "authorized-chat-hash", "fields": "id,encrypted_content"},
        admin_required=True,
    )
    assert actual == rows
    assert len(calls) == 8
    assert all(params["limit"] == 20 and options["admin_required"] and options["raise_on_error"]
               for params, options in calls)


# contract-test: supporting surface=rest_api assertions=storage.export.persisted-bounded-complete
@pytest.mark.asyncio
async def test_partial_read_failure_is_not_a_successful_complete_collection():
    first_page = [{"id": f"row-{number:04d}"} for number in range(20)]
    directus = SimpleNamespace(get_items=AsyncMock(side_effect=[first_page, None]))
    with pytest.raises(RuntimeError, match="page unavailable"):
        await read_complete_scoped_records(directus, "embed_keys", params={"filter[key_type][_eq]": "chat"})


# contract-test: supporting surface=rest_api assertions=storage.export.persisted-bounded-complete
@pytest.mark.asyncio
async def test_repeated_provider_page_fails_instead_of_repeating_or_looping():
    page = [{"id": f"row-{number:04d}"} for number in range(20)]
    directus = SimpleNamespace(get_items=AsyncMock(return_value=page))
    with pytest.raises(RuntimeError, match="cursor did not advance"):
        await read_complete_scoped_records(directus, "embed_keys", params={"filter[key_type][_eq]": "chat"})
    assert directus.get_items.await_count == 2


# contract-test: supporting surface=rest_api assertions=storage.export.persisted-bounded-complete
@pytest.mark.asyncio
async def test_uuid_collection_121_rows_survives_deletion_of_preceding_records():
    records = [{"id": str(UUID(int=index + 1)), "encrypted_content": f"cipher-{index}"} for index in range(121)]
    live_rows = list(records)
    calls = []

    async def read(_collection, *, params, **options):
        assert params["filter[hashed_user_id][_eq]"] == "authorized-owner"
        assert params["limit"] == 20 and params["sort"] == "id"
        assert "offset" not in params and "filter[id][_gt]" not in params
        assert options["no_cache"] and options["raise_on_error"] and options["admin_required"]
        if len(calls) == 1:
            del live_rows[:3]
        excluded = params.get("filter[id][_nin]", [])
        calls.append(list(excluded))
        return [row for row in live_rows if row["id"] not in excluded][:20]

    result = await read_complete_scoped_records(
        SimpleNamespace(get_items=read), "embed_keys",
        params={"filter[hashed_user_id][_eq]": "authorized-owner", "fields": "id,encrypted_content"},
        admin_required=True,
    )
    assert result == records
    assert len(calls) == 8 and len(calls[-1]) == 121


# contract-test: supporting surface=rest_api assertions=storage.export.persisted-bounded-complete
@pytest.mark.asyncio
@pytest.mark.parametrize("bad_rows", [[{"id": ""}], [{"id": " "}], [{"id": "one,two"}], [{"id": 1}], [{"id": "b"}, {"id": "a"}], [{"id": "a"}, {"id": "a"}]])
async def test_invalid_identity_and_out_of_order_rows_cannot_complete(bad_rows):
    directus = SimpleNamespace(get_items=AsyncMock(return_value=bad_rows))
    with pytest.raises(RuntimeError):
        await read_complete_scoped_records(directus, "embed_keys", params={"filter[owner][_eq]": "authorized-owner"})


# contract-test: supporting surface=rest_api assertions=storage.export.persisted-bounded-complete
@pytest.mark.asyncio
async def test_short_page_requires_exact_empty_terminal_read():
    directus = SimpleNamespace(get_items=AsyncMock(side_effect=[[{"id": "one"}], [{"id": "two"}]]))
    with pytest.raises(RuntimeError, match="changed at terminal"):
        await read_complete_scoped_records(directus, "embed_keys", params={"filter[owner][_eq]": "authorized-owner"})


# contract-test: supporting surface=rest_api assertions=storage.export.persisted-bounded-complete
@pytest.mark.asyncio
async def test_cursor_request_size_limit_never_returns_partial_success(monkeypatch):
    monkeypatch.setattr("backend.core.api.app.services.scoped_directus_pagination.MAX_COMPLETE_CURSOR_BYTES", 5)
    directus = SimpleNamespace(get_items=AsyncMock(return_value=[{"id": "uuid-like-identity"}]))
    with pytest.raises(RuntimeError, match="bounded request size"):
        await read_complete_scoped_records(directus, "embed_keys", params={"filter[owner][_eq]": "authorized-owner"})


# contract-test: supporting surface=rest_api assertions=storage.export.persisted-bounded-complete
@pytest.mark.asyncio
async def test_nested_original_owner_scope_is_preserved_in_exclusion_pages():
    records = [{"id": str(UUID(int=index + 1))} for index in range(21)]
    original = {"filter": {"_or": [{"owner": {"_eq": "authorized-owner"}}, {"team": {"_eq": "authorized-team"}}]}}
    calls = []

    async def read(_collection, *, params, **options):
        calls.append(params)
        if len(calls) == 1:
            assert params["filter"] == original["filter"]
            return records[:20]
        scope, exclusion = params["filter"]["_and"]
        assert scope == original["filter"]
        if len(calls) == 2:
            assert exclusion == {"id": {"_nin": [row["id"] for row in records[:20]]}}
            return records[20:]
        assert exclusion == {"id": {"_nin": [row["id"] for row in records]}}
        return []

    assert await read_complete_scoped_records(SimpleNamespace(get_items=read), "embed_keys", params=original) == records
    assert "_and" not in original["filter"]


# contract-test: supporting surface=rest_api assertions=storage.export.persisted-bounded-complete,storage.cold.discoverable-bounded
@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, RuntimeError("Database read failed")])
async def test_hot_message_read_failure_cannot_be_reported_as_empty_history(failure, monkeypatch):
    monkeypatch.setenv("INTERNAL_API_SHARED_TOKEN", "disposable-unit-token")

    async def fail_read(method, url, **kwargs):
        assert method == "POST" and url.endswith("/chat-archive-transaction")
        assert kwargs["json"]["operation"] == "hot_message_window"
        if isinstance(failure, Exception):
            raise failure
        return SimpleNamespace(status_code=200, json=lambda: {"data": None})

    methods = ChatMethods(SimpleNamespace(base_url="http://cms:8055", _make_api_request=fail_read))
    with pytest.raises(RuntimeError):
        await methods.get_message_window_for_chat(
            "authorized-chat", direction="after", after_timestamp=0, after_message_id="", limit=20,
        )


# contract-test: supporting surface=rest_api assertions=storage.export.persisted-bounded-complete
@pytest.mark.asyncio
async def test_legacy_complete_embed_method_returns_record_121(monkeypatch):
    rows = [{"id": f"row-{number:04d}", "embed_id": f"embed-{number}", "created_at": number}
            for number in range(121)]

    async def read(_collection, *, params, **_kwargs):
        assert params["filter[hashed_chat_id][_eq]"] == "authorized-hash"
        assert params["limit"] == 20
        return [row for row in rows if row["id"] not in params.get("filter[id][_nin]", [])][:20]

    async def native_read(_service, request):
        assert request["operation"] == "complete_embeds"
        assert request["hashed_chat_id"] == "authorized-hash"
        return [row for row in rows if row["id"] > request["after_id"]][:20]
    monkeypatch.setitem(EmbedMethods._complete_embed_records.__globals__, "read_embed_uuid_page", native_read)
    actual = await EmbedMethods(SimpleNamespace(get_items=read)).get_embeds_by_hashed_chat_id("authorized-hash")
    assert actual == list(reversed(rows))


# contract-test: supporting surface=rest_api assertions=storage.export.persisted-bounded-complete,storage.cold.shared-team-authorized
@pytest.mark.asyncio
async def test_shared_complete_keys_cross_default_limit_without_master_keys(monkeypatch):
    rows = [{"id": f"key-{number:04d}", "hashed_embed_id": f"embed-{number}", "key_type": "chat"}
            for number in range(121)]

    async def read(_collection, *, params, **_kwargs):
        assert params["filter[hashed_chat_id][_eq]"] == "authorized-hash"
        assert params["filter[key_type][_eq]"] == "chat"
        assert params["limit"] == 20
        return [row for row in rows if row["id"] not in params.get("filter[id][_nin]", [])][:20]

    async def native_read(_service, request):
        assert request["operation"] == "complete_embed_keys"
        assert request["hashed_chat_id"] == "authorized-hash" and request["key_type"] == "chat"
        return [row for row in rows if row["id"] > request["after_id"]][:20]
    monkeypatch.setitem(EmbedMethods._complete_embed_records.__globals__, "read_embed_uuid_page", native_read)
    actual = await EmbedMethods(SimpleNamespace(get_items=read)).get_embed_keys_by_hashed_chat_id(
        "authorized-hash", include_master_keys=False,
    )
    assert actual == rows
