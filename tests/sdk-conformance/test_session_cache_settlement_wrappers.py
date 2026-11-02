"""Actual source-extracted facades, fake native only; no core enforcement claim."""

# contract-test-file: tooling
import ast
import asyncio
import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = json.loads(
    (
        ROOT / "tests/sdk-conformance/fixtures/session-cache-settlement-wrappers.json"
    ).read_text()
)


def classes():
    source = ROOT / "packages/openmates-python/openmates/session_client.py"
    tree = ast.parse(source.read_text())
    selected = [
        n
        for n in tree.body
        if isinstance(n, (ast.ClassDef, ast.FunctionDef))
        and n.name in {"SessionClient", "SessionClientError", "_failure"}
    ]
    assert len(selected) == 3
    values = {"asyncio": asyncio, "json": json}
    module = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__", names=[ast.alias(name="annotations")], level=0
            ),
            *selected,
        ],
        type_ignores=[],
    )
    exec(compile(ast.fix_missing_locations(module), str(source), "exec"), values)
    source = ROOT / "packages/openmates-python/openmates/essential_session.py"
    tree = ast.parse(source.read_text())
    monitor = next(
        n
        for n in tree.body
        if isinstance(n, ast.ClassDef) and n.name == "SessionChatMonitor"
    )
    # Resolve the maintained relative imports without loading package/native dependencies.
    monitor = ast.parse(
        ast.unparse(monitor)
        .replace("from .session_client import SessionClientError", "pass")
        .replace("from .session_client import _failure", "pass")
    ).body[0]
    module = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__", names=[ast.alias(name="annotations")], level=0
            ),
            monitor,
        ],
        type_ignores=[],
    )
    exec(compile(ast.fix_missing_locations(module), str(source), "exec"), values)
    return values


class Native:
    def __init__(self):
        self.calls = []
        self.error = None
        self.gate = None
        self.publication = FIXTURE["publications"][1]

    async def cache_chat_stage(self, *args):
        self.calls.append(("stage", args))
        if self.gate is not None:
            await self.gate
        return json.dumps(FIXTURE["stage"])

    async def cache_chat_commit(self, *args):
        self.calls.append(("commit", args))
        if self.error:
            raise ValueError(json.dumps(self.error))
        return json.dumps(self.publication)

    def cache_chat_discard(self, *args):
        self.calls.append(("discard", args))

    async def chat_monitor_stage_prefer_cache(self, *args):
        self.calls.append(("monitor_stage_prefer_cache", args))
        if self.gate is not None:
            await self.gate
        return json.dumps(FIXTURE["stage"])

    def chat_monitor_discard(self, *args):
        self.calls.append(("monitor_discard", args))

    def chat_monitor_close(self, *args):
        self.calls.append(("monitor_close", args))


def client():
    values = classes()
    instance = object.__new__(values["SessionClient"])
    instance._native = Native()
    instance._essential_epoch = 0
    return instance, values


def test_explicit_stage_keeps_exact_opaque_bytes_without_automatic_ack():
    async def run():
        c, _ = client()
        assert (
            await c.cache_chat_stage("synthetic-chat", include_secrets=True)
            == FIXTURE["stage"]
        )
        assert c._native.calls == [("stage", ("synthetic-chat", True))]
        await c.cache_chat_discard("synthetic-stage")
        assert c._native.calls[-1] == ("discard", ("synthetic-stage",))

    asyncio.run(run())


@pytest.mark.parametrize("publication", FIXTURE["publications"])
def test_source_tagged_publication_and_exact_actual_receipt_forwarding(publication):
    async def run():
        c, _ = client()
        c._native.publication = publication
        assert (
            await c.cache_chat_commit("synthetic-stage", FIXTURE["receipt"])
            == publication
        )
        operation, args = c._native.calls[-1]
        assert operation == "commit" and args[0] == "synthetic-stage"
        assert json.loads(args[1]) == FIXTURE["receipt"]

    asyncio.run(run())


