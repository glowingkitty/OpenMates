"""Pair-only deadline and pending acknowledgement survive Redis loss and rotation."""
import hashlib

import pytest
from fastapi import HTTPException

from backend.core.api.app.services import pair_session_deadline as deadlines


class Cache:
    SESSION_TTL = 86400

    def __init__(self):
        self.values = {}

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, ttl=None):
        self.values[key] = value
        return True


class Directus:
    def __init__(self):
        self.rows = {}
        self.next_id = 0

    async def get_items(self, collection, params=None, **kwargs):
        assert collection == "pair_session_deadlines"
        key = params["filter"]["token_hash"]["_eq"]
        row = self.rows.get(key)
        return [dict(row)] if row else []

    async def create_item(self, collection, payload, **kwargs):
        assert collection == "pair_session_deadlines"
        key = payload["token_hash"]
        if key in self.rows:
            return False, {}
        self.next_id += 1
        row = {"id": str(self.next_id), **payload}
        self.rows[key] = row
        return True, dict(row)

    async def _update_item(self, collection, row_id, payload, **kwargs):
        assert collection == "pair_session_deadlines"
        row = next((r for r in self.rows.values() if r["id"] == row_id), None)
        if row is None:
            return None
        row.update(payload)
        return dict(row)


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=auth.session.lifecycle,auth.session.isolation
async def test_pending_pair_stays_denied_after_cache_loss_until_ack():
    db, cache = Directus(), Cache()
    await deadlines.register_pair_session(db, cache, "pair-token", "user-1", None)
    with pytest.raises(HTTPException) as error:
        await deadlines.enforce_pair_deadline(db, cache, "pair-token")
    assert error.value.status_code == 401

    cache.values.clear()
    with pytest.raises(HTTPException) as error:
        await deadlines.enforce_pair_deadline(db, cache, "pair-token")
    assert error.value.status_code == 401

    await deadlines.activate_pair_session(db, cache, digest("pair-token"), "user-1")
    with pytest.raises(HTTPException):
        await deadlines.get_pair_deadline(db, cache, "pair-token")
    await deadlines.confirm_pair_session(db, cache, digest("pair-token"), "user-1")
    assert await deadlines.get_pair_deadline(db, cache, "pair-token") == (None, "user-1")
    cache.values.clear()
    assert await deadlines.get_pair_deadline(db, cache, "pair-token") == (None, "user-1")


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=auth.session.lifecycle,auth.session.isolation
async def test_numeric_deadline_and_retired_old_hash_survive_rotation_and_cache_loss(monkeypatch):
    now = [1_800_000_000]
    monkeypatch.setattr(deadlines.time, "time", lambda: now[0])
    db, cache = Directus(), Cache()
    expiry = now[0] + 1800
    await deadlines.register_pair_session(db, cache, "old", "user-1", expiry)
    await deadlines.activate_pair_session(db, cache, digest("old"), "user-1")
    await deadlines.confirm_pair_session(db, cache, digest("old"), "user-1")
    await deadlines.transfer_pair_deadline(db, cache, "old", "new", expiry, "user-1")

    cache.values.clear()
    with pytest.raises(HTTPException) as error:
        await deadlines.get_pair_deadline(db, cache, "old")
    assert error.value.status_code == 401
    assert await deadlines.get_pair_deadline(db, cache, "new") == (expiry, "user-1")
    now[0] = expiry
    with pytest.raises(HTTPException) as error:
        await deadlines.get_pair_deadline(db, cache, "new")
    assert error.value.status_code == 401


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=auth.session.lifecycle,auth.session.isolation
async def test_null_lifetime_keeps_pair_membership_and_missing_warm_marker_falls_back():
    db, cache = Directus(), Cache()
    await deadlines.register_pair_session(db, cache, "old", "user-1", None)
    await deadlines.activate_pair_session(db, cache, digest("old"), "user-1")
    await deadlines.confirm_pair_session(db, cache, digest("old"), "user-1")
    # A partial cache writer cannot make this paired token an ordinary token.
    cache.values[f"session:{digest('old')}"] = {"user_id": "user-1"}
    assert await deadlines.get_pair_deadline(db, cache, "old") == (None, "user-1")
    await deadlines.transfer_pair_deadline(db, cache, "old", "new", None, "user-1")
    cache.values.clear()
    assert await deadlines.get_pair_deadline(db, cache, "new") == (None, "user-1")
    with pytest.raises(HTTPException):
        await deadlines.get_pair_deadline(db, cache, "old")


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=auth.pair-login.lifecycle,auth.pair-login.expiry
async def test_partial_ack_and_warm_retired_link_stay_denied():
    db, cache = Directus(), Cache()
    await deadlines.register_pair_session(db, cache, "old", "user-1", None)
    await deadlines.activate_pair_session(db, cache, digest("old"), "user-1")
    # A failed relay ACK cannot activate the Directus row, even after cache loss.
    with pytest.raises(HTTPException) as error:
        await deadlines.get_pair_deadline(db, cache, "old")
    assert error.value.status_code == 401
    cache.values.clear()
    with pytest.raises(HTTPException):
        await deadlines.get_pair_deadline(db, cache, "old")

    await deadlines.confirm_pair_session(db, cache, digest("old"), "user-1")
    await deadlines.transfer_pair_deadline(db, cache, "old", "new", None, "user-1")
    # A failure before complete_refresh_rotation leaves the old cache link warm.
    assert f"session:{digest('old')}" in cache.values
    with pytest.raises(HTTPException) as error:
        await deadlines.get_pair_deadline(db, cache, "old")
    assert error.value.status_code == 401
    assert await deadlines.get_pair_deadline(db, cache, "new") == (None, "user-1")


@pytest.mark.asyncio
# contract-test: direct surface=rest_api assertions=auth.pair-login.expiry,auth.session.isolation
async def test_verified_ordinary_membership_cache_cannot_hide_new_pair_marker():
    db, cache = Directus(), Cache()
    assert await deadlines.get_pair_deadline(db, cache, "new-pair-token") is None
    assert cache.values[deadlines._membership_key(digest("new-pair-token"))] == "absent"
    await deadlines.register_pair_session(db, cache, "new-pair-token", "user-1", None)
    assert cache.values[deadlines._membership_key(digest("new-pair-token"))] == "present"
    with pytest.raises(HTTPException) as error:
        await deadlines.get_pair_deadline(db, cache, "new-pair-token")
    assert error.value.status_code == 401
