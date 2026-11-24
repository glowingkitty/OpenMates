"""Live item relay: ciphertext-only storage, access, limits, removal, compaction.

Uses in-memory fakes for Redis and Directus; the relay is driven through its
WebSocket message entry point. See docs/plans/live-collaboration-crdt.
"""

import base64
import json

import pytest

from backend.core.api.app.services.live_items import relay as relay_mod
from backend.core.api.app.services.live_items.access import hash_id
from backend.core.api.app.services.live_items.relay import LiveItemRelay, sender_hash

ITEM = "embed-1"
TEAM = "team-1"


class FakeRedis:
    def __init__(self):
        self.kv, self.lists = {}, {}

    async def get(self, k):
        return self.kv.get(k)

    async def exists(self, k):
        return k in self.kv

    async def set(self, k, v, nx=False):
        if nx and k in self.kv:
            return False
        self.kv[k] = v
        return True

    async def incr(self, k):
        self.kv[k] = int(self.kv.get(k, 0)) + 1
        return self.kv[k]

    async def incrby(self, k, n):
        self.kv[k] = int(self.kv.get(k, 0)) + n
        return self.kv[k]

    async def decrby(self, k, n):
        self.kv[k] = int(self.kv.get(k, 0)) - n
        return self.kv[k]

    async def rpush(self, k, v):
        self.lists.setdefault(k, []).append(v)

    async def ltrim(self, k, a, b):
        self.lists[k] = self.lists[k][a:]

    async def expire(self, k, t):
        return True

    async def lrange(self, k, a, b):
        return list(self.lists.get(k, []))


class FakeCache:
    def __init__(self):
        self._r = FakeRedis()
        self.published = []

    @property
    async def client(self):
        return self._r

    async def publish_event(self, channel, data):
        self.published.append((channel, data))
        return True


def _match(row, params):
    for key, want in params.items():
        if not key.startswith("filter["):
            continue
        field, op = key[7:].split("][")
        op = op.rstrip("]")
        have = row.get(field)
        if op == "_eq" and have != want:
            return False
        if op == "_gt" and not have > want:
            return False
        if op == "_lte" and not have <= want:
            return False
    return True


class FakeDirectus:
    def __init__(self, embed_row, role="member"):
        self.tables = {
            "embeds": [embed_row],
            "team_memberships": [],
            "teams": [{"hashed_team_id": hash_id(TEAM), "status": "active", "team_key_epoch": 1}],
            "live_item_updates": [],
            "live_item_snapshots": [],
            "project_items": [],
        }
        self.members = {}
        self.role = role
        self.n = 0

    def add_member(self, user_id, role):
        self.tables["team_memberships"].append(
            {
                "hashed_team_id": hash_id(TEAM),
                "hashed_user_id": hash_id(user_id),
                "status": "active",
                "role": role,
            }
        )

    def remove_member(self, user_id):
        self.tables["team_memberships"] = [
            m
            for m in self.tables["team_memberships"]
            if m["hashed_user_id"] != hash_id(user_id)
        ]

    async def get_items(self, collection, params=None, **_):
        rows = [r for r in self.tables[collection] if _match(r, params or {})]
        sort = (params or {}).get("sort")
        if sort:
            for field in reversed(sort.split(",")):
                rows.sort(key=lambda r: r[field.lstrip("-")], reverse=field.startswith("-"))
        limit = (params or {}).get("limit", -1)
        return rows if limit == -1 else rows[:limit]

    async def create_item(self, collection, payload, admin_required=False):
        self.n += 1
        self.tables[collection].append({"id": f"id{self.n}", **payload})
        return True, payload

    async def update_item(self, collection, item_id, data, admin_required=False):
        for r in self.tables[collection]:
            if r["id"] == item_id:
                r.update(data)
        return True

    async def bulk_delete_items(self, collection, ids, params=None):
        self.tables[collection] = [
            r for r in self.tables[collection] if r["id"] not in ids
        ]
        return True


class Socket:
    def __init__(self):
        self.frames = []

    async def send_json(self, value):
        self.frames.append(value)

    def of(self, type_):
        return [f["payload"] for f in self.frames if f["type"] == type_]


def packet(raw: bytes, *, kind: int = 1, epoch: int = 1) -> str:
    # Structurally valid envelope with opaque dummy nonce and tag. The Rust
    # packet tests prove AES-GCM authentication separately.
    framed = bytes([1, kind]) + epoch.to_bytes(4, "big") + bytes(12) + raw + bytes(16)
    return base64.b64encode(framed).decode()


def make(team=True):
    row = {
        "hashed_embed_id": hash_id(ITEM),
        "hashed_user_id": hash_id("owner"),
        "hashed_team_id": hash_id(TEAM) if team else None,
    }
    directus = FakeDirectus(row)
    cache = FakeCache()
    return LiveItemRelay(directus, cache), directus, cache


async def join(relay, user, since=None):
    ws = Socket()
    await relay.handle(
        ws,
        user,
        "live_item_subscribe",
        {
            "item_id": ITEM,
            "kind": "embed",
            **({"since_seq": since} if since is not None else {}),
        },
    )
    return ws


