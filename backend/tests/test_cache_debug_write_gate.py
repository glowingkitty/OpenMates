"""Optional debug writes cannot publish stale admin-list snapshots after expiry."""

# contract-test-file: infrastructure

import asyncio
import json
from types import SimpleNamespace

from backend.core.api.app.services.cache_debug_mixin import DebugCacheMixin, DEBUG_REQUESTS_KEY


def test_expired_optional_writer_cannot_replace_newer_admin_entry(monkeypatch):
    from backend.core.api.app.services import directus

    class Redis:
        def __init__(self):
            self.values = {}

        async def get(self, key):
            return self.values.get(key)

        async def set(self, key, value, **_kwargs):
            self.values[key] = value
            return True

    class Cache(DebugCacheMixin):
        def __init__(self, client):
            self.client = asyncio.get_running_loop().create_future()
            self.client.set_result(client)

    class Encryption:
        async def encrypt_debug_request_data(self, payload):
            return payload

        async def decrypt_debug_request_data(self, payload):
            return payload

    class DelayedEncryption(Encryption):
        def __init__(self, started, release):
            self.started = started
            self.release = release

        async def encrypt_debug_request_data(self, payload):
            self.started.set()
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                # Simulate an encryption dependency that completes despite
                # cancellation after the owner has left its turn.
                await self.release.wait()
            return payload

    class Directus:
        def __init__(self, **_kwargs):
            self.admin = SimpleNamespace(is_user_admin=self.is_user_admin)

        async def is_user_admin(self, _user_id):
            return True

    monkeypatch.setattr(directus, "DirectusService", Directus)

    async def check():
        redis = Redis()
        redis.values[DEBUG_REQUESTS_KEY] = json.dumps([
            {"task_id": "seed", "preprocessor_input": {"turn": "seed"}},
        ])
        cache = Cache(redis)
        started = asyncio.Event()
        release = asyncio.Event()
        cancelled = asyncio.Event()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 0.01
        old = asyncio.create_task(cache.cache_debug_request_entry(
            DelayedEncryption(started, release), "old", "chat", "admin", "preprocessor",
            input_data={"turn": "old"},
            accept_write=lambda: not cancelled.is_set() and loop.time() < deadline,
        ))
        await asyncio.wait_for(started.wait(), 1)

        # This writer sees a newer list while the old snapshot is stuck in
        # encryption. The default path remains enabled for normal callers.
        assert await cache.cache_debug_request_entry(
            Encryption(), "new", "chat", "admin", "preprocessor",
            input_data={"turn": "new"},
        )
        await asyncio.sleep(0.02)
        cancelled.set()
        old.cancel()
        release.set()
        assert await asyncio.wait_for(old, 1) is False

        entries = json.loads(redis.values[DEBUG_REQUESTS_KEY])
        assert [entry["task_id"] for entry in entries] == ["new", "seed"]
        assert entries[0]["preprocessor_input"] == {"turn": "new"}

    asyncio.run(check())


