"""Exercise the production pairing Lua against isolated Redis-compatible storage.

These are relay-state unit tests: no product server, account, or shared Redis is used.
"""

import asyncio
import base64
import hashlib
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import fakeredis.aioredis
import pytest
from fastapi import HTTPException, Response

from backend.core.api.app.routes.auth_routes import auth_pair_v2 as pair


TOKEN = "ABCDEF"
RECEIVER = hashlib.sha256(b"receiver capability").hexdigest()
OTHER_RECEIVER = hashlib.sha256(b"another receiver capability").hexdigest()
GRANT = hashlib.sha256(b"one-use grant").hexdigest()
AUTHORIZER = {"user_id": "approver", "binding": "b" * 64}


class Cache:
    def __init__(self, client):
        self._client = client

    @property
    async def client(self):
        return self._client

    async def get(self, key):
        raw = await self._client.get(key)
        return json.loads(raw) if raw is not None else None


@pytest.fixture
async def relay():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    cache = Cache(client)
    state = {
        "status": "waiting", "protocol_version": 2,
        "receiver_token_hash": RECEIVER, "session_id": "new-device-session",
        "device_name": "Test receiver", "created_at": int(time.time()),
        "expires_at": int(time.time()) + pair.PAIR_TTL, "attempts": 0,
    }
    await client.set(pair._key(TOKEN), json.dumps(state), ex=pair.PAIR_TTL)
    try:
        yield cache
    finally:
        await client.aclose()


async def change(cache, operation, **payload):
    return await pair._change(cache, TOKEN, operation, payload)


async def rejects(cache, operation, code, detail, **payload):
    with pytest.raises(HTTPException) as error:
        await change(cache, operation, **payload)
    assert error.value.status_code == code
    assert error.value.detail == detail


async def advance_to_ready(cache, grant_hash=GRANT):
    await change(cache, "approve", **AUTHORIZER, device_name="Test approver", auto_logout_minutes=30)
    await change(cache, "request", receiver_hash=RECEIVER, message="opaque PAKE request")
    await change(cache, "response", **AUTHORIZER, message="opaque PAKE response")
    await change(cache, "finish", receiver_hash=RECEIVER, message="opaque PAKE finish")
    return await change(cache, "authorize", **AUTHORIZER, encrypted_bundle="encrypted master bundle", iv="nonce", grant_hash=grant_hash)


# contract-test: direct surface=rest_api assertions=auth.pair-login.session-grant,auth.pair-login.lifecycle
@pytest.mark.asyncio
async def test_complete_issues_session_without_fabricated_login_lookup(relay, monkeypatch):
    secret = b"g" * 32
    grant_hash = hashlib.sha256(secret).hexdigest()
    grant_secret = base64.urlsafe_b64encode(secret).decode().rstrip("=")
    receiver_secret = b"r" * 32
    receiver_capability = base64.urlsafe_b64encode(receiver_secret).decode().rstrip("=")
    await advance_to_ready(relay, grant_hash=grant_hash)
    # Use the real receiver capability format and bind it to this relay.
    state = await relay.get(pair._key(TOKEN))
    state["receiver_token_hash"] = hashlib.sha256(receiver_secret).hexdigest()
    await relay._client.set(pair._key(TOKEN), json.dumps(state), keepttl=True)

    class Directus:
        async def create_trusted_user_session(self, user_id):
            assert user_id == "approver"
            return True, {"user": {"id": user_id}, "cookies": {"auth_refresh_token": "issued-refresh"}}, None

        async def get_user_profile(self, user_id):
            assert user_id == "approver"
            return True, {"username": "paired-user", "credits": 13, "vault_key_id": "vault-key"}, None

    issued = AsyncMock(return_value="issued-refresh")
    registered = AsyncMock()
    monkeypatch.setattr(pair, "finalize_login_session", issued)
    monkeypatch.setattr(pair, "register_pair_session", registered)
    monkeypatch.setattr(pair, "generate_device_fingerprint_hash", lambda *_: ("device", "connection", None, "US", "City", None, None, None))
    request = SimpleNamespace(headers={"user-agent": "test"}, client=SimpleNamespace(host="127.0.0.1"),
                              app=SimpleNamespace(state=SimpleNamespace()))
    response = Response()
    result = await pair.complete(request, response, TOKEN, pair.Complete(grant_secret=grant_secret),
                                 receiver_capability, relay, Directus(), SimpleNamespace(), SimpleNamespace())

    context = issued.await_args.args[14]
    assert isinstance(context, pair.PairingSessionContext)
    assert context.session_id == "new-device-session"
    assert context.login_method == "pairing"
    assert context.lookup_hash is None
    assert result.user.username == "paired-user"
    assert result.user.credits == 13
    registered.assert_awaited_once()
    assert registered.await_args.args[:4] == (issued.await_args.args[6], relay, "issued-refresh", "approver")
    assert int(time.time()) < registered.await_args.args[4] <= int(time.time()) + 1800
    persisted = await relay.get(pair._key(TOKEN))
    assert persisted["status"] == "completed"
    assert persisted["session_token_hash"] == hashlib.sha256(b"issued-refresh").hexdigest()
    assert not {"grant_hash", "encrypted_bundle", "iv"}.intersection(persisted)
    with pytest.raises(HTTPException) as reused:
        await pair.complete(request, Response(), TOKEN, pair.Complete(grant_secret=grant_secret),
                            receiver_capability, relay, Directus(), SimpleNamespace(), SimpleNamespace())
    assert reused.value.status_code == 409
    issued.assert_awaited_once()


