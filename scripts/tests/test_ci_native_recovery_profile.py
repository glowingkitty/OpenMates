# contract-test-file: tooling
"""Inert fixed native recovery admission/accounting, never product execution."""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts import ci_metadata_rust_browser as m  # noqa: E402  # Requires the original sys.path bootstrap above.
from scripts import ci_rust_wasm as lane  # noqa: E402  # Requires the original sys.path bootstrap above.
from scripts import ci_production_rust_browser as supplier  # noqa: E402  # Requires the original sys.path bootstrap above.
from scripts import ci_results as results  # noqa: E402  # Requires the original sys.path bootstrap above.

TITLES = (
    "original native recovery port binds inside genuine restored Worker and drains before root teardown",
    *(
        "actual profile native IDB opaque receipt and shared commit: " + v
        for v in ("positive", "uncertain", "cancel", "foreign")
    ),
    *(
        "same native original row Master reread and draft floor hydration: " + v
        for v in (
            "cleared_floor",
            "large_draft",
            "changed_row",
            "cancel_native",
            "large_existing_cache",
            "cancel_crypto",
        )
    ),
    "actual shared metadata Progress cancellation preserves the complete native pending checkpoint and header",
    *(
        "same original Core metadata CAS reread and exact journal retirement: " + v
        for v in (
            "success",
            "rewrap_same_key",
            "cancel_read",
            "cancel_write",
            "cancel_reread",
            "journal_race",
            "key_change",
            "profile_negative",
            "unknown_retirement_reply",
        )
    ),
    *(
        "actual Main recovery metadata remains pending with original journal: " + v
        for v in ("success", "cancel_read")
    ),
    "actual Main normal canonical alias reply persists with original pending journal: success",
)


def report():
    return {
        "suites": [
            {
                "specs": [
                    {
                        "title": title,
                        "tests": [
                            {
                                "status": "expected",
                                "results": [{"status": "passed", "retry": 0}],
                            }
                        ],
                    }
                    for title in TITLES
                ]
            }
        ]
    }


def valid(value):
    return m.native_recovery_browser_case_proof(value)["complete"]


