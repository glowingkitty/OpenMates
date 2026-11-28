"""Live item WebSocket relay (messages on the existing /v1/ws socket).

Client -> server: live_item_subscribe, live_item_unsubscribe, live_item_update,
live_item_snapshot, live_item_snapshot_confirm, live_item_presence.
Server -> client: live_item_state, live_item_update_ack, live_item_update,
live_item_snapshot_available, live_item_presence, live_item_refused.
Every payload field contains a sealed packet. The relay validates its framing and
epoch, and the client authenticates the encrypted contents.
The sender is the per-user hash of the authenticated connection, never client input.
See docs/plans/live-collaboration-crdt/build-contract.md section 2.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import logging
import time
import uuid
import weakref
from enum import IntEnum
from collections import deque
from dataclasses import dataclass
from typing import Any

from backend.core.api.app.services.live_items.access import (
    LiveAccess,
    hash_id,
    live_role_for,
    resolve_access,
)
from backend.core.api.app.services.live_items.store import LiveItemStore

logger = logging.getLogger(__name__)

MAX_PACKET_BYTES = 256 * 1024
UPDATE_RATE_PER_SECOND = 50
PRESENCE_RATE_PER_SECOND = 20
CHANNEL_PREFIX = "live_item:"
CONTROL_CHANNEL = CHANNEL_PREFIX + "control"
LIVE_ITEM_MESSAGE_TYPES = frozenset(
    {
        "live_item_subscribe",
        "live_item_unsubscribe",
        "live_item_update",
        "live_item_snapshot",
        "live_item_snapshot_confirm",
        "live_item_presence",
    }
)


def sender_hash(user_id: str) -> str:
    return hashlib.sha256(f"live_sender:{user_id}".encode()).hexdigest()[:32]


async def publish_project_editor_event(cache: Any, user_id: str, event: str, body: dict[str, Any]) -> None:
    """Route metadata for an authorized Project write to the requester's open editor."""
    await cache.publish_event(CHANNEL_PREFIX + hash_id(body["embed_id"]), {
        "op": "project_editor", "user": user_id, "event": event, "body": body,
    })


class PacketKind(IntEnum):
    """Shared Rust live packet v1 type bytes."""

    UPDATE = 1
    SNAPSHOT = 2
    PRESENCE = 3


def packet_size(value: Any, kind: PacketKind, epoch: int) -> int | None:
    """Validate clear framing before relaying opaque ciphertext."""
    if not isinstance(value, str) or not value:
        return None
    try:
        sealed = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return None
    # version + kind + big-endian epoch + AES-GCM nonce and tag
    if len(sealed) < 34 or sealed[0] != 1 or sealed[1] != kind:
        return None
    if int.from_bytes(sealed[2:6], "big") != epoch:
        return None
    return len(sealed)

@dataclass
class Subscription:
    item_id: str
    user_id: str
    sender: str
    role: str
    team_hash: str | None
    connection: str


class _Window:
    def __init__(self, limit: int):
        self.limit = limit
        self.stamps: deque[float] = deque()

    def allow(self) -> bool:
        now = time.monotonic()
        while self.stamps and now - self.stamps[0] >= 1.0:
            self.stamps.popleft()
        if len(self.stamps) >= self.limit:
            return False
        self.stamps.append(now)
        return True


