"""Live item storage: Redis seq/hot tail and batched Directus append.

Packets are stored as the base64 string received (ciphertext). Redis holds the
per-item seq counter (INCR), the hot tail and the item epoch; Directus holds the
durable log (live_item_updates) and snapshots (live_item_snapshots). Compaction
deletes updates with seq <= covers_seq only after the snapshot is confirmed.
"""

from __future__ import annotations

import json
import time
from typing import Any

HOT_TAIL_MAX = 500
HOT_TAIL_TTL = 24 * 3600
FLUSH_BATCH = 50
ITEM_LOG_MAX_BYTES = 64 * 1024 * 1024


class LiveItemStore:
    def __init__(self, directus: Any, cache: Any):
        self.directus = directus
        self.cache = cache
        self._pending: list[dict[str, Any]] = []

    async def _redis(self) -> Any:
        client = await self.cache.client
        if client is None:
            raise RuntimeError("live_item_store_unavailable")
        return client

    async def _seed_from_directus(self, item_hash: str) -> int:
        rows = await self.directus.get_items(
            "live_item_updates",
            params={
                "filter[hashed_item_id][_eq]": item_hash,
                "sort": "-seq",
                "fields": "seq",
                "limit": 1,
            },
            no_cache=True,
            admin_required=True,
        )
        return int(rows[0]["seq"]) if rows else 0

    async def head_seq(self, item_hash: str) -> int:
        redis = await self._redis()
        value = await redis.get(f"live:seq:{item_hash}")
        return (
            int(value)
            if value is not None
            else await self._seed_from_directus(item_hash)
        )

    async def next_seq(self, item_hash: str) -> int:
        redis = await self._redis()
        key = f"live:seq:{item_hash}"
        if not await redis.exists(key):
            await redis.set(key, await self._seed_from_directus(item_hash), nx=True)
        return int(await redis.incr(key))

    async def add_bytes(self, item_hash: str, size: int) -> bool:
        """Account log size; False when the 64 MB item log limit would be exceeded."""
        redis = await self._redis()
        total = int(await redis.incrby(f"live:bytes:{item_hash}", size))
        if total > ITEM_LOG_MAX_BYTES:
            await redis.decrby(f"live:bytes:{item_hash}", size)
            return False
        return True

    async def append(
        self, item_hash: str, sender: str, epoch: int, payload: str
    ) -> dict[str, Any]:
        seq = await self.next_seq(item_hash)
        row = {
            "hashed_item_id": item_hash,
            "seq": seq,
            "sender_hash": sender,
            "epoch": epoch,
            "payload": payload,
            "created_at": int(time.time()),
        }
        redis = await self._redis()
        tail_key = f"live:tail:{item_hash}"
        await redis.rpush(tail_key, json.dumps(row))
        await redis.ltrim(tail_key, -HOT_TAIL_MAX, -1)
        await redis.expire(tail_key, HOT_TAIL_TTL)
        self._pending.append(row)
        if len(self._pending) >= FLUSH_BATCH:
            await self.flush()
        return row

    async def flush(self) -> None:
        """Batched append of buffered updates to Directus."""
        batch, self._pending = self._pending, []
        for index, row in enumerate(batch):
            ok, _ = await self.directus.create_item(
                "live_item_updates", row, admin_required=True
            )
            if not ok:
                self._pending = batch[index:] + self._pending
                raise RuntimeError("live_item_flush_failed")

    async def updates_since(
        self, item_hash: str, since_seq: int
    ) -> list[dict[str, Any]]:
        redis = await self._redis()
        raw = await redis.lrange(f"live:tail:{item_hash}", 0, -1)
        tail = [json.loads(r) for r in raw]
        if tail and tail[0]["seq"] <= since_seq + 1:
            return [r for r in tail if r["seq"] > since_seq]
        if not tail and await self.head_seq(item_hash) <= since_seq:
            return []
        await self.flush()
        rows = await self.directus.get_items(
            "live_item_updates",
            params={
                "filter[hashed_item_id][_eq]": item_hash,
                "filter[seq][_gt]": since_seq,
                "sort": "seq",
                "limit": -1,
            },
            no_cache=True,
            admin_required=True,
        )
        return list(rows or [])

    async def latest_snapshot(self, item_hash: str) -> dict[str, Any] | None:
        rows = await self.directus.get_items(
            "live_item_snapshots",
            params={
                "filter[hashed_item_id][_eq]": item_hash,
                "sort": "-covers_seq,-epoch",
                "limit": 1,
            },
            no_cache=True,
            admin_required=True,
        )
        return rows[0] if rows else None

    async def add_snapshot(
        self, item_hash: str, covers_seq: int, epoch: int, sender: str, payload: str
    ) -> bool:
        ok, _ = await self.directus.create_item(
            "live_item_snapshots",
            {
                "hashed_item_id": item_hash,
                "covers_seq": covers_seq,
                "epoch": epoch,
                "sender_hash": sender,
                "payload": payload,
                "confirmed": False,
                "created_at": int(time.time()),
            },
            admin_required=True,
        )
        return bool(ok)

    async def confirm_snapshot(
        self, item_hash: str, covers_seq: int, epoch: int, confirmer: str
    ) -> bool:
        """Mark a snapshot confirmed (by a different client) and compact the log."""
        rows = await self.directus.get_items(
            "live_item_snapshots",
            params={
                "filter[hashed_item_id][_eq]": item_hash,
                "filter[covers_seq][_eq]": covers_seq,
                "filter[epoch][_eq]": epoch,
                "limit": 1,
            },
            no_cache=True,
            admin_required=True,
        )
        if not rows or rows[0].get("sender_hash") == confirmer:
            return False
        if not rows[0].get("confirmed"):
            await self.directus.update_item(
                "live_item_snapshots",
                rows[0]["id"],
                {"confirmed": True},
                admin_required=True,
            )
        await self.compact(item_hash)
        return True

    async def compact(self, item_hash: str) -> int:
        """Delete updates with seq <= covers_seq of the newest confirmed snapshot."""
        rows = await self.directus.get_items(
            "live_item_snapshots",
            params={
                "filter[hashed_item_id][_eq]": item_hash,
                "filter[confirmed][_eq]": True,
                "sort": "-covers_seq,-epoch",
                "limit": 1,
            },
            no_cache=True,
            admin_required=True,
        )
        if not rows:
            return 0
        covers = int(rows[0]["covers_seq"])
        await self.flush()
        old = await self.directus.get_items(
            "live_item_updates",
            params={
                "filter[hashed_item_id][_eq]": item_hash,
                "filter[seq][_lte]": covers,
                "fields": "id",
                "limit": -1,
            },
            no_cache=True,
            admin_required=True,
        )
        ids = [r["id"] for r in old or []]
        if ids:
            await self.directus.bulk_delete_items("live_item_updates", ids)
        return len(ids)
