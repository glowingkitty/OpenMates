# contract-test-file: tooling
"""Pure finite profile proofs; no Cargo/network/browser execution."""

from copy import deepcopy
import importlib.util
import json
import os
import re
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True
from scripts import (  # noqa: E402  # Requires the original sys.path bootstrap above.
    ci_metadata_rust_browser as m,
    ci_rust_wasm as lane,
    ci_results as results,
    ci_production_rust_browser as supplier,
)

spec = importlib.util.spec_from_file_location(
    "metadata_fixture", ROOT / "scripts/tests/test_ci_rust_wasm.py"
)
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)


def package():
    c = "snippets/openmates-browser-bindings-0123456789abcdef/inline0.js"
    r = "snippets/openmates-sdk-0123456789abcdef/inline0.js"
    n = "snippets/openmates-sdk-0123456789abcdef/src/platform/browser_metadata_native.js"
    raw = (ROOT / m.RECOVERY_SOURCE).read_text()
    body = json.loads(
        '"'
        + re.search(r'inline_js = "([\s\S]*?)"\)\]\s*extern', raw)[1]
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        + '"'
    ).encode()
    return {
        "openmates_browser.js": "".join(
            "import * as import" + str(i) + ' from "./' + v + '"\n'
            for i, v in enumerate([c, r, n], 1)
        ).encode()
        + b"export default function init(){};",
        "openmates_browser_bg.wasm": f.WASM,
        "openmates_browser.d.ts": b"export default function init():Promise<void>;",
        c: m.CRYPTO_BYTES,
        r: body,
        n: (ROOT / m.NATIVE_SOURCE).read_bytes(),
    }


def compiler():
    _, receipt, job, kwargs = f.WasmReceiptTests().fixture()
    files = package()
    inputs = {
        **kwargs["expected_inputs"],
        **m.SOURCE_PINS,
        **{n: "a" * 64 for n in m.WEB_INPUTS},
    }
    job.update(mode="e2e", specs=json.dumps([m.SPEC]))
    receipt.update(
        runtime_profile="rust-browser-package-for-e2e",
        requestedMode="e2e",
        requestedTargets=[m.SPEC],
        workerProof=None,
        inputs=inputs,
        inputSetSha256=lane.sdk.sha(json.dumps(inputs, sort_keys=True).encode()),
    )
    receipt["steps"] = receipt["steps"][:6]
    for row, argv in zip(receipt["steps"], lane.commands(metadata_profile=True)):
        row["command"]["argvSha256"] = lane.sdk.sha(
            json.dumps(argv, separators=(",", ":")).encode()
        )
    manifest = json.loads(kwargs["package_manifest"])
    manifest.update(
        inputs=inputs,
        inputSetSha256=receipt["inputSetSha256"],
        requestedMode="e2e",
        requestedTargets=[m.SPEC],
        features=[m.FEATURE],
    )
    rows = [
        {"path": n, "sha256": lane.sdk.sha(b), "rawBytes": len(b)}
        for n, b in sorted(files.items())
    ]
    manifest["inventory"] = {
        "files": rows,
        "rawBytes": sum(r["rawBytes"] for r in rows),
        "inventorySha256": lane.sdk.sha(
            json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
        ),
    }
    raw = json.dumps(manifest, sort_keys=True).encode()
    receipt["package"].update(
        manifestSha256=lane.sdk.sha(raw),
        inventorySha256=manifest["inventory"]["inventorySha256"],
    )
    kwargs.update(expected_inputs=inputs, package_files=files, package_manifest=raw)
    return receipt, job, kwargs


