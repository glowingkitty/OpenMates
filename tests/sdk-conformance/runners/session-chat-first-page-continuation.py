"""Authored UNRUN actual Python/PyO3 vectors; owned synthetic encrypted peer."""

import argparse
import asyncio
import hashlib
import importlib
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tests/sdk-conformance/runners"))
from essential_session import Store, client, refused, session  # noqa: E402 - import follows sys.path setup for sibling runner modules
from support.owned_lifecycle import cleanup_owned  # noqa: E402 - import follows sys.path setup for sibling runner modules

CAP = "session.chat-first-page-continuation.v1"
MODES = {
    "admit",
    "capacity-false",
    "capacity-error",
    "wrong-hash",
    "wrong-revision",
    "wrong-purpose",
    "cas-refused",
    "callback-failure",
    "callback-cancel",
    "stale-a-b",
    "no-secrets",
    "no-private",
    "warm",
    "strict",
}


def requests(log):
    return (
        [json.loads(line) for line in log.read_text().splitlines()]
        if log.exists()
        else []
    )


def logical(chat, mode, index):
    physical = f"10000000-0000-4000-8000-{index:012d}"
    if mode == "uuid":
        return physical
    if mode == "composite":
        return chat.replace("-", "")[:10] + "-" + physical
    if mode == "opaque":
        return f"legacy_msg_{index:04d}"
    raise AssertionError("unregistered ID mode")


def rows(value, chat, mode, start, count):
    assert value["chat"]["id"] == chat and len(value["chat"]["messages"]) == count
    for index, row in enumerate(value["chat"]["messages"], start):
        assert row["id"] == logical(chat, mode, index)
        assert row["content"] == f"Synthetic first-page row {index:03d} 雪"
        assert row["role"] == ("user" if index % 2 else "assistant")
        assert (
            row["sender"] == "Fixture sender"
            and row["thinking"] == ""
            and row["embeds"] == []
        )


def completed(value, chat, mode, canonical=True, count=140):
    assert value["source"] == ("canonical" if canonical else "cache_settled")
    assert value["history_complete"] is canonical and value["cached"] is (not canonical)
    assert value["refreshing"] is False
    assert value["pii_restoration"] == (
        "all_user_rows" if canonical else "all_cached_user_rows"
    )
    rows(value, chat, mode, 141 - count, count)


class CallbackFailure(Exception):
    pass


class CapacityFailure(Exception):
    pass


class Durable(Store):
    def __init__(self, directory, mode, chat, log):
        super().__init__(directory)
        self.mode, self.chat, self.log = mode, chat, log
        self.admissions = 0
        self.stages = []
        self.stage_ids = []

    async def admit_first_page(self, value):
        self.admissions += 1
        assert self.admissions == 1 and value["checkpoint_json_bytes"] > 0
        assert value["scope"]["account_id"] and value["scope"]["api_url"].startswith(
            "http://127.0.0.1:"
        )
        assert requests(self.log) == [{"direction": "latest", "limit": 100}]
        if self.mode == "capacity-error":
            raise CapacityFailure()
        return self.mode != "capacity-false"

    async def compare_and_swap(self, value):
        checkpoint = json.loads(value["checkpoint_json"])
        selected = checkpoint.get("selected_first_pages", {}).get(self.chat)
        purpose = (
            "first_page"
            if selected
            else "canonical"
            if self.chat in checkpoint.get("history", {})
            else "cache_settled"
        )
        assert value["next_version"] not in self.stage_ids
        self.stage_ids.append(value["next_version"])
        self.stages.append(purpose)
        if selected:
            assert len(selected["messages"]) == 100 and self.chat not in checkpoint.get(
                "history", {}
            )
            assert (
                "Synthetic first-page row" not in value["checkpoint_json"]
                and "Fixture sender" not in value["checkpoint_json"]
            )
            assert requests(self.log) == [{"direction": "latest", "limit": 100}]
        if self.mode == "cas-refused":
            return {"stored": False}
        receipt = await super().compare_and_swap(value)
        assert receipt["stored"] is True
        if self.mode == "wrong-hash":
            receipt["ciphertext_sha256"] = "0" * 64
        elif self.mode == "wrong-revision":
            receipt["credential_revision"] += 1
        elif self.mode == "wrong-purpose":
            receipt["ciphertext_sha256"] = hashlib.sha256(
                value["credentials_json"].encode()
            ).hexdigest()
        return receipt


