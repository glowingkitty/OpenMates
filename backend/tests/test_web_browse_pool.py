"""Cross-owner storage isolation, exclusive handoff and crash cleanup."""

import asyncio
import base64
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
import json
import time
from types import SimpleNamespace
import uuid

from fastapi import HTTPException
import pytest

from backend.core.api.app.services.web_browse_pool import BrowsePool
from backend.shared.providers.e2b_browser import BrowserUnavailable


class Database:
    def __init__(self):
        self.items = {
            "browser_pool": {},
            "browser_pool_claims": {},
            "browser_sessions": {},
        }
        self.lock = asyncio.Lock()

    async def create_item(self, collection, row, **kwargs):
        async with self.lock:
            if row["id"] in self.items[collection] or (
                collection == "browser_pool_claims"
                and any(
                    r["session_id"] == row["session_id"]
                    for r in self.items[collection].values()
                )
            ):
                return False, {}
            self.items[collection][row["id"]] = deepcopy(row)
            return True, deepcopy(row)

    async def get_items(self, collection, params, **kwargs):
        filters = json.loads(params.get("filter", "{}"))
        if "filter[id][_eq]" in params:
            filters["id"] = {"_eq": params["filter[id][_eq]"]}

        def matches(row):
            for k, conditions in filters.items():
                for op, v in conditions.items():
                    x = row.get(k)
                    if (
                        op == "_eq"
                        and x != v
                        or op == "_in"
                        and x not in v
                        or op == "_gt"
                        and x <= v
                        or op == "_lte"
                        and x > v
                    ):
                        return False
            return True

        return [deepcopy(r) for r in self.items[collection].values() if matches(r)][
            : params.get("limit", 100)
        ]

    async def update_item_if_version(
        self, collection, identity, values, expected, **kwargs
    ):
        async with self.lock:
            row = self.items[collection][identity]
            if (
                row["version"] != expected
                or row[kwargs["owner_hash_field"]] != kwargs["owner_hash"]
            ):
                return None
            if any(row.get(k) != v for k, v in kwargs.get("extra_filters", {}).items()):
                return None
            row.update(deepcopy(values))
            return deepcopy(row)

    async def bulk_delete_items(self, collection, ids):
        for identity in ids:
            self.items[collection].pop(identity, None)
        return True


class Encryption:
    async def encrypt(self, value):
        return "vault:" + base64.b64encode(value.encode()).decode(), "v1"

    async def decrypt(self, value):
        return base64.b64decode(value[6:]).decode() if value else None


class Store:
    def __init__(self):
        self.db = Database()
        self.encryption = Encryption()
        self.records = {}

    @asynccontextmanager
    async def lease(self, key, **kwargs):
        yield

    async def load(self, identity, owner):
        if identity not in self.records:
            raise HTTPException(404)
        return deepcopy(self.records[identity])

    async def owned(self, identity, provider):
        self.records[identity] = {
            "provider": deepcopy(provider),
            "status": "ai",
            "active_run": "run",
            "last_activity": time.time(),
        }
        self.db.items["browser_sessions"][identity] = {
            "id": identity,
            "status": "ai",
            "expires_at": time.time() + 86400,
        }


class Driver:
    scope = "development"

    def __init__(self):
        self.machines = {}
        self.created = []
        self.killed = []
        self.dirty_template = False

    def validate_creation(self):
        return "public-blank-template"

    async def create(self, *, session_id, owner, on_created):
        sid = str(uuid.uuid4())
        state = {
            k: {}
            for k in ("cookies", "localStorage", "sessionStorage", "indexedDB", "cache")
        }
        if self.dirty_template:
            state["cookies"]["account"] = "unexpected-user"
        self.machines[sid] = state
        provider = {
            "sandbox_id": sid,
            "token": "private-" + sid,
            "traffic_access_token": "private-ingress",
            "cpu_count": 2,
            "memory_mb": 4096,
            "created_at": time.time() - 8,
            "running_since": time.time() - 8,
            "provider_deadline": time.time() + 120,
        }
        self.created.append(sid)
        await on_created(provider)
        return provider

    async def rpc(self, provider, body):
        return {"pristine": not any(self.machines[provider["sandbox_id"]].values())}

    async def pause(self, provider):
        pass

    async def info(self, provider):
        return SimpleNamespace(state="paused")

    async def kill(self, provider):
        sid = provider["sandbox_id"]
        self.killed.append(sid)
        self.machines.pop(sid, None)


