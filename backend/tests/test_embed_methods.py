"""Tests for embed deletion project protection.

Project-referenced embeds must survive chat/message cleanup unless the caller
explicitly removes the project reference first.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock
import importlib.util
from pathlib import Path

import pytest


def _load_embed_methods_class():
    module_path = Path(__file__).resolve().parents[1] / "core" / "api" / "app" / "services" / "directus" / "embed_methods.py"
    spec = importlib.util.spec_from_file_location("embed_methods_under_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.EmbedMethods


# contract-test: direct surface=rest_api assertions=storage.files.reference-safe-single-copy
@pytest.mark.asyncio
async def test_delete_all_embeds_for_chat_keeps_project_referenced_embeds() -> None:
    EmbedMethods = _load_embed_methods_class()
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(
        return_value=[
            {"id": "directus-a", "embed_id": "embed-a", "is_private": True, "is_shared": False},
            {"id": "directus-b", "embed_id": "embed-b", "is_private": True, "is_shared": False},
        ]
    )
    directus.bulk_delete_items = AsyncMock(return_value=True)
    directus.project = SimpleNamespace(
        get_project_embed_reference_counts=AsyncMock(return_value={"embed-a": 1, "embed-b": 0})
    )

    methods = EmbedMethods(directus)
    success, deleted_embed_ids = await methods.delete_all_embeds_for_chat(
        "hashed-chat",
        user_id="user-1",
    )

    assert success is True
    assert deleted_embed_ids == ["embed-b"]
    directus.bulk_delete_items.assert_awaited_once_with(
        collection="embeds",
        item_ids=["directus-b"],
    )


# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted
@pytest.mark.asyncio
async def test_create_embed_rejects_vault_encrypted_content() -> None:
    EmbedMethods = _load_embed_methods_class()
    methods = EmbedMethods(SimpleNamespace())

    with pytest.raises(ValueError, match="client-side encrypted"):
        await methods.create_embed({"embed_id": "embed-vault", "encrypted_content": "vault:v1:ciphertext"})


# contract-test: supporting surface=rest_api assertions=chats.persistence.client-encrypted
@pytest.mark.asyncio
async def test_update_embed_rejects_vault_encrypted_content() -> None:
    EmbedMethods = _load_embed_methods_class()
    methods = EmbedMethods(SimpleNamespace())

    with pytest.raises(ValueError, match="client-side encrypted"):
        await methods.update_embed("embed-vault", {"encrypted_content": "vault:v1:ciphertext"})


# contract-test: supporting surface=rest_api assertions=storage.files.reference-safe-single-copy
@pytest.mark.asyncio
async def test_get_embeds_by_hashed_embed_ids_uses_admin_read() -> None:
    EmbedMethods = _load_embed_methods_class()
    directus = SimpleNamespace()
    directus.get_items = AsyncMock(return_value=[{"embed_id": "pdf-embed"}])

    methods = EmbedMethods(directus)
    embeds = await methods.get_embeds_by_hashed_embed_ids(["hash-pdf"])

    assert embeds == [{"embed_id": "pdf-embed"}]
    directus.get_items.assert_awaited_once()
    call = directus.get_items.await_args
    assert call.args[0] == "embeds"
    assert call.kwargs["params"]["filter[hashed_embed_id][_in]"] == "hash-pdf"
    assert call.kwargs["no_cache"] is True
    assert call.kwargs["admin_required"] is True


# contract-test: direct surface=rest_api assertions=storage.deletion.global-authoritative
@pytest.mark.asyncio
async def test_draft_upload_keeps_prepared_tombstone_when_reference_delete_fails() -> None:
    EmbedMethods = _load_embed_methods_class()
    directus = SimpleNamespace()
    upload = {
        "id": "upload-row",
        "file_size_bytes": 10,
        "files_metadata": {"original": {"s3_key": "owner/draft.bin"}},
    }
    initial_query_done = False

    async def get_items(collection: str, **_kwargs: object) -> list[dict]:
        nonlocal initial_query_done
        if collection == "upload_files" and not initial_query_done:
            initial_query_done = True
            return [upload]
        return []

    directus.get_items = AsyncMock(side_effect=get_items)
    directus.create_item = AsyncMock(
        return_value=(
            True,
            {"id": "prepared-1", "state": "prepared", "version": 1},
        )
    )
    directus.delete_item = AsyncMock(return_value=False)
    directus.update_item = AsyncMock()

    methods = EmbedMethods(directus)
    bytes_freed = await methods.delete_draft_upload_file(
        "embed-1",
        "user-1",
    )

    assert bytes_freed == 0
    assert directus.create_item.await_args.args[1]["state"] == "prepared"
    directus.update_item.assert_not_awaited()
