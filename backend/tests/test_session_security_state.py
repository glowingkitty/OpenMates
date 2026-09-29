"""Durable session authority across cache loss, rotation and revocation."""
import asyncio
from copy import deepcopy

import pytest
from fastapi import HTTPException

from backend.core.api.app.services import session_security_state as state


class Cache:
    def __init__(self):
        self.values = {}

    async def get(self, key):
        return deepcopy(self.values.get(key))

    async def set(self, key, value, ttl):
        self.values[key] = deepcopy(value)
        return True

    async def delete(self, key):
        self.values.pop(key, None)
        return True


class Directus:
    def __init__(self):
        self.rows = {}

    async def get_items(self, collection, *, params, **_kwargs):
        assert collection == state.COLLECTION
        digest = params["filter"]["token_hash"]["_eq"]
        row = self.rows.get(digest)
        return [deepcopy(row)] if row else []

    async def create_item(self, collection, payload, **_kwargs):
        assert collection == state.COLLECTION
        digest = payload["token_hash"]
        if digest in self.rows:
            return False, None
        row = {"id": f"row-{len(self.rows)}", **deepcopy(payload)}
        self.rows[digest] = row
        return True, deepcopy(row)

    async def _update_item(self, collection, item_id, changes, **_kwargs):
        assert collection == state.COLLECTION
        for row in self.rows.values():
            if row["id"] == item_id:
                row.update(deepcopy(changes))
                return deepcopy(row)
        return None


# contract-test: direct surface=rest_api assertions=auth.session.authoritative-enforcement,auth.session.isolation
def test_revoked_session_cannot_reappear_after_cache_loss_or_sibling_rotation(monkeypatch):
    async def run():
        now = [1000]
        monkeypatch.setattr(state.time, "time", lambda: now[0])
        directus, cache = Directus(), Cache()
        await state.register_session_state(directus, cache, "first", "u1", ttl_seconds=86400)
        await state.register_session_state(directus, cache, "sibling", "u1", ttl_seconds=86400)
        await state.get_session_state_cached(directus, cache, state.token_hash("first"))
        await state.revoke_session_state(directus, cache, state.token_hash("first"), "u1")
        cache.values.clear()
        with pytest.raises(HTTPException) as error:
            await state.get_session_state_cached(directus, cache, state.token_hash("first"))
        assert error.value.status_code == 401
        sibling = await state.transfer_session_state(directus, cache, "sibling", "sibling-new")
        assert sibling["expires_at"] == 1000 + 86400
        assert (await state.get_session_state(directus, state.token_hash("sibling-new")))["user_id"] == "u1"

    asyncio.run(run())


# contract-test: direct surface=rest_api assertions=auth.session.authoritative-enforcement
@pytest.mark.parametrize("stale_cache", [
    {"absent": True},
    {"user_id": "u1", "expires_at": 9999999999, "revoked": False, "retired": False},
])
def test_stale_positive_and_negative_cache_cannot_override_revocation(stale_cache):
    async def run():
        directus, cache = Directus(), Cache()
        digest = state.token_hash("revoked")
        await state.register_session_state(directus, cache, "revoked", "u1", ttl_seconds=600)
        await state.revoke_session_state(directus, cache, digest, "u1")
        cache.values[f"auth:session-state:{digest}"] = deepcopy(stale_cache)

        with pytest.raises(HTTPException) as denied:
            await state.get_session_state_cached(directus, cache, digest, user_id="u1")
        assert denied.value.status_code == 401

    asyncio.run(run())