async def stale_pending(native, suite, endpoint, store, chat, id_mode, log):
    async def next_event(operation):
        return json.loads(await native.first_page_next(operation))

    def conflict(operation):
        try:
            operation()
        except RuntimeError as error:
            assert json.loads(str(error))["code"] == "conflict"
        else:
            raise AssertionError("stale A must refuse while B awaits ACK")

    async def persist(stage):
        receipt = await store.compare_and_swap(
            {
                "scope": stage["scope"],
                "expected_version": await store.generation(stage["scope"]),
                "next_version": stage["id"],
                "checkpoint_json": stage["checkpoint_json"],
                "credentials_json": stage["credentials_json"],
                "ciphertext_sha256": stage["ciphertext_sha256"],
                "credential_revision": stage["credential_revision"],
            }
        )
        assert receipt["stored"] is True
        return json.dumps(
            {
                "ciphertext_sha256": receipt["ciphertext_sha256"],
                "credential_revision": receipt["credential_revision"],
            }
        )

    a = json.loads(await native.first_page_open(chat, True, True))["id"]
    capacity = await next_event(a)
    assert capacity["kind"] == "capacity"
    native.first_page_capacity(a, capacity["id"], True)
    stage_a = await next_event(a)
    assert stage_a["source"] == "first_page"
    receipt_a = await persist(stage_a)
    native.first_page_receipt(a, stage_a["id"], receipt_a)
    page = await next_event(a)
    assert page["kind"] == "first_page"
    rows(page, chat, id_mode, 41, 100)
    assert requests(log) == [{"direction": "latest", "limit": 100}]
    native.first_page_close(a)
    b = json.loads(await native.first_page_open(chat, True, True))["id"]
    stage_b = await next_event(b)
    assert stage_b["kind"] == "stage" and stage_b["source"] == "cache_settled"
    receipt_b = await persist(stage_b)
    # B is live and blocked awaiting its own exact ACK throughout stale A calls.
    conflict(lambda: native.first_page_close(a))
    conflict(lambda: native.first_page_receipt(a, stage_a["id"], receipt_a))
    assert requests(log) == [{"direction": "latest", "limit": 100}]
    native.first_page_receipt(b, stage_b["id"], receipt_b)
    done = await next_event(b)
    assert done["kind"] == "completed"
    completed(done, chat, id_mode, False, 100)
    assert requests(log) == [{"direction": "latest", "limit": 100}]


