"""Pure actual Python facade extraction with inert native output; no SDK import."""

# contract-test-file: tooling
from __future__ import annotations
import ast
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class SessionClientError(RuntimeError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def failure(error):
    try:
        value = json.loads(str(error))
        return SessionClientError(value["code"], value["message"])
    except Exception:
        return SessionClientError(
            "native_failure", "The native session operation failed."
        )


def api():
    tree = ast.parse(
        (ROOT / "packages/openmates-python/openmates/remote_crypto.py").read_bytes()
    )
    wanted = {
        "RemoteCryptoError",
        "RemoteHandshake",
        "RemoteSession",
        "_error",
        "_bytes",
        "_wire",
    }
    nodes = [
        node
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.name in wanted
    ]
    assert len(nodes) == len(wanted)
    module = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__", names=[ast.alias(name="annotations")], level=0
            ),
            *nodes,
        ],
        type_ignores=[],
    )
    namespace = {
        "json": json,
        "SessionClientError": SessionClientError,
        "_failure": failure,
    }
    exec(
        compile(ast.fix_missing_locations(module), "<actual remote facade>", "exec"),
        namespace,
    )
    return namespace


API = api()


class Native:
    def __init__(self):
        self.closed = 0

    def open_json_text(self, *args):
        return '{"n":9007199254740993}'

    def open(self, *args):
        return b"\x00\xff"

    def seal(self, *args):
        return '{"version":1,"nonce":"public","ciphertext":"public"}'

    def close(self):
        self.closed += 1


class PendingNative:
    def __init__(self):
        self.closed = False
        self.closes = 0
        self.finishes = 0
        self.close_raises = False

    def handshake_json(self):
        if self.closed:
            raise RuntimeError(
                json.dumps(
                    {
                        "code": "crypto",
                        "message": "Encrypted data could not be authenticated.",
                    }
                )
            )
        return '{"version":1,"role":"requester","publicKey":"public","authenticationTag":"public"}'

    def finish(self, value):
        self.finishes += 1
        if self.closed:
            raise RuntimeError(
                json.dumps(
                    {
                        "code": "crypto",
                        "message": "Encrypted data could not be authenticated.",
                    }
                )
            )
        self.closed = True
        return Native()

    def close(self):
        self.closed = True
        self.closes += 1
        if self.close_raises:
            raise RuntimeError("synthetic cleanup failure")


def pending(native):
    value = object.__new__(API["RemoteHandshake"])
    value._RemoteHandshake__native = native
    return value


class FacadeTests(unittest.TestCase):
    def test_json_text_is_lossless_and_raw_bytes_unchanged(self):
        value = API["RemoteSession"](Native())
        self.assertEqual(value.open_json_text("id", {}), '{"n":9007199254740993}')
        self.assertEqual(value.open("id", {}), b"\x00\xff")

    def test_public_wire_only_serialization_and_close(self):
        native = Native()
        value = API["RemoteSession"](native)
        self.assertEqual(
            value.seal("id", b"\x00\xff"),
            {"version": 1, "nonce": "public", "ciphertext": "public"},
        )
        value.close()
        self.assertEqual(native.closed, 1)
        self.assertEqual(repr(value), "<RemoteSession>")

    def test_no_string_key_or_plaintext_conversion(self):
        with self.assertRaises(API["RemoteCryptoError"]) as error:
            API["_bytes"]("secret-string")
        self.assertEqual(error.exception.code, "invalid_argument")
        with self.assertRaises(API["RemoteCryptoError"]):
            API["RemoteSession"](Native()).seal("id", "private-string")

    def test_generic_error_remains_typed_without_raw_payload(self):
        native = Native()

        def refused(*args):
            raise RuntimeError(
                json.dumps(
                    {
                        "code": "crypto",
                        "message": "Encrypted data could not be authenticated.",
                    }
                )
            )

        native.open = refused
        with self.assertRaises(API["RemoteCryptoError"]) as error:
            API["RemoteSession"](native).open("id", {})
        self.assertEqual(error.exception.code, "crypto")
        self.assertEqual(
            str(error.exception), "Encrypted data could not be authenticated."
        )

    def test_serialization_refusal_consumes_only_original_pending(self):
        cyclic = {}
        cyclic["self"] = cyclic
        for remote in [cyclic, object(), {"nan": float("nan")}, set(["unsupported"])]:
            with self.subTest(kind=type(remote).__name__):
                original = PendingNative()
                sibling = PendingNative()
                a = pending(original)
                b = pending(sibling)
                with self.assertRaises(API["RemoteCryptoError"]) as error:
                    a.finish(remote)
                self.assertEqual(error.exception.code, "invalid_argument")
                self.assertEqual(original.closes, 1)
                self.assertEqual(original.finishes, 0)
                with self.assertRaises(API["RemoteCryptoError"]) as closed:
                    a.handshake()
                self.assertEqual(closed.exception.code, "crypto")
                with self.assertRaises(API["RemoteCryptoError"]) as closed:
                    a.finish({"valid": "wire"})
                self.assertEqual(closed.exception.code, "crypto")
                self.assertEqual(sibling.closes, 0)
                self.assertEqual(b.handshake()["publicKey"], "public")

    def test_cleanup_refusal_preserves_original_typed_serializer_failure(self):
        original = PendingNative()
        original.close_raises = True
        value = pending(original)
        preserved = API["RemoteCryptoError"](
            "synthetic_original", "Synthetic original refusal."
        )
        globals_ = API["RemoteHandshake"].finish.__globals__
        old = globals_["_wire"]

        def refused(_value):
            raise preserved

        try:
            globals_["_wire"] = refused
            with self.assertRaises(API["RemoteCryptoError"]) as error:
                value.finish({})
            self.assertIs(error.exception, preserved)
            self.assertTrue(original.closed)
            self.assertEqual(original.closes, 1)
        finally:
            globals_["_wire"] = old

    def test_serializer_interruption_also_retires_original(self):
        original = PendingNative()
        value = pending(original)
        globals_ = API["RemoteHandshake"].finish.__globals__
        old = globals_["_wire"]

        def interrupted(_value):
            raise KeyboardInterrupt()

        try:
            globals_["_wire"] = interrupted
            with self.assertRaises(KeyboardInterrupt):
                value.finish({})
            self.assertTrue(original.closed)
            self.assertEqual(original.finishes, 0)
        finally:
            globals_["_wire"] = old


if __name__ == "__main__":
    unittest.main()
