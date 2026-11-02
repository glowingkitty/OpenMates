"""Actual facade/helper methods with native/store doubles only.

No Rust, native VM, HTTP, credentials, CLI or performance acceptance is supplied.
Encoders and asyncio ticket ordering are actual installed Python operations.
Old dispatch remains zero; fresh B must retain ordinary callable behavior.
Public coroutine creation alone remains lazy and does not admit an operation.
"""

import asyncio
import json
import pytest
from openmates.session_client import SessionClient, SessionClientError, SessionTasks

CHAT = "22222222-2222-4222-8222-222222222222"


def done(value):
    future = asyncio.get_running_loop().create_future()
    future.set_result(value)
    return future


class Output:
    def release_json(self):
        return '{"id":"B"}'

    def discard(self):
        pass


def client(native):
    c = SessionClient.__new__(SessionClient)
    c._native = native
    c._essential_epoch = 0
    return c


def cancelled(error):
    assert isinstance(error, SessionClientError) and error.code == "cancelled"


# contract-test: supporting surface=sdks.pip assertions=sdk.library.explicit-headless,auth.session.isolation
def test_actual_ticket_captures_original_before_first_poll_and_fresh_read_b_succeeds():
    async def run():
        calls = []

        class Native:
            def cancel(self):
                pass

            def chat_details_prepare(self, *args):
                calls.append(args)
                return done(Output())

        c = client(Native())
        # The callback precedes the inner ticket scheduled by the actual facade.
        asyncio.get_running_loop().call_soon(c.cancel)
        with pytest.raises(SessionClientError) as failure:
            await c.chat_details(CHAT)
        cancelled(failure.value)
        assert calls == []
        assert await c.chat_details(CHAT) == {"id": "B"}
        assert len(calls) == 1

    asyncio.run(run())


# contract-test: supporting surface=sdks.pip assertions=sdk.library.explicit-headless,auth.session.isolation
def test_actual_dict_encoder_cancel_prevents_read_work_and_auth_dispatch():
    async def run():
        calls = []

        class Native:
            def cancel(self):
                pass

            def chat_details_prepare(self, *args):
                calls.append(("read", args))
                return done(Output())

            def tasks_create(self, *args):
                calls.append(("work", args))
                return done('{"task":"B"}')

            def import_session(self, *args):
                calls.append(("import", args))
                return done(None)

        c = client(Native())

        class Reentrant(dict):
            def items(self):
                c.cancel()
                return super().items()

        for call in [
            lambda: c.chat_details(
                CHAT, Reentrant({"history": {"kind": "latest", "limit": 30}})
            ),
            lambda: SessionTasks(c).create(
                Reentrant({"title": "A"}), filters={"personal": True}
            ),
            lambda: c.import_session(Reentrant({"identity": "A"})),
        ]:
            with pytest.raises(SessionClientError) as failure:
                await call()
            cancelled(failure.value)
            assert calls == []
        assert await SessionTasks(c).create(
            {"title": "B"}, filters={"personal": True}
        ) == {"task": "B"}
        await c.import_session({"identity": "B"})
        assert [x[0] for x in calls] == ["work", "import"]

    asyncio.run(run())


# contract-test: supporting surface=sdks.pip assertions=sdk.library.explicit-headless,auth.session.isolation
def test_nested_public_import_started_by_encoder_cannot_dispatch_old_import_after_b():
    async def run():
        seen = []

        class Native:
            def import_session(self, raw):
                seen.append(json.loads(raw))
                return done(None)

        c = client(Native())

        class Reentrant(dict):
            def items(self):
                # Drive a supported coroutine synchronously until its immediate
                # completed future; creating it alone would intentionally be lazy.
                nested = c.import_session({"identity": "B"})
                try:
                    nested.send(None)
                except StopIteration:
                    pass
                else:
                    raise AssertionError("synthetic B unexpectedly suspended")
                return super().items()

        with pytest.raises(SessionClientError) as failure:
            await c.import_session(Reentrant({"identity": "A"}))
        cancelled(failure.value)
        assert seen == [{"identity": "B"}]
        await c.import_session({"identity": "fresh"})
        assert len(seen) == 2

    asyncio.run(run())


