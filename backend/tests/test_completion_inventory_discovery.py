"""PRIVATE UNRUN: authenticated discovery completeness never hides failure.

Offers contain metadata only. Claims, working-copy access, persistence and billing
remain in their existing distinct handlers and cannot occur in these read paths.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.routes.handlers.websocket_handlers import (
    chat_recovery_job_handlers as main,
    task_update_job_handlers as task,
)
from backend.core.api.app.services.chat_recovery_service import ChatRecoveryProtocolError


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class Manager:
    def __init__(self, capable=True):
        self.capable = capable
        self.messages = []
        self.active_connections = {"owner": {"device": object()}}

    def is_connection_completion_capable(self, user, device):
        assert (user, device) == ("owner", "device")
        return self.capable

    supports_task_update_jobs = is_connection_completion_capable

    async def send_personal_message(self, message, user, device, *, expected_websocket=None):
        assert (user, device) == ("owner", "device")
        if expected_websocket is not None and self.active_connections[user][device] is not expected_websocket:
            return False
        self.messages.append(message)
        return True


@pytest.mark.anyio
@pytest.mark.parametrize("result", [{"jobs": []}, {"jobs": None}, {}, {"jobs": {}}])
# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover
async def test_main_empty_only_after_successful_typed_owner_device_query(monkeypatch, result):
    execute = AsyncMock(return_value=result)
    monkeypatch.setattr(main, "ChatRecoveryService", lambda _: SimpleNamespace(execute=execute))
    manager = Manager()
    await main.send_available_recovery_jobs(manager=manager, directus_service=object(),
        user_id="owner", user_id_hash="owner-hash", device_fingerprint_hash="device")
    execute.assert_awaited_once_with("list_available_jobs", {
        "protocol_version": 1, "hashed_user_id": "owner-hash", "device_hash": "device",
    })
    assert manager.messages == ([{"type": "recovery_jobs_available", "payload": {"jobs": []}}]
                                if result.get("jobs") == [] else [])


@pytest.mark.anyio
@pytest.mark.parametrize("status", [403, 404, 503])
# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover
async def test_main_denial_or_operational_error_never_emits_empty_success(monkeypatch, status):
    execute = AsyncMock(side_effect=ChatRecoveryProtocolError(status, "synthetic-denied-or-unavailable"))
    monkeypatch.setattr(main, "ChatRecoveryService", lambda _: SimpleNamespace(execute=execute))
    manager = Manager()
    await main.send_available_recovery_jobs(manager=manager, directus_service=object(),
        user_id="owner", user_id_hash="owner-hash", device_fingerprint_hash="device")
    assert manager.messages == []


@pytest.mark.anyio
@pytest.mark.parametrize("revoke_during_read", [False, True])
# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover
async def test_main_ineligible_or_revoked_device_never_settles_discovery(monkeypatch, revoke_during_read):
    manager = Manager(capable=revoke_during_read)

    async def execute(*_):
        manager.capable = False
        return {"jobs": []}

    query = AsyncMock(side_effect=execute)
    monkeypatch.setattr(main, "ChatRecoveryService", lambda _: SimpleNamespace(execute=query))
    await main.send_available_recovery_jobs(manager=manager, directus_service=object(),
        user_id="owner", user_id_hash="owner-hash", device_fingerprint_hash="device")
    assert query.await_count == int(revoke_during_read)
    assert manager.messages == []


class Cache:
    def __init__(self, client):
        self.raw = client
        self.get_keys_by_pattern = AsyncMock(return_value=[])
        self.get = AsyncMock(return_value=None)
        self.set = AsyncMock()

    @property
    async def client(self):
        return self.raw


def raw_client():
    return SimpleNamespace(scan=AsyncMock(return_value=(0, [])), get=AsyncMock())


async def offer(cache, manager=None, *, complete=True):
    manager = manager or Manager()
    await task.send_available_task_update_jobs(manager=manager, cache_service=cache,
        user_id="owner", device_fingerprint_hash="device", complete_inventory=complete)
    cache.set.assert_not_awaited()
    return manager.messages


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=tasks.lifecycle.visible
async def test_task_complete_empty_is_bounded_read_only_and_legacy_no_frame_unchanged():
    raw = raw_client()
    cache = Cache(raw)
    assert await offer(cache) == [{"type": "task_update_jobs_available", "payload": {"jobs": [], "complete": True}}]
    raw.scan.assert_awaited_once_with(cursor=0, match=f"{task.TASK_TOOL_JOB_CACHE_PREFIX}*", count=256)
    raw.get.assert_not_awaited()
    cache.get_keys_by_pattern.assert_not_awaited()
    raw.scan.reset_mock()
    assert await offer(cache, complete=False) == []
    raw.scan.assert_not_awaited()


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=tasks.lifecycle.visible
async def test_task_inventory_owner_filter_offer_has_no_claim_or_working_copy(monkeypatch):
    monkeypatch.setattr(task.time, "time", lambda: 100)
    raw = raw_client()
    records = {}
    for label, owner, state, expires in [("own", "owner", "PENDING", 200), ("other", "other", "PENDING", 200),
                                         ("terminal", "owner", "TERMINAL", 200), ("expired", "owner", "PENDING", 99)]:
        records[f"{task.TASK_TOOL_JOB_CACHE_PREFIX}{label}"] = json.dumps({
            "owner_hash": task.hash_id(owner), "job_id": label, "state": state, "expires_at": expires,
            "task_id": "task", "chat_id": "chat", "expected_task_version": 1,
            "working_copy_ref": "private-working-copy", "lease_token": "private-lease",
        })
    raw.scan.return_value = (0, list(records))
    raw.get.side_effect = lambda key: records[key]
    messages = await offer(Cache(raw))
    payload = messages[0]["payload"]
    assert payload["complete"] is True
    assert [job["job_id"] for job in payload["jobs"]] == ["own"]
    assert "private-working-copy" not in json.dumps(payload)
    assert "private-lease" not in json.dumps(payload)
    assert raw.get.await_count == len(records)


@pytest.mark.anyio
@pytest.mark.parametrize("failure", ["unavailable", "scan", "get", "malformed-json", "malformed-job", "malformed-page", "pages", "keys"])
# contract-test: supporting surface=rest_api assertions=tasks.lifecycle.visible
async def test_task_failure_or_incomplete_scan_never_certifies_empty(failure):
    raw = raw_client()
    key = f"{task.TASK_TOOL_JOB_CACHE_PREFIX}job"
    raw.scan.return_value = (0, [key])
    raw.get.return_value = None
    if failure == "scan":
        raw.scan.side_effect = RuntimeError("synthetic Redis unavailable")
    elif failure == "get":
        raw.get.side_effect = RuntimeError("synthetic Redis unavailable")
    elif failure == "malformed-json":
        raw.get.return_value = b"{"
    elif failure == "malformed-job":
        raw.get.return_value = b"{}"
    elif failure == "malformed-page":
        raw.scan.return_value = (False, [])
    elif failure == "pages":
        raw.scan.return_value = (1, [])
    elif failure == "keys":
        raw.scan.return_value = (0, [f"{key}{n}" for n in range(task._COMPLETE_JOB_SCAN_KEYS + 1)])
    cache = Cache(None if failure == "unavailable" else raw)
    assert await offer(cache) == []
    assert raw.scan.await_count <= task._COMPLETE_JOB_SCAN_PAGES


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=tasks.lifecycle.visible
async def test_task_failed_complete_scan_preserves_ordinary_nonempty_offer():
    raw = raw_client()
    raw.scan.side_effect = RuntimeError("synthetic strict scan failure")
    cache = Cache(raw)
    cache.get_keys_by_pattern.return_value = ["job"]
    cache.get.return_value = {"owner_hash": task.hash_id("owner"), "state": "PENDING", "expires_at": 2**62,
        "job_id": "own", "task_id": "task", "chat_id": "chat", "expected_task_version": 1}
    messages = await offer(cache)
    assert messages[0]["payload"]["jobs"][0]["job_id"] == "own"
    assert "complete" not in messages[0]["payload"]


@pytest.mark.anyio
# contract-test: supporting surface=rest_api assertions=tasks.lifecycle.visible
async def test_task_limited_device_never_queries_or_emits_completion():
    raw = raw_client()
    assert await offer(Cache(raw), Manager(capable=False)) == []
    raw.scan.assert_not_awaited()


# The merge regressions below extract only the discovery functions. They can run
# without importing an application/service graph or opening any transport.
def _compat_discovery_functions():
    import ast
    from pathlib import Path
    from types import SimpleNamespace

    root = Path(__file__).resolve().parents[1]
    namespace = {
        "logger": SimpleNamespace(warning=lambda *_: None, exception=lambda *_: None),
        "_start_ws_span": lambda *_: (None, None),
        "_end_ws_span": lambda *_: None,
    }
    class ProtocolError(Exception):
        def __init__(self, status_code, code):
            self.status_code, self.code = status_code, code
    namespace["ChatRecoveryProtocolError"] = ProtocolError
    for path, names in [
        (root / "core/api/app/routes/handlers/websocket_handlers/chat_recovery_job_handlers.py",
         {"_OriginBoundRecoveryManager", "_bound_recovery_inventory_manager", "send_available_recovery_jobs", "send_available_recovery_outputs"}),
        (root / "core/api/app/routes/websockets.py",
         {"_discover_foreground_recovery", "_validated_inventory_request_id"}),
    ]:
        tree = ast.parse(path.read_text())
        functions = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in names]
        assert {node.name for node in functions} == names
        exec("from __future__ import annotations\n" + ast.unparse(ast.Module(body=functions, type_ignores=[])), namespace)
    import uuid
    namespace["uuid"] = uuid
    return namespace


def _compat_manager():
    class Manager:
        capable = True
        messages = None
        def __init__(self):
            self.messages = []
            self.active_connections = {"owner": {"device": object()}}
        def is_connection_completion_capable(self, *_):
            return self.capable
        supports_typed_recovery_outputs = is_connection_completion_capable
        async def send_personal_message(self, message, user, device, *, expected_websocket=None):
            if expected_websocket is not None and self.active_connections[user][device] is not expected_websocket:
                return False
            self.messages.append(message)
            return True
    return Manager()


def _compat_arguments(manager):
    return {"manager": manager, "directus_service": object(), "user_id": "owner",
            "user_id_hash": "owner-hash", "device_fingerprint_hash": "device",
            "request_id": "legacy-scan-17", "inventory_request_id": "22222222-2222-4222-8222-222222222222"}


# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover,storage.background.complete-sealed-recovery
def test_compat_jobs_pending_and_both_request_namespaces_are_preserved():
    import asyncio
    from types import SimpleNamespace
    ns = _compat_discovery_functions()
    async def run():
        for result in ({"jobs": [], "pending_jobs": []},
                       {"jobs": [], "pending_jobs": [{"job_id": "pending"}]},
                       {"pending_jobs": [{"job_id": "pending-only"}]},
                       {"jobs": [{"job_id": "available"}]}):
            async def execute(operation, payload):
                assert operation == "list_available_jobs"
                assert payload == {"protocol_version": 1, "hashed_user_id": "owner-hash", "device_hash": "device"}
                return result
            ns["ChatRecoveryService"] = lambda _: SimpleNamespace(execute=execute)
            manager = _compat_manager()
            assert await ns["send_available_recovery_jobs"](**_compat_arguments(manager)) is True
            payload = manager.messages[0]["payload"]
            assert payload["request_id"] == "legacy-scan-17"
            assert payload["inventory_request_id"] == "22222222-2222-4222-8222-222222222222"
            assert payload["jobs"] == result.get("jobs", [])
            if result.get("pending_jobs"):
                assert payload["pending_jobs"] == result["pending_jobs"]
    asyncio.run(run())


# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover,storage.background.complete-sealed-recovery
def test_compat_paused_pending_rows_and_schema_failures_never_certify_empty():
    import asyncio
    from types import SimpleNamespace
    ns = _compat_discovery_functions()
    async def run():
        for result, completed in [({"jobs": [], "pending_jobs": [{"job_id": "pending"}]}, True),
                                  ({"jobs": [{"job_id": "available"}], "pending_jobs": []}, True),
                                  ({"jobs": []}, True), (None, False), ({}, False),
                                  ({"jobs": None}, False), ({"jobs": [], "pending_jobs": None}, False),
                                  ({"jobs": [], "pending_jobs": {}}, False)]:
            async def execute(*_):
                return result
            ns["ChatRecoveryService"] = lambda _: SimpleNamespace(execute=execute)
            manager = _compat_manager()
            assert await ns["send_available_recovery_jobs"](**_compat_arguments(manager), empty_only=True) is completed
            assert len(manager.messages) == int(result == {"jobs": []})
        async def denied(*_):
            raise ns["ChatRecoveryProtocolError"](404, "synthetic-missing-schema")
        ns["ChatRecoveryService"] = lambda _: SimpleNamespace(execute=denied)
        manager = _compat_manager()
        assert await ns["send_available_recovery_jobs"](**_compat_arguments(manager)) is False
        assert manager.messages == []
        async def revoked(*_):
            manager.capable = False
            return {"jobs": []}
        ns["ChatRecoveryService"] = lambda _: SimpleNamespace(execute=revoked)
        assert await ns["send_available_recovery_jobs"](**_compat_arguments(manager)) is False
        assert manager.messages == []
    asyncio.run(run())


# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover,storage.background.complete-sealed-recovery
def test_compat_typed_pages_and_error_fence_echo_independent_identifiers():
    import asyncio
    from types import SimpleNamespace
    ns = _compat_discovery_functions()
    async def run():
        manager = _compat_manager()
        pages = [{"outputs": [{"record_id": "first"}], "next_cursor": {"cursor": "second"}},
                 {"outputs": [{"record_id": "second"}]}]
        requests = []
        async def execute(operation, payload):
            requests.append((operation, payload))
            return pages.pop(0)
        ns["ChatRecoveryService"] = lambda _: SimpleNamespace(execute=execute)
        await ns["send_available_recovery_outputs"](**_compat_arguments(manager))
        assert [message["type"] for message in manager.messages] == ["recovery_outputs_available", "recovery_outputs_available", "recovery_outputs_discovery_complete"]
        assert requests[1][1]["cursor"] == "second"
        for message in manager.messages:
            assert message["payload"]["request_id"] == "legacy-scan-17"
            assert message["payload"]["inventory_request_id"] == "22222222-2222-4222-8222-222222222222"
        manager.messages.clear()
        async def fail(*_):
            raise RuntimeError("synthetic unavailable schema")
        ns["ChatRecoveryService"] = lambda _: SimpleNamespace(execute=fail)
        try:
            await ns["send_available_recovery_outputs"](**_compat_arguments(manager))
        except RuntimeError:
            pass
        else:
            raise AssertionError("canonical output-discovery failure was swallowed")
        assert manager.messages[0]["payload"] == {"status": "failed", "request_id": "legacy-scan-17", "inventory_request_id": "22222222-2222-4222-8222-222222222222"}
    asyncio.run(run())


# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover,storage.background.complete-sealed-recovery
def test_compat_boolean_failure_and_paused_pending_fences_remain_closed():
    import asyncio
    from types import SimpleNamespace
    ns = _compat_discovery_functions()
    async def run():
        epoch = 1
        class Cutover:
            def __init__(self, *_):
                pass
            async def get_epoch(self, *, authoritative):
                assert authoritative is True
                return epoch
        ns["ChatRecoveryCutoverController"] = Cutover
        async def execute(*_):
            return {"jobs": [], "pending_jobs": [{"job_id": "pending"}]}
        ns["ChatRecoveryService"] = lambda _: SimpleNamespace(execute=execute)
        async def failed(**_):
            return False
        real_jobs = ns["send_available_recovery_jobs"]
        ns["send_available_recovery_jobs"] = failed
        manager = _compat_manager()
        arguments = {**_compat_arguments(manager), "cache_service": object(), "supports_typed_recovery_outputs": True, "user_otel_attrs": {}, "inventory_empty_ack": True}
        await ns["_discover_foreground_recovery"](**arguments)
        assert manager.messages[0]["payload"] == {"status": "failed", "request_id": "legacy-scan-17", "inventory_request_id": "22222222-2222-4222-8222-222222222222"}
        epoch = 0
        manager.messages.clear()
        ns["send_available_recovery_jobs"] = real_jobs
        await ns["_discover_foreground_recovery"](**arguments)
        assert manager.messages == [{"type": "recovery_outputs_discovery_complete", "payload": {"status": "disabled", "request_id": "legacy-scan-17", "inventory_request_id": "22222222-2222-4222-8222-222222222222"}}]
    asyncio.run(run())


# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover,storage.background.complete-sealed-recovery
def test_compat_route_preserves_legacy_validation_and_distinct_inventory_uuid():
    from pathlib import Path
    ns = _compat_discovery_functions()
    valid = "22222222-2222-4222-8222-222222222222"
    assert ns["_validated_inventory_request_id"](valid) == valid
    for value in ("legacy-scan-17", "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA", "", 7, None):
        assert ns["_validated_inventory_request_id"](value) is None
    source = (Path(__file__).resolve().parents[1] / "core/api/app/routes/websockets.py").read_text()
    assert 'not isinstance(request_id, str) or not 0 < len(request_id) <= 128' in source
    assert 'replace=request_id is not None, request_id=request_id' in source
    assert 'inventory_empty_ack=complete_task_inventory' in source
    assert 'payload.get("inventory_request_id") == inventory_request_id' in source


# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover,storage.background.complete-sealed-recovery
def test_compat_new_inventory_guard_rejects_replacement_but_preserves_legacy_request_id():
    import asyncio
    from types import SimpleNamespace
    ns = _compat_discovery_functions()
    async def run():
        for kind in ("main", "empty-only", "empty-only-no-nonce", "outputs", "legacy-request-only"):
            manager = _compat_manager()
            original = manager.active_connections["owner"]["device"]
            replacement = object()
            operations = []
            async def execute(operation, *_):
                operations.append(operation)
                manager.active_connections["owner"]["device"] = replacement
                return {"jobs": [], "outputs": [{"record_id": "synthetic"}]}
            ns["ChatRecoveryService"] = lambda _: SimpleNamespace(execute=execute)
            arguments = _compat_arguments(manager)
            if kind in ("legacy-request-only", "empty-only-no-nonce"):
                arguments["inventory_request_id"] = None
            if kind == "outputs":
                await ns["send_available_recovery_outputs"](**arguments)
            else:
                completed = await ns["send_available_recovery_jobs"](**arguments, empty_only=kind in ("empty-only", "empty-only-no-nonce"))
                assert completed is (kind == "legacy-request-only")
            assert len(operations) == 1
            if kind == "legacy-request-only":
                assert manager.messages == [{"type": "recovery_jobs_available", "payload": {"jobs": [], "request_id": "legacy-scan-17"}}]
            else:
                assert manager.messages == []
            assert manager.active_connections["owner"]["device"] is replacement
            assert original is not replacement
        # The adapter checks before send, but the underlying exact-socket send
        # must also reject a replacement occurring at the call boundary.
        manager = _compat_manager()
        original = manager.active_connections["owner"]["device"]
        bound = ns["_bound_recovery_inventory_manager"](manager, "owner", "device", "inventory")
        sent_handles = []
        async def racing_send(message, user, device, *, expected_websocket=None):
            sent_handles.append(expected_websocket)
            manager.active_connections[user][device] = object()
            if expected_websocket is not manager.active_connections[user][device]:
                return False
            raise AssertionError("foreign socket was admitted")
        manager.send_personal_message = racing_send
        assert await bound.send_personal_message({"type": "test"}, "owner", "device") is False
        assert sent_handles == [original]
        assert manager.messages == []
        # No original route means no capture, query or ACK at all.
        manager = _compat_manager()
        manager.active_connections.clear()
        called = []
        async def forbidden_query(*_):
            called.append(True)
            raise AssertionError("missing origin must not query")
        ns["ChatRecoveryService"] = lambda _: SimpleNamespace(execute=forbidden_query)
        assert await ns["send_available_recovery_jobs"](**_compat_arguments(manager)) is False
        assert called == [] and manager.messages == []
    asyncio.run(run())


# contract-test: supporting surface=rest_api assertions=chats.completion.recovery-takeover,storage.background.complete-sealed-recovery
def test_compat_inventory_origin_is_captured_before_epoch_and_bound_at_endpoint():
    import asyncio
    from pathlib import Path
    ns = _compat_discovery_functions()
    async def run():
        manager = _compat_manager()
        original = manager.active_connections["owner"]["device"]
        replacement = object()
        class Cutover:
            def __init__(self, *_):
                pass
            async def get_epoch(self, *, authoritative):
                manager.active_connections["owner"]["device"] = replacement
                return 0
        ns["ChatRecoveryCutoverController"] = Cutover
        async def unexpected_query(**_):
            raise AssertionError("stale origin must not query")
        ns["send_available_recovery_jobs"] = unexpected_query
        await ns["_discover_foreground_recovery"](**_compat_arguments(manager), cache_service=object(), supports_typed_recovery_outputs=True, user_otel_attrs={}, inventory_empty_ack=True)
        assert manager.messages == []
        assert original is not replacement
        assert manager.active_connections["owner"]["device"] is replacement
    asyncio.run(run())
    source = (Path(__file__).resolve().parents[1] / "core/api/app/routes/websockets.py").read_text()
    assert 'inventory_request_id, websocket,' in source
    assert 'manager=recovery_inventory_manager, directus_service=directus_service' in source
    assert 'manager=recovery_inventory_manager, cache_service=cache_service' in source
