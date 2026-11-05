# contract-test-file: tooling
"""Actual retained9d9 JS closure only; no compiler, WASM or runtime acceptance."""

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "scripts.ci_rust_wasm", ROOT / "scripts/ci_rust_wasm.py"
)
lane = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = lane
spec.loader.exec_module(lane)
FIXTURES = ROOT / "scripts/tests/fixtures/rust-wasm-checkpoint-40985930000"


class CurrentGeneratedRecoveryCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.context = json.loads((FIXTURES / "context.json").read_bytes())
        self.root = (FIXTURES / "generated-root.js").read_bytes()
        self.guard = (FIXTURES / "post-header-guard.js").read_bytes()
        self.inputs = self.context["packageInputPins"]
        self.sdk_name = self.context["sdkSnippet"]
        self.crypto_name = self.context["cryptoSnippet"]
        # Fixed same-source body, NOT a separately captured9d9 snippet. Original
        # validator independently proved exact body/source match before refusing.
        self.body = (FIXTURES / self.context["sdkBodyFixtureReference"]).read_bytes()
        self.files = dict(
            zip(
                lane.PACKAGE_FILES,
                [self.root, b"\0asm\x01\0\0\0", b"export {};", b"export {};"],
            )
        )
        self.files.update(
            {self.sdk_name: self.body, self.crypto_name: lane.SNIPPET_BYTES}
        )

    def test_original_capture_identity_and_unchanged_raw_dependency_refusal(self):
        self.assertEqual(
            self.context["source_commit"], "9d9f7af627f90ea11efe78221fe3221f39a31072"
        )
        self.assertEqual(self.context["run_id"], "40985930000")
        self.assertEqual(len(self.root), 164656)
        self.assertEqual(
            hashlib.sha256(self.root).hexdigest(),
            "dc1617f1d43c211baf82aaa4ae66553c5431cc80773088780a3d981128de2b98",
        )
        self.assertEqual(len(self.guard), 164483)
        self.assertEqual(
            hashlib.sha256(self.guard).hexdigest(),
            "8c1528b69deb30c87dae3e86ac934846c0555828a9082306f97c0feafa5d451b",
        )
        self.assertEqual(len(self.body), 4310)
        self.assertEqual(
            hashlib.sha256(self.body).hexdigest(),
            "1bdc2c5ed63001a8ebc06a79d29a2df60ef357840f4d993a55f96de69a57903b",
        )
        sdk_header = ('import * as import2 from "./' + self.sdk_name + '"\n').encode()
        crypto_header = lane.package_import_headers(self.crypto_name)[1]
        self.assertEqual(
            self.root.replace(sdk_header, b"", 1).replace(crypto_header, b"", 1),
            self.guard,
        )
        self.assertEqual(lane.module_dependency_reason(self.guard), 4)
        self.assertFalse(lane.closed_module_dependencies(self.guard))

    def test_exact_current_graph_closes_without_modifying_original_files(self):
        original = dict(self.files)
        state = {}
        self.assertTrue(lane.package_modules(self.files, self.inputs, state))
        self.assertTrue(state["packageDependenciesClosed"])
        self.assertTrue(state["packageSdkNamespaceUsesClosed"])
        self.assertEqual(self.files, original)
        view = lane.recovery_sdk_output(self.files, self.inputs)
        reduced = view[lane.PACKAGE_FILES[0]].replace(
            lane.package_import_headers(self.crypto_name)[1], b"", 1
        )
        self.assertEqual(lane.module_dependency_reason(reduced), 0)
        self.assertEqual(lane.module_dependency_reason(self.guard), 4)

    def test_both_actual_roots_match_one_exact_seven_slot_template(self):
        prior = (
            FIXTURES.parent / "rust-wasm-checkpoint-40951833663/generated-root.js"
        ).read_bytes()
        expected = "68a13b10930921eceb33ac81d151def1499a306e5e7a9e38958277fe4e4e64b2"
        self.assertEqual(lane.observed_recovery_template_sha256(prior), expected)
        self.assertEqual(lane.observed_recovery_template_sha256(self.root), expected)
        self.assertEqual(len(lane.OBSERVED_RECOVERY_SHIM_SLOTS), 7)
        for value in (b"0", b"1", b"4294967295"):
            lines = self.root.splitlines(keepends=True)
            for index, prefix, suffix in lane.OBSERVED_RECOVERY_SHIM_SLOTS:
                lines[index] = prefix + value + suffix
            changed = dict(self.files)
            changed[lane.PACKAGE_FILES[0]] = b"".join(lines)
            self.assertTrue(lane.package_modules(changed, self.inputs))
            self.assertEqual(changed[lane.PACKAGE_FILES[0]], b"".join(lines))

    def test_only_canonical_bounded_decimal_metadata_is_admitted(self):
        for index, prefix, suffix in lane.OBSERVED_RECOVERY_SHIM_SLOTS:
            for value in (
                b"",
                b"00",
                b"01",
                b"-1",
                b"+1",
                b"1.0",
                b"1e2",
                b"4294967296",
                b"99999999999",
                b"1 import('bad')",
                b"1\n",
            ):
                with self.subTest(line=index, value=value):
                    lines = self.root.splitlines(keepends=True)
                    lines[index] = prefix + value + suffix
                    changed = dict(self.files)
                    changed[lane.PACKAGE_FILES[0]] = b"".join(lines)
                    self.assertFalse(lane.package_modules(changed, self.inputs))
        for raw in (None, bytearray(self.root), b"", self.root * 2):
            self.assertIsNone(lane.observed_recovery_template_sha256(raw))

    def test_every_exact_source_pin_and_module_body_remains_required(self):
        for path in self.inputs:
            for wrong in (None, "0" * 64):
                with self.subTest(path=path, wrong=wrong):
                    changed = dict(self.inputs)
                    changed[path] = wrong
                    self.assertFalse(lane.package_modules(self.files, changed))
        for name in (self.sdk_name, self.crypto_name):
            with self.subTest(module=name):
                changed = dict(self.files)
                changed[name] += b" "
                self.assertFalse(lane.package_modules(changed, self.inputs))

    def test_no_other_comment_or_executable_graph_can_use_template_admission(self):
        namespace = ('import * as import3 from "./' + self.sdk_name + '"\n').encode()
        mutations = [
            self.root + b"\n",
            self.root.replace(b"// Cast intrinsic", b"// Other intrinsic", 1),
            self.root + b"import('./other.js');",
            self.root + b"export * from './other.js';",
            self.root.replace(
                b"wasm.__wbindgen_free(deferred1_0, deferred1_1, 1)",
                b"wasm.__wbindgen_free(deferred1_0, deferred1_1, 2)",
                1,
            ),
            self.root.replace(
                b"openmates_browser_bg.wasm", b"other_browser_bg.wasm", 1
            ),
            self.root.replace(namespace, namespace * 2, 1),
            self.root.replace(b"import3,", b'import3["recoveryRead"],', 1),
            self.root.replace(
                b"recoveryRead(arg0, arg1)", b"recoveryOther(arg0, arg1)", 1
            ),
            self.root.replace(b'inline0.js": import4', b'other.js": import4', 1),
        ]
        for changed in mutations:
            with self.subTest(digest=hashlib.sha256(changed).hexdigest()):
                self.assertNotEqual(changed, self.root)
                files = dict(self.files)
                files[lane.PACKAGE_FILES[0]] = changed
                self.assertFalse(lane.package_modules(files, self.inputs))

    def test_extra_and_missing_physical_module_inventory_refuses(self):
        for name in (self.sdk_name, self.crypto_name):
            changed = dict(self.files)
            del changed[name]
            self.assertFalse(lane.package_modules(changed, self.inputs))
        changed = dict(self.files)
        changed["extra.js"] = b"export {};"
        self.assertFalse(lane.package_modules(changed, self.inputs))


if __name__ == "__main__":
    unittest.main()