# contract-test: supporting surface=sdks.pip assertions=sdk.library.explicit-headless,auth.session.isolation
def test_watch_open_ticket_cannot_capture_replacement_epoch_at_task_first_poll():
    async def run():
        calls = []

        class Native:
            def cancel(self):
                pass

            def chat_monitor_open(self):
                calls.append("open")
                return done('{"id":"B","scope":{}}')

        c = client(Native())
        asyncio.get_running_loop().call_soon(c.cancel)
        with pytest.raises(SessionClientError) as failure:
            await c.watch_chats()
        cancelled(failure.value)
        assert calls == []
        assert await c.watch_chats() is not None
        assert calls == ["open"]

    asyncio.run(run())


# contract-test: supporting surface=sdks.pip assertions=sdk.library.explicit-headless,auth.session.isolation
def test_public_coroutine_not_started_before_cancel_remains_ordinary_lazy_new_invocation():
    async def run():
        calls = []

        class Native:
            def cancel(self):
                pass

            def chat_details_prepare(self, *args):
                calls.append(args)
                return done(Output())

        c = client(Native())
        not_started = c.chat_details(CHAT)
        c.cancel()
        assert calls == []
        assert await not_started == {"id": "B"}
        assert len(calls) == 1

    asyncio.run(run())


# contract-test: supporting surface=sdks.pip assertions=sdk.library.explicit-headless,auth.session.isolation
def test_first_page_store_validation_reentrancy_starts_no_old_native_open_then_fresh_positive():
    async def run():
        calls = []
        scope = {
            "api_url": "https://example.test",
            "account_id": "synthetic",
            "team_id": None,
        }

        def stage(source, id):
            return {
                "kind": "stage",
                "id": id,
                "source": source,
                "scope": scope,
                "checkpoint_json": "synthetic ciphertext",
                "credentials_json": "synthetic opaque credentials",
                "ciphertext_sha256": "stored",
                "credential_revision": 1,
            }

        events = [
            {
                "kind": "capacity",
                "id": "capacity",
                "scope": scope,
                "checkpoint_json_bytes": 3,
            },
            stage("first_page", "first"),
            {
                "kind": "first_page",
                "source": "first_page",
                "chat": {"id": CHAT, "messages": []},
                "cached": True,
                "refreshing": True,
                "history_complete": False,
                "has_more_before": True,
                "pii_restoration": "page_local",
            },
            stage("canonical", "last"),
            {
                "kind": "completed",
                "source": "canonical",
                "chat": {"id": CHAT, "messages": []},
                "cached": False,
                "refreshing": False,
                "history_complete": True,
                "has_more_before": False,
                "pii_restoration": "all_user_rows",
            },
        ]

        class Native:
            def cancel(self):
                pass

            def first_page_open(self, *args):
                calls.append("open")
                return done('{"id":"B"}')

            def first_page_next(self, *args):
                return done(json.dumps(events.pop(0)))

            def first_page_capacity(self, *args):
                pass

            def first_page_receipt(self, *args):
                pass

            def first_page_close(self, *args):
                calls.append("close")

        c = client(Native())

        class Store:
            reenter = True

            @property
            def generation(self):
                if self.reenter:
                    self.reenter = False
                    c.cancel()

                async def value(_scope):
                    return "expected"

                return value

            async def admit_first_page(self, input):
                return True

            async def compare_and_swap(self, input):
                return {
                    "stored": True,
                    "ciphertext_sha256": "stored",
                    "credential_revision": 1,
                }

        store = Store()
        with pytest.raises(SessionClientError) as failure:
            await c.read_chat_with_first_page(
                CHAT,
                store,
                include_secrets=True,
                include_private_output=True,
                on_first_page=lambda _: None,
            )
        cancelled(failure.value)
        assert calls == []
        result = await c.read_chat_with_first_page(
            CHAT,
            store,
            include_secrets=True,
            include_private_output=True,
            on_first_page=lambda _: None,
        )
        assert result["source"] == "canonical"
        assert calls == ["open", "close"]

    asyncio.run(run())