class MetadataTests(unittest.TestCase):
    def test_exact_selector_and_feature_argv(self):
        self.assertTrue(lane.browser_e2e_targets([m.SPEC]))
        self.assertTrue(
            lane.production_browser_e2e_targets([lane.PRODUCTION_BROWSER_SPEC])
        )
        for bad in [
            [],
            [m.SPEC, m.SPEC],
            [m.SPEC, lane.PRODUCTION_BROWSER_SPEC],
            ["nested/" + m.SPEC],
        ]:
            self.assertFalse(lane.production_browser_e2e_targets(bad))
        old = lane.commands()
        new = lane.commands(metadata_profile=True)
        self.assertEqual(new[:2] + new[3:], old[:2] + old[3:])
        self.assertEqual(new[2], old[2] + ["--features", m.FEATURE])
        self.assertEqual(old[2][-1], "--lib")

    def test_exact_modules_no_original_guard_widening(self):
        files = package()
        self.assertFalse(lane.package_names(files))
        self.assertTrue(
            m.package_modules(files, m.SOURCE_PINS, lane.closed_module_dependencies)
        )
        for name in files:
            if name.startswith("snippets/"):
                self.assertFalse(
                    m.package_modules(
                        {**files, name: files[name] + b"\n//tamper"},
                        m.SOURCE_PINS,
                        lane.closed_module_dependencies,
                    )
                )
        for attack in [
            b'import("https://foreign.invalid/a")',
            b'export * from "./foreign.js"',
            b'import "./foreign.js"',
        ]:
            self.assertFalse(
                m.package_modules(
                    {
                        **files,
                        "openmates_browser.js": files["openmates_browser.js"] + attack,
                    },
                    m.SOURCE_PINS,
                    lane.closed_module_dependencies,
                )
            )
        self.assertFalse(
            m.package_modules(
                files,
                {**m.SOURCE_PINS, m.NATIVE_SOURCE: "0" * 64},
                lane.closed_module_dependencies,
            )
        )

    def test_physical_inventory_rejects_extra_and_symlink(self):
        previous = os.umask(0o077)
        try:
            with TemporaryDirectory() as tmp:
                root = Path(tmp)
                for n, b in package().items():
                    p = root / n
                    p.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                    p.write_bytes(b)
                self.assertEqual(
                    len(
                        lane.package_inventory(
                            root, m.SOURCE_PINS, metadata_profile=True
                        )["files"]
                    ),
                    6,
                )
                q = root / "foreign.js"
                q.write_text("bad")
                with self.assertRaises(lane.sdk.Refused):
                    lane.package_inventory(root, m.SOURCE_PINS, metadata_profile=True)
                q.unlink()
                q = root / "openmates_browser.d.ts"
                q.unlink()
                q.symlink_to(root / "openmates_browser.js")
                with self.assertRaises(lane.sdk.Refused):
                    lane.package_inventory(root, m.SOURCE_PINS, metadata_profile=True)
        finally:
            os.umask(previous)

    def test_full_receipt_binds_actual_feature_command_and_package(self):
        receipt, job, kwargs = compiler()

        def valid(r, k):
            return results.valid_rust_wasm_compiler_receipt(r, job, "f" * 40, **k)

        self.assertTrue(valid(receipt, kwargs))
        r = deepcopy(receipt)
        r["steps"][2]["command"]["argvSha256"] = lane.sdk.sha(
            json.dumps(lane.commands()[2], separators=(",", ":")).encode()
        )
        self.assertFalse(valid(r, kwargs))
        for feature in [None, [], ["other"]]:
            k = deepcopy(kwargs)
            man = json.loads(k["package_manifest"])
            man.pop("features") if feature is None else man.update(features=feature)
            k["package_manifest"] = json.dumps(man, sort_keys=True).encode()
            r = deepcopy(receipt)
            r["package"]["manifestSha256"] = lane.sdk.sha(k["package_manifest"])
            self.assertFalse(valid(r, k))
        k = deepcopy(kwargs)
        k["expected_inputs"][m.NATIVE_SOURCE] = "0" * 64
        self.assertFalse(valid(receipt, k))
        r = deepcopy(receipt)
        k = deepcopy(kwargs)
        missing = m.WEB_INPUTS[0]
        k["expected_inputs"].pop(missing)
        r["inputs"].pop(missing)
        r["inputSetSha256"] = lane.sdk.sha(
            json.dumps(r["inputs"], sort_keys=True).encode()
        )
        man = json.loads(k["package_manifest"])
        man.update(inputs=r["inputs"], inputSetSha256=r["inputSetSha256"])
        k["package_manifest"] = json.dumps(man, sort_keys=True).encode()
        r["package"]["manifestSha256"] = lane.sdk.sha(k["package_manifest"])
        self.assertFalse(valid(r, k))

    def test_fifteen_actual_reports_require_child_and_preserve_fourteen(self):
        prefix = "actual Master-free native opaque metadata prototype: "
        predecessor_suffixes = {
            "fresh_absent",
            "partial_clear_floor",
            "master_absent",
            "master_transition_held",
            "refresh_lock_store",
            "auth_generation_held",
            "logout_held",
            "owner_switch",
            "replaced_database",
            "cancel_held_transaction",
            "foreign_configured_api",
            "foreign_factory_frame",
            "copied_native_event",
            "provider_missing",
        }
        predecessors = {prefix + name for name in predecessor_suffixes}
        child = prefix + "personal_child_navigation"
        self.assertEqual(len(predecessors), 14)
        self.assertEqual(m.REQUIRED_CASES, predecessors | {child})
        specs = [
            {
                "title": name,
                "tests": [{"status": "expected", "results": [{"status": "passed"}]}],
            }
            for name in sorted(m.REQUIRED_CASES)
        ]
        report = {"suites": [{"specs": specs}]}
        self.assertTrue(m.browser_case_proof(report)["complete"])
        old_only = {
            "suites": [{"specs": [spec for spec in specs if spec["title"] != child]}]
        }
        missing_child = m.browser_case_proof(old_only)
        self.assertEqual(missing_child["observedRequiredCases"], 14)
        self.assertFalse(missing_child["complete"])
        self.assertIn(child, missing_child["requiredCases"])
        self.assertEqual(len(missing_child["requiredCases"]), 15)

        for fault in ["missing", "skipped", "failed", "flaky", "duplicate"]:
            r = deepcopy(report)
            if fault == "missing":
                r["suites"][0]["specs"].pop()
            elif fault == "duplicate":
                r["suites"][0]["specs"].append(deepcopy(specs[0]))
            elif fault == "failed":
                r["suites"][0]["specs"][0]["tests"][0]["results"][0]["status"] = (
                    "failed"
                )
            else:
                r["suites"][0]["specs"][0]["tests"][0]["status"] = fault
            self.assertFalse(m.browser_case_proof(r)["complete"], fault)

    def test_feature_web_receipt_binds_eight_actual_source_hashes(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            expected = {}
            for crate in [
                "packages/openmates-rust",
                "packages/openmates-browser-bindings",
            ]:
                for name in ["Cargo.toml", "Cargo.lock", "src/lib.rs"]:
                    n = crate + "/" + name
                    p = root / n
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_bytes(b"synthetic")
                    expected[n] = lane.sdk.sha(b"synthetic")
            for n in m.WEB_INPUTS:
                p = root / n
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(n.encode())
                expected[n] = lane.sdk.sha(n.encode())
            expected[m.NATIVE_SOURCE] = "1" * 64
            man = {
                "target": "wasm32-unknown-unknown",
                "toolchain": "1.98.1",
                "wasmBindgenVersion": lane.BINDGEN_VERSION,
                "inputWasmSha256": "a" * 64,
                "toolSha256": "b" * 64,
                "features": [m.FEATURE],
            }
            p = json.loads(supplier.project_receipt(root, man, expected, package()))
            self.assertEqual(p["features"], [m.FEATURE])
            self.assertEqual(set(p["metadataPrototypeInputs"]), set(m.WEB_INPUTS))
            self.assertFalse(p["applicationActivated"])
            self.assertFalse(p["browserExecutionVerified"])

    def test_fixed_dormant_sdk_js_bound_without_enabling_metadata(self):
        from unittest.mock import patch

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            expected = {"packages/openmates-rust/Cargo.toml": "a" * 64}
            for n in m.EXTRA_INPUTS:
                p = root / n
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(n.encode())
                expected[n] = lane.sdk.sha(n.encode())
            base = {"packages/openmates-rust/Cargo.toml": "a" * 64}
            with patch.object(
                lane,
                "snapshot",
                side_effect=lambda r, e: (
                    e
                    if e == base
                    else (_ for _ in ()).throw(lane.sdk.Refused("source"))
                ),
            ):
                plain = {**base, m.NATIVE_SOURCE: expected[m.NATIVE_SOURCE]}
                self.assertEqual(lane.source_snapshot(root, plain), plain)
                self.assertEqual(
                    lane.source_snapshot(root, expected, metadata_profile=True),
                    expected,
                )
                (root / m.NATIVE_SOURCE).write_bytes(b"drift")
                self.assertNotEqual(lane.source_snapshot(root, plain), plain)
                with self.assertRaises(lane.sdk.Refused):
                    lane.source_snapshot(root, plain, metadata_profile=True)

    def test_real_controller_sequence_with_inert_compiler_keeps_feature_and_failure_closed(
        self,
    ):
        legacy = f.WasmRunTests()
        legacy.setUp()
        try:
            manifest = {}

            def observe(root, receipt):
                manifest.update(
                    json.loads(
                        (
                            root / "test-results/rust-wasm/package-manifest.json"
                        ).read_bytes()
                    )
                )

            receipt, _, _, _, _, _, _ = legacy.execute(
                browser_e2e=True, metadata_package=package(), diagnostic_probe=observe
            )
            self.assertEqual(receipt["status"], "passed")
            self.assertEqual(manifest["features"], [m.FEATURE])
            self.assertTrue(m.EXTRA_INPUTS <= set(receipt["inputs"]))
            bad = package()
            name = next(n for n in bad if n.endswith("browser_metadata_native.js"))
            bad[name] += b"\n//changed"
            failed, _, _, output, _, _, _ = legacy.execute(
                browser_e2e=True, metadata_package=bad
            )
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(failed["code"], "outputs")
            self.assertFalse(failed["compilationProof"])
            self.assertEqual(output, b"")
        finally:
            legacy.doCleanups()

    def test_workflow_and_candidate_coverage_wired(self):
        s = (ROOT / ".github/workflows/isolated-tests.yml").read_text()
        self.assertGreaterEqual(
            s.count("inputs.specs_json == '[\"" + m.SPEC + "\"]'"), 6
        )
        self.assertIn("'e2e:[\"" + m.SPEC + "\"]'|", s)
        self.assertIn("src/platform/browser_metadata_native.js", s)
        from scripts import ci_coverage

        self.assertEqual(ci_coverage.partition([m.SPEC])[0], [m.SPEC])
        self.assertIn(
            '"' + m.SPEC + '"', (ROOT / "scripts/ci_environment.py").read_text()
        )
        self.assertIn(
            'selected_case_complete = selected_case_complete and metadata_native_proof["complete"]',
            (ROOT / "scripts/ci_run_tests.py").read_text(),
        )


class StartupProfileTests(unittest.TestCase):
    def test_startup_singleton_is_finite_and_not_combined_metadata(self):
        self.assertTrue(m.targets([m.STARTUP_SPEC]))
        self.assertFalse(m.targets([m.STARTUP_SPEC, m.SPEC]))
        self.assertFalse(m.targets([m.STARTUP_SPEC, m.STARTUP_SPEC]))
        self.assertFalse(m.targets([m.STARTUP_SPEC + "x"]))

    def test_genuine_startup_case_is_required_once_and_passed(self):
        cases = [
            {
                "title": title,
                "tests": [
                    {
                        "status": "expected",
                        "results": [{"status": "passed", "retry": 0}],
                    }
                ],
            }
            for title in sorted(m.STARTUP_REQUIRED_CASES)
        ]
        self.assertEqual(len(cases), 4)
        self.assertTrue(
            m.startup_browser_case_proof({"suites": [{"specs": cases}]})["complete"]
        )
        for observed in [
            [],
            cases[:1],
            cases[1:],
            cases + [cases[0]],
            [
                {
                    **case,
                    "tests": [
                        {
                            "status": "expected",
                            "results": [{"status": "failed", "retry": 0}],
                        }
                    ],
                }
                for case in cases
            ],
        ]:
            self.assertFalse(
                m.startup_browser_case_proof({"suites": [{"specs": observed}]})[
                    "complete"
                ]
            )
        self.assertFalse(
            m.browser_case_proof({"suites": [{"specs": cases}]})["complete"]
        )


if __name__ == "__main__":
    unittest.main()
