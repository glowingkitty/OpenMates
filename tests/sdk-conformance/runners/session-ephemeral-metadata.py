"""Actual Python library/PyO3 calls; fixed gate owns the independent peer."""

import asyncio
import json
from pathlib import Path
import sys
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "packages/openmates-python"))
from openmates import MetadataAuthentication, MetadataEphemeralError  # noqa: E402 - import follows sys.path setup for sibling runner modules


def arg(name):
    return sys.argv[sys.argv.index(name) + 1]


suite = json.loads(Path(arg("--fixture")).read_bytes())["capabilities"][
    "session.ephemeral-metadata-startup.v1"
]
vector = next(row for row in suite["vectors"] if row["id"] == arg("--vector"))
endpoint = arg("--endpoint")
observed_lifecycle = None


def options(extra=None):
    return {
        "apiUrl": endpoint,
        "appUrl": suite["protocol"]["app_origin"],
        "sessionId": suite["account"]["session_id"],
        "cookies": {"auth_refresh_token": suite["account"]["cookie"]},
        **(extra or {}),
    }


async def refused(awaitable, code):
    try:
        await awaitable
    except MetadataEphemeralError as error:
        assert error.code == code
    else:
        raise AssertionError("negative metadata operation succeeded")


def count_refused(snapshot, client, code):
    try:
        snapshot.received_metadata_count(client)
    except MetadataEphemeralError as error:
        assert error.code == code
    else:
        raise AssertionError("foreign/stale metadata escaped")


async def wait_metadata():
    def read():
        with urlopen(endpoint + "/__test/status", timeout=2) as response:
            return json.load(response)

    for _ in range(200):
        if (await asyncio.to_thread(read))["metadata_requests"] == 1:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("bounded metadata dispatch")


AUTH_FAILURE_MODES = {
    "late_invalid_cookie",
    "late_undecodable_cookie",
    "malformed_body",
    "truncated_body",
    "held_malformed_body",
    "cancel_before_headers",
    "cancel_after_headers",
    "foreign_auth_cancel",
    "early_invalid_cookie",
    "early_undecodable_cookie",
}


async def request(route):
    def read():
        with urlopen(endpoint + route, timeout=2) as response:
            return json.load(response)

    return await asyncio.wait_for(asyncio.to_thread(read), 3)


async def wait_for(predicate):
    for _ in range(200):
        value = await request("/__test/status")
        if predicate(value):
            return value
        await asyncio.sleep(0.01)
    raise AssertionError("bounded original auth condition")


async def auth_failure(pending):
    global observed_lifecycle
    mode = vector["mode"]
    run = asyncio.create_task(pending.authenticate())
    held = mode in {
        "held_malformed_body",
        "cancel_before_headers",
        "cancel_after_headers",
        "foreign_auth_cancel",
    }
    if held:
        marker = (
            "before_headers_held" if mode == "cancel_before_headers" else "body_held"
        )
        observed = await wait_for(lambda value: marker in value["auth_events"])
        assert (
            observed["auth_active"] == 1
            and observed["connections"] == 0
            and not run.done()
        )
        if mode == "cancel_before_headers":
            assert (
                pending.credential_snapshot()["cookies"]["auth_refresh_token"]
                == suite["account"]["cookie"]
            )
        else:
            await wait_for(
                lambda _: (
                    pending.credential_snapshot()["cookies"]["auth_refresh_token"]
                    == "synthetic-rotation-1"
                )
            )
        drain = None
        if mode == "foreign_auth_cancel":
            # Supported Python cancellation invokes the facade's ORIGINAL
            # negative token. It is not proof of the retained Rust IO ending.
            run.cancel()
            try:
                await run
            except asyncio.CancelledError:
                pass
            else:
                raise AssertionError("foreign cancellation returned a scope")
            drain = asyncio.create_task(pending.cancel_and_drain())
        elif mode != "held_malformed_body":
            pending.cancel()
            drain = asyncio.create_task(pending.cancel_and_drain())
        if drain:
            still_held = await request("/__test/status")
            assert (
                still_held["auth_active"] == 1
                and "body_written" not in still_held["auth_events"]
                and not drain.done()
            )
        assert await request("/__test/release-auth") == {"released": True}
        if mode != "foreign_auth_cancel":
            await refused(run, vector["error"])
        if drain:
            await drain
    else:
        await refused(run, vector["error"])
    await pending.cancel_and_drain()
    assert pending.credential_snapshot()["cookies"] == {
        "auth_refresh_token": "synthetic-rotation-1"
    }
    await refused(pending.authenticate(), "conflict")
    after = await wait_for(lambda value: value["auth_active"] == 0)
    assert after["auth_requests"] == 1 and after["connections"] == 0
    if mode == "foreign_auth_cancel":
        observed_lifecycle = "task-cancel-propagates-original-cancel"


