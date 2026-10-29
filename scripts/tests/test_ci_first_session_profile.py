# contract-test-file: tooling
"""Inert first-session selector, source binding and mandatory-case controls.
Exercises the actual protected predicates and environment builder.
Synthetic compiler receipts are validator inputs, never runtime proof.
No Cargo, Vite, browser, account, network or product invocation occurs.
Existing metadata and startup profiles remain separate obligations.
"""

import ast
from copy import deepcopy
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
    "actual first normal session retains one original Worker through UI and startup",
    "actual revoked first normal session expires once without a Rust restore retry",
    "actual first normal auth queue preserves its original deadline without fallback",
    "actual missing cached Master reads normal Rust session DATA once without private admission",
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
    return m.first_session_browser_case_proof(value)["complete"]


class FirstSessionProfileTests(unittest.TestCase):
    def test_exact_titles_and_each_missing_duplicate_or_failed_case(self):
        self.assertEqual(m.FIRST_SESSION_REQUIRED_CASES, frozenset(TITLES))
        self.assertTrue(valid(report()))
        for index in range(len(TITLES)):
            for fault in ("missing", "duplicate", "failed"):
                with self.subTest(index=index, fault=fault):
                    value = report()
                    specs = value["suites"][0]["specs"]
                    if fault == "missing":
                        specs.pop(index)
                    elif fault == "duplicate":
                        specs.append(deepcopy(specs[index]))
                    else:
                        specs[index]["tests"][0]["results"][0]["status"] = "failed"
                    self.assertFalse(valid(value))

    def test_duplicate_empty_or_malformed_required_specs_cannot_disappear(self):
        for title in TITLES:
            for tests in (None, {}, "", [], [None]):
                with self.subTest(title=title, tests=tests):
                    value = report()
                    bad = {"title": title}
                    if tests is not None:
                        bad["tests"] = tests
                    value["suites"].append({"specs": [bad]})
                    self.assertFalse(valid(value))

    def test_exact_one_expected_test_and_one_explicit_integer_retry_zero(self):
        for index in range(len(TITLES)):
            for retry in (None, True, False, "0", 0.0, 1, -1):
                value = report()
                result = value["suites"][0]["specs"][index]["tests"][0]["results"][0]
                if retry is None:
                    result.pop("retry")
                else:
                    result["retry"] = retry
                self.assertFalse(valid(value), (index, retry))
            for fault in (
                "empty",
                "multiple-results",
                "multiple-tests",
                "skipped",
                "flaky",
                "unexpected",
            ):
                value = report()
                test = value["suites"][0]["specs"][index]["tests"][0]
                if fault == "empty":
                    test["results"] = []
                elif fault == "multiple-results":
                    test["results"].append(deepcopy(test["results"][0]))
                elif fault == "multiple-tests":
                    value["suites"][0]["specs"][index]["tests"].append(deepcopy(test))
                elif fault in ("skipped", "flaky"):
                    test["results"][0]["status"] = fault
                else:
                    test["status"] = fault
                self.assertFalse(valid(value), (index, fault))

    def test_finite_singleton_and_existing_isolation_admission(self):
        ambient = dict(
            GITHUB_ACTIONS="true",
            RUNNER_ENVIRONMENT="github-hosted",
            OPENMATES_CI_ISOLATED="1",
            CI_TEST_MODE="e2e",
            CI_SPECS_JSON=json.dumps([m.FIRST_SESSION_SPEC]),
        )
        self.assertTrue(m.targets([m.FIRST_SESSION_SPEC]))
        self.assertTrue(lane.production_browser_e2e_targets([m.FIRST_SESSION_SPEC]))
        supplier.require_selector(ambient)
        for selection in (
            [],
            [m.FIRST_SESSION_SPEC] * 2,
            [m.FIRST_SESSION_SPEC, m.STARTUP_SPEC],
            [m.FIRST_SESSION_SPEC, lane.PRODUCTION_BROWSER_SPEC],
            ["nested/" + m.FIRST_SESSION_SPEC],
            (m.FIRST_SESSION_SPEC,),
        ):
            self.assertFalse(m.first_session_targets(selection))
            self.assertFalse(lane.production_browser_e2e_targets(selection))
        for key, value in (
            ("GITHUB_ACTIONS", "false"),
            ("RUNNER_ENVIRONMENT", "self-hosted"),
            ("OPENMATES_CI_ISOLATED", "0"),
            ("CI_TEST_MODE", "component"),
            ("CI_CASE_TITLE", TITLES[0]),
            ("CI_CAPACITY_CONFIGURATION", "other"),
        ):
            with self.subTest(key=key), self.assertRaises(lane.sdk.Refused):
                supplier.require_selector({**ambient, key: value})

    def test_verified_build_enables_only_fixed_first_session_and_old_profiles_stay_off(
        self,
    ):
        poison = {
            "OPENMATES_RUST_FIRST_SESSION_PROVIDER": "attacker",
            "VITE_OPENMATES_RUST_INITIAL_SYNC_PROTOTYPE": "attacker",
            "OPENMATES_RUST_CORE_ARTIFACT": "a" * 64,
        }
        for target in (
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
                    supplier, "safe_destination", return_value=Path("/inert/verified")
                ),
            ):
                output = supplier.build_environment(Path("/inert"), ambient)
            verify.assert_called_once_with(Path("/inert"), environ=ambient)
            self.assertEqual(
                output.get("OPENMATES_RUST_FIRST_SESSION_PROVIDER"),
                "1" if target == m.FIRST_SESSION_SPEC else None,
            )
            self.assertEqual(
                output.get("VITE_OPENMATES_RUST_INITIAL_SYNC_PROTOTYPE"),
                "1"
                if target in (m.FIRST_SESSION_SPEC, m.STARTUP_SPEC, m.PAIRED_SPEC)
                else None,
            )
            self.assertEqual(
                output.get("OPENMATES_RUST_METADATA_PROTOTYPE"),
                "1" if m.targets([target]) else None,
            )
        with patch.object(
            supplier, "verify_for_e2e", side_effect=lane.sdk.Refused("outputs")
        ):
            with self.assertRaises(lane.sdk.Refused):
                supplier.build_environment(
                    Path("/inert"),
                    {**poison, "CI_SPECS_JSON": json.dumps([m.FIRST_SESSION_SPEC])},
                )

    def test_actual_build_keeps_same_command_and_reverification_for_default_and_feature(
        self,
    ):
        for target in (lane.PRODUCTION_BROWSER_SPEC, m.FIRST_SESSION_SPEC):
            ambient = {
                "CI_SPECS_JSON": json.dumps([target]),
                "OPENMATES_RUST_CORE_ARTIFACT": "a" * 64,
            }
            with (
                patch.object(supplier, "verify_for_e2e", return_value={}) as verify,
                patch.object(
                    supplier, "safe_destination", return_value=Path("/inert/verified")
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
            self.assertTrue(run.call_args.kwargs["check"])
            self.assertEqual(
                run.call_args.kwargs["env"].get(
                    "OPENMATES_RUST_FIRST_SESSION_PROVIDER"
                ),
                "1" if target == m.FIRST_SESSION_SPEC else None,
            )

    def test_first_session_source_snapshot_requires_all_fixed_inputs_and_detects_drift(
        self,
    ):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            expected = {}
            for name in m.FIRST_SESSION_INPUTS | m.EXTRA_INPUTS:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(name.encode())
                expected[name] = lane.sdk.sha(name.encode())
            base = {"packages/openmates-rust/Cargo.toml": "a" * 64}
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
                        first_session_profile=True,
                    ),
                    expected,
                )
                for name in sorted(m.FIRST_SESSION_INPUTS):
                    missing = dict(expected)
                    missing.pop(name)
                    with (
                        self.subTest(missing=name),
                        self.assertRaises(lane.sdk.Refused),
                    ):
                        lane.source_snapshot(
                            root,
                            missing,
                            metadata_profile=True,
                            first_session_profile=True,
                        )
                    path = root / name
                    raw = path.read_bytes()
                    path.write_bytes(raw + b"changed")
                    self.assertNotEqual(
                        lane.source_snapshot(
                            root,
                            expected,
                            metadata_profile=True,
                            first_session_profile=True,
                        ),
                        expected,
                    )
                    path.write_bytes(raw)
                with self.assertRaises(lane.sdk.Refused):
                    lane.source_snapshot(root, expected, first_session_profile=True)

    def test_actual_compiler_receipt_rejects_self_consistent_missing_first_session_input(
        self,
    ):
        spec = importlib.util.spec_from_file_location(
            "first_session_metadata_fixture",
            ROOT / "scripts/tests/test_ci_metadata_rust_browser.py",
        )
        fixture = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fixture)
        receipt, job, kwargs = fixture.compiler()
        job["specs"] = json.dumps([m.FIRST_SESSION_SPEC])
        receipt["requestedTargets"] = [m.FIRST_SESSION_SPEC]
        receipt["inputs"].update(
            {name: "b" * 64 for name in m.FIRST_SESSION_INPUTS - m.EXTRA_INPUTS}
        )

        def reseal():
            inputs = receipt["inputs"]
            receipt["inputSetSha256"] = lane.sdk.sha(
                json.dumps(inputs, sort_keys=True).encode()
            )
            manifest = json.loads(kwargs["package_manifest"])
            manifest.update(
                requestedTargets=[m.FIRST_SESSION_SPEC],
                inputs=inputs,
                inputSetSha256=receipt["inputSetSha256"],
            )
            kwargs.update(
                expected_inputs=deepcopy(inputs),
                package_manifest=json.dumps(manifest, sort_keys=True).encode(),
            )
            receipt["package"]["manifestSha256"] = lane.sdk.sha(
                kwargs["package_manifest"]
            )

        reseal()
        self.assertTrue(
            results.valid_rust_wasm_compiler_receipt(receipt, job, "f" * 40, **kwargs)
        )
        for name in sorted(m.FIRST_SESSION_INPUTS):
            old = receipt["inputs"].pop(name)
            reseal()
            self.assertFalse(
                results.valid_rust_wasm_compiler_receipt(
                    receipt, job, "f" * 40, **kwargs
                ),
                name,
            )
            receipt["inputs"][name] = old
            reseal()
        kwargs["package_files"]["unknown.js"] = b"export const unknown=true;"
        self.assertFalse(
            results.valid_rust_wasm_compiler_receipt(receipt, job, "f" * 40, **kwargs)
        )

    def test_actual_result_region_keeps_full_spec_conjunction(self):
        source = (ROOT / "scripts/ci_run_tests.py").read_text()
        start = source.index("                metadata_native_proof = None")
        end = source.index("                results.append(", start)
        region = "\n".join(line[16:] for line in source[start:end].splitlines())
        sys.modules["ci_metadata_rust_browser"] = m
        for complete in (True, False):
            namespace = dict(
                name=m.FIRST_SESSION_SPEC,
                report=report(),
                selected_case_complete=complete,
                paired=False,
            )
            exec(region, namespace)
            self.assertEqual(namespace["selected_case_complete"], complete)
        namespace = dict(
            name=m.FIRST_SESSION_SPEC,
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
        self.assertIn('env.pop("OPENMATES_RUST_FIRST_SESSION_PROVIDER", None)', source)

    def test_workflow_exact_singleton_build_clock_cli_upload_and_existing_tools(self):
        import yaml

        source = (ROOT / ".github/workflows/isolated-tests.yml").read_text()
        steps = next(iter(yaml.safe_load(source)["jobs"].values()))["steps"]
        marker = "inputs.specs_json == '[\"" + m.FIRST_SESSION_SPEC + "\"]'"
        clock = next(
            step
            for step in steps
            if step.get("name") == "Start bounded same-source browser package clock"
        )
        self.assertIn(marker, clock["if"])
        self.assertIn("started + 1800", clock["run"])
        self.assertEqual(source.count(marker), 6)
        self.assertIn("'e2e:[\"" + m.FIRST_SESSION_SPEC + "\"]'|", source)
        self.assertIn("ci_production_rust_browser.py prepare", source)
        self.assertIn("ci_production_rust_browser.py build", source)
        self.assertIn("subject/test-results/rust-wasm/package/", source)
        self.assertIn("src/platform/browser_metadata_native.js", source)
        for file, constant in (
            ("ci_environment.py", "PRIVATE_BACKEND_SPECS"),
            ("ci_run_tests.py", "MARKER_CHAT_EPOCH_SPECS"),
            ("ci_run_tests.py", "RUST_PRODUCTION_BROWSER_SPECS"),
        ):
            tree = ast.parse((ROOT / "scripts" / file).read_text())
            node = next(
                n
                for n in tree.body
                if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == constant for t in n.targets)
            )
            self.assertIn(m.FIRST_SESSION_SPEC, ast.literal_eval(node.value.args[0]))
        self.assertEqual(
            lane.commands(metadata_profile=True)[2],
            lane.commands()[2] + ["--features", m.FEATURE],
        )
        self.assertEqual(lane.BROWSER_BUDGET, 1800)


if __name__ == "__main__":
    unittest.main()
