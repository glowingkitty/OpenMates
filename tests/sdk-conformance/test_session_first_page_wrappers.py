"""Actual helper source with mock native/store; no Rust or real-SDK proof."""

# contract-test-file: tooling
import asyncio
import json
import os
from pathlib import Path
import unittest

ROOT = Path(
    os.environ.get("OPENMATES_FIRST_PAGE_OVERLAY", Path(__file__).resolve().parents[2])
)
from openmates.session_client import SessionClient, SessionClientError  # noqa: E402 - import follows sys.path setup for sibling runner modules

scope = {
    "SessionClientError": SessionClientError,
    "__name__": "openmates.first_page_session",
    "__package__": "openmates",
}
source = (
    (ROOT / "packages/openmates-python/openmates/first_page_session.py")
    .read_text()
    .replace("    from .session_client import SessionClientError", "    pass")
)
exec(compile(source, "first_page_session.py", "exec"), scope)
read = scope["read_chat_with_first_page"]
CHAT = "22222222-2222-4222-8222-222222222222"


def stage(source, id):
    return {
        "kind": "stage",
        "id": id,
        "source": source,
        "scope": {
            "api_url": "https://example.test",
            "account_id": "synthetic",
            "team_id": None,
        },
        "checkpoint_json": '{"encrypted":"exact 雪\\n"}',
        "credentials_json": '{"session":"synthetic opaque"}',
        "ciphertext_sha256": "actual-stored-hash",
        "credential_revision": 7,
    }