async def vector(suite, entry, fixture):
    mode, id_mode = entry["mode"], entry["message_id_mode"]
    assert mode in MODES, "unregistered mode must fail"
    value = peer = None
    with tempfile.TemporaryDirectory(prefix="openmates-first-page-sdk-") as raw:
        directory = Path(raw)
        log = directory / "requests.jsonl"
        store_dir = directory / "store"
        store_dir.mkdir(mode=0o700)
        try:
            peer = await asyncio.create_subprocess_exec(
                sys.executable,
                str(ROOT / "tests/sdk-conformance/first_page_continuation_peer.py"),
                "--fixture",
                str(fixture),
                "--capability",
                CAP,
                "--request-log",
                str(log),
                "--identity",
                "pip",
                "--message-id-mode",
                id_mode,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            endpoint = json.loads(await asyncio.wait_for(peer.stdout.readline(), 5))[
                "endpoint"
            ]
            assert endpoint.startswith("http://127.0.0.1:")
            chat = suite["protocol"]["initial_chat_id"]
            store = Durable(store_dir, mode, chat, log)
            callbacks = []
            if mode == "stale-a-b":
                from openmates._native import NativeSessionClient

                value = NativeSessionClient(
                    json.dumps(
                        {
                            "api_url": endpoint,
                            "app_url": suite["protocol"]["app_origin"],
                            "enhanced_privacy": False,
                            "allow_private_operations": True,
                        }
                    )
                )
                await value.import_session(json.dumps(session(suite, endpoint)))
                await value.validate_session()
                await stale_pending(value, suite, endpoint, store, chat, id_mode, log)
                return {"id": entry["id"], "status": "passed"}
            value = await client(suite, endpoint)
            await value.validate_session()

            async def callback(page):
                assert page["source"] == "first_page" and page["kind"] == "first_page"
                assert (
                    page["cached"] is True
                    and page["refreshing"] is True
                    and page["history_complete"] is False
                )
                assert (
                    page["has_more_before"] is True
                    and page["pii_restoration"] == "page_local"
                )
                rows(page, chat, id_mode, 41, 100)
                callbacks.append(page)
                assert store.stages == ["first_page"]
                assert requests(log) == [{"direction": "latest", "limit": 100}]
                await asyncio.sleep(0)
                assert requests(log) == [{"direction": "latest", "limit": 100}]
                if mode == "callback-failure":
                    raise CallbackFailure()
                if mode == "callback-cancel":
                    raise asyncio.CancelledError()

            async def read(
                secret=True, private=True, cb=callback, selected_store=store
            ):
                return await value.read_chat_with_first_page(
                    chat,
                    selected_store,
                    include_secrets=secret,
                    include_private_output=private,
                    on_first_page=cb,
                )

            if mode in ("no-secrets", "no-private"):
                await refused(
                    read(secret=mode != "no-secrets", private=mode != "no-private"),
                    {"invalid_argument"},
                )
                assert not callbacks and not requests(log) and not store.stages
            elif mode == "strict":
                stage = await value.cache_chat_stage(chat, include_secrets=True)
                assert stage["source"] == "canonical" and not store.admissions
                ack = importlib.import_module("session-cache-preferred-settlement").ack
                completed(
                    await value.cache_chat_commit(
                        stage["id"], ack(stage, directory, 0)
                    ),
                    chat,
                    id_mode,
                )
            elif mode in ("capacity-error", "callback-failure"):
                expected = (
                    CapacityFailure if mode == "capacity-error" else CallbackFailure
                )
                try:
                    await read()
                except expected:
                    pass
                else:
                    raise AssertionError("callback/store exception must propagate")
                assert len(callbacks) == int(mode == "callback-failure")
                assert requests(log) == [{"direction": "latest", "limit": 100}]
            elif mode == "callback-cancel":
                try:
                    await read()
                except asyncio.CancelledError:
                    pass
                else:
                    raise AssertionError("callback cancellation must propagate")
                assert len(callbacks) == 1 and requests(log) == [
                    {"direction": "latest", "limit": 100}
                ]
            elif mode in (
                "wrong-hash",
                "wrong-revision",
                "wrong-purpose",
                "cas-refused",
            ):
                await refused(read(), {"conflict"})
                assert not callbacks and requests(log) == [
                    {"direction": "latest", "limit": 100}
                ]
            else:
                completed(await read(), chat, id_mode)
                assert len(callbacks) == int(mode != "capacity-false")
                assert store.stages == (
                    ["canonical"]
                    if mode == "capacity-false"
                    else ["first_page", "canonical"]
                )
                if mode == "warm":
                    callbacks.clear()
                    before = requests(log)
                    completed(await read(), chat, id_mode, False)
                    assert (
                        not callbacks
                        and requests(log) == before
                        and store.admissions == 1
                    )
            if mode in ("admit", "capacity-false", "warm", "strict"):
                expected = [
                    {"direction": "latest", "limit": 100},
                    {"direction": "before", "limit": 100},
                ]
                if id_mode != "uuid":
                    expected[1]["cursor_message_id"] = logical(chat, id_mode, 41)
                assert requests(log) == expected
            return {"id": entry["id"], "status": "passed"}
        finally:
            await cleanup_owned(peer, value)


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--capability", choices=[CAP], required=True)
    args = parser.parse_args()
    raw = args.fixture.read_bytes()
    suite = json.loads(raw)["capabilities"][CAP]
    results = [
        await asyncio.wait_for(vector(suite, entry, args.fixture), 25)
        for entry in suite["vectors"]
    ]
    print(
        json.dumps(
            {
                "capability": CAP,
                "language": "python",
                "status": "passed",
                "fixtureSha256": hashlib.sha256(raw).hexdigest(),
                "results": results,
            }
        )
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception:
        print("First-page Python conformance failed", file=sys.stderr)
        sys.exit(1)