class NativeRecoveryProfileTests(unittest.TestCase):
    def test_every_original_and_main_case_required_once(self):
        self.assertEqual(len(TITLES), 24)
        self.assertEqual(m.NATIVE_RECOVERY_REQUIRED_CASES, frozenset(TITLES))
        self.assertTrue(valid(report()))
        for index in range(len(TITLES)):
            for fault in ("missing", "duplicate", "failed"):
                value = report()
                specs = value["suites"][0]["specs"]
                if fault == "missing":
                    specs.pop(index)
                elif fault == "duplicate":
                    specs.append(deepcopy(specs[index]))
                else:
                    specs[index]["tests"][0]["results"][0]["status"] = "failed"
                self.assertFalse(valid(value), (index, fault))
        value = report()
        value["suites"][0]["specs"] = value["suites"][0]["specs"][:21]
        self.assertFalse(valid(value))

    def test_required_title_specs_count_even_when_empty_or_malformed(self):
        for title in TITLES:
            for tests in (None, {}, "", [], [None]):
                value = report()
                bad = {"title": title}
                if tests is not None:
                    bad["tests"] = tests
                value["suites"].append({"specs": [bad]})
                self.assertFalse(valid(value), (title, tests))

    def test_each_result_has_explicit_nonboolean_integer_zero_retry(self):
        for index in range(len(TITLES)):
            for retry in (None, True, False, "0", 0.0, 1, -1):
                value = report()
                result = value["suites"][0]["specs"][index]["tests"][0]["results"][0]
                if retry is None:
                    result.pop("retry")
                else:
                    result["retry"] = retry
                self.assertFalse(valid(value), (index, retry))

    def test_partial_multiple_retried_skipped_or_wrong_title_refuse(self):
        for index in range(len(TITLES)):
            for fault in (
                "missing-results",
                "nonlist-results",
                "empty",
                "multiple-results",
                "multiple-tests",
                "skipped",
                "flaky",
                "unexpected",
                "near-title",
            ):
                value = report()
                spec = value["suites"][0]["specs"][index]
                test = spec["tests"][0]
                if fault == "missing-results":
                    test.pop("results")
                elif fault == "nonlist-results":
                    test["results"] = {}
                elif fault == "empty":
                    test["results"] = []
                elif fault == "multiple-results":
                    test["results"].append(deepcopy(test["results"][0]))
                elif fault == "multiple-tests":
                    spec["tests"].append(deepcopy(test))
                elif fault in ("skipped", "flaky"):
                    test["results"][0]["status"] = fault
                elif fault == "near-title":
                    spec["title"] += " "
                else:
                    test["status"] = fault
                self.assertFalse(valid(value), (index, fault))

    def test_actual_result_region_preserves_full_spec_and_process_exit(self):
        source = (ROOT / "scripts/ci_run_tests.py").read_text()
        start = source.index("                metadata_native_proof = None")
        end = source.index("                results.append(", start)
        region = "\n".join(line[16:] for line in source[start:end].splitlines())
        sys.modules["ci_metadata_rust_browser"] = m
        for complete in (True, False):
            namespace = dict(
                name=m.NATIVE_RECOVERY_SPEC,
                report=report(),
                selected_case_complete=complete,
                paired=False,
            )
            exec(region, namespace)
            self.assertEqual(namespace["selected_case_complete"], complete)
        namespace = dict(
            name=m.NATIVE_RECOVERY_SPEC,
            report={"suites": []},
            selected_case_complete=True,
            paired=False,
        )
        exec(region, namespace)
        self.assertFalse(namespace["selected_case_complete"])
        self.assertIn(
            '"exit_code": result.returncode if selected_case_complete else 1',
            source[end:],
        )
        self.assertIn('stats.get("skipped", 0)', source[:start])

    def test_exact_singleton_and_existing_isolated_admission(self):
        ambient = dict(
            GITHUB_ACTIONS="true",
            RUNNER_ENVIRONMENT="github-hosted",
            OPENMATES_CI_ISOLATED="1",
            CI_TEST_MODE="e2e",
            CI_SPECS_JSON=json.dumps([m.NATIVE_RECOVERY_SPEC]),
        )
        supplier.require_selector(ambient)
        for targets in (
            [],
            [m.NATIVE_RECOVERY_SPEC] * 2,
            [m.NATIVE_RECOVERY_SPEC, m.SPEC],
            ["nested/" + m.NATIVE_RECOVERY_SPEC],
            (m.NATIVE_RECOVERY_SPEC,),
        ):
            self.assertFalse(m.native_recovery_targets(targets))
            self.assertFalse(lane.production_browser_e2e_targets(targets))
        for key, value in (
            ("GITHUB_ACTIONS", "false"),
            ("RUNNER_ENVIRONMENT", "self-hosted"),
            ("OPENMATES_CI_ISOLATED", "0"),
            ("CI_TEST_MODE", "component"),
            ("CI_CASE_TITLE", TITLES[-1]),
            ("CI_CAPACITY_CONFIGURATION", "other"),
        ):
            with self.assertRaises(lane.sdk.Refused):
                supplier.require_selector({**ambient, key: value})
        source = (ROOT / "scripts/ci_run_tests.py").read_text()
        start = source.index('    if "rust-core-native-recovery-port.spec.ts" in specs')
        end = source.index("    if paired and", start)
        guard = "\n".join(line[4:] for line in source[start:end].splitlines())
        for flags in (
            (False, False, False, ""),
            (True, False, False, ""),
            (False, True, False, ""),
            (False, False, True, ""),
            (False, False, False, TITLES[-1]),
        ):
            namespace = dict(
                specs=[m.NATIVE_RECOVERY_SPEC],
                artifact=flags[0],
                component=flags[1],
                visual_smoke=flags[2],
                case_title=flags[3],
            )
            if any(flags):
                with self.assertRaises(ValueError):
                    exec(guard, namespace)
            else:
                exec(guard, namespace)

    def test_build_keeps_old_limits_and_provider_initial_sync_off(self):
        poison = dict(
            OPENMATES_RUST_FIRST_SESSION_PROVIDER="attacker",
            VITE_OPENMATES_RUST_INITIAL_SYNC_PROTOTYPE="attacker",
            OPENMATES_RUST_CORE_ARTIFACT="a" * 64,
        )
        for target in (
            m.NATIVE_RECOVERY_SPEC,
            m.FIRST_SESSION_SPEC,
            m.SPEC,
            m.STARTUP_SPEC,
            m.PAIRED_SPEC,
            lane.PRODUCTION_BROWSER_SPEC,
        ):
            ambient = {**poison, "CI_SPECS_JSON": json.dumps([target])}
            with (
                patch.object(supplier, "verify_for_e2e", return_value={}) as verify,
                patch.object(
                    supplier, "safe_destination", return_value=Path("/inert/held")
                ),
                patch.object(supplier.subprocess, "run") as run,
            ):
                supplier.build(Path("/inert"), ambient)
            self.assertEqual(verify.call_count, 2)
            self.assertEqual(
                run.call_args.args[0],
                ["pnpm", "--dir", "frontend/apps/web_app", "exec", "vite", "build"],
            )
            self.assertEqual(run.call_args.kwargs["timeout"], 900)
            env = run.call_args.kwargs["env"]
            self.assertEqual(
                env.get("OPENMATES_RUST_FIRST_SESSION_PROVIDER"),
                "1" if target == m.FIRST_SESSION_SPEC else None,
            )
            self.assertEqual(
                env.get("VITE_OPENMATES_RUST_INITIAL_SYNC_PROTOTYPE"),
                "1"
                if target in (m.FIRST_SESSION_SPEC, m.STARTUP_SPEC, m.PAIRED_SPEC)
                else None,
            )
            self.assertEqual(
                env.get("OPENMATES_RUST_METADATA_PROTOTYPE"),
                "1" if m.targets([target]) else None,
            )
        self.assertEqual(lane.BROWSER_BUDGET, 1800)
        self.assertEqual(
            lane.commands(metadata_profile=True)[2],
            lane.commands()[2] + ["--features", m.FEATURE],
        )

    def test_actual_snapshot_rejects_every_missing_input_and_detects_drift(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            expected = {}
            base = {"packages/openmates-rust/Cargo.toml": "a" * 64}
            for name in m.NATIVE_RECOVERY_INPUTS | m.EXTRA_INPUTS:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(name.encode())
                expected[name] = lane.sdk.sha(name.encode())
            expected.update(base)
            with patch.object(
                lane,
                "snapshot",
                side_effect=lambda r, e: (
                    e
                    if e == base
                    else (_ for _ in ()).throw(lane.sdk.Refused("source"))
                ),
            ):
                self.assertEqual(
                    lane.source_snapshot(
                        root,
                        expected,
                        metadata_profile=True,
                        native_recovery_profile=True,
                    ),
                    expected,
                )
                for name in sorted(m.NATIVE_RECOVERY_INPUTS):
                    missing = dict(expected)
                    missing.pop(name)
                    with self.assertRaises(lane.sdk.Refused):
                        lane.source_snapshot(
                            root,
                            missing,
                            metadata_profile=True,
                            native_recovery_profile=True,
                        )
                    path = root / name
                    raw = path.read_bytes()
                    path.write_bytes(raw + b"changed")
                    self.assertNotEqual(
                        lane.source_snapshot(
                            root,
                            expected,
                            metadata_profile=True,
                            native_recovery_profile=True,
                        ),
                        expected,
                    )
                    path.write_bytes(raw)
                with self.assertRaises(lane.sdk.Refused):
                    lane.source_snapshot(root, expected, native_recovery_profile=True)

    def test_exact_current_kernel_bridge_tuple_and_generated_bytes(self):
        bridge = "packages/openmates-rust/src/platform/browser_metadata_native.rs"
        inputs = {
            **m.SOURCE_PINS,
            m.NATIVE_SOURCE: "cf00e87ad951749f1c656af6f653dfac33f06c7d1b010883b60f19bf87ec044b",
            bridge: "fd9af1ccfc3c6fd1ebacf9e656140b821f5a5f5dd66a9a3eb97fdca007a91575",
            m.RECOVERY_SOURCE: "1cdcd6adfc192a0841dc8985e57bf7d1b2a23506d90061f34bd2b4ce5dc77478",
            "packages/openmates-rust/Cargo.toml": "38a1e0eb7218dc52b3121d528b49411d481ef3a602e1e2d69e124520e3d3f441",
        }
        self.assertTrue(m.native_source_bound(m.SOURCE_PINS))
        self.assertTrue(m.native_source_bound(inputs))
        for name in (
            m.NATIVE_SOURCE,
            bridge,
            m.RECOVERY_SOURCE,
            "packages/openmates-rust/Cargo.toml",
        ):
            self.assertFalse(m.native_source_bound({**inputs, name: "0" * 64}), name)
            self.assertFalse(
                m.native_source_bound(
                    {key: value for key, value in inputs.items() if key != name}
                ),
                name,
            )
        self.assertFalse(
            m.native_source_bound(
                {**inputs, m.NATIVE_SOURCE: m.SOURCE_PINS[m.NATIVE_SOURCE]}
            )
        )
        self.assertFalse(
            m.native_source_bound(
                {
                    **inputs,
                    m.NATIVE_SOURCE: "4c27064dc94a07bde450a23af21fb5f832130134ec5324551b5d8c9416f785f0",
                }
            )
        )
        c = "snippets/openmates-browser-bindings-0123456789abcdef/inline0.js"
        r = "snippets/openmates-sdk-0123456789abcdef/inline0.js"
        n = "snippets/openmates-sdk-0123456789abcdef/src/platform/browser_metadata_native.js"
        files = {
            "openmates_browser.js": "".join(
                "import * as import" + str(i) + ' from "./' + v + '"\n'
                for i, v in enumerate((c, r, n), 1)
            ).encode()
            + b"export default function init(){};",
            "openmates_browser_bg.wasm": b"\0asm\x01\0\0\0",
            "openmates_browser.d.ts": b"export {};",
            c: m.CRYPTO_BYTES,
            r: recovery_body(ROOT / m.RECOVERY_SOURCE),
            n: (ROOT / m.NATIVE_SOURCE).read_bytes(),
        }
        self.assertEqual(hashlib.sha256(files[n]).hexdigest(), inputs[m.NATIVE_SOURCE])
        self.assertTrue(
            m.package_modules(files, inputs, lane.closed_module_dependencies)
        )
        for key in (c, r, n):
            self.assertFalse(
                m.package_modules(
                    {**files, key: files[key] + b"changed"},
                    inputs,
                    lane.closed_module_dependencies,
                )
            )
        for attack in (
            b'import("./foreign.js")',
            b'export * from "./foreign.js"',
            b'import "./foreign.js"',
        ):
            self.assertFalse(
                m.package_modules(
                    {
                        **files,
                        "openmates_browser.js": files["openmates_browser.js"] + attack,
                    },
                    inputs,
                    lane.closed_module_dependencies,
                )
            )

    def test_actual_compiler_receipt_rejects_each_self_consistent_missing_input(self):
        spec = importlib.util.spec_from_file_location(
            "native_recovery_receipt_fixture",
            ROOT / "scripts/tests/test_ci_rust_wasm.py",
        )
        fixture = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fixture)
        _, receipt, job, kwargs = fixture.WasmReceiptTests().fixture()
        c = "snippets/openmates-browser-bindings-0123456789abcdef/inline0.js"
        r = "snippets/openmates-sdk-0123456789abcdef/inline0.js"
        n = "snippets/openmates-sdk-0123456789abcdef/src/platform/browser_metadata_native.js"
        inputs = {
            **kwargs["expected_inputs"],
            **m.SOURCE_PINS,
            **{p: "b" * 64 for p in m.NATIVE_RECOVERY_INPUTS | m.EXTRA_INPUTS},
        }
        for path in (
            m.NATIVE_SOURCE,
            m.RECOVERY_SOURCE,
            m.CRYPTO_SOURCE,
            "packages/openmates-rust/src/platform/browser_metadata_native.rs",
            "packages/openmates-rust/Cargo.toml",
        ):
            inputs[path] = lane.sdk.sha((ROOT / path).read_bytes())
        files = {
            "openmates_browser.js": "".join(
                "import * as import" + str(i) + ' from "./' + p + '"\n'
                for i, p in enumerate((c, r, n), 1)
            ).encode()
            + b"export default function init(){};",
            "openmates_browser_bg.wasm": fixture.WASM,
            "openmates_browser.d.ts": b"export {};",
            c: m.CRYPTO_BYTES,
            r: recovery_body(ROOT / m.RECOVERY_SOURCE),
            n: (ROOT / m.NATIVE_SOURCE).read_bytes(),
        }
        job.update(mode="e2e", specs=json.dumps([m.NATIVE_RECOVERY_SPEC]))
        receipt.update(
            runtime_profile="rust-browser-package-for-e2e",
            requestedMode="e2e",
            requestedTargets=[m.NATIVE_RECOVERY_SPEC],
            workerProof=None,
            inputs=inputs,
        )
        receipt["steps"] = receipt["steps"][:6]
        for row, argv in zip(receipt["steps"], lane.commands(metadata_profile=True)):
            row["command"]["argvSha256"] = lane.sdk.sha(
                json.dumps(argv, separators=(",", ":")).encode()
            )
        manifest = json.loads(kwargs["package_manifest"])
        manifest.update(
            requestedMode="e2e",
            requestedTargets=[m.NATIVE_RECOVERY_SPEC],
            features=[m.FEATURE],
        )
        rows = [
            {"path": p, "sha256": lane.sdk.sha(raw), "rawBytes": len(raw)}
            for p, raw in sorted(files.items())
        ]
        manifest["inventory"] = {
            "files": rows,
            "rawBytes": sum(row["rawBytes"] for row in rows),
            "inventorySha256": lane.sdk.sha(
                json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
            ),
        }
        receipt["package"]["inventorySha256"] = manifest["inventory"]["inventorySha256"]

        def reseal():
            receipt["inputSetSha256"] = lane.sdk.sha(
                json.dumps(inputs, sort_keys=True).encode()
            )
            manifest.update(inputs=inputs, inputSetSha256=receipt["inputSetSha256"])
            raw = json.dumps(manifest, sort_keys=True).encode()
            receipt["package"]["manifestSha256"] = lane.sdk.sha(raw)
            kwargs.update(
                expected_inputs=deepcopy(inputs),
                package_manifest=raw,
                package_files=files,
            )

        reseal()
        self.assertTrue(
            results.valid_rust_wasm_compiler_receipt(receipt, job, "f" * 40, **kwargs)
        )
        for path in sorted(m.NATIVE_RECOVERY_INPUTS):
            value = inputs.pop(path)
            reseal()
            self.assertFalse(
                results.valid_rust_wasm_compiler_receipt(
                    receipt, job, "f" * 40, **kwargs
                ),
                path,
            )
            inputs[path] = value
            reseal()
        kwargs["package_files"]["unknown.js"] = b"export {};"
        self.assertFalse(
            results.valid_rust_wasm_compiler_receipt(receipt, job, "f" * 40, **kwargs)
        )


def recovery_body(path):
    import re

    raw = path.read_text()
    found = re.search(r'inline_js = "([\s\S]*?)"\)\]\s*extern', raw)
    return json.loads(
        '"' + found[1].replace("\n", "\\n").replace("\r", "\\r") + '"'
    ).encode()


if __name__ == "__main__":
    unittest.main()
