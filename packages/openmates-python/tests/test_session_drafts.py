"""Wrapper-boundary tests only; fake native methods do not prove Rust execution."""

# contract-test-file: tooling
import asyncio
import json
from types import SimpleNamespace
import pytest
from openmates.session_client import SessionClient, SessionClientError, SessionDrafts


def facade(native):
    client = SessionClient.__new__(SessionClient)
    client._native = native
    client._essential_epoch = 0
    return client, SessionDrafts(client)


def test_forwarding_null_and_read_only_contract():
    async def run():
        calls = []

        async def cached():
            calls.append(("cached",))
            return "[]"

        async def listed(raw):
            calls.append(("list", json.loads(raw)))
            return "[]"

        async def loaded(id, raw):
            calls.append(("get", id, json.loads(raw)))
            return "null"

        async def synced():
            calls.append(("sync",))
            return "{}"

        _, drafts = facade(
            SimpleNamespace(
                drafts_list_cached=cached,
                drafts_list=listed,
                drafts_get=loaded,
                drafts_sync=synced,
            )
        )
        assert await drafts.cached_list() == []
        assert await drafts.list() == []
        assert await drafts.get("exact", refresh=True) is None
        assert await drafts.sync() == {}
        assert calls == [
            ("cached",),
            ("list", {"force_refresh": False}),
            ("get", "exact", {"force_refresh": True}),
            ("sync",),
        ]
        assert not hasattr(drafts, "create") and not hasattr(drafts, "clear")

    asyncio.run(run())


def test_late_host_epoch_and_private_error_sanitization():
    async def run():
        future = asyncio.get_running_loop().create_future()
        client, drafts = facade(
            SimpleNamespace(drafts_get=lambda *_args: future, cancel=lambda: None)
        )
        pending = asyncio.create_task(drafts.get("exact"))
        await asyncio.sleep(0)
        client.cancel()
        future.set_result(json.dumps({"markdown": "synthetic private draft"}))
        with pytest.raises(SessionClientError) as captured:
            await pending
        assert (
            captured.value.code == "cancelled"
            and "synthetic private draft" not in str(captured.value)
        )

        def broken(*_args):
            raise RuntimeError("synthetic-private-cookie must not escape")

        _, drafts = facade(SimpleNamespace(drafts_get=broken))
        with pytest.raises(SessionClientError) as captured:
            await drafts.get("exact")
        assert (
            captured.value.code == "native_failure"
            and "synthetic-private-cookie" not in str(captured.value)
        )

    asyncio.run(run())


def test_python_cancellation_does_not_drop_native_transaction():
    async def run():
        future = asyncio.get_running_loop().create_future()
        _, drafts = facade(SimpleNamespace(drafts_get=lambda *_args: future))
        pending = asyncio.create_task(drafts.get("exact"))
        await asyncio.sleep(0)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert not future.cancelled()
        future.set_result("null")
        await asyncio.sleep(0)

    asyncio.run(run())
