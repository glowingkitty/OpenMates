"""PRIVATE UNRUN actual Python facade/PyO3 cache settlement shared vectors."""

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tests/sdk-conformance/runners"))
from essential_session import client, durable, refused, request  # noqa: E402 - import follows sys.path setup for sibling runner modules

CAP = "session.cache-preferred-settlement.v1"


def ack(stage, directory, index):
    target = directory / str(index)
    target.mkdir(mode=0o700)
    for name in ("checkpoint_json", "credentials_json"):
        raw = stage[name].encode("utf8")
        durable(target / name, raw)
        assert (target / name).read_bytes() == raw
    fd = os.open(target, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    digest = hashlib.sha256((target / "checkpoint_json").read_bytes()).hexdigest()
    assert digest == stage["ciphertext_sha256"]
    return {
        "ciphertext_sha256": digest,
        "credential_revision": stage["credential_revision"],
    }


def assert_owned_rows(chat):
    rows = chat["messages"]
    assert len(rows) == 40
    for index, row in enumerate(rows, 1):
        assert row["id"] == f"10000000-0000-4000-8000-{index:012d}"
        assert row["content"] == f"Synthetic cache row {index:03d} 雪"
        assert row["role"] == ("user" if index % 2 else "assistant")
        assert row["sender"] == "Fixture sender"
        assert row["thinking"] == "" and row["embeds"] == []


def output(value, canonical=False):
    assert value["source"] == ("canonical" if canonical else "cache_settled")
    assert value["history_complete"] is canonical
    assert value["cached"] is (not canonical)
    assert value["refreshing"] is False
    assert value["pii_restoration"] == (
        "all_user_rows" if canonical else "all_cached_user_rows"
    )
    assert value["chat"]["messages"]
    assert_owned_rows(value["chat"])
    if not canonical:
        assert value["has_more_before"] is None


async def vector(suite, entry, fixture):
    peer = await asyncio.create_subprocess_exec(
        sys.executable,
        str(ROOT / "tests/sdk-conformance/cache_settlement_peer.py"),
        "--fixture",
        str(fixture),
        "--capability",
        CAP,
        "--vector",
        entry["id"],
        "--identity",
        "pip",
        stdout=asyncio.subprocess.PIPE,
        stderr=None,  # inherited: the driver projects only class and tracked frames
    )
    value = monitor = None
    try:
        endpoint = json.loads(await asyncio.wait_for(peer.stdout.readline(), 5))[
            "endpoint"
        ]
        assert endpoint.startswith("http://127.0.0.1:")
        value = await client(suite, endpoint)
        await value.validate_session()
        chat = suite["protocol"]["initial_chat_id"]
        with tempfile.TemporaryDirectory(prefix="openmates-cache-sdk-") as raw:
            directory = Path(raw)
            stage = await value.cache_chat_stage(chat, include_secrets=True)
            assert stage["source"] == "canonical"
            output(
                await value.cache_chat_commit(stage["id"], ack(stage, directory, 0)),
                True,
            )
            mode = entry["mode"]
            if mode == "explicit-consent":
                await refused(
                    value.cache_chat_stage(chat, include_secrets=False),
                    {"invalid_argument"},
                )
            elif mode == "selected-denied":
                await request(endpoint, "/__test/control?action=deny")
                await refused(
                    value.cache_chat_stage(chat, include_secrets=True), {"forbidden"}
                )
            elif mode == "monitor-exact-ack":
                monitor = await value.watch_chats()
                await anext(monitor)
                stage = await monitor.stage_refresh_prefer_cache(
                    include_secrets=True, selected_chat_id=chat
                )
                result = await monitor.commit_refresh(
                    stage["id"], ack(stage, directory, 1)
                )
                selection = result["selection"]
                assert selection["kind"] == "cache_settled"
                assert selection["history_complete"] is False
                assert selection["pii_restoration"] == "all_cached_user_rows"
                assert_owned_rows(selection["chat"])
            else:
                stage = await value.cache_chat_stage(chat, include_secrets=True)
                assert stage["source"] == "cache_settled"
                receipt = ack(stage, directory, 1)
                if mode.startswith("selected-wrong-"):
                    wrong = dict(receipt)
                    if mode.endswith("hash"):
                        wrong["ciphertext_sha256"] = "0" * 64
                    else:
                        wrong["credential_revision"] += 1
                    await refused(
                        value.cache_chat_commit(stage["id"], wrong), {"conflict"}
                    )
                elif mode == "stale-a-active-b":
                    other = await value.cache_chat_stage(chat, include_secrets=True)
                    await refused(
                        value.cache_chat_commit(stage["id"], receipt), {"cancelled"}
                    )
                    stage, receipt = other, ack(other, directory, 2)
                elif mode == "discarded-stage":
                    await value.cache_chat_discard(stage["id"])
                    await refused(
                        value.cache_chat_commit(stage["id"], receipt), {"conflict"}
                    )
                    return {"id": entry["id"], "status": "passed"}
                output(await value.cache_chat_commit(stage["id"], receipt))
                await refused(
                    value.cache_chat_commit(stage["id"], receipt), {"conflict"}
                )
        return {"id": entry["id"], "status": "passed"}
    finally:
        try:
            if monitor is not None:
                await monitor.close()
            if value is not None:
                await value.close()
        finally:
            if peer.returncode is None:
                peer.terminate()
                try:
                    await asyncio.wait_for(peer.wait(), 2)
                except asyncio.TimeoutError:
                    peer.kill()
                    await peer.wait()


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--capability", required=True, choices=[CAP])
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
        print("Cache settlement Python conformance failed", file=sys.stderr)
        sys.exit(1)