# contract-test: direct surface=rest_api assertions=auth.pair-login.single-use-zk,auth.pair-login.lifecycle
@pytest.mark.asyncio
async def test_ordered_relay_keeps_ttl_and_erases_one_use_bundle_after_claim(relay):
    initial_ttl = await relay._client.ttl(pair._key(TOKEN))
    await rejects(relay, "request", 409, "conflict", receiver_hash=RECEIVER, message="early")
    ready = await advance_to_ready(relay)
    assert ready["status"] == "ready"
    assert ready["grant_hash"] == GRANT
    assert 0 < await relay._client.ttl(pair._key(TOKEN)) <= initial_ttl
    await rejects(relay, "claim", 401, "invalid_grant", receiver_hash=RECEIVER, grant_hash="0" * 64)
    assert (await relay.get(pair._key(TOKEN)))["attempts"] == 1

    claimed = await change(relay, "claim", receiver_hash=RECEIVER, grant_hash=GRANT)
    assert claimed["status"] == "claimed"
    assert not {"encrypted_bundle", "iv", "grant_hash"}.intersection(claimed)
    await rejects(relay, "claim", 409, "conflict", receiver_hash=RECEIVER, grant_hash=GRANT)
    await change(relay, "complete", session_token_hash="s" * 64)
    assert (await change(relay, "ack_begin", receiver_hash=RECEIVER))["status"] == "acknowledging"
    assert (await change(relay, "ack_finish", receiver_hash=RECEIVER))["status"] == "acknowledged"
    assert 0 < await relay._client.ttl(pair._key(TOKEN)) <= initial_ttl
    persisted = await relay.get(pair._key(TOKEN))
    assert persisted["status"] == "acknowledged"
    assert not {"pin", "grant_secret", "master_key", "encrypted_bundle", "iv", "grant_hash"}.intersection(persisted)


# contract-test: direct surface=rest_api assertions=auth.pair-login.single-use-zk,auth.pair-login.lifecycle
@pytest.mark.asyncio
async def test_receiver_and_approving_session_are_bound_at_every_relay_stage(relay):
    await change(relay, "approve", **AUTHORIZER, device_name="Test approver", auto_logout_minutes=None)
    await rejects(relay, "approve", 409, "conflict", **AUTHORIZER)
    await rejects(relay, "request", 403, "forbidden", receiver_hash=OTHER_RECEIVER, message="request")
    await change(relay, "request", receiver_hash=RECEIVER, message="request")
    await rejects(relay, "response", 403, "forbidden", user_id="other", binding=AUTHORIZER["binding"], message="response")
    await rejects(relay, "response", 403, "forbidden", user_id="approver", binding="c" * 64, message="response")
    await change(relay, "response", **AUTHORIZER, message="response")
    await rejects(relay, "finish", 403, "forbidden", receiver_hash=OTHER_RECEIVER, message="finish")
    await change(relay, "finish", receiver_hash=RECEIVER, message="finish")
    await rejects(relay, "authorize", 403, "forbidden", user_id="approver", binding="c" * 64,
                  encrypted_bundle="bundle", iv="nonce", grant_hash=GRANT)
    await change(relay, "authorize", **AUTHORIZER, encrypted_bundle="bundle", iv="nonce", grant_hash=GRANT)
    await rejects(relay, "claim", 403, "forbidden", receiver_hash=OTHER_RECEIVER, grant_hash=GRANT)
    await rejects(relay, "cancel", 403, "forbidden", receiver_hash=OTHER_RECEIVER)
    await rejects(relay, "cancel", 403, "forbidden", user_id="approver", binding="c" * 64)
    assert (await relay.get(pair._key(TOKEN)))["status"] == "ready"


