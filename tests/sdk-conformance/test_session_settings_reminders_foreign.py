"""Pure foreign-adapter and fixture-oracle checks; no SDK imports/network/timers."""

# contract-test-file: tooling
from __future__ import annotations
import ast
import asyncio
import json
from pathlib import Path
import runpy
from typing import Any
import unittest

ROOT = Path(__file__).resolve().parents[2]


# The Python SessionClient source is split across these modules; definitions
# are extracted from their combined module body without importing the package.
SESSION_SOURCES = ("session_types.py", "session_facades.py", "session_client.py")


def session_source_text(root):
    package = root / "packages/openmates-python/openmates"
    return "\n".join((package / name).read_text() for name in SESSION_SOURCES)


def extracted_api():
    source = ast.parse(session_source_text(ROOT))
    wanted = {
        "SessionClientError",
        "SessionSettingsReadError",
        "_failure",
        "SessionAccount",
    }
    nodes = [
        node
        for node in source.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.name in wanted
    ]
    assert {node.name for node in nodes} == wanted
    tree = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__", names=[ast.alias(name="annotations")], level=0
            ),
            *nodes,
        ],
        type_ignores=[],
    )
    namespace = {"asyncio": asyncio, "json": json, "Any": Any}
    exec(
        compile(ast.fix_missing_locations(tree), "<actual foreign adapter>", "exec"),
        namespace,
    )
    return namespace


API = extracted_api()


class Output:
    def __init__(self, operation):
        self.operation = operation
        self.discarded = 0
        self.released = 0

    def release_json(self):
        self.released += 1
        if self.operation.cancelled:
            raise RuntimeError(
                json.dumps(
                    {
                        "code": "cancelled",
                        "message": "synthetic cancellation",
                        "http_status": None,
                    }
                )
            )
        return json.dumps(self.operation.value)

    def discard(self):
        self.discarded += 1


class Operation:
    def __init__(self, value=None):
        self.value = value
        self.cancelled = False
        self.future = asyncio.get_running_loop().create_future()
        self.started = asyncio.Event()
        self.output = Output(self)

    def run(self):
        self.started.set()
        return self.future

    def cancel(self):
        self.cancelled = True

    def finish(self):
        self.future.set_result(self.output)


class Client:
    _essential_epoch = 0

    def __init__(self, operations):
        self.operations = iter(operations)
        self._native = self

    def account_reminders_open(self):
        return next(self.operations)

    def _check_epoch(self, epoch, message):
        if epoch != self._essential_epoch:
            raise API["SessionClientError"]("cancelled", message)


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_complete_raw_value_and_opaque_discard(self):
        value = {
            "encrypted_title": "opaque",
            "extension": {"unknownCamelCase": [True, 1, None]},
        }
        operation = Operation(value)
        operation.finish()
        result = await API["SessionAccount"](Client([operation])).reminders()
        self.assertEqual(result, value)
        self.assertEqual(operation.output.discarded, 1)
        self.assertTrue(operation.cancelled)

    async def test_ordered_root_is_not_remapped_by_facade(self):
        value = json.loads('{"z":3,"a":2,"é":4}')
        operation = Operation(value)
        operation.finish()
        result = await API["SessionAccount"](Client([operation])).reminders()
        self.assertEqual(
            json.dumps(result, ensure_ascii=False, separators=(",", ":")),
            '{"z":3,"a":2,"é":4}',
        )

    async def test_exact_http_status_and_message_are_retained(self):
        operation = Operation()
        operation.future.set_exception(
            RuntimeError(
                json.dumps(
                    {
                        "code": "forbidden",
                        "message": "Settings GET failed with HTTP 403",
                        "http_status": 403,
                    }
                )
            )
        )
        with self.assertRaises(API["SessionSettingsReadError"]) as caught:
            await API["SessionAccount"](Client([operation])).reminders()
        self.assertEqual(caught.exception.http_status, 403)
        self.assertEqual(str(caught.exception), "Settings GET failed with HTTP 403")
        self.assertEqual(caught.exception.code, "forbidden")

    async def test_protocol_refusal_is_typed_and_never_empty_success(self):
        operation = Operation()
        operation.future.set_exception(
            RuntimeError(
                json.dumps(
                    {
                        "code": "protocol",
                        "message": "The service returned an invalid response.",
                        "http_status": None,
                    }
                )
            )
        )
        with self.assertRaises(API["SessionSettingsReadError"]) as caught:
            await API["SessionAccount"](Client([operation])).reminders()
        self.assertEqual(caught.exception.code, "protocol")
        self.assertIsNone(caught.exception.http_status)
        self.assertEqual(
            str(caught.exception), "The service returned an invalid response."
        )
        self.assertEqual(operation.output.released, 0)

    async def test_unsupported_json_refusal_preserves_exact_core_message(self):
        operation = Operation()
        message = (
            "The settings response exceeds the supported JSON limits or representation."
        )
        operation.future.set_exception(
            RuntimeError(
                json.dumps(
                    {"code": "unavailable", "message": message, "http_status": None}
                )
            )
        )
        with self.assertRaises(API["SessionSettingsReadError"]) as caught:
            await API["SessionAccount"](Client([operation])).reminders()
        self.assertEqual(caught.exception.code, "unavailable")
        self.assertIsNone(caught.exception.http_status)
        self.assertEqual(str(caught.exception), message)
        self.assertEqual(operation.output.released, 0)

    async def test_owner_error_is_not_an_http_fallback(self):
        operation = Operation()
        operation.future.set_exception(
            RuntimeError(
                json.dumps(
                    {
                        "code": "expired",
                        "message": "original owner denial",
                        "http_status": None,
                    }
                )
            )
        )
        with self.assertRaises(API["SessionSettingsReadError"]) as caught:
            await API["SessionAccount"](Client([operation])).reminders()
        self.assertIsNone(caught.exception.http_status)
        self.assertEqual(str(caught.exception), "original owner denial")

    async def test_host_cancel_drains_only_A_and_discards_late_output(self):
        a, b = Operation("private-A"), Operation("healthy-B")
        client = Client([a, b])
        api = API["SessionAccount"](client)
        pending = asyncio.create_task(api.reminders())
        await a.started.wait()
        pending.cancel()
        await asyncio.sleep(0)
        self.assertTrue(a.cancelled)
        self.assertFalse(b.cancelled)
        self.assertFalse(pending.done(), "original native transaction must drain")
        a.finish()
        with self.assertRaises(asyncio.CancelledError):
            await pending
        self.assertEqual(a.output.released, 0)
        self.assertGreaterEqual(a.output.discarded, 1)
        b.finish()
        self.assertEqual(await api.reminders(), "healthy-B")

    async def test_repeated_cancel_keeps_late_discard_callback(self):
        a = Operation("private-A")
        pending = asyncio.create_task(API["SessionAccount"](Client([a])).reminders())
        await a.started.wait()
        pending.cancel()
        await asyncio.sleep(0)
        pending.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await pending
        a.finish()
        await asyncio.sleep(0)
        self.assertGreaterEqual(a.output.discarded, 1)
        self.assertEqual(a.output.released, 0)

    async def test_changed_epoch_refuses_before_allocator(self):
        a = Operation("private-A")
        client = Client([a])
        pending = asyncio.create_task(API["SessionAccount"](client).reminders())
        await a.started.wait()
        client._essential_epoch += 1
        a.finish()
        with self.assertRaises(API["SessionSettingsReadError"]) as caught:
            await pending
        self.assertEqual(caught.exception.code, "cancelled")
        self.assertEqual(a.output.released, 0)
        self.assertEqual(a.output.discarded, 1)


class PeerOracleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.peer = runpy.run_path(
            str(ROOT / "tests/sdk-conformance/session_settings_reminders_server.py"),
            run_name="pure_fixture_tools",
        )

    def headers(self):
        return [("Cookie", "auth_refresh_token=fixture"), ("X-OpenMates-SDK", "pip")]

    def test_only_fixed_get_no_query_and_original_cookie(self):
        validate = self.peer["validate_request"]
        validate("GET", "/v1/settings/reminders", self.headers(), "fixture", "pip")
        for method, path in [
            ("POST", "/v1/settings/reminders"),
            ("GET", "/v1/settings/reminders?team_id=x"),
            ("GET", "/v1/settings/other"),
        ]:
            with (
                self.subTest(method=method, path=path),
                self.assertRaises(AssertionError),
            ):
                validate(method, path, self.headers(), "fixture", "pip")
        with self.assertRaises(AssertionError):
            validate("GET", "/v1/settings/reminders", self.headers(), "rotated", "pip")

    def test_no_team_body_api_key_or_duplicate_cookie_authority(self):
        validate = self.peer["validate_request"]
        for header in [
            ("Authorization", "Bearer fixture"),
            ("X-API-Key", "fixture"),
            ("Api-Key", "fixture"),
            ("X-Team-Id", "fixture"),
            ("X-OpenMates-Team", "fixture"),
            ("Content-Type", "application/json"),
            ("Content-Length", "0"),
            ("Transfer-Encoding", "chunked"),
            ("Cookie", "auth_refresh_token=fixture"),
        ]:
            with self.subTest(header=header), self.assertRaises(AssertionError):
                validate(
                    "GET",
                    "/v1/settings/reminders",
                    self.headers() + [header],
                    "fixture",
                    "pip",
                )

    def test_response_body_bounds_remain_actual_header_data(self):
        wire = self.peer["wire_response"](
            {"status": 200, "body": "{", "headers": [["Content-Length", "16777217"]]}
        )
        self.assertIn(b"Content-Length: 16777217\r\n", wire)
        self.assertTrue(wire.endswith(b"\r\n\r\n{"))
        with self.assertRaises(AssertionError):
            self.peer["wire_response"](
                {
                    "status": 200,
                    "body": "{}",
                    "headers": [["Set-Cookie", "bad\r\nInjected: true"]],
                }
            )


if __name__ == "__main__":
    unittest.main()
