# contract-test-file: tooling
"""Inert failed-package diagnostic coverage; no Cargo/WASM/browser execution.

Temporary packages are explicit byte fixtures, never generated-output proof.
The actual closed inventory, dependency predicate and private retention execute.
Capture is observational only; primary refusal and original cleanup stay held.
Existing two-file artifact schema and128KiB payload limit are not expanded.
"""

import base64
import gzip
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from scripts import ci_rust_wasm as lane


class DependencyCaptureTests(unittest.TestCase):
    def receipt(self):
        return {
            "source_commit": "a" * 40,
            "source_tree": "b" * 40,
            "harness_commit": "c" * 40,
            "run_id": "40768767890",
            "inputSetSha256": "d" * 64,
        }

    def capture(
        self, root=b"/* import is deliberately refused raw text */\n", guard=None
    ):
        return {"root": root, "guard": root if guard is None else guard, "reason": 4}

    def tree(self, folder, *, refused=True):
        folder.mkdir(mode=0o700)
        name = "snippets/openmates-browser-bindings-0123456789abcdef/inline0.js"
        header = lane.package_import_headers(name)[0]
        guard = (
            b"/* import fixture: not an observed compiler shape */\n"
            if refused
            else b"export default function init() {}\n"
        )
        files = {
            lane.PACKAGE_FILES[0]: header + guard,
            lane.PACKAGE_FILES[1]: b"\0asm\x01\0\0\0",
            lane.PACKAGE_FILES[2]: b"export default function init(): void;\n",
            name: lane.SNIPPET_BYTES,
        }
        for relative, raw in files.items():
            target = folder / relative
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            target.write_bytes(raw)
            target.chmod(0o600)
        for directory in [folder, *[p for p in folder.rglob("*") if p.is_dir()]]:
            directory.chmod(0o700)
        return files, guard

    def test_actual_inventory_failure_captures_original_and_exact_post_header_view(
        self,
    ):
        with TemporaryDirectory() as tmp:
            folder = Path(tmp) / "package"
            files, guard = self.tree(folder)
            capture = {}
            diagnostic = {}
            with self.assertRaises(lane.sdk.Refused) as error:
                lane.package_inventory(
                    folder,
                    {lane.SNIPPET_SOURCE: lane.SNIPPET_SOURCE_SHA256},
                    diagnostic,
                    dependency_capture=capture,
                )
            self.assertEqual(error.exception.args, ("outputs",))
            self.assertEqual(diagnostic["packageDependencyRefusalKind"], 4)
            self.assertIs(diagnostic["packageDependenciesClosed"], False)
            self.assertEqual(
                capture,
                {"root": files[lane.PACKAGE_FILES[0]], "guard": guard, "reason": 4},
            )
            self.assertNotEqual(capture["root"], capture["guard"])

    def test_pass_and_earlier_body_refusal_never_capture_or_change_inventory(self):
        with TemporaryDirectory() as tmp:
            folder = Path(tmp) / "package"
            files, _ = self.tree(folder, refused=False)
            capture = {}
            inputs = {lane.SNIPPET_SOURCE: lane.SNIPPET_SOURCE_SHA256}
            self.assertEqual(
                lane.package_inventory(folder, inputs),
                lane.package_inventory(folder, inputs, dependency_capture=capture),
            )
            self.assertEqual(capture, {})
            target = folder / next(n for n in files if n.startswith("snippets/"))
            target.write_bytes(lane.SNIPPET_BYTES + b" ")
            with self.assertRaises(lane.sdk.Refused):
                lane.package_inventory(folder, inputs, dependency_capture=capture)
            self.assertEqual(capture, {})

    def test_actual_inventory_symlink_nonregular_and_size_refusals_do_not_capture(self):
        for kind in ("symlink", "directory", "size"):
            with self.subTest(kind=kind), TemporaryDirectory() as tmp:
                folder = Path(tmp) / "package"
                self.tree(folder)
                target = folder / lane.PACKAGE_FILES[0]
                capture = {}
                diagnostic = {}
                target.unlink()
                if kind == "symlink":
                    outside = Path(tmp) / "outside"
                    outside.write_bytes(b"import x from 'bad'")
                    target.symlink_to(outside)
                elif kind == "directory":
                    target.mkdir()
                else:
                    with target.open("wb") as stream:
                        stream.truncate(64 * 1024**2 + 1)
                with self.assertRaises((lane.sdk.Refused, OSError)):
                    lane.package_inventory(
                        folder,
                        {lane.SNIPPET_SOURCE: lane.SNIPPET_SOURCE_SHA256},
                        diagnostic,
                        dependency_capture=capture,
                    )
                self.assertEqual(diagnostic["substage"], "package-file-read")
                self.assertEqual(capture, {})

    def test_full_exact_pair_compresses_with_source_harness_and_file_hashes(self):
        with TemporaryDirectory() as tmp:
            private = Path(tmp)
            private.chmod(0o700)
            capture = self.capture()
            descriptor = lane.retain_dependency_capture(
                private, self.receipt(), capture
            )
            raw = lane.retained_dependency_capture(private, descriptor)
            self.assertLessEqual(len(raw), 128 * 1024)
            outer = json.loads(raw)
            self.assertEqual(outer["format"], "openmates-wasm-dependency-capture-v1")
            packed = base64.b64decode(outer["payload"], validate=True)
            decoded = gzip.decompress(packed)
            value = json.loads(decoded)
            self.assertEqual(
                (len(packed), lane.sdk.sha(packed)),
                (outer["compressedBytes"], outer["compressedSha256"]),
            )
            self.assertEqual(
                (len(decoded), lane.sdk.sha(decoded)),
                (outer["decodedBytes"], outer["decodedSha256"]),
            )
            self.assertLessEqual(len(decoded), 8 * 1024**2)
            for key, expected in self.receipt().items():
                self.assertEqual(value[key], expected)
            self.assertEqual(value["failureOrdinal"], 4)
            self.assertEqual(value["rootFile"], lane.PACKAGE_FILES[0])
            for prefix, key in (
                ("root", "rootJavascript"),
                ("guard", "postHeaderGuardJavascript"),
            ):
                actual = value[key].encode()
                self.assertEqual(actual, capture[prefix])
                self.assertEqual(value[prefix + "Sha256"], lane.sdk.sha(actual))
                self.assertEqual(value[prefix + "Bytes"], len(actual))
            self.assertEqual(
                (private / lane.DEPENDENCY_CAPTURE_FILE).stat().st_mode & 0o777, 0o600
            )

    def test_capture_type_byte_utf8_reason_and_context_refusals_before_write(self):
        for kind in (
            "bytearray",
            "empty",
            "large",
            "utf8",
            "reason_bool",
            "reason_zero",
            "reason_mismatch",
            "context",
        ):
            with self.subTest(kind=kind), TemporaryDirectory() as tmp:
                private = Path(tmp)
                private.chmod(0o700)
                capture = self.capture()
                receipt = self.receipt()
                if kind == "bytearray":
                    capture["root"] = bytearray(capture["root"])
                if kind == "empty":
                    capture["guard"] = b""
                if kind == "large":
                    capture["root"] = b"x" * (lane.DEPENDENCY_CAPTURE_TEXT_LIMIT + 1)
                if kind == "utf8":
                    capture["root"] = b"\xff"
                if kind == "reason_bool":
                    capture["reason"] = True
                if kind == "reason_zero":
                    capture["reason"] = 0
                if kind == "reason_mismatch":
                    capture["reason"] = 7
                if kind == "context":
                    receipt["harness_commit"] = {}
                with self.assertRaises((lane.sdk.Refused, UnicodeError)):
                    lane.retain_dependency_capture(private, receipt, capture)
                self.assertFalse((private / lane.DEPENDENCY_CAPTURE_FILE).exists())

    def test_uncompressible_full_pair_refuses_instead_of_truncating_or_raising_limit(
        self,
    ):
        data = base64.b64encode(
            b"".join(hashlib.sha256(n.to_bytes(4, "big")).digest() for n in range(3000))
        )
        raw = b"/*" + data + b"*/ import fixture;"
        with TemporaryDirectory() as tmp:
            private = Path(tmp)
            private.chmod(0o700)
            with self.assertRaises(lane.sdk.Refused):
                lane.retain_dependency_capture(
                    private, self.receipt(), self.capture(raw)
                )
            self.assertFalse((private / lane.DEPENDENCY_CAPTURE_FILE).exists())
            self.assertEqual(lane.DIAGNOSTIC_LIMIT, 128 * 1024)

    def test_capture_symlink_existing_target_and_unsafe_parent_refuse_without_overwrite(
        self,
    ):
        for kind in ("symlink", "existing", "parent"):
            with self.subTest(kind=kind), TemporaryDirectory() as tmp:
                private = Path(tmp)
                private.chmod(0o700)
                target = private / lane.DEPENDENCY_CAPTURE_FILE
                outside = private / "outside"
                outside.write_bytes(b"held")
                if kind == "symlink":
                    target.symlink_to(outside)
                if kind == "existing":
                    target.write_bytes(b"held")
                if kind == "parent":
                    private.chmod(0o777)
                try:
                    with self.assertRaises((lane.sdk.Refused, OSError)):
                        lane.retain_dependency_capture(
                            private, self.receipt(), self.capture()
                        )
                    self.assertEqual(outside.read_bytes(), b"held")
                    if kind == "existing":
                        self.assertEqual(target.read_bytes(), b"held")
                finally:
                    private.chmod(0o700)

    def test_file_alone_cannot_supply_held_descriptor_and_mutation_symlink_hardlink_refuse(
        self,
    ):
        for kind in ("missing_descriptor", "mutation", "symlink", "hardlink"):
            with self.subTest(kind=kind), TemporaryDirectory() as tmp:
                private = Path(tmp)
                private.chmod(0o700)
                descriptor = lane.retain_dependency_capture(
                    private, self.receipt(), self.capture()
                )
                target = private / lane.DEPENDENCY_CAPTURE_FILE
                if kind == "missing_descriptor":
                    self.assertIsNone(lane.retained_dependency_capture(private, None))
                    continue
                if kind == "mutation":
                    target.write_bytes(target.read_bytes() + b" ")
                if kind == "symlink":
                    held = private / "held"
                    target.rename(held)
                    target.symlink_to(held)
                if kind == "hardlink":
                    os.link(target, private / "alias")
                with self.assertRaises((lane.sdk.Refused, OSError)):
                    lane.retained_dependency_capture(private, descriptor)

    def test_existing_two_file_tail_identity_carries_exact_capture_without_schema_change(
        self,
    ):
        with TemporaryDirectory() as tmp:
            private = Path(tmp) / "private"
            private.mkdir(mode=0o700)
            output = Path(tmp) / "out"
            output.mkdir()
            (private / "bindgen-package.log").write_bytes(b"original stage tail")
            descriptor = lane.retain_dependency_capture(
                private, self.receipt(), self.capture()
            )
            expected = lane.retained_dependency_capture(private, descriptor)
            result = lane.retain_failure_diagnostic(
                private,
                output,
                self.receipt(),
                "bindgen-package",
                dependency_capture=descriptor,
            )
            target = output / "ci-rust-wasm-private"
            self.assertEqual(
                {p.name for p in target.iterdir()}, {"identity.json", "cargo-tail.log"}
            )
            self.assertEqual((target / "cargo-tail.log").read_bytes(), expected)
            identity = result["identity"]
            self.assertEqual(identity["bytes"], len(expected))
            self.assertEqual(identity["originalBytes"], len(expected))
            self.assertIs(identity["truncated"], False)
            self.assertEqual(identity["sha256"], lane.sdk.sha(expected))
            self.assertIs(result["publicRawUpload"], False)

    def test_unavailable_invalid_or_wrong_stage_capture_falls_back_to_original_tail(
        self,
    ):
        for kind in ("none", "mutated", "symlink", "wrong_stage"):
            with self.subTest(kind=kind), TemporaryDirectory() as tmp:
                private = Path(tmp) / "private"
                private.mkdir(mode=0o700)
                output = Path(tmp) / "out"
                output.mkdir()
                stage = "wasm-build" if kind == "wrong_stage" else "bindgen-package"
                tail = b"original failure remains"
                (private / (stage + ".log")).write_bytes(tail)
                descriptor = lane.retain_dependency_capture(
                    private, self.receipt(), self.capture()
                )
                target = private / lane.DEPENDENCY_CAPTURE_FILE
                if kind == "none":
                    descriptor = None
                if kind == "mutated":
                    target.write_bytes(b"changed")
                if kind == "symlink":
                    held = private / "held"
                    target.rename(held)
                    target.symlink_to(held)
                result = lane.retain_failure_diagnostic(
                    private,
                    output,
                    self.receipt(),
                    stage,
                    dependency_capture=descriptor,
                )
                self.assertEqual(
                    (output / "ci-rust-wasm-private/cargo-tail.log").read_bytes(), tail
                )
                self.assertEqual(result["identity"]["sha256"], lane.sdk.sha(tail))

    def test_capture_failure_never_masks_original_producer_exception(self):
        original = lane.sdk.Refused("outputs")
        runner = SimpleNamespace()
        with (
            patch.object(lane, "locked_bindgen_version", side_effect=original),
            patch.object(
                lane,
                "retain_dependency_capture",
                side_effect=RuntimeError("diagnostic failure"),
            ),
        ):
            with self.assertRaises(lane.sdk.Refused) as actual:
                lane.produce_browser_package(runner, None, None, None, None, {})
        self.assertIs(actual.exception, original)


if __name__ == "__main__":
    unittest.main()