@pytest.mark.parametrize("error", FIXTURE["native_errors"])
def test_native_refusal_is_propagated_without_publication(error):
    async def run():
        c, values = client()
        c._native.error = error
        with pytest.raises(values["SessionClientError"]) as raised:
            await c.cache_chat_commit("synthetic-stage", FIXTURE["receipt"])
        assert raised.value.code == error["code"]
        assert [name for name, _ in c._native.calls] == ["commit"]

    asyncio.run(run())


def test_consent_refusal_does_not_call_native():
    async def run():
        c, values = client()
        with pytest.raises(values["SessionClientError"]) as raised:
            await c.cache_chat_stage("synthetic-chat", include_secrets=False)
        assert raised.value.code == "invalid_argument" and c._native.calls == []

    asyncio.run(run())


@pytest.mark.parametrize("monitor", [False, True])
@pytest.mark.parametrize("cancel", [False, True])
def test_abandoned_or_stale_stage_discards_exact_admitted_handle(monitor, cancel):
    async def run():
        c, values = client()
        c._native.gate = asyncio.get_running_loop().create_future()
        m = (
            values["SessionChatMonitor"](
                c, "synthetic-monitor", FIXTURE["stage"]["scope"]
            )
            if monitor
            else None
        )
        operation = (
            m.stage_refresh_prefer_cache(
                include_secrets=True, selected_chat_id="synthetic-chat"
            )
            if monitor
            else c.cache_chat_stage("synthetic-chat", include_secrets=True)
        )
        task = asyncio.create_task(operation)
        for _ in range(3):
            await asyncio.sleep(0)
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            c._essential_epoch += 1
        c._native.gate.set_result(None)
        if not cancel:
            with pytest.raises(values["SessionClientError"]) as raised:
                await task
            assert raised.value.code == "cancelled"
        for _ in range(6):
            await asyncio.sleep(0)
        expected = (
            ("monitor_discard", ("synthetic-monitor", "synthetic-stage"))
            if monitor
            else ("discard", ("synthetic-stage",))
        )
        assert expected in c._native.calls
        assert not any(name == "commit" for name, _ in c._native.calls)
        if m:
            await m.close()

    asyncio.run(run())


def test_monitor_cache_policy_forwards_explicit_selector_and_does_not_ack():
    async def run():
        c, values = client()
        m = values["SessionChatMonitor"](
            c, "synthetic-monitor", FIXTURE["stage"]["scope"]
        )
        assert (
            await m.stage_refresh_prefer_cache(
                include_secrets=True, selected_chat_id="synthetic-chat"
            )
            == FIXTURE["stage"]
        )
        assert c._native.calls == [
            (
                "monitor_stage_prefer_cache",
                ("synthetic-monitor", True, "synthetic-chat"),
            )
        ]
        await m.close()

    asyncio.run(run())


@pytest.mark.parametrize("error", FIXTURE["native_errors"][:2])
def test_stage_native_denial_or_expiry_is_not_a_cached_success(error):
    async def run():
        c, values = client()

        async def refused(*args):
            c._native.calls.append(("stage", args))
            raise ValueError(json.dumps(error))

        c._native.cache_chat_stage = refused
        with pytest.raises(values["SessionClientError"]) as raised:
            await c.cache_chat_stage("synthetic-chat", include_secrets=True)
        assert raised.value.code == error["code"]
        assert [name for name, _ in c._native.calls] == ["stage"]

    asyncio.run(run())


def test_commit_output_is_suppressed_after_authority_changes_during_await():
    async def run():
        c, values = client()
        gate = asyncio.get_running_loop().create_future()

        async def commit(*args):
            await gate
            return json.dumps(FIXTURE["publications"][1])

        c._native.cache_chat_commit = commit
        task = asyncio.create_task(
            c.cache_chat_commit("synthetic-stage", FIXTURE["receipt"])
        )
        await asyncio.sleep(0)
        c._essential_epoch += 1
        gate.set_result(None)
        with pytest.raises(values["SessionClientError"]) as raised:
            await task
        assert raised.value.code == "cancelled"

    asyncio.run(run())
