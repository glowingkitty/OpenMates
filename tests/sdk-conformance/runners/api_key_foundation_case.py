"""Actual installed Python native facade; product runs isolated CI only."""

import asyncio
import json
import sys
from pathlib import Path
from urllib.request import urlopen
from openmates import RustApiKeyClient

fixture, id, endpoint = sys.argv[1:]
suite = json.loads(Path(fixture).read_text())["capabilities"]["sdk.configuration"]
v = next(x for x in suite["vectors"] if x["id"] == id)


def code(error):
    return getattr(error, "code", None) or json.loads(str(error))["code"]


async def control(path):
    def read():
        with urlopen(endpoint + path, timeout=5) as response:
            return json.load(response)

    return await asyncio.to_thread(read)


async def wait_post():
    async with asyncio.timeout(10):
        while (await control("/__test/status"))["skill_posts"] != 1:
            await asyncio.sleep(0)


async def main():
    client = RustApiKeyClient(
        api_key=suite["account"]["api_key"],
        api_url=endpoint,
        app_url=endpoint,
        device_id=suite["account"]["device_id"],
        enhanced_privacy=False,
        allow_private_operations=True,
    )
    value = None
    error = None
    try:
        mode = v["mode"]
        if mode in {"account", "account_auth_refusal"}:
            value = await client.account_info()
        elif mode in {"allocation_cancel", "allocation_close", "stale_successor"}:
            a = client._native.request()
            output = await a.account_info_prepare()
            try:
                if mode == "allocation_close":
                    client.close()
                else:
                    a.cancel()
                if mode == "stale_successor":
                    b = client._native.request()
                    next = await b.account_info_prepare()
                    output.discard()
                    a.cancel()
                    try:
                        value = json.loads(next.release_json())
                    finally:
                        next.discard()
                        b.cancel()
                else:
                    value = json.loads(output.release_json())
            finally:
                output.discard()
                a.cancel()
        elif mode in {"cancel_after_dispatch", "concurrent_account"}:
            a = asyncio.create_task(
                client.run_skill(
                    suite["request"]["app"],
                    suite["request"]["skill"],
                    suite["request"]["input"],
                )
            )
            await wait_post()
            if mode == "concurrent_account":
                value = await asyncio.wait_for(client.account_info(), 5)
            a.cancel()
            await control("/__test/release")
            try:
                await a
            except asyncio.CancelledError:
                if mode == "cancel_after_dispatch":
                    error = "cancelled"
            else:
                raise AssertionError("A did not cancel")
        elif mode in {
            "parallel_code_success",
            "parallel_code_failed_status",
            "parallel_code_http_failure",
        }:
            r = v["request"]
            pending = asyncio.create_task(
                client.run_skill(r["app"], r["skill"], r["input"])
            )
            async with asyncio.timeout(10):
                while True:
                    status = await control("/__test/status")
                    if status["code_all_arrived"] and status["code_b_sent"]:
                        assert not status["a_released"], (
                            "A released before B status response"
                        )
                        break
                    await asyncio.sleep(0)
            if mode == "parallel_code_http_failure":
                try:
                    await asyncio.wait_for(asyncio.shield(pending), 5)
                except Exception as failure:
                    assert code(failure) == "forbidden", (
                        "safe typed code HTTP failure before A release"
                    )
                    error = "forbidden"
                else:
                    raise AssertionError("code HTTP failure returned a value")
                assert (await control("/__test/code-terminal"))["terminal_while_a_held"]
                await control("/__test/release")
            else:
                await control("/__test/release")
                value = await pending
        elif mode in {"parallel_tasks_success", "parallel_tasks_failure"}:
            pending = asyncio.create_task(
                client.run_skill(
                    suite["request"]["app"],
                    suite["request"]["skill"],
                    suite["request"]["input"],
                )
            )
            async with asyncio.timeout(10):
                while True:
                    status = await control("/__test/status")
                    if status["parallel_all_arrived"] and status["parallel_b_sent"]:
                        assert not status["a_released"], "A released before B response"
                        break
                    await asyncio.sleep(0)
            if mode == "parallel_tasks_failure":
                try:
                    await asyncio.wait_for(asyncio.shield(pending), 5)
                except Exception as failure:
                    assert code(failure) == "invalid_argument", (
                        "safe typed original B failure before A release"
                    )
                    error = "invalid_argument"
                else:
                    raise AssertionError("B failure returned a value")
                assert (await control("/__test/parallel-terminal"))[
                    "terminal_while_a_held"
                ]
                await control("/__test/release")
            else:
                await control("/__test/release")
                value = await pending
        elif mode == "pre_cancel":
            request = client._native.request()
            request.cancel()
            try:
                await request.run_skill_prepare(
                    suite["request"]["app"],
                    suite["request"]["skill"],
                    json.dumps(suite["request"]["input"]),
                )
            finally:
                request.cancel()
        else:
            input = dict(suite["request"]["input"])
            if mode == "routing_override":
                input["model"] = None
            value = await client.run_skill(
                suite["request"]["app"], suite["request"]["skill"], input
            )
    except Exception as failure:
        error = code(failure)
    finally:
        client.close()
    print(
        json.dumps(
            {
                "id": id,
                "adapter": "actual-rust-api-key-library",
                **({"error": error} if error else {"value": value}),
            }
        )
    )  # sensitive-logging: allow - conformance runner result protocol on stdout; synthetic fixture data only


asyncio.run(main())