class Fixture:
    # Use the actual new preparation checks; retain all original protocol oracles.
    _prepared_call = SessionClient._prepared_call
    _dispatch_prepared = SessionClient._dispatch_prepared
    _check_epoch = SessionClient._check_epoch

    def __init__(self):
        self._native = self
        self._essential_epoch = 0
        self.calls = []
        self.callback = False
        self.refused = False
        self.events = [
            {
                "kind": "capacity",
                "id": "capacity-first",
                "scope": stage("first_page", "unused")["scope"],
                "checkpoint_json_bytes": 123456,
            },
            stage("first_page", "stage-first"),
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
            stage("canonical", "stage-final"),
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

    async def _call(self, operation):
        return await operation()

    async def _essential_call(self, operation):
        return await operation()

    async def first_page_open(self, *args):
        self.calls.append(("open", args))
        return json.dumps({"id": "owned-read"})

    async def first_page_next(self, id):
        self.calls.append(("next", id))
        if self.events[0].get("id") == "stage-final" and not self.refused:
            assert self.callback
        return json.dumps(self.events.pop(0))

    def first_page_capacity(self, id, stage, accepted):
        self.calls.append(("capacity-receipt", (id, stage, accepted)))
        if not accepted:
            self.refused = True
            del self.events[:2]

    async def admit_first_page(self, input):
        self.calls.append(("capacity-policy", input))
        return True

    def first_page_receipt(self, *args):
        self.calls.append(("receipt", args))

    def first_page_close(self, id):
        self.calls.append(("close", id))

    async def generation(self, scope):
        return "stored-generation"

    async def compare_and_swap(self, input):
        self.calls.append(("save", input))
        return {
            "stored": True,
            "ciphertext_sha256": "actual-stored-hash",
            "credential_revision": 7,
        }

    async def on_first_page(self, page):
        assert page["pii_restoration"] == "page_local"
        self.callback = True
        self.calls.append(("callback", None))

    async def run(self, **kwargs):
        return await read(
            self,
            CHAT,
            self,
            include_secrets=True,
            include_private_output=True,
            on_first_page=kwargs.pop("callback", self.on_first_page),
            **kwargs,
        )


class Tests(unittest.IsolatedAsyncioTestCase):
    async def test_exact_store_receipt_and_callback_order(self):
        f = Fixture()
        output = await f.run()
        self.assertTrue(output["history_complete"])
        self.assertEqual(
            [c[0] for c in f.calls],
            [
                "open",
                "next",
                "capacity-policy",
                "capacity-receipt",
                "next",
                "save",
                "receipt",
                "next",
                "callback",
                "next",
                "save",
                "receipt",
                "next",
                "close",
            ],
        )
        for _, item in [c for c in f.calls if c[0] == "save"]:
            self.assertEqual(item["checkpoint_json"], '{"encrypted":"exact 雪\\n"}')
        for _, args in [c for c in f.calls if c[0] == "receipt"]:
            self.assertEqual(
                json.loads(args[2]),
                {"ciphertext_sha256": "actual-stored-hash", "credential_revision": 7},
            )

    async def test_each_consent_refused_without_native_call(self):
        for secrets, private in [(False, True), (True, False), (False, False)]:
            f = Fixture()
            with self.assertRaises(SessionClientError):
                await read(
                    f,
                    CHAT,
                    f,
                    include_secrets=secrets,
                    include_private_output=private,
                    on_first_page=f.on_first_page,
                )
            self.assertEqual(f.calls, [])

    async def test_callback_failure_no_older_pull(self):
        f = Fixture()

        async def fail(page):
            raise ValueError("callback stop")

        with self.assertRaisesRegex(ValueError, "callback stop"):
            await f.run(callback=fail)
        self.assertEqual(sum(c[0] == "next" for c in f.calls), 3)
        self.assertEqual(f.calls[-1], ("close", "owned-read"))

    async def test_cas_failure_has_no_ack_or_callback(self):
        f = Fixture()

        async def refuse(input):
            return {"stored": False}

        f.compare_and_swap = refuse
        with self.assertRaises(SessionClientError) as raised:
            await f.run()
        self.assertEqual(raised.exception.code, "conflict")
        self.assertFalse(any(c[0] in ("receipt", "callback") for c in f.calls))

    async def test_actual_writer_wrong_receipt_is_forwarded_not_fabricated(self):
        f = Fixture()

        async def wrong(input):
            return {
                "stored": True,
                "ciphertext_sha256": "WRITER_DIFFERENT",
                "credential_revision": 8,
            }

        def reject(id, stage, receipt):
            self.assertEqual(
                json.loads(receipt),
                {"ciphertext_sha256": "WRITER_DIFFERENT", "credential_revision": 8},
            )
            raise SessionClientError("conflict", "wrong exact ACK")

        f.compare_and_swap = wrong
        f.first_page_receipt = reject
        with self.assertRaises(SessionClientError):
            await f.run()
        self.assertEqual(sum(c[0] == "next" for c in f.calls), 2)

    async def test_cancel_during_callback_closes_owned_read_no_continuation(self):
        f = Fixture()
        entered = asyncio.Event()
        hold = asyncio.Event()

        async def block(page):
            entered.set()
            await hold.wait()

        task = asyncio.create_task(f.run(callback=block))
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(sum(c[0] == "next" for c in f.calls), 3)
        self.assertEqual(f.calls[-1], ("close", "owned-read"))

    async def test_unstaged_private_event_is_rejected(self):
        f = Fixture()
        del f.events[:2]
        with self.assertRaises(SessionClientError) as raised:
            await f.run()
        self.assertEqual(raised.exception.code, "protocol")
        self.assertFalse(f.callback)

    async def test_late_epoch_suppresses_final_output(self):
        f = Fixture()
        original = f.first_page_next

        async def changed(id):
            raw = await original(id)
            if json.loads(raw)["kind"] == "completed":
                f._essential_epoch += 1
            return raw

        f.first_page_next = changed
        with self.assertRaises(SessionClientError) as raised:
            await f.run()
        self.assertEqual(raised.exception.code, "cancelled")

    async def test_explicit_quota_skips_only_preview_and_finishes_strict(self):
        f = Fixture()

        async def refuse(input):
            return False

        f.admit_first_page = refuse
        done = await f.run()
        self.assertEqual(done["source"], "canonical")
        self.assertTrue(done["history_complete"])
        self.assertFalse(f.callback)
        self.assertEqual(
            next(c[1] for c in f.calls if c[0] == "capacity-receipt"),
            ("owned-read", "capacity-first", False),
        )
        self.assertEqual(sum(c[0] == "save" for c in f.calls), 1)

    async def test_capacity_io_failure_is_not_quota_refusal(self):
        f = Fixture()

        async def fail(input):
            raise SessionClientError("io", "store failure")

        f.admit_first_page = fail
        with self.assertRaises(SessionClientError) as raised:
            await f.run()
        self.assertEqual(raised.exception.code, "io")
        self.assertFalse(
            any(c[0] in ("capacity-receipt", "receipt", "save") for c in f.calls)
        )
        self.assertEqual(f.calls[-1], ("close", "owned-read"))

    async def test_missing_explicit_capacity_policy_refuses_before_open(self):
        f = Fixture()
        f.admit_first_page = None
        with self.assertRaises(SessionClientError) as raised:
            await f.run()
        self.assertEqual(raised.exception.code, "invalid_argument")
        self.assertEqual(f.calls, [])


if __name__ == "__main__":
    unittest.main()
