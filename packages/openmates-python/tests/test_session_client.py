"""Host cancellation/error behavior around the actual native API shape."""

# contract-test-file: tooling
import asyncio
import json
import pytest
from openmates import SessionClient, SessionClientError, SessionProjectUnlinkInput
from openmates.session_client import SessionProjects


class _SavedOutput:
    def __init__(self, raw):
        self.raw = raw
    def release_json(self):
        return self.raw
    def discard(self):
        pass
    def is_terminal(self):
        return json.loads(self.raw)["type"] in {"completed", "error"}


# contract-test: supporting surface=cli assertions=cli.surface.semantic-parity
def test_project_item_operations_preserve_strict_unlink_input():
    assert SessionProjectUnlinkInput.__required_keys__ == {
        "item_type",
        "target_id",
        "confirmed",
    }

    async def scenario():
        calls = []

        class Native:
            async def projects_items(self, identity, filters):
                calls.append((identity, json.loads(filters)))
                return json.dumps({"items": []})

            async def projects_unlink_item(self, identity, data, filters):
                calls.append((identity, json.loads(data), json.loads(filters)))
                return json.dumps({"deleted": False})

        client = SessionClient.__new__(SessionClient)
        client._essential_epoch = 0
        client._native = Native()
        projects = SessionProjects(client)
        assert await projects.items("exact", filters={"personal": True}) == {
            "items": []
        }
        # No Python truthiness coercion: Rust must reject this string itself.
        data = {
            "item_type": "chat",
            "target_id": "target",
            "confirmed": "true",
            "unknown": True,
        }
        assert await projects.unlink_item(
            "exact", data, filters={"team_id": "team"}
        ) == {"deleted": False}
        assert calls == [
            ("exact", {"personal": True}),
            ("exact", data, {"team_id": "team"}),
        ]

    asyncio.run(scenario())


def test_abandoned_anonymous_consumer_cancels_only_its_exact_stream():
    async def scenario():
        loop = asyncio.get_running_loop()
        calls = []
        events = [
            {"type": "update", "update": {"Content": {"content": "Synthetic"}}},
            {"type": "error", "error": {"code": "cancelled", "message": "Cancelled"}},
        ]

        def complete(value):
            future = loop.create_future()
            future.set_result(value)
            return future

        class Native:
            def start_anonymous(self, identity, text, options):
                assert identity == "synthetic-anonymous" and text == "Synthetic"
                assert json.loads(options) == {}
                return complete("exact-stream")

            def next_event(self, identity):
                assert identity == "exact-stream"
                calls.append("event")
                return complete(json.dumps(events.pop(0)))

            def cancel_stream(self, identity):
                calls.append("cancel:" + identity)

            def cancel(self):
                raise AssertionError("must not cancel unrelated work")

        client = SessionClient.__new__(SessionClient)
        client._essential_epoch = 0
        client._native = Native()
        stream = client.stream_anonymous("synthetic-anonymous", "Synthetic")
        assert (await anext(stream))["type"] == "update"
        await stream.aclose()
        assert calls == ["event", "cancel:exact-stream", "event"]

    asyncio.run(scenario())


def test_cancelled_startup_is_eventually_cancelled_and_drained():
    async def scenario():
        loop = asyncio.get_running_loop()
        startup = loop.create_future()
        drained = asyncio.Event()
        calls = []

        class Native:
            def start_send(self, _text, _chat):
                return startup

            def cancel_stream(self, identity):
                calls.append("cancel:" + identity)

            def cancel(self):
                raise AssertionError("saved startup must not cancel unrelated work")

            def next_event_prepare(self, stream):
                assert stream == "synthetic-stream"
                future = loop.create_future()
                future.set_result(
                    _SavedOutput(json.dumps(
                        {
                            "type": "error",
                            "error": {"code": "cancelled", "message": "Cancelled"},
                        }
                    ))
                )
                drained.set()
                return future

        client = SessionClient.__new__(SessionClient)
        client._essential_epoch = 0
        client._native = Native()
        pending = asyncio.create_task(client.send("Synthetic"))
        await asyncio.sleep(0)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert not startup.cancelled(), (
            "host cancellation must preserve native admission"
        )
        startup.set_result("synthetic-stream")
        await asyncio.wait_for(drained.wait(), timeout=1)
        assert calls == ["cancel:synthetic-stream"]

    asyncio.run(scenario())


def test_synchronous_native_errors_are_sanitized():
    async def scenario():
        class Native:
            def list(self, _workspace):
                raise RuntimeError("synthetic-private-token must not escape")

        client = SessionClient.__new__(SessionClient)
        client._essential_epoch = 0
        client._native = Native()
        with pytest.raises(SessionClientError) as failure:
            await client.list("chats")
        assert failure.value.code == "native_failure"
        assert "synthetic-private-token" not in str(failure.value)

    asyncio.run(scenario())