async def send(relay, ws, user, **fields):
    await relay.handle(
        ws,
        user,
        "live_item_update",
        {"item_id": ITEM, "client_msg_id": "m1", "epoch": 1, **fields},
    )


# contract-test: supporting surface=rest_api assertions=live-collab.access.roles
@pytest.mark.asyncio
async def test_non_member_gets_not_found_and_viewer_is_read_only():
    relay, directus, _ = make()
    ws = await join(relay, "stranger")
    assert ws.of("live_item_refused") == [{"item_id": ITEM, "reason": "not_found"}]
    directus.add_member("viewer", "viewer")
    v = await join(relay, "viewer")
    assert v.of("live_item_state")[0]["role"] == "view"
    await send(relay, v, "viewer", payload=packet(b"x"))
    assert v.of("live_item_refused")[0]["reason"] == "read_only"
    assert v.of("live_item_refused")[0]["client_msg_id"] == "m1"


# contract-test: supporting surface=rest_api assertions=live-collab.access.roles
@pytest.mark.asyncio
async def test_personal_owner_edits_and_other_user_not_found():
    relay, _, _ = make(team=False)
    assert (await join(relay, "owner")).of("live_item_state")[0]["role"] == "edit"
    assert (await join(relay, "other")).of("live_item_refused")[0][
        "reason"
    ] == "not_found"


# contract-test: supporting surface=rest_api assertions=live-collab.privacy.ciphertext-only,live-collab.sync.concurrent-convergence
@pytest.mark.asyncio
async def test_ciphertext_only_storage_monotonic_seq_and_fanout_excludes_sender():
    relay, directus, cache = make()
    directus.add_member("a", "member")
    directus.add_member("b", "admin")
    a, b = await join(relay, "a"), await join(relay, "b")
    packets = [bytes([i, 255, 0, 7]) for i in range(3)]
    for raw in packets:
        await send(relay, a, "a", payload=packet(raw))
    assert [x["seq"] for x in a.of("live_item_update_ack")] == [1, 2, 3]
    assert a.of("live_item_update") == []
    got = b.of("live_item_update")
    assert [g["seq"] for g in got] == [1, 2, 3]
    assert all(g["sender"] == sender_hash("a") for g in got)
    await relay.store.flush()
    stored = directus.tables["live_item_updates"]
    assert [r["payload"] for r in stored] == [packet(raw) for raw in packets]
    allowed = {
        "id",
        "hashed_item_id",
        "seq",
        "sender_hash",
        "epoch",
        "payload",
        "created_at",
    }
    assert all(set(r) <= allowed for r in stored)
    assert all(ITEM not in json.dumps(r) and '"a"' not in json.dumps(r) for r in stored)
    # late joiner gets the tail with head_seq
    c_user = "b"
    late = await join(relay, c_user, since=1)
    state = late.of("live_item_state")[0]
    assert [u["seq"] for u in state["updates"]] == [2, 3] and state["head_seq"] == 3
    # cross-worker publish carries the same ciphertext and skips nothing locally
    assert cache.published[-1][1]["body"]["payload"] == packet(packets[-1])


# contract-test: supporting surface=rest_api assertions=live-collab.access.roles,live-collab.keys.rotation-on-removal
@pytest.mark.asyncio
async def test_oversize_rate_limit_and_stale_epoch(monkeypatch):
    relay, directus, _ = make()
    directus.add_member("a", "member")
    a = await join(relay, "a")
    await send(relay, a, "a", payload=packet(b"x" * (256 * 1024 + 1)))
    assert a.of("live_item_refused")[-1]["reason"] == "too_large"
    team = directus.tables["teams"][0]
    await send(relay, a, "a", epoch=3, payload=packet(b"future", epoch=3))
    assert a.of("live_item_refused")[-1]["reason"] == "key_epoch_stale"
    team["rotation_pending"] = True
    await send(relay, a, "a", epoch=1, payload=packet(b"awaiting-rotation"))
    assert a.of("live_item_refused")[-1]["reason"] == "key_epoch_stale"
    team.update({"rotation_pending": False, "team_key_epoch": 3})
    await send(relay, a, "a", epoch=2, payload=packet(b"old", epoch=2))
    assert a.of("live_item_refused")[-1]["reason"] == "key_epoch_stale"
    assert a.of("live_item_refused")[-1]["rejected_epoch"] == 2
    await send(relay, a, "a", epoch=3, payload=packet(b"relabelled", epoch=2))
    assert a.of("live_item_update_ack") == []
    await send(relay, a, "a", epoch=3, payload=packet(b"current", epoch=3))
    assert a.of("live_item_update_ack")[-1]["seq"] == 1
    monkeypatch.setattr(relay_mod, "UPDATE_RATE_PER_SECOND", 50)
    refused_before = len(a.of("live_item_refused"))
    for _ in range(60):
        await send(relay, a, "a", epoch=3, payload=packet(b"p", epoch=3))
    reasons = [r["reason"] for r in a.of("live_item_refused")[refused_before:]]
    assert reasons.count("rate_limited") >= 9