@pytest.fixture
def pool(monkeypatch):
    monkeypatch.setenv("E2B_BROWSE_POOL_SIZE", "3")
    monkeypatch.setenv("E2B_BROWSE_PREBOOTED", "true")
    return BrowsePool(Store(), Driver())


# contract-test: supporting surface=rest_api assertions=web-browse.private-storage-and-api,web-browse.session-and-run,web-browse.cost-accounting
@pytest.mark.asyncio
async def test_claim_is_exclusive_and_platform_credentials_are_scrubbed_before_return(
    pool,
):
    await pool.prepare()
    owners = [str(uuid.uuid4()), str(uuid.uuid4())]

    async def claim(owner):
        return await pool.claim(owner, lambda p: pool.store.owned(owner, p))

    results = await asyncio.gather(*(claim(owner) for owner in owners))
    assert sum(r is not None for r in results) == 1
    provider = next(r for r in results if r is not None)
    assert provider["running_since"] is None  # No paid user resume before admission.
    assert provider["pool_assigned"] and not provider["pool_verified"]
    row = next(iter(pool.db.items["browser_pool"].values()))
    assert row["status"] == "claimed" and row["encrypted_payload"] == ""
    assert provider["token"] not in json.dumps(row)
    assert provider["traffic_access_token"] not in json.dumps(row)
    assert len(pool.driver.created) == 1  # No cold creation on a pool miss.


# contract-test: supporting surface=rest_api assertions=web-browse.private-storage-and-api,web-browse.session-and-run
@pytest.mark.asyncio
async def test_user_cookies_cache_and_storage_never_enter_another_assignment(pool):
    await pool.prepare()
    first_owner = str(uuid.uuid4())
    first = await pool.claim(first_owner, lambda p: pool.store.owned(first_owner, p))
    first_state = pool.driver.machines[first["sandbox_id"]]
    for storage in first_state.values():
        storage["private-value"] = "owner-A-only"
    claimed = next(iter(pool.db.items["browser_pool"].values()))
    with pytest.raises(BrowserUnavailable):
        await pool.update(deepcopy(claimed), {"status": "ready"})
    assert await pool.claim(str(uuid.uuid4()), lambda p: asyncio.sleep(0)) is None
    await pool.prepare()
    second_owner = str(uuid.uuid4())
    second = await pool.claim(second_owner, lambda p: pool.store.owned(second_owner, p))
    assert first["sandbox_id"] != second["sandbox_id"]
    assert not any(pool.driver.machines[second["sandbox_id"]].values())
    assert all(s["private-value"] == "owner-A-only" for s in first_state.values())


# contract-test: supporting surface=rest_api assertions=web-browse.private-storage-and-api,web-browse.lifecycle
@pytest.mark.asyncio
async def test_interrupted_owner_handoff_destroys_instead_of_recycling(pool):
    await pool.prepare()

    async def fail(provider):
        raise RuntimeError("owner persistence unavailable")

    with pytest.raises(RuntimeError):
        await pool.claim(str(uuid.uuid4()), fail)
    row = next(iter(pool.db.items["browser_pool"].values()))
    assert row["status"] == "retired" and not row["encrypted_payload"]
    assert pool.driver.killed and not pool.driver.machines


# contract-test: supporting surface=rest_api assertions=web-browse.private-storage-and-api,web-browse.session-and-run
@pytest.mark.asyncio
async def test_immutable_claim_blocks_reassignment_even_if_mutable_journal_is_stale(
    pool,
):
    await pool.prepare()
    stale = deepcopy(next(iter(pool.db.items["browser_pool"].values())))
    first_owner = str(uuid.uuid4())
    first = await pool.claim(first_owner, lambda p: pool.store.owned(first_owner, p))
    pool.db.items["browser_pool"][stale["id"]] = stale
    assert await pool.claim(str(uuid.uuid4()), lambda p: asyncio.sleep(0)) is None
    assert await pool.sweep() == 0
    row = pool.db.items["browser_pool"][stale["id"]]
    assert row["claimed_session_id"] == first_owner
    assert row["status"] == "claimed" and not row["encrypted_payload"]
    assert first["sandbox_id"] not in pool.driver.killed