# contract-test: direct surface=rest_api assertions=auth.pair-login.session-grant,auth.pair-login.single-use-zk
@pytest.mark.asyncio
async def test_simultaneous_grant_claims_have_exactly_one_winner(relay):
    await advance_to_ready(relay)
    outcomes = await asyncio.gather(
        change(relay, "claim", receiver_hash=RECEIVER, grant_hash=GRANT),
        change(relay, "claim", receiver_hash=RECEIVER, grant_hash=GRANT),
        return_exceptions=True,
    )
    winners = [result for result in outcomes if isinstance(result, dict)]
    losers = [result for result in outcomes if isinstance(result, HTTPException)]
    assert len(winners) == len(losers) == 1
    assert winners[0]["status"] == "claimed"
    assert (losers[0].status_code, losers[0].detail) == (409, "conflict")
    state = await relay.get(pair._key(TOKEN))
    assert state["status"] == "claimed"
    assert not {"encrypted_bundle", "iv", "grant_hash"}.intersection(state)


# contract-test: direct surface=rest_api assertions=auth.pair-login.lifecycle,auth.pair-login.session-grant
@pytest.mark.asyncio
async def test_cancel_and_ack_begin_race_has_one_terminal_path(relay):
    await advance_to_ready(relay)
    await change(relay, "claim", receiver_hash=RECEIVER, grant_hash=GRANT)
    await change(relay, "complete", session_token_hash="s" * 64)
    outcomes = await asyncio.gather(
        change(relay, "ack_begin", receiver_hash=RECEIVER),
        change(relay, "cancel", **AUTHORIZER),
        return_exceptions=True,
    )
    successes = [result for result in outcomes if isinstance(result, dict)]
    conflicts = [result for result in outcomes if isinstance(result, HTTPException)]
    assert len(successes) == len(conflicts) == 1
    assert (conflicts[0].status_code, conflicts[0].detail) == (409, "conflict")
    status = (await relay.get(pair._key(TOKEN)))["status"]
    assert status in {"cancelled", "acknowledging"}
    if status == "acknowledging":
        await rejects(relay, "cancel", 409, "conflict", **AUTHORIZER)
        assert (await change(relay, "ack_finish", receiver_hash=RECEIVER))["status"] == "acknowledged"
    else:
        await rejects(relay, "ack_begin", 409, "conflict", receiver_hash=RECEIVER)


# contract-test: direct surface=rest_api assertions=auth.pair-login.lifecycle,auth.pair-login.session-grant
@pytest.mark.asyncio
async def test_ack_retry_is_idempotent_but_cancel_and_foreign_ack_are_denied(relay):
    await advance_to_ready(relay)
    await change(relay, "claim", receiver_hash=RECEIVER, grant_hash=GRANT)
    await change(relay, "complete", session_token_hash="s" * 64)
    await change(relay, "ack_begin", receiver_hash=RECEIVER)
    assert (await change(relay, "ack_begin", receiver_hash=RECEIVER))["status"] == "acknowledging"
    await rejects(relay, "ack_finish", 403, "forbidden", receiver_hash=OTHER_RECEIVER)
    await change(relay, "ack_finish", receiver_hash=RECEIVER)
    assert (await change(relay, "ack_begin", receiver_hash=RECEIVER))["status"] == "acknowledged"
    assert (await change(relay, "ack_finish", receiver_hash=RECEIVER))["status"] == "acknowledged"
    await rejects(relay, "cancel", 409, "conflict", receiver_hash=RECEIVER)


# contract-test: direct surface=rest_api assertions=auth.pair-login.lifecycle,auth.pair-login.expiry
@pytest.mark.asyncio
async def test_expired_key_is_distinct_from_live_cancelled_and_failed_states(relay):
    await change(relay, "cancel", receiver_hash=RECEIVER)
    assert (await pair._state(relay, TOKEN))["status"] == "cancelled"
    await rejects(relay, "request", 409, "conflict", receiver_hash=RECEIVER, message="late")
    await relay._client.expire(pair._key(TOKEN), 0)
    with pytest.raises(HTTPException) as expired:
        await pair._state(relay, TOKEN)
    assert expired.value.status_code == 404
    await rejects(relay, "request", 404, "expired", receiver_hash=RECEIVER, message="late")


# contract-test: direct surface=rest_api assertions=auth.pair-login.single-use-zk,auth.pair-login.lifecycle
@pytest.mark.asyncio
async def test_wrong_grant_is_bounded_and_never_allows_later_claim(relay):
    await advance_to_ready(relay)
    for _ in range(pair.MAX_GRANT_ATTEMPTS - 1):
        await rejects(relay, "claim", 401, "invalid_grant", receiver_hash=RECEIVER, grant_hash="0" * 64)
    await rejects(relay, "claim", 429, "too_many_attempts", receiver_hash=RECEIVER, grant_hash="0" * 64)
    assert (await relay.get(pair._key(TOKEN)))["status"] == "failed"
    await rejects(relay, "claim", 409, "conflict", receiver_hash=RECEIVER, grant_hash=GRANT)
