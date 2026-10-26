#!/usr/bin/env python3
"""Real E2B + durable pool isolation proof, using synthetic owners only.

The documented httpbin /base64 endpoint serves our own HTML fixture. Its script
stores only random synthetic markers; no real account or inference is involved.
See https://httpbin.org/ and https://github.com/postmanlabs/httpbin (ISC).
All created VMs, test rows and test Vault keys are removed in finally. The proof
uses a separate native/pool scope so it cannot consume or delete users' browsers.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
from copy import deepcopy
import json
import os
import time
import uuid

from backend.core.api.app.tasks.base_task import BaseServiceTask
from backend.core.api.app.tasks.celery_config import app
from backend.core.api.app.services.web_browse_service import BrowseStore
from backend.core.api.app.services.web_browse_pool import BrowsePool
from backend.shared.providers.e2b_browser import E2BBrowser, BrowserUnavailable
from backend.shared.providers.e2b_code_runner import get_e2b_api_key_async
from backend.shared.python_utils.private_inference_logging import (
    private_inference_logging,
)


FIXTURE = """<!doctype html><meta charset=utf-8><body>Loading<script>
(async()=>{const k='openmates_pool_isolation';const seed=location.hash.slice(1);
if(seed){document.cookie=k+'='+encodeURIComponent(seed)+';path=/;Secure;SameSite=Lax';
localStorage.setItem(k,seed);sessionStorage.setItem(k,seed);
const db=await new Promise((ok,no)=>{const r=indexedDB.open(k,1);r.onupgradeneeded=()=>r.result.createObjectStore('values');r.onsuccess=()=>ok(r.result);r.onerror=()=>no(r.error)});
await new Promise((ok,no)=>{const t=db.transaction('values','readwrite');t.objectStore('values').put(seed,'marker');t.oncomplete=ok;t.onerror=no});db.close();
const c=await caches.open(k);await c.put(new Request(location.origin+'/openmates-test-marker'),new Response(seed));}
const out={cookie:document.cookie.split(';').some(x=>x.trim().startsWith(k+'=')),local:localStorage.getItem(k)!==null,session:sessionStorage.getItem(k)!==null,idb:(await indexedDB.databases()).some(x=>x.name===k),cache:(await caches.keys()).includes(k)};
document.body.textContent=JSON.stringify(out)})().catch(()=>document.body.textContent='fixture failed');
</script>"""


# contract-test: supporting surface=rest_api assertions=web-browse.private-storage-and-api,web-browse.session-and-run,web-browse.lifecycle,web-browse.cost-accounting
async def test_live_pool_isolation(age_seconds: int) -> dict:
    os.environ["E2B_BROWSE_POOL_SIZE"] = "3"
    worker = BaseServiceTask()
    worker.bind(app)
    pool = None
    keys, owners, assignments = [], [], []
    report = {}
    try:
        await worker.initialize_core_services()
        key = await get_e2b_api_key_async(worker.secrets_manager)
        driver = E2BBrowser(key)
        driver.scope = "pool-qualification-d7bf-" + uuid.uuid4().hex[:10]
        store = BrowseStore(
            worker.directus_service, worker.encryption_service, worker.cache_service
        )
        pool = BrowsePool(store, driver)
        with private_inference_logging():
            for _ in range(2):
                await pool.refill()
            assert len(await pool.rows({"status": {"_eq": "ready"}})) == 3
            if age_seconds:
                await asyncio.sleep(age_seconds)

            async def acquire():
                owner, sid, chat = (str(uuid.uuid4()) for _ in range(3))
                vault_key = await worker.encryption_service.create_user_key()
                keys.append(vault_key)
                record = {
                    "session_id": sid,
                    "user_id": "qa-pool-" + owner,
                    "chat_id": chat,
                    "vault_key_id": vault_key,
                    "status": "paused",
                    "active_run": None,
                    "last_activity": time.time(),
                    "charged_credits": 0,
                    "runtime_cost_usd": "0",
                    "inference_cost_usd": "0",
                    "provider": None,
                }
                await store.save(record, create=True)
                owners.append(sid)

                async def created(provider):
                    record["provider"] = deepcopy(provider)
                    await store.save(record)

                started = time.monotonic()
                provider = await pool.claim(sid, created)
                assert provider is not None
                assignments.append(provider)
                await driver.resume(provider)
                verified = await driver.rpc(
                    provider,
                    {
                        "operation": "control",
                        "mode": "ai",
                        "check_ready": True,
                        "require_pristine": True,
                    },
                )
                assert verified.get("pristine") is True
                provider["pool_verified"] = True
                record["provider"] = deepcopy(provider)
                await store.save(record)
                return provider, round(time.monotonic() - started, 3)

            fixture = (
                "https://httpbin.org/base64/"
                + base64.urlsafe_b64encode(FIXTURE.encode()).decode()
            )

            async def inspect(provider, seed=""):
                await driver.rpc(
                    provider,
                    {
                        "operation": "navigate",
                        "url": fixture
                        + "?check="
                        + uuid.uuid4().hex
                        + ("#" + seed if seed else ""),
                    },
                )
                for _ in range(5):
                    observed = await driver.rpc(provider, {"operation": "observe"})
                    if observed.get("blocked_reason"):
                        raise BrowserUnavailable(
                            "The public test fixture denied access."
                        )
                    text = observed.get("document_text", "").strip()
                    if text.startswith("{"):
                        return json.loads(text)
                    await asyncio.sleep(0.2)
                raise AssertionError("The public test fixture did not finish")

            first, first_seconds = await acquire()
            assert all((await inspect(first, "synthetic-" + uuid.uuid4().hex)).values())
            await driver.pause(first)
            second, second_seconds = await acquire()
            assert not any((await inspect(second)).values())
            assert first["sandbox_id"] != second["sandbox_id"]
            try:
                await driver.rpc(
                    {**second, "token": first["token"]}, {"operation": "metadata"}
                )
            except BrowserUnavailable:
                report["cross_session_bearer_rejected"] = True
            else:
                raise AssertionError("Another session's bearer was accepted")
            await driver.resume(first)
            assert all((await inspect(first)).values())
            await driver.pause(first)
            await driver.pause(second)
            report.update(
                cookie_cache_local_session_indexeddb_isolated=True,
                original_owner_state_retained=True,
                aged_seconds=age_seconds,
                acquisition_seconds=[first_seconds, second_seconds],
            )

            # One remaining slot; exercise the real database primary-key race.
            race_owners = [str(uuid.uuid4()), str(uuid.uuid4())]
            race = await asyncio.gather(
                *(pool.claim(sid, lambda p: asyncio.sleep(0)) for sid in race_owners)
            )
            assert sum(p is not None for p in race) == 1
            race_vm = next(p for p in race if p is not None)
            race_row = next(
                r
                for r in await pool.rows({})
                if r["sandbox_id"] == race_vm["sandbox_id"]
            )
            await pool.retire(race_row)
            report["database_unique_claim_race_passed"] = True
            for _ in range(2):
                await pool.refill()
            burst = await asyncio.gather(*(acquire() for _ in range(3)))
            report["burst_acquisition_seconds"] = [elapsed for _, elapsed in burst]
            assert len({p["sandbox_id"] for p in assignments}) == len(assignments)
            missed = await pool.claim(str(uuid.uuid4()), lambda p: asyncio.sleep(0))
            assert missed is None
            report["pool_exhaustion_returns_no_handle"] = True
            rows = await pool.rows({"status": {"_eq": "claimed"}})
            assert all(not r["encrypted_payload"] for r in rows)
            report["platform_credential_copies_removed"] = True
        report["status"] = "passed"
        return report
    finally:
        failures = []
        if pool:
            with private_inference_logging():
                try:
                    rows = await pool.rows({})
                except Exception:
                    rows = []
                    failures.append("pool journal lookup")
                retired = []
                for row in rows:
                    try:
                        await pool.retire(row)
                        retired.append(row["id"])
                    except Exception:
                        failures.append("native retirement")
                for collection in ("browser_pool_claims", "browser_pool"):
                    try:
                        if retired and not await pool.db.bulk_delete_items(
                            collection, retired
                        ):
                            failures.append(collection)
                    except Exception:
                        failures.append(collection)
                if owners:
                    try:
                        if not await pool.db.bulk_delete_items(
                            "browser_sessions", owners
                        ):
                            failures.append("synthetic sessions")
                    except Exception:
                        failures.append("synthetic sessions")
        for key_id in keys:
            try:
                await worker.encryption_service.delete_user_key(key_id)
            except Exception:
                failures.append("synthetic Vault key")
        await worker.cleanup_services()
        if failures:
            raise RuntimeError(
                "Qualification cleanup needs retry: " + ", ".join(failures)
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--age-seconds", type=int, choices=(0, 125), default=125)
    args = parser.parse_args()
    if not args.execute:
        parser.error("--execute is required for paid E2B qualification")
    print(json.dumps(asyncio.run(test_live_pool_isolation(args.age_seconds))))
