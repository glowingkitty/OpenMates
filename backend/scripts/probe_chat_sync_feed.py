"""Dev probe for the chat sync feed (architecture.sync@2) with a synthetic owner.

Run inside the API container on the dev server:
    docker exec api python /app/backend/scripts/probe_chat_sync_feed.py
It never touches a real account: a random owner ID that belongs to no user is
hashed exactly like a real owner, and only its own synthetic chats are created
and deleted. It exercises the live triggers, the chat-sync Directus extension,
the commit-hint path (pg_notify -> Directus -> API -> Redis) and page hydration,
then prints a content-free JSON summary.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid

from backend.core.api.app.services.cache import CacheService
from backend.core.api.app.services.chat_sync_feed_service import HINT_CHANNEL_PREFIX, ChatSyncFeedService, scope_keys
from backend.core.api.app.services.directus import DirectusService
from backend.core.api.app.utils.encryption import EncryptionService


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


async def _drain(feed: ChatSyncFeedService, owner: str, cursor: str, limit: int) -> tuple[list[dict], str, int, float]:
    changes: list[dict] = []
    pages = 0
    slowest = 0.0
    while True:
        started = time.perf_counter()
        page = await feed.read_page(owner, None, cursor, limit)
        slowest = max(slowest, time.perf_counter() - started)
        pages += 1
        assert not page["reset"], "unexpected reset"
        changes.extend(page["changes"])
        cursor = page["next_cursor"]
        if not page["has_more"]:
            return changes, cursor, pages, slowest


async def _await_hint(cache: CacheService, scope: str, timeout: float) -> int | None:
    async def first() -> int | None:
        async for event in cache.subscribe_to_channel(f"{HINT_CHANNEL_PREFIX}{scope}"):
            data = event.get("data")
            if isinstance(data, dict) and isinstance(data.get("revision"), int):
                return data["revision"]
        return None
    try:
        return await asyncio.wait_for(first(), timeout)
    except asyncio.TimeoutError:
        return None


async def main() -> None:
    cache = CacheService()
    encryption = EncryptionService()
    directus = DirectusService(cache_service=cache, encryption_service=encryption)
    feed = ChatSyncFeedService(directus, cache, encryption)
    owner = str(uuid.uuid4())  # synthetic: belongs to no account
    owner_hash = _sha(owner)
    scope, _ = scope_keys(owner, None)
    summary: dict = {"scope_kind": "personal", "synthetic_owner": True}
    created: list[str] = []
    try:
        cursor = await feed.cold_start_cursor(owner, None)
        now = int(time.time())
        for index in range(3):
            chat_id = str(uuid.uuid4())
            ok, _ = await directus.create_item("chats", {
                "id": chat_id, "hashed_user_id": owner_hash, "encrypted_title": "probe-ciphertext",
                "messages_v": 0, "title_v": 1, "metadata_v": 1, "pinned": False,
                "last_edited_overall_timestamp": now + index, "created_at": now, "updated_at": now,
            }, admin_required=True)
            assert ok, "chat create failed"
            created.append(chat_id)
        changes, cursor, pages, slowest = await _drain(feed, owner, cursor, 2)
        seen = {c.get("chat_id") for c in changes if c.get("chat_details")}
        summary["create"] = {"pages": pages, "all_seen": seen == set(created), "slowest_page_ms": round(slowest * 1000)}

        hint_task = asyncio.create_task(_await_hint(cache, scope, 15))
        await asyncio.sleep(0.5)
        await directus.update_item("chats", created[0], {"pinned": True}, admin_required=True)
        hint_revision = await hint_task
        changes, cursor, _, _ = await _drain(feed, owner, cursor, 50)
        summary["pin"] = {
            "hint_received": hint_revision is not None,
            "entries": [(c.get("chat_id") == created[0], c.get("kinds"), (c.get("chat_details") or {}).get("pinned")) for c in changes],
        }

        await directus.delete_item("chats", created[1], admin_required=True)
        deleted = created.pop(1)
        changes, cursor, _, _ = await _drain(feed, owner, cursor, 50)
        summary["delete"] = [{"hash_only": "chat_id" not in c and c.get("hashed_chat_id") == _sha(deleted), "kinds": c.get("kinds")} for c in changes]

        replay = await feed.read_page(owner, None, cursor, 50)
        summary["caught_up"] = {"changes": len(replay["changes"]), "has_more": replay["has_more"]}
        summary["reset_on_foreign_epoch"] = (await feed.read_page(owner, None, f"{uuid.uuid4()}:1|{uuid.uuid4()}:1", 10))["reset"]
        summary["forbidden_fields_absent"] = all(
            key not in json.dumps(summary) for key in ("encrypted_content", "embed_keys")
        )
    finally:
        for chat_id in created:
            await directus.delete_item("chats", chat_id, admin_required=True)
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