# contract-test: direct surface=rest_api assertions=auth.session.authoritative-enforcement
@pytest.mark.parametrize("registered", [True, False])
def test_inflight_reader_cannot_republish_stale_state_after_revocation(registered):
    class PausedDirectus(Directus):
        def __init__(self):
            super().__init__()
            self.snapshot_ready = asyncio.Event()
            self.resume = asyncio.Event()
            self.pause_next_read = False

        async def get_items(self, *args, **kwargs):
            rows = await super().get_items(*args, **kwargs)
            if self.pause_next_read:
                self.pause_next_read = False
                self.snapshot_ready.set()
                await self.resume.wait()
            return rows

    async def run():
        directus, cache = PausedDirectus(), Cache()
        digest = state.token_hash("inflight")
        if registered:
            await state.register_session_state(directus, cache, "inflight", "u1", ttl_seconds=600)
        directus.pause_next_read = True
        reader = asyncio.create_task(state.get_session_state_cached(directus, cache, digest))
        await directus.snapshot_ready.wait()
        await state.revoke_session_state(directus, cache, digest, "u1")
        directus.resume.set()
        # The in-flight read can linearize before revocation, but must not
        # publish its old active/absent snapshot for later authorizations.
        await reader
        assert f"auth:session-state:{digest}" not in cache.values
        with pytest.raises(HTTPException) as denied:
            await state.get_session_state_cached(directus, cache, digest)
        assert denied.value.status_code == 401

    asyncio.run(run())


# contract-test: direct surface=rest_api assertions=auth.session.authoritative-enforcement,auth.pair-login.approval-assurance
def test_strong_proof_is_session_bound_and_refresh_does_not_extend_it(monkeypatch):
    async def run():
        now = [1000]
        monkeypatch.setattr(state.time, "time", lambda: now[0])
        directus, cache = Directus(), Cache()
        await state.register_session_state(directus, cache, "first", "u1", ttl_seconds=600)
        await state.register_session_state(directus, cache, "other", "u1", ttl_seconds=600)
        await state.mark_recent_strong_proof(directus, cache, "first", "u1")
        await state.require_recent_strong_proof(directus, cache, "first", "u1")
        with pytest.raises(HTTPException):
            await state.require_recent_strong_proof(directus, cache, "other", "u1")
        now[0] += 250
        await state.transfer_session_state(directus, cache, "first", "first-new")
        await state.require_recent_strong_proof(directus, cache, "first-new", "u1")
        now[0] += 50
        with pytest.raises(HTTPException) as error:
            await state.require_recent_strong_proof(directus, cache, "first-new", "u1")
        assert error.value.status_code == 401
        now[0] += 301
        with pytest.raises(HTTPException) as error:
            await state.get_session_state_cached(directus, cache, state.token_hash("first-new"))
        assert error.value.status_code == 401

    asyncio.run(run())


# contract-test: direct surface=rest_api assertions=auth.sensitive-actions.recent-verification
def test_password_v2_email_proof_is_accepted_with_distinct_provenance():
    async def run():
        directus, cache = Directus(), Cache()
        await state.register_session_state(directus, cache, "v2-cookie", "u1", ttl_seconds=600)
        await state.mark_recent_strong_proof(
            directus, cache, "v2-cookie", "u1", method="password_v2_email",
        )
        row = await state.get_session_state(directus, state.token_hash("v2-cookie"), user_id="u1")
        assert row["proof_method"] == "password_v2_email"
        await state.require_recent_strong_proof(directus, cache, "v2-cookie", "u1")

    asyncio.run(run())


# contract-test: direct surface=rest_api assertions=auth.session.authoritative-enforcement
def test_legacy_revocation_creates_tombstone_and_state_failure_fails_closed():
    async def run():
        directus, cache = Directus(), Cache()
        digest = state.token_hash("legacy")
        assert await state.get_session_state_cached(directus, cache, digest) is None
        await state.revoke_session_state(directus, cache, digest, "u1")
        with pytest.raises(HTTPException) as error:
            await state.get_session_state_cached(directus, cache, digest)
        assert error.value.status_code == 401

        async def unavailable(*_args, **_kwargs):
            raise OSError("database down")

        directus.get_items = unavailable
        cache.values.clear()
        with pytest.raises(HTTPException) as error:
            await state.get_session_state_cached(directus, cache, digest)
        assert error.value.status_code == 503

    asyncio.run(run())


# contract-test: direct surface=rest_api assertions=auth.session.authoritative-enforcement,auth.session.lifecycle
def test_first_use_migration_fixes_deadline_and_does_not_extend_it(monkeypatch):
    async def run():
        clock = [1000]
        monkeypatch.setattr(state.time, "time", lambda: clock[0])
        directus, cache = Directus(), Cache()
        cache.SESSION_TTL = 86400
        digest = state.token_hash("old-cookie")
        cache.values["user_tokens:u1"] = {digest: {"stay_logged_in": True}}
        first = await state.ensure_legacy_session_state(directus, cache, "old-cookie", "u1")
        assert first["expires_at"] == 1000 + 30 * 86400
        clock[0] += 300
        again = await state.ensure_legacy_session_state(directus, cache, "old-cookie", "u1")
        assert again["expires_at"] == first["expires_at"]
        await state.revoke_session_state(directus, cache, digest, "u1")
        with pytest.raises(HTTPException):
            await state.ensure_legacy_session_state(directus, cache, "old-cookie", "u1")

    asyncio.run(run())