# contract-test: supporting surface=rest_api assertions=live-collab.presence.who-and-where,live-collab.privacy.ciphertext-only
@pytest.mark.asyncio
async def test_presence_relayed_never_stored_and_rate_limited():
    relay, directus, _ = make()
    directus.add_member("a", "member")
    directus.add_member("v", "viewer")
    a, v = await join(relay, "a"), await join(relay, "v")
    await relay.handle(
        v, "v", "live_item_presence", {"item_id": ITEM, "payload": packet(b"cursor", kind=3)}
    )
    got = a.of("live_item_presence")
    assert got[0]["payload"] == packet(b"cursor", kind=3) and got[0]["sender"] == sender_hash("v")
    assert v.of("live_item_presence") == []
    await relay.store.flush()
    assert directus.tables["live_item_updates"] == []
    assert await relay.store.head_seq(hash_id(ITEM)) == 0
    for _ in range(25):
        await relay.handle(
            v, "v", "live_item_presence", {"item_id": ITEM, "payload": packet(b"c", kind=3)}
        )
    assert [r["reason"] for r in v.of("live_item_refused")].count("rate_limited") >= 5


# contract-test: supporting surface=rest_api assertions=live-collab.access.roles
@pytest.mark.asyncio
async def test_removal_mid_session_revokes_then_refuses_updates():
    relay, directus, cache = make()
    directus.add_member("a", "member")
    directus.add_member("b", "member")
    a, b = await join(relay, "a"), await join(relay, "b")
    directus.remove_member("a")
    await relay.revoke_team_member(TEAM, "a")
    assert a.of("live_item_refused") == [{"item_id": ITEM, "reason": "access_revoked"}]
    assert b.of("live_item_refused") == []
    await send(relay, a, "a", payload=packet(b"late"))
    assert a.of("live_item_refused")[-1]["reason"] == "not_found"
    assert (
        directus.tables["live_item_updates"] == []
        and a.of("live_item_update_ack") == []
    )
    assert cache.published[-1][0].endswith("control")
    # another worker applies the published revoke
    other, _, _ = make()
    other.directus = directus
    c = await join(other, "b")
    await other.handle_event(
        "live_item:control",
        {
            "op": "revoke",
            "team": hash_id(TEAM),
            "user": hash_id("b"),
            "origin": "elsewhere",
        },
    )
    assert c.of("live_item_refused")[-1]["reason"] == "access_revoked"


# contract-test: supporting surface=rest_api assertions=live-collab.privacy.ciphertext-only
@pytest.mark.asyncio
async def test_compaction_only_after_confirmed_snapshot():
    relay, directus, _ = make()
    directus.add_member("a", "member")
    directus.add_member("b", "member")
    a, b = await join(relay, "a"), await join(relay, "b")
    for i in range(3):
        await send(relay, a, "a", payload=packet(bytes([i])))
    await relay.store.flush()
    await relay.handle(
        a,
        "a",
        "live_item_snapshot",
        {"item_id": ITEM, "covers_seq": 3, "epoch": 1, "payload": packet(b"snap", kind=2)},
    )
    assert b.of("live_item_snapshot_available")[0]["covers_seq"] == 3
    assert (
        len(directus.tables["live_item_updates"]) == 3
    )  # unconfirmed: nothing compacted
    assert await relay.store.compact(hash_id(ITEM)) == 0
    await relay.handle(
        a, "a", "live_item_snapshot_confirm", {"item_id": ITEM, "covers_seq": 3}
    )
    assert len(directus.tables["live_item_updates"]) == 3  # author cannot confirm
    await relay.handle(
        b, "b", "live_item_snapshot_confirm", {"item_id": ITEM, "covers_seq": 3}
    )
    assert directus.tables["live_item_updates"] == []
    assert directus.tables["live_item_snapshots"][0]["confirmed"] is True
    late = await join(relay, "b")
    state = late.of("live_item_state")[-1]
    assert state["snapshot"]["payload"] == packet(b"snap", kind=2) and state["updates"] == []


# contract-test: supporting surface=rest_api assertions=live-collab.keys.rotation-on-removal
@pytest.mark.asyncio
async def test_rotation_snapshot_with_same_coverage_requires_an_epoch_specific_confirmation():
    relay, directus, _ = make()
    directus.add_member("a", "member")
    directus.add_member("b", "member")
    author = await join(relay, "a")
    for epoch in (1, 2):
        directus.tables["teams"][0]["team_key_epoch"] = epoch
        await relay.handle(author, "a", "live_item_snapshot", {
            "item_id": ITEM, "covers_seq": 0, "epoch": epoch,
            "payload": packet(f"snapshot-{epoch}".encode(), kind=2, epoch=epoch),
        })

    peer = await join(relay, "b")
    assert peer.of("live_item_state")[-1]["snapshot"]["epoch"] == 2
    await relay.handle(peer, "b", "live_item_snapshot_confirm", {
        "item_id": ITEM, "covers_seq": 0, "epoch": 2,
    })
    assert [row["confirmed"] for row in directus.tables["live_item_snapshots"]] == [False, True]
