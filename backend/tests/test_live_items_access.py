"""Live item access changes mid-session and multi-device delivery.

Reuses the in-memory fakes of test_live_items_relay. See docs/plans/live-collaboration-crdt.
"""

import pytest

from backend.core.api.app.services.live_items.relay import LiveItemRelay
from backend.core.api.app.services.live_items.access import hash_id
from backend.tests.test_live_items_relay import ITEM, TEAM, Socket, b64, join, make, send


# contract-test: supporting surface=rest_api assertions=live-collab.access.roles
@pytest.mark.asyncio
async def test_role_lowered_to_viewer_goes_read_only_once_and_raise_restores():
    relay, directus, cache = make()
    directus.add_member("a", "member")
    ws = await join(relay, "a")
    await relay.change_team_member_role("team-1", "a", "viewer")
    assert ws.of("live_item_refused") == [{"item_id": ITEM, "reason": "read_only"}]
    await send(relay, ws, "a", payload=b64(b"x"))
    assert ws.of("live_item_refused")[-1]["reason"] == "read_only"
    assert directus.tables["live_item_updates"] == []
    await relay.change_team_member_role("team-1", "a", "member")
    await send(relay, ws, "a", payload=b64(b"x"))
    assert ws.of("live_item_update_ack")
    assert cache.published[0][1]["op"] == "role"


# contract-test: supporting surface=rest_api assertions=live-collab.access.roles
@pytest.mark.asyncio
async def test_role_change_applies_on_other_worker_via_control_event():
    relay, directus, cache = make()
    directus.add_member("a", "member")
    other = LiveItemRelay(directus, cache)
    ws = await join(other, "a")
    await relay.change_team_member_role("team-1", "a", "viewer")
    channel, event = cache.published[-1]
    await other.handle_event(channel, event)
    assert ws.of("live_item_refused") == [{"item_id": ITEM, "reason": "read_only"}]


# contract-test: supporting surface=rest_api assertions=live-collab.access.roles
@pytest.mark.asyncio
async def test_role_change_does_not_touch_other_users():
    relay, directus, _ = make()
    directus.add_member("a", "member")
    directus.add_member("b", "member")
    wb = await join(relay, "b")
    await relay.change_team_member_role("team-1", "a", "viewer")
    assert wb.of("live_item_refused") == []


# contract-test: supporting surface=rest_api assertions=live-collab.devices.same-account
@pytest.mark.asyncio
async def test_two_devices_of_one_user_get_updates_except_sender_and_show_separately():
    relay, directus, _ = make(team=False)
    phone, laptop = await join(relay, "owner"), await join(relay, "owner")
    await send(relay, phone, "owner", payload=b64(b"x"))
    assert len(laptop.of("live_item_update")) == 1
    assert phone.of("live_item_update") == []
    await relay.handle(
        phone, "owner", "live_item_presence", {"item_id": ITEM, "payload": b64(b"p")}
    )
    seen = laptop.of("live_item_presence")
    assert len(seen) == 1 and seen[0]["connection"]
    await relay.handle(
        laptop, "owner", "live_item_presence", {"item_id": ITEM, "payload": b64(b"p")}
    )
    back = phone.of("live_item_presence")[0]
    assert back["sender"] == seen[0]["sender"]
    assert back["connection"] != seen[0]["connection"]


# contract-test: supporting surface=rest_api assertions=live-collab.access.roles
@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["doc", "sheet", "deck", "code"])
async def test_subscribe_with_contract_kind_is_admitted(kind):
    """Clients send the editor kind (build contract), not the storage class."""
    relay, directus, cache = make()
    directus.add_member("a", "member")
    ws = Socket()
    await relay.handle(ws, "a", "live_item_subscribe", {"item_id": ITEM, "kind": kind})
    assert ws.of("live_item_refused") == []
    assert len(ws.of("live_item_state")) == 1


# contract-test: supporting surface=rest_api assertions=live-collab.access.roles
@pytest.mark.asyncio
async def test_subscribe_with_unknown_kind_is_not_found():
    relay, directus, cache = make()
    directus.add_member("a", "member")
    ws = Socket()
    await relay.handle(ws, "a", "live_item_subscribe", {"item_id": ITEM, "kind": "chat"})
    assert ws.of("live_item_refused") == [{"item_id": ITEM, "reason": "not_found"}]


# contract-test: supporting surface=rest_api assertions=live-collab.access.roles
@pytest.mark.asyncio
async def test_team_project_file_admits_team_member_through_its_project_item():
    """A Team Project file is an embed owned by its creator; members get in via the Project's Team."""
    relay, directus, cache = make(team=False)
    directus.tables["project_items"].append(
        {"target_id_hash": hash_id(ITEM), "hashed_team_id": hash_id(TEAM)}
    )
    directus.add_member("member-b", "member")
    ws = Socket()
    await relay.handle(ws, "member-b", "live_item_subscribe", {"item_id": ITEM, "kind": "doc"})
    assert ws.of("live_item_refused") == []
    assert len(ws.of("live_item_state")) == 1


# contract-test: supporting surface=rest_api assertions=live-collab.access.roles
@pytest.mark.asyncio
async def test_personal_file_still_refuses_other_users():
    relay, directus, cache = make(team=False)
    directus.add_member("stranger", "member")
    ws = Socket()
    await relay.handle(ws, "stranger", "live_item_subscribe", {"item_id": ITEM, "kind": "doc"})
    assert ws.of("live_item_refused") == [{"item_id": ITEM, "reason": "not_found"}]