def test_inflight_optional_cas_rejects_newer_write_or_clear(monkeypatch):
    """A late Redis command cannot replace changes made after its raw snapshot."""
    from backend.core.api.app.services import directus

    class Redis:
        def __init__(self, initial):
            self.values = {DEBUG_REQUESTS_KEY: initial}
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def get(self, key):
            return self.values.get(key)

        async def set(self, key, value, **_kwargs):
            self.values[key] = value
            return True

        async def delete(self, key):
            self.values.pop(key, None)
            return 1

        async def eval(self, script, count, key, absent, expected, value, _ttl):
            assert count == 1 and "redis.call('GET'" in script and "redis.call('SET'" in script
            self.started.set()
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                await self.release.wait()
            current = self.values.get(key)
            matches = current is None if absent == "1" else current == expected
            if not matches:
                return 0
            self.values[key] = value
            return 1

    class Cache(DebugCacheMixin):
        def __init__(self, client):
            self.client = asyncio.get_running_loop().create_future()
            self.client.set_result(client)

    class Encryption:
        async def encrypt_debug_request_data(self, payload):
            return payload

        async def decrypt_debug_request_data(self, payload):
            return payload

    class Directus:
        def __init__(self, **_kwargs):
            self.admin = SimpleNamespace(is_user_admin=self.is_user_admin)

        async def is_user_admin(self, _user_id):
            return True

    monkeypatch.setattr(directus, "DirectusService", Directus)

    async def check():
        for change in ("newer_write", "clear"):
            redis = Redis(json.dumps([{"task_id": "seed", "preprocessor_input": {"turn": "seed"}}]))
            cache = Cache(redis)
            cancelled = asyncio.Event()
            loop = asyncio.get_running_loop()
            deadline = loop.time() + 0.01
            old = asyncio.create_task(cache.cache_debug_request_entry(
                Encryption(), "old", "chat", "admin", "preprocessor",
                input_data={"turn": "old"},
                accept_write=lambda: not cancelled.is_set() and loop.time() < deadline,
            ))
            await asyncio.wait_for(redis.started.wait(), 1)
            await asyncio.sleep(0.02)
            cancelled.set()
            old.cancel()
            if change == "newer_write":
                assert await cache.cache_debug_request_entry(
                    Encryption(), "new", "chat", "admin", "preprocessor",
                    input_data={"turn": "new"},
                )
                expected_ids = ["new", "seed"]
            else:
                assert await cache.clear_debug_requests()
                expected_ids = []
            redis.release.set()
            assert await asyncio.wait_for(old, 1) is False
            current = redis.values.get(DEBUG_REQUESTS_KEY)
            ids = [entry["task_id"] for entry in json.loads(current)] if current is not None else []
            assert ids == expected_ids

    asyncio.run(check())


def test_absent_optional_snapshot_drops_after_newer_write_and_clear(monkeypatch):
    """Best-effort optional writes cannot revive an initially absent list."""
    from backend.core.api.app.services import directus

    class Redis:
        def __init__(self):
            self.values = {}
            self.hold_first_get = True
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def get(self, key):
            if self.hold_first_get:
                self.hold_first_get = False
                original = self.values.get(key)
                self.started.set()
                try:
                    await self.release.wait()
                except asyncio.CancelledError:
                    await self.release.wait()
                return original
            return self.values.get(key)

        async def set(self, key, value, **_kwargs):
            self.values[key] = value
            return True

        async def delete(self, key):
            self.values.pop(key, None)
            return 1

        async def eval(self, *_args):
            raise AssertionError("Absent optional snapshot must never reach CAS")

    class Cache(DebugCacheMixin):
        def __init__(self, client):
            self.client = asyncio.get_running_loop().create_future()
            self.client.set_result(client)

    class Encryption:
        async def encrypt_debug_request_data(self, payload):
            return payload

        async def decrypt_debug_request_data(self, payload):
            return payload

    class Directus:
        def __init__(self, **_kwargs):
            self.admin = SimpleNamespace(is_user_admin=self.is_user_admin)

        async def is_user_admin(self, _user_id):
            return True

    monkeypatch.setattr(directus, "DirectusService", Directus)

    async def check():
        redis = Redis()
        cache = Cache(redis)
        old = asyncio.create_task(cache.cache_debug_request_entry(
            Encryption(), "old", "chat", "admin", "preprocessor",
            input_data={"turn": "old"}, accept_write=lambda: True,
        ))
        await asyncio.wait_for(redis.started.wait(), 1)
        assert await cache.cache_debug_request_entry(
            Encryption(), "new", "chat", "admin", "preprocessor",
            input_data={"turn": "new"},
        )
        assert [row["task_id"] for row in json.loads(redis.values[DEBUG_REQUESTS_KEY])] == ["new"]
        assert await cache.clear_debug_requests()
        old.cancel()
        redis.release.set()
        assert await asyncio.wait_for(old, 1) is False
        assert DEBUG_REQUESTS_KEY not in redis.values

    asyncio.run(check())
