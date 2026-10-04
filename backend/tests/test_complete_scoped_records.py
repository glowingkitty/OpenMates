"""Legacy complete responses cannot truncate at Directus's default page size."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

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
        after = params.get("filter[id][_gt]", "")
        return [row for row in rows if row["id"] > after][:params["limit"]]

    actual = await read_complete_scoped_records(
        SimpleNamespace(get_items=read), "embeds",
        params={"filter[hashed_chat_id][_eq]": "authorized-chat-hash", "fields": "id,encrypted_content"},
        admin_required=True,
    )
    assert actual == rows
    assert len(calls) == 7
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


# contract-test: supporting surface=rest_api assertions=storage.export.persisted-bounded-complete,storage.cold.discoverable-bounded
@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, RuntimeError("Database read failed")])
async def test_hot_message_read_failure_cannot_be_reported_as_empty_history(failure):
    async def fail_read(_collection, **kwargs):
        assert kwargs["raise_on_error"] is True
        assert kwargs["no_cache"] is True
        if isinstance(failure, Exception):
            raise failure
        return failure

    methods = ChatMethods(SimpleNamespace(get_items=fail_read))
    with pytest.raises(RuntimeError):
        await methods.get_message_window_for_chat(
            "authorized-chat", direction="after", after_timestamp=0, after_message_id="", limit=20,
        )


# contract-test: supporting surface=rest_api assertions=storage.export.persisted-bounded-complete
@pytest.mark.asyncio
async def test_legacy_complete_embed_method_returns_record_121():
    rows = [{"id": f"row-{number:04d}", "embed_id": f"embed-{number}", "created_at": number}
            for number in range(121)]

    async def read(_collection, *, params, **_kwargs):
        assert params["filter[hashed_chat_id][_eq]"] == "authorized-hash"
        assert params["limit"] == 20
        return [row for row in rows if row["id"] > params.get("filter[id][_gt]", "")][:20]

    actual = await EmbedMethods(SimpleNamespace(get_items=read)).get_embeds_by_hashed_chat_id("authorized-hash")
    assert actual == list(reversed(rows))


# contract-test: supporting surface=rest_api assertions=storage.export.persisted-bounded-complete,storage.cold.shared-team-authorized
@pytest.mark.asyncio
async def test_shared_complete_keys_cross_default_limit_without_master_keys():
    rows = [{"id": f"key-{number:04d}", "hashed_embed_id": f"embed-{number}", "key_type": "chat"}
            for number in range(121)]

    async def read(_collection, *, params, **_kwargs):
        assert params["filter[hashed_chat_id][_eq]"] == "authorized-hash"
        assert params["filter[key_type][_eq]"] == "chat"
        assert params["limit"] == 20
        return [row for row in rows if row["id"] > params.get("filter[id][_gt]", "")][:20]

    actual = await EmbedMethods(SimpleNamespace(get_items=read)).get_embed_keys_by_hashed_chat_id(
        "authorized-hash", include_master_keys=False,
    )
    assert actual == rows
