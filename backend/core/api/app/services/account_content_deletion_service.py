"""Delete personal account content without removing Team-owned resources."""

import hashlib
from collections.abc import Awaitable, Callable
from typing import Any

from backend.core.api.app.services.scoped_directus_pagination import read_complete_scoped_records
from backend.core.api.app.services.storage_reference_service import AccountDeletableEmbedRows


async def load_account_personal_embed_key_ids(
    *, directus_service: Any, user_id_hash: str, eligible_embed_rows: AccountDeletableEmbedRows,
) -> list[str]:
    """Capture only personal key wrappers before their parent rows disappear."""
    chats = await read_complete_scoped_records(
        directus_service, "chats", admin_required=True,
        params={"fields": "id", "filter[hashed_user_id][_eq]": user_id_hash,
                "filter[hashed_team_id][_null]": True},
    )
    personal_chat_hashes = {hashlib.sha256(row["id"].encode()).hexdigest() for row in chats}
    deleted_embed_hashes = {row["hashed_embed_id"] for row in eligible_embed_rows.embeds
                            if row.get("hashed_embed_id")}
    deleted_embed_hashes.update(hashlib.sha256(row["embed_id"].encode()).hexdigest()
                                for row in eligible_embed_rows.embeds if row.get("embed_id"))
    keys = await read_complete_scoped_records(
        directus_service, "embed_keys", admin_required=True,
        params={"fields": "id,key_type,hashed_embed_id,hashed_chat_id,hashed_team_id",
                "filter[hashed_user_id][_eq]": user_id_hash},
    )
    return [row["id"] for row in keys if (
        row.get("hashed_embed_id") in deleted_embed_hashes
        or (row.get("key_type") == "master" and not row.get("hashed_team_id"))
        or (row.get("key_type") == "chat" and not row.get("hashed_team_id")
            and row.get("hashed_chat_id") in personal_chat_hashes)
    )]


async def delete_account_personal_embed_keys(*, directus_service: Any, key_ids: list[str]) -> int:
    """Remove the proven keys in bounded batches, preserving shared wrappers."""
    ids = list(dict.fromkeys(key_ids))
    for start in range(0, len(ids), 20):
        if not await directus_service.bulk_delete_items("embed_keys", ids[start:start + 20]):
            raise RuntimeError("Failed to delete account personal embed keys")
    return len(ids)


async def delete_account_personal_content(
    *, directus_service: Any, user_id_hash: str, eligible_embed_rows: AccountDeletableEmbedRows,
) -> dict[str, int]:
    """Read complete fenced personal identities, then delete in bounded batches.

    The caller must fence account storage and prepare reference-safe tombstones
    first. A Team chat can retain its creator's hash, so that hash alone does
    not confer personal deletion authority. Embed selection uses the same
    current ownership/reference proof as storage inventory.
    """
    chats = await read_complete_scoped_records(
        directus_service, "chats", admin_required=True,
        params={"fields": "id", "filter[hashed_user_id][_eq]": user_id_hash,
                "filter[hashed_team_id][_null]": True},
    )
    embed_ids = []
    for embed in eligible_embed_rows.embeds:
        if not isinstance(embed.get("id"), str) or not embed["id"]:
            raise RuntimeError("Account embed deletion identity unavailable")
        embed_ids.append(embed["id"])
    message_ids = []
    for chat in chats:
        messages = await read_complete_scoped_records(
            directus_service, "messages", admin_required=True,
            params={"fields": "id", "filter[chat_id][_eq]": chat["id"]},
        )
        message_ids.extend(row["id"] for row in messages)
    specification_rows = {}
    for collection in ("user_specification_revisions", "user_specifications"):
        specification_rows[collection] = await read_complete_scoped_records(
            directus_service, collection, admin_required=True,
            params={"fields": "id", "filter[hashed_user_id][_eq]": user_id_hash,
                    "filter[hashed_team_id][_null]": True},
        )
    identities = {
        **{collection: [row["id"] for row in rows] for collection, rows in specification_rows.items()},
        "messages": list(dict.fromkeys(message_ids)),
        "embeds": list(dict.fromkeys(embed_ids)),
        "chats": [row["id"] for row in chats],
    }
    for collection, ids in identities.items():
        for start in range(0, len(ids), 20):
            if not await directus_service.bulk_delete_items(collection, ids[start:start + 20]):
                raise RuntimeError(f"Failed to delete account {collection} rows")
    return {collection: len(ids) for collection, ids in identities.items()}


async def delete_account_personal_speech(
    *, directus_service: Any, user_id: str, user_id_hash: str,
    delete_file: Callable[[str], Awaitable[None]],
) -> None:
    """Clean speech after account fencing, before upload or owner rows vanish.

    The caller already holds the account's personal chat deletion fences. Team
    chats remain outside this scope, even when they retain the creator's hash.
    """
    from backend.apps.audio.assistant_speech.persistence import (
        cleanup_generated_speech_asset, delete_speech_assets,
    )

    chats = await read_complete_scoped_records(
        directus_service, "chats", admin_required=True,
        params={"fields": "id,storage_state", "filter[hashed_user_id][_eq]": user_id_hash,
                "filter[hashed_team_id][_null]": True},
    )
    identities: set[tuple[str, str]] = set()
    # Cancel all executions before touching any objects. The second cleanup
    # read captures pending asset identities published before cancellation.
    for chat in chats:
        if chat.get("storage_state") != "deleting":
            raise RuntimeError("Account speech cleanup requires chat deletion fences")
        for collection in ("assistant_speech_segments", "assistant_speech_manifests"):
            rows = await read_complete_scoped_records(
                directus_service, collection, admin_required=True,
                params={"filter[chat_id][_eq]": chat["id"], "filter[user_id][_eq]": user_id},
            )
            for row in rows:
                message_id = row.get("assistant_message_id")
                if not message_id:
                    raise RuntimeError("Account speech cleanup message identity unavailable")
                identities.add((chat["id"], str(message_id)))
                if collection == "assistant_speech_segments" and row.get("status") != "cancelled":
                    if not await directus_service.update_item(collection, row["id"], {"status": "cancelled"}):
                        raise RuntimeError("Account speech cancellation failed")

    async def delete_asset(segment: dict[str, object]) -> None:
        asset_ids = {segment.get("generated_asset_id"), segment.get("pending_generated_asset_id")} - {None, ""}
        for asset_id in asset_ids:
            await cleanup_generated_speech_asset(
                directus_service, str(asset_id), delete_file=delete_file,
                fallback_file_key=(f"{user_id}/assistant_speech/{asset_id}/original.mp3"
                                   if asset_id == segment.get("pending_generated_asset_id") else None),
            )

    for chat_id, message_id in sorted(identities):
        await delete_speech_assets(
            directus_service, user_id=user_id, chat_id=chat_id,
            assistant_message_id=message_id, delete_asset=delete_asset,
        )