class LiveItemRelay:
    def __init__(self, directus: Any, cache: Any):
        self.directus = directus
        self.cache = cache
        self.store = LiveItemStore(directus, cache)
        self.worker_id = uuid.uuid4().hex
        # item hash -> {websocket: Subscription}
        self.subscribers: dict[str, weakref.WeakKeyDictionary] = {}
        self.windows: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
        self.connections: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()

    # ---- entry point ----
    async def handle(
        self, websocket: Any, user_id: str, message_type: str, payload: dict
    ) -> None:
        item_id = payload.get("item_id") if isinstance(payload, dict) else None
        if not isinstance(item_id, str) or not 0 < len(item_id) <= 512:
            return
        msg_id = payload.get("client_msg_id")
        client_msg_id = (
            msg_id if isinstance(msg_id, str) and len(msg_id) <= 128 else None
        )
        if message_type == "live_item_subscribe":
            await self.subscribe(
                websocket,
                user_id,
                item_id,
                payload.get("kind", "embed"),
                payload.get("since_seq"),
            )
        elif message_type == "live_item_unsubscribe":
            self.unsubscribe(websocket, item_id)
        elif message_type == "live_item_update":
            await self.update(
                websocket,
                item_id,
                client_msg_id,
                payload.get("epoch"),
                payload.get("payload"),
            )
        elif message_type == "live_item_snapshot":
            await self.snapshot(
                websocket,
                item_id,
                payload.get("covers_seq"),
                payload.get("epoch"),
                payload.get("payload"),
            )
        elif message_type == "live_item_snapshot_confirm":
            await self.confirm_snapshot(websocket, item_id, payload.get("covers_seq"), payload.get("epoch", 1))
        elif message_type == "live_item_presence":
            await self.presence(websocket, item_id, payload.get("epoch", 1), payload.get("payload"))

    # ---- helpers ----
    async def _refuse(
        self,
        websocket: Any,
        item_id: str,
        reason: str,
        client_msg_id: str | None = None,
        *,
        rejected_epoch: int | None = None,
    ) -> None:
        body: dict[str, Any] = {"item_id": item_id, "reason": reason}
        if client_msg_id:
            body["client_msg_id"] = client_msg_id
        if rejected_epoch is not None:
            body["rejected_epoch"] = rejected_epoch
        await self._send(websocket, "live_item_refused", body)

    async def _send(
        self, websocket: Any, message_type: str, body: dict[str, Any]
    ) -> None:
        try:
            await websocket.send_json({"type": message_type, "payload": body})
        except (RuntimeError, ConnectionError, OSError):
            self.disconnect(websocket)

    def _sub(self, websocket: Any, item_id: str) -> Subscription | None:
        return self.subscribers.get(hash_id(item_id), {}).get(websocket)

    def _window(self, websocket: Any, kind: str, limit: int) -> _Window:
        windows = self.windows.setdefault(websocket, {})
        return windows.setdefault(kind, _Window(limit))

    async def _team_epoch(self, team_hash: str | None) -> int | None:
        """Load the Team's write epoch, with no writes while rotation is pending."""
        if team_hash is None:
            return 1
        rows = await self.directus.get_items(
            "teams",
            params={
                "filter[hashed_team_id][_eq]": team_hash,
                "filter[status][_eq]": "active",
                "fields": "team_key_epoch,rotation_pending",
                "limit": 1,
            },
            no_cache=True,
            admin_required=True,
        )
        if not isinstance(rows, list) or not rows or rows[0].get("rotation_pending"):
            return None
        epoch = rows[0].get("team_key_epoch")
        if epoch is None:  # Existing Teams predate the epoch field.
            return 1
        return epoch if isinstance(epoch, int) and not isinstance(epoch, bool) and epoch >= 1 else None

    async def _accept_epoch(
        self, websocket: Any, sub: Subscription, epoch: int, client_msg_id: str | None = None
    ) -> bool:
        if epoch == await self._team_epoch(sub.team_hash):
            return True
        await self._refuse(
            websocket, sub.item_id, "key_epoch_stale", client_msg_id, rejected_epoch=epoch
        )
        return False

    async def _publish(self, item_hash: str, event: dict[str, Any]) -> None:
        await self.cache.publish_event(
            CHANNEL_PREFIX + item_hash, {**event, "origin": self.worker_id}
        )

    async def _fan_out(
        self,
        item_hash: str,
        message_type: str,
        body: dict[str, Any],
        skip_connection: str | None,
    ) -> None:
        for ws, sub in list(self.subscribers.get(item_hash, {}).items()):
            if sub.connection != skip_connection:
                await self._send(ws, message_type, body)

    # ---- subscribe / unsubscribe ----
    async def subscribe(
        self, websocket: Any, user_id: str, item_id: str, kind: Any, since_seq: Any
    ) -> None:
        access: LiveAccess | None = await resolve_access(
            self.directus, user_id, item_id, kind if isinstance(kind, str) else ""
        )
        if access is None:
            await self._refuse(websocket, item_id, "not_found")
            return
        item_hash = hash_id(item_id)
        connection = self.connections.setdefault(websocket, uuid.uuid4().hex)
        self.subscribers.setdefault(item_hash, weakref.WeakKeyDictionary())[
            websocket
        ] = Subscription(
            item_id,
            user_id,
            sender_hash(user_id),
            access.role,
            access.team_hash,
            connection,
        )
        since = since_seq if isinstance(since_seq, int) and since_seq >= 0 else None
        snap = await self.store.latest_snapshot(item_hash)
        body: dict[str, Any] = {
            "item_id": item_id,
            "role": access.role,
            "epoch": await self._team_epoch(access.team_hash),
        }
        floor = since if since is not None else (int(snap["covers_seq"]) if snap else 0)
        if snap and (since is None or since < int(snap["covers_seq"])):
            body["snapshot"] = {
                "seq": int(snap["covers_seq"]),
                "epoch": int(snap["epoch"]),
                "payload": snap["payload"],
            }
            floor = max(floor, int(snap["covers_seq"]))
        rows = await self.store.updates_since(item_hash, floor)
        body["updates"] = [
            {
                "seq": r["seq"],
                "sender": r["sender_hash"],
                "epoch": r["epoch"],
                "payload": r["payload"],
                "ts": r["created_at"],
            }
            for r in rows
        ]
        body["head_seq"] = max([floor] + [r["seq"] for r in rows])
        await self._send(websocket, "live_item_state", body)

    def unsubscribe(self, websocket: Any, item_id: str) -> None:
        subs = self.subscribers.get(hash_id(item_id))
        if subs is not None:
            subs.pop(websocket, None)

    def disconnect(self, websocket: Any) -> None:
        for subs in self.subscribers.values():
            subs.pop(websocket, None)

    # ---- update / snapshot / presence ----
    async def update(
        self,
        websocket: Any,
        item_id: str,
        client_msg_id: str | None,
        epoch: Any,
        payload: Any,
    ) -> None:
        sub = self._sub(websocket, item_id)
        if sub is None:
            await self._refuse(websocket, item_id, "not_found", client_msg_id)
            return
        if sub.role != "edit":
            await self._refuse(websocket, item_id, "read_only", client_msg_id)
            return
        if not self._window(websocket, "update", UPDATE_RATE_PER_SECOND).allow():
            await self._refuse(websocket, item_id, "rate_limited", client_msg_id)
            return
        if not isinstance(epoch, int) or isinstance(epoch, bool) or epoch < 1:
            return
        size = packet_size(payload, PacketKind.UPDATE, epoch)
        if size is None:
            return
        item_hash = hash_id(item_id)
        if size > MAX_PACKET_BYTES:
            await self._refuse(websocket, item_id, "too_large", client_msg_id)
            return
        if not await self._accept_epoch(websocket, sub, epoch, client_msg_id):
            return
        if not await self.store.add_bytes(item_hash, size):
            await self._refuse(websocket, item_id, "too_large", client_msg_id)
            return
        row = await self.store.append(item_hash, sub.sender, epoch, payload)
        await self._send(
            websocket,
            "live_item_update_ack",
            {"item_id": item_id, "client_msg_id": client_msg_id, "seq": row["seq"]},
        )
        body = {
            "item_id": item_id,
            "seq": row["seq"],
            "sender": sub.sender,
            "epoch": epoch,
            "payload": payload,
            "ts": row["created_at"],
        }
        await self._fan_out(item_hash, "live_item_update", body, sub.connection)
        await self._publish(
            item_hash, {"op": "update", "body": body, "skip": sub.connection}
        )

    async def snapshot(
        self, websocket: Any, item_id: str, covers_seq: Any, epoch: Any, payload: Any
    ) -> None:
        sub = self._sub(websocket, item_id)
        if sub is None:
            await self._refuse(websocket, item_id, "not_found")
            return
        if sub.role != "edit":
            await self._refuse(websocket, item_id, "read_only")
            return
        ints_ok = all(
            isinstance(v, int) and not isinstance(v, bool) and v >= 0
            for v in (covers_seq, epoch)
        )
        if not ints_ok:
            return
        size = packet_size(payload, PacketKind.SNAPSHOT, epoch)
        if size is None:
            return
        item_hash = hash_id(item_id)
        if size > MAX_PACKET_BYTES:
            await self._refuse(websocket, item_id, "too_large")
            return
        if not await self._accept_epoch(websocket, sub, epoch):
            return
        if covers_seq > await self.store.head_seq(item_hash):
            return
        if await self.store.add_snapshot(
            item_hash, covers_seq, epoch, sub.sender, payload
        ):
            body = {"item_id": item_id, "covers_seq": covers_seq, "epoch": epoch}
            await self._fan_out(
                item_hash, "live_item_snapshot_available", body, sub.connection
            )
            await self._publish(
                item_hash, {"op": "snapshot", "body": body, "skip": sub.connection}
            )

    async def confirm_snapshot(
        self, websocket: Any, item_id: str, covers_seq: Any, epoch: Any
    ) -> None:
        sub = self._sub(websocket, item_id)
        if sub is None or not all(
            isinstance(value, int) and not isinstance(value, bool) and value >= 0
            for value in (covers_seq, epoch)
        ):
            return
        await self.store.confirm_snapshot(hash_id(item_id), covers_seq, epoch, sub.sender)

    async def presence(self, websocket: Any, item_id: str, epoch: Any, payload: Any) -> None:
        sub = self._sub(websocket, item_id)
        if sub is None:
            await self._refuse(websocket, item_id, "not_found")
            return
        if not self._window(websocket, "presence", PRESENCE_RATE_PER_SECOND).allow():
            await self._refuse(websocket, item_id, "rate_limited")
            return
        if not isinstance(epoch, int) or isinstance(epoch, bool) or epoch < 1:
            return
        size = packet_size(payload, PacketKind.PRESENCE, epoch)
        if size is None:
            return
        if size > MAX_PACKET_BYTES:
            await self._refuse(websocket, item_id, "too_large")
            return
        if not await self._accept_epoch(websocket, sub, epoch):
            return
        item_hash = hash_id(item_id)
        body = {
            "item_id": item_id,
            "sender": sub.sender,
            "connection": sub.connection,
            "payload": payload,
        }
        await self._fan_out(item_hash, "live_item_presence", body, sub.connection)
        await self._publish(
            item_hash, {"op": "presence", "body": body, "skip": sub.connection}
        )

    # ---- removal mid-session ----
    async def _drop_team_member(self, team_hash: str, user_hash: str) -> None:
        for item_hash, subs in list(self.subscribers.items()):
            for ws, sub in list(subs.items()):
                if sub.team_hash == team_hash and hash_id(sub.user_id) == user_hash:
                    subs.pop(ws, None)
                    await self._refuse(ws, sub.item_id, "access_revoked")

    async def revoke_team_member(self, team_id: str, user_id: str) -> None:
        """Called when a Team membership is removed; drops that user's live subscriptions on every worker."""
        team_hash, user_hash = hash_id(team_id), hash_id(user_id)
        await self._drop_team_member(team_hash, user_hash)
        await self.cache.publish_event(
            CONTROL_CHANNEL,
            {
                "op": "revoke",
                "team": team_hash,
                "user": user_hash,
                "origin": self.worker_id,
            },
        )

    async def _apply_team_role(
        self, team_hash: str, user_hash: str, role: str | None
    ) -> None:
        """Switch one user's subscriptions on a Team's items to a new live role."""
        if role is None:
            await self._drop_team_member(team_hash, user_hash)
            return
        for subs in list(self.subscribers.values()):
            for ws, sub in list(subs.items()):
                if sub.team_hash != team_hash or hash_id(sub.user_id) != user_hash:
                    continue
                lowered = sub.role == "edit" and role != "edit"
                sub.role = role
                if lowered:
                    await self._refuse(ws, sub.item_id, "read_only")

    async def change_team_member_role(
        self, team_id: str, user_id: str, team_role: str
    ) -> None:
        """Called when a Team role changes; lowering to viewer makes live items read-only on every worker."""
        team_hash, user_hash = hash_id(team_id), hash_id(user_id)
        role = live_role_for(team_role)
        await self._apply_team_role(team_hash, user_hash, role)
        await self.cache.publish_event(
            CONTROL_CHANNEL,
            {
                "op": "role",
                "team": team_hash,
                "user": user_hash,
                "role": role,
                "origin": self.worker_id,
            },
        )

    # ---- cross-worker events ----
    async def handle_event(self, channel: str, event: Any) -> None:
        if not isinstance(event, dict) or event.get("origin") == self.worker_id:
            return
        if event.get("op") == "revoke":
            await self._drop_team_member(str(event.get("team")), str(event.get("user")))
            return
        if event.get("op") == "role":
            role = event.get("role")
            await self._apply_team_role(
                str(event.get("team")),
                str(event.get("user")),
                role if isinstance(role, str) else None,
            )
            return
        item_hash = channel.removeprefix(CHANNEL_PREFIX)
        if event.get("op") == "project_editor":
            await self._project_editor_event(item_hash, event)
            return
        kinds = {
            "update": "live_item_update",
            "snapshot": "live_item_snapshot_available",
            "presence": "live_item_presence",
        }
        message_type = kinds.get(event.get("op"))
        if message_type and isinstance(event.get("body"), dict):
            await self._fan_out(item_hash, message_type, event["body"], None)

    async def _project_editor_event(self, item_hash: str, event: dict[str, Any]) -> None:
        body, name = event["body"], event["event"]
        for ws, sub in list(self.subscribers.get(item_hash, {}).items()):
            if sub.user_id != event["user"] or sub.role != "edit":
                continue
            if name == "embed_assistant_project_commit":
                # Only one replica should translate the durable revision into a
                # new CRDT transaction, even if the requester has several devices.
                client = await self.cache.client
                if client is None or not await client.set(
                    f"live-project-revision:{item_hash}:{body['current_revision']}", "1", nx=True, ex=3600,
                ):
                    return
                await self._send(ws, name, body)
                return
            await self._send(ws, name, body)

    async def listen(self) -> None:
        while True:
            try:
                async for event in self.cache.subscribe_to_channel(
                    CHANNEL_PREFIX + "*"
                ):
                    await self.handle_event(
                        str(event.get("channel", "")), event.get("data")
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - listener must survive transient Redis faults
                logger.warning(
                    "Live item listener reconnecting: %s", type(exc).__name__
                )
                await asyncio.sleep(2)

    async def flush_loop(self) -> None:
        """Flush buffered updates to Directus once a second."""
        while True:
            await asyncio.sleep(1)
            try:
                await self.store.flush()
            except RuntimeError as exc:
                logger.warning("Live item flush deferred: %s", exc)