def test_message_window_forwards_exact_options_and_refuses_changed_authority():
    async def scenario():
        calls = []
        client = SessionClient.__new__(SessionClient)
        client._essential_epoch = 0
        class Native:
            async def chat_message_window(self, identity, raw):
                calls.append((identity, json.loads(raw)))
                return json.dumps({"historyComplete": False, "piiRestoration": "page_local"})
        client._native = Native()
        options = {"direction": "latest", "limit": 2, "unknown": "Rust must reject"}
        assert await client.chat_message_window("exact", options) == {"historyComplete": False, "piiRestoration": "page_local"}
        assert calls == [("exact", options)]
        class Revoked:
            async def chat_message_window(self, identity, raw):
                client._essential_epoch += 1
                return json.dumps({"private": "must not escape"})
        client._native = Revoked()
        try:
            await client.chat_message_window("exact")
        except SessionClientError as error:
            assert error.code == "cancelled"
        else:
            raise AssertionError("stale page escaped")
    asyncio.run(scenario())


def test_password_login_preference_defaults_false_and_never_coerces():
    async def scenario():
        calls = []
        class Native:
            async def login_password(self, *args):
                calls.append(args)
                return '{"id":"synthetic-owner"}'
        client = SessionClient.__new__(SessionClient)
        client._native = Native()
        client._essential_epoch = 0
        for options in [{}, {"stay_logged_in": False}, {"stay_logged_in": True}]:
            assert await client.login_password("synthetic@example.invalid", "synthetic", **options) == {"id": "synthetic-owner"}
        assert calls == [("synthetic@example.invalid", "synthetic", None, False), ("synthetic@example.invalid", "synthetic", None, False), ("synthetic@example.invalid", "synthetic", None, True)]
        for value in [None, 0, 1, "true", [], {}]:
            with pytest.raises(SessionClientError) as error:
                await client.login_password("e", "p", stay_logged_in=value)
            assert error.value.code == "invalid_argument"
        assert len(calls) == 3
    asyncio.run(scenario())


# contract-test: supporting surface=sdks.pip assertions=sdk.library.explicit-headless,cli.surface.semantic-parity
def test_saved_consumer_close_cancels_only_exact_id_and_drains():
    async def scenario():
        calls = []
        events = [
            {"type": "update", "update": {"Content": {"content": "Synthetic"}}},
            {"type": "error", "error": {"code": "cancelled", "message": "Cancelled"}},
        ]
        loop = asyncio.get_running_loop()
        def complete(value):
            future = loop.create_future()
            future.set_result(value)
            return future
        class Native:
            def start_send(self, text, chat):
                return complete("A")
            def next_event_prepare(self, identity):
                assert identity == "A"
                calls.append("event")
                return complete(_SavedOutput(json.dumps(events.pop(0))))
            def cancel_stream(self, identity):
                calls.append("cancel:" + identity)
            def cancel(self):
                raise AssertionError("saved consumer must not cancel unrelated work")
        client = SessionClient.__new__(SessionClient)
        client._essential_epoch = 0
        client._native = Native()
        stream = client.stream("Synthetic")
        assert (await anext(stream))["type"] == "update"
        await stream.aclose()
        assert calls == ["event", "cancel:A", "event"]
        assert client._essential_epoch == 0
    asyncio.run(scenario())


def test_stale_saved_cleanup_cannot_cancel_successor_and_still_attempts_exact_drain():
    async def scenario():
        loop = asyncio.get_running_loop()
        calls = []
        active = "A"
        b_cancelled = False
        finished = False
        def complete(value):
            future = loop.create_future()
            future.set_result(value)
            return future
        class Native:
            def start_send(self, text, chat):
                return complete(text)
            def next_event_prepare(self, identity):
                calls.append("event:" + identity)
                if identity != active:
                    raise RuntimeError(json.dumps({"code": "conflict", "message": "Stale stream"}))
                return complete(_SavedOutput(json.dumps({"type": "completed", "chat": {"id": identity}} if finished else {"type": "update", "update": {"Content": {"content": identity}}})))
            def cancel_stream(self, identity):
                nonlocal b_cancelled
                calls.append("cancel:" + identity)
                if identity != active:
                    raise RuntimeError(json.dumps({"code": "conflict", "message": "Stale stream"}))
                b_cancelled = identity == "B"
            def cancel(self):
                raise AssertionError("stale cleanup must not globally cancel B")
        client = SessionClient.__new__(SessionClient)
        client._essential_epoch = 0
        client._native = Native()
        a = client.stream("A")
        assert (await anext(a))["type"] == "update"
        # Model a separately consumed native A terminal. Genuine adapters prove
        # the actual binding/core rearm and native B driver independently.
        active = "B"
        b = client.stream("B")
        assert (await anext(b))["type"] == "update"
        await a.aclose()
        assert calls[-2:] == ["cancel:A", "event:A"]
        assert not b_cancelled and client._essential_epoch == 0
        finished = True
        assert (await anext(b))["type"] == "completed"
        await b.aclose()
    asyncio.run(scenario())