async def main():
    mode = vector["mode"]
    if mode in AUTH_FAILURE_MODES:
        pending = MetadataAuthentication(options())
        try:
            await auth_failure(pending)
        finally:
            await pending.cancel_and_drain()
        return
    if mode in ("owner_dto", "api_key"):
        try:
            MetadataAuthentication(
                options(
                    {"ownerId": suite["account"]["owner_id"]}
                    if mode == "owner_dto"
                    else {"apiKey": "synthetic-api-key"}
                )
            )
        except MetadataEphemeralError as error:
            assert error.code == vector["error"]
        else:
            raise AssertionError("caller authority accepted")
        return
    pending = MetadataAuthentication(options())
    client = None
    try:
        if mode in ("denied", "malformed", "expired"):
            await refused(pending.authenticate(), vector["error"])
            assert (
                pending.credential_snapshot()["cookies"]["auth_refresh_token"]
                == "synthetic-rotation-1"
            )
            return
        client = await pending.authenticate()
        assert (
            client.credential_snapshot()["cookies"]["auth_refresh_token"]
            == "synthetic-rotation-1"
        )
        if mode == "auth_cancel":
            pending.cancel()
            try:
                client.prepare_initial_sync()
            except MetadataEphemeralError as error:
                assert error.code == "cancelled"
            else:
                raise AssertionError("cancelled auth origin issued usable context")
            return
        operation = client.prepare_initial_sync()
        if mode == "cancel_before":
            operation.cancel()
        if "error" in vector:
            run = asyncio.create_task(operation.run())
            if mode == "cancel_inflight":
                await wait_metadata()
                operation.cancel()
            await refused(run, vector["error"])
            if mode in ("rotation_failure", "changed_principal"):
                assert (
                    client.credential_snapshot()["cookies"]["auth_refresh_token"]
                    == "synthetic-rotation-2"
                )
            try:
                client.prepare_initial_sync()
            except MetadataEphemeralError as error:
                assert error.code == "cancelled"
            else:
                raise AssertionError("failed original rearmed")
            return
        snapshot = await operation.run()
        assert snapshot.received_metadata_count(client) == vector["expected_count"]
        await refused(operation.run(), "conflict")
        if mode == "foreign_snapshot":
            second = MetadataAuthentication(
                {**options(), **client.credential_snapshot()}
            )
            foreign = await second.authenticate()
            try:
                count_refused(snapshot, foreign, "forbidden")
            finally:
                await foreign.close()
            assert snapshot.received_metadata_count(client) == vector["expected_count"]
        if mode == "stale_snapshot":
            next_operation = client.prepare_initial_sync()
            count_refused(snapshot, client, "cancelled")
            next_operation.cancel()
        await client.close()
        count_refused(snapshot, client, "cancelled")
    finally:
        if client:
            await client.close()
        pending.cancel()


if __name__ == "__main__":
    try:
        asyncio.run(main())
        print(
            json.dumps(
                {
                    "id": vector["id"],
                    "status": "passed",
                    **({"lifecycle": observed_lifecycle} if observed_lifecycle else {}),
                }
            )
        )
    except Exception:
        print("Python opaque metadata conformance failed", file=sys.stderr)
        raise SystemExit(1)