# contract-test: direct surface=rest_api assertions=auth.session.authoritative-enforcement,auth.session.lifecycle
def test_signed_ws_session_hash_migrates_with_fixed_deadline(monkeypatch):
    async def run():
        clock = [1000]
        monkeypatch.setattr(state.time, "time", lambda: clock[0])
        directus, cache = Directus(), Cache()
        cache.SESSION_TTL = 86400
        digest = state.token_hash("old-signed-ws-session")
        first = await state.ensure_legacy_session_hash_state(directus, cache, digest, "u1")
        assert first["token_hash"] == digest
        assert first["expires_at"] == 1000 + 86400
        clock[0] += 300
        assert (await state.ensure_legacy_session_hash_state(
            directus, cache, digest, "u1",
        ))["expires_at"] == first["expires_at"]
        clock[0] += 86400
        with pytest.raises(HTTPException) as expired:
            await state.ensure_legacy_session_hash_state(directus, cache, digest, "u1")
        assert expired.value.status_code == 401

    asyncio.run(run())


# contract-test: direct surface=rest_api assertions=auth.session.risk-reauth,auth.session.isolation
def test_pending_risk_denies_same_session_until_verified_and_preserves_sibling():
    async def run():
        directus, cache = Directus(), Cache()
        await state.register_session_state(directus, cache, "at-risk", "u1", ttl_seconds=600)
        await state.register_session_state(directus, cache, "sibling", "u1", ttl_seconds=600)
        await state.mark_recent_strong_proof(directus, cache, "at-risk", "u1", method="passkey")
        await state.set_session_risk_pending(directus, cache, "at-risk", "u1", True)
        with pytest.raises(HTTPException) as pending:
            await state.get_session_state_cached(
                directus, cache, state.token_hash("at-risk"), allow_risk=False,
            )
        assert pending.value.status_code == 401
        with pytest.raises(HTTPException):
            await state.require_recent_strong_proof(directus, cache, "at-risk", "u1")
        await state.get_session_state_cached(directus, cache, state.token_hash("sibling"), allow_risk=False)
        await state.mark_recent_strong_proof(
            directus, cache, "at-risk", "u1", method="passkey", clear_risk=True,
        )
        await state.require_recent_strong_proof(directus, cache, "at-risk", "u1")

    asyncio.run(run())


# contract-test: direct surface=rest_api assertions=auth.login.verified-method,auth.session.lifecycle
def test_verified_password_v1_login_binding_survives_refresh_without_renewal(monkeypatch):
    async def run():
        clock = [1000]
        monkeypatch.setattr(state.time, "time", lambda: clock[0])
        directus, cache = Directus(), Cache()
        digest = state.token_hash("accepted-lookup-hash")
        original = await state.register_session_state(
            directus, cache, "old-cookie", "u1", ttl_seconds=86400,
            verified_login_method="password", verified_credential_version=1,
            verified_lookup_digest=digest,
        )
        assert original["login_verified_at"] == 1000
        assert original["verified_lookup_digest"] == digest
        clock[0] += 299
        rotated = await state.transfer_session_state(
            directus, cache, "old-cookie", "new-cookie",
        )
        assert rotated["verified_login_method"] == "password"
        assert rotated["verified_credential_version"] == 1
        assert rotated["verified_lookup_digest"] == digest
        assert rotated["login_verified_at"] == 1000
        clock[0] += 2
        assert clock[0] - rotated["login_verified_at"] >= 300

        with pytest.raises(ValueError):
            await state.register_session_state(
                directus, cache, "invalid", "u1", ttl_seconds=86400,
                verified_login_method="password", verified_credential_version=1,
                verified_lookup_digest="accepted-lookup-hash",
            )

    asyncio.run(run())