def test_explicit_global_cancel_keeps_native_call_and_epoch_invalidation():
    calls = []
    class Native:
        def cancel(self):
            calls.append("global")
    client = SessionClient.__new__(SessionClient)
    client._native = Native()
    client._essential_epoch = 7
    client.cancel()
    assert calls == ["global"] and client._essential_epoch == 8


def test_saved_startup_and_queued_event_epoch_are_checked_before_parsing():
    async def scenario():
        for phase in ["startup", "event"]:
            calls = []
            reads = 0
            loop = asyncio.get_running_loop()
            def complete(value):
                future = loop.create_future()
                future.set_result(value)
                return future
            class Native:
                def start_send(self, text, chat):
                    if phase == "startup":
                        client._essential_epoch += 1
                    return complete("A")
                def next_event_prepare(self, identity):
                    nonlocal reads
                    assert identity == "A"
                    reads += 1
                    if phase == "event" and reads == 1:
                        client._essential_epoch += 1
                        return complete(_SavedOutput("synthetic-private-non-json"))
                    return complete(_SavedOutput(json.dumps({"type": "error", "error": {"code": "cancelled", "message": "Cancelled"}})))
                def cancel_stream(self, identity):
                    calls.append("cancel:" + identity)
                def cancel(self):
                    raise AssertionError("must not globally cancel changed context")
            client = SessionClient.__new__(SessionClient)
            client._essential_epoch = 0
            client._native = Native()
            with pytest.raises(SessionClientError) as error:
                await client.send("Synthetic")
            assert error.value.code == "cancelled" and "synthetic-private" not in str(error.value)
            assert calls == ["cancel:A"]
            assert reads == (1 if phase == "startup" else 2)
    asyncio.run(scenario())


def test_abandoned_saved_event_prepare_disposes_its_eventual_opaque_output():
    async def scenario():
        loop = asyncio.get_running_loop()
        entered, disposed = asyncio.Event(), asyncio.Event()
        late = loop.create_future()
        calls = []
        reads = 0
        def complete(value):
            future = loop.create_future()
            future.set_result(value)
            return future
        class LateOutput:
            def release_json(self):
                pytest.fail("abandoned private event allocated a foreign string")
            def discard(self):
                calls.append("late-discard:A")
                disposed.set()
        class Terminal:
            def release_json(self):
                pytest.fail("drain must not allocate foreign plaintext")
            def is_terminal(self):
                return True
            def discard(self):
                calls.append("terminal-discard:A")
        class Native:
            def start_send(self, text, chat):
                return complete("A")
            def next_event_prepare(self, identity):
                nonlocal reads
                assert identity == "A"
                reads += 1
                if reads == 1:
                    entered.set()
                    return late
                return complete(Terminal())
            def cancel_stream(self, identity):
                calls.append("cancel:" + identity)
            def cancel(self):
                pytest.fail("abandoned A must not globally cancel B")
        client = SessionClient.__new__(SessionClient)
        client._native, client._essential_epoch = Native(), 0
        iterator = client.stream("Synthetic")
        pending = asyncio.create_task(anext(iterator))
        await entered.wait()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert not late.cancelled()
        late.set_result(LateOutput())
        await asyncio.wait_for(disposed.wait(), 1)
        assert calls == ["cancel:A", "terminal-discard:A", "late-discard:A"]
    asyncio.run(scenario())


# contract-test: supporting surface=sdks.pip assertions=sdk.library.explicit-headless
def test_missing_native_extension_raises_typed_error_without_fallback(monkeypatch):
    import sys
    from openmates import RustApiKeyClient, RustApiKeyClientError, prepare_privacy, sort_tasks

    # A None entry makes ``from ._native import ...`` raise ImportError, exactly
    # like an installation without the platform extension.
    monkeypatch.setitem(sys.modules, "openmates._native", None)
    with pytest.raises(SessionClientError) as caught:
        SessionClient(api_url="https://api.example.invalid", enhanced_privacy=False, allow_private_operations=False)
    assert caught.value.code == "native_binding_unavailable"
    with pytest.raises(RustApiKeyClientError) as caught_key:
        RustApiKeyClient(api_key="synthetic-explicit-key", api_url="https://api.example.invalid", device_id="synthetic-device", enhanced_privacy=False, allow_private_operations=False)
    assert caught_key.value.code == "native_binding_unavailable"
    for operation in (lambda: prepare_privacy("plain"), lambda: sort_tasks([], locale="en")):
        with pytest.raises(SessionClientError) as caught_local:
            operation()
        assert caught_local.value.code == "native_binding_unavailable"