# contract-test: supporting surface=rest_api assertions=web-browse.private-storage-and-api,web-browse.lifecycle
@pytest.mark.asyncio
async def test_lost_claim_response_never_grants_access_or_recycles(pool, monkeypatch):
    await pool.prepare()
    create = pool.db.create_item

    async def ambiguous(collection, row, **kwargs):
        result = await create(collection, row, **kwargs)
        return (False, {}) if collection == "browser_pool_claims" else result

    monkeypatch.setattr(pool.db, "create_item", ambiguous)
    assert await pool.claim(str(uuid.uuid4()), lambda p: asyncio.sleep(0)) is None
    assert await pool.claim(str(uuid.uuid4()), lambda p: asyncio.sleep(0)) is None
    assert await pool.sweep() == 1
    assert not pool.driver.machines


# contract-test: supporting surface=rest_api assertions=web-browse.private-storage-and-api,web-browse.lifecycle
@pytest.mark.asyncio
async def test_dirty_template_is_destroyed_before_becoming_available(pool):
    pool.driver.dirty_template = True
    with pytest.raises(BrowserUnavailable):
        await pool.prepare()
    assert all(r["status"] == "retired" for r in pool.db.items["browser_pool"].values())
    assert not pool.driver.machines


# contract-test: supporting surface=rest_api assertions=web-browse.lifecycle,web-browse.private-storage-and-api
@pytest.mark.asyncio
async def test_claimed_owner_survives_pool_expiry_and_cache_loss(pool):
    await pool.prepare()
    owner = str(uuid.uuid4())
    provider = await pool.claim(owner, lambda p: pool.store.owned(owner, p))
    row = next(iter(pool.db.items["browser_pool"].values()))
    row["expires_at"] = time.time() - 10
    info = SimpleNamespace(
        sandbox_id=provider["sandbox_id"],
        metadata={"openmates_browser_session": row["id"]},
        started_at=datetime.now(timezone.utc),
    )
    assert await pool.retain_native(info)
    assert await pool.sweep() == 0
    assert provider["sandbox_id"] in pool.driver.machines
    pool.db.items["browser_sessions"][owner]["status"] = "closed"
    assert not await pool.retain_native(info)
    assert await pool.sweep() == 1
    assert provider["sandbox_id"] not in pool.driver.machines


# contract-test: supporting surface=rest_api assertions=web-browse.private-storage-and-api,web-browse.lifecycle
@pytest.mark.asyncio
async def test_crash_after_atomic_claim_has_a_bounded_handoff_grace(pool):
    await pool.prepare()
    row = next(iter(pool.db.items["browser_pool"].values()))
    owner = str(uuid.uuid4())
    row.update(status="claimed", claimed_session_id=owner, claimed_at=time.time())
    pool.db.items["browser_pool_claims"][row["id"]] = {
        "id": row["id"],
        "scope": pool.scope,
        "session_id": owner,
        "created_at": time.time(),
    }
    await pool.store.owned(owner, None)
    assert await pool.sweep() == 0
    row["claimed_at"] = time.time() - 91
    pool.db.items["browser_pool_claims"][row["id"]]["created_at"] = time.time() - 91
    assert await pool.sweep() == 1
    assert row["status"] == "retired" and not row["encrypted_payload"]


# contract-test: supporting surface=rest_api assertions=web-browse.private-storage-and-api
@pytest.mark.asyncio
async def test_foreign_environment_cannot_claim_a_blank_vm(pool):
    await pool.prepare()
    pool.scope = "production"
    assert await pool.claim(str(uuid.uuid4()), lambda p: asyncio.sleep(0)) is None
    assert not pool.driver.killed


# contract-test: supporting surface=rest_api assertions=web-browse.lifecycle,web-browse.cost-accounting
@pytest.mark.asyncio
async def test_disabling_pool_retires_only_unassigned_inventory(pool, monkeypatch):
    await pool.prepare()
    monkeypatch.setenv("E2B_BROWSE_POOL_SIZE", "0")
    assert await pool.sweep() == 1
    assert not pool.driver.machines
