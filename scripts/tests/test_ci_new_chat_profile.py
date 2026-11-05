# contract-test-file: tooling
# Fixed ActiveChat admission/accounting with inert process/package fixture ports.
# These tests never run Cargo, WASM, Vite, a browser, backend or SDK operation.
# Synthetic producer bytes exercise validators, not compilation/runtime proof.
# Original protected process/deadline/module policies remain external authority.
from copy import deepcopy
import ast
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
from scripts import ci_environment as environment  # noqa: E402  # Requires the original sys.path bootstrap above.

TITLE = "actual Rust first request persists before routing then follows up on the original startup owner"


def report():
    return {
        "suites": [
            {
                "specs": [
                    {
                        "title": TITLE,
                        "tests": [
                            {
                                "status": "expected",
                                "results": [{"status": "passed", "retry": 0}],
                            }
                        ],
                    }
                ]
            }
        ]
    }


def valid(value):
    return m.new_chat_browser_case_proof(value)["complete"]


class NewChatProfileTests(unittest.TestCase):
    def test_exact_singleton_and_original_isolated_guard(self):
        self.assertEqual(m.NEW_CHAT_REQUIRED_CASES, frozenset((TITLE,)))
        self.assertTrue(m.new_chat_targets([m.NEW_CHAT_SPEC]))
        self.assertTrue(m.targets([m.NEW_CHAT_SPEC]))
        self.assertTrue(lane.production_browser_e2e_targets([m.NEW_CHAT_SPEC]))
        for selected in (
            [],
            [m.NEW_CHAT_SPEC] * 2,
            [m.NEW_CHAT_SPEC, m.STARTUP_SPEC],
            ["nested/" + m.NEW_CHAT_SPEC],
            (m.NEW_CHAT_SPEC,),
        ):
            self.assertFalse(m.new_chat_targets(selected))
            self.assertFalse(lane.production_browser_e2e_targets(selected))
        ambient = dict(
            GITHUB_ACTIONS="true",
            RUNNER_ENVIRONMENT="github-hosted",
            OPENMATES_CI_ISOLATED="1",
            CI_TEST_MODE="e2e",
            CI_SPECS_JSON=json.dumps([m.NEW_CHAT_SPEC]),
        )
        supplier.require_selector(ambient)
        for key, value in (
            ("GITHUB_ACTIONS", "false"),
            ("RUNNER_ENVIRONMENT", "self-hosted"),
            ("OPENMATES_CI_ISOLATED", "0"),
            ("CI_TEST_MODE", "component"),
            ("CI_CASE_TITLE", TITLE),
            ("CI_CAPACITY_CONFIGURATION", "other"),
        ):
            with self.assertRaises(lane.sdk.Refused):
                supplier.require_selector({**ambient, key: value})
        source = (ROOT / "scripts/ci_run_tests.py").read_text()
        start = source.index('    if "' + m.NEW_CHAT_SPEC + '" in specs')
        end = source.index('    if "rust-core-native-recovery-port.spec.ts"', start)
        region = "\n".join(line[4:] for line in source[start:end].splitlines())
        for flags in (
            (False, False, False, ""),
            (True, False, False, ""),
            (False, True, False, ""),
            (False, False, True, ""),
            (False, False, False, TITLE),
        ):
            scope = dict(
                specs=[m.NEW_CHAT_SPEC],
                artifact=flags[0],
                component=flags[1],
                visual_smoke=flags[2],
                case_title=flags[3],
            )
            if any(flags):
                with self.assertRaises(ValueError):
                    exec(region, scope)
            else:
                exec(region, scope)

    def test_required_title_counted_before_malformed_duplicate_validation(self):
        self.assertTrue(valid(report()))
        self.assertFalse(valid({"suites": []}))
        for tests in (None, {}, "", [], [None]):
            value = report()
            duplicate = {"title": TITLE}
            if tests is not None:
                duplicate["tests"] = tests
            value["suites"].append({"specs": [duplicate]})
            self.assertFalse(valid(value))
        value = report()
        value["suites"].append(deepcopy(value["suites"][0]))
        self.assertFalse(valid(value))

    def test_explicit_retry_and_single_actual_result_are_required(self):
        for retry in (None, True, False, "0", 0.0, 1, -1):
            value = report()
            row = value["suites"][0]["specs"][0]["tests"][0]["results"][0]
            if retry is None:
                row.pop("retry")
            else:
                row["retry"] = retry
            self.assertFalse(valid(value), retry)
        for fault in (
            "empty",
            "multiple-results",
            "multiple-tests",
            "skipped",
            "flaky",
            "unexpected",
            "missing-result",
            "wrong-title",
            "failed",
        ):
            value = report()
            spec = value["suites"][0]["specs"][0]
            test = spec["tests"][0]
            if fault == "empty":
                test["results"] = []
            elif fault == "multiple-results":
                test["results"].append(deepcopy(test["results"][0]))
            elif fault == "multiple-tests":
                spec["tests"].append(deepcopy(test))
            elif fault == "missing-result":
                test.pop("results")
            elif fault == "wrong-title":
                spec["title"] += " "
            elif fault == "unexpected":
                test["status"] = "unexpected"
            else:
                test["results"][0]["status"] = fault
            self.assertFalse(valid(value), fault)

    def test_full_spec_and_process_exit_remain_conjoined(self):
        source = (ROOT / "scripts/ci_run_tests.py").read_text()
        start = source.index("                metadata_native_proof = None")
        end = source.index("                results.append(", start)
        region = "\n".join(line[16:] for line in source[start:end].splitlines())
        sys.modules["ci_metadata_rust_browser"] = m
        for complete in (True, False):
            scope = dict(
                name=m.NEW_CHAT_SPEC,
                report=report(),
                selected_case_complete=complete,
                paired=False,
            )
            exec(region, scope)
            self.assertEqual(scope["selected_case_complete"], complete)
        scope = dict(
            name=m.NEW_CHAT_SPEC,
            report={"suites": []},
            selected_case_complete=True,
            paired=False,
        )
        exec(region, scope)
        self.assertFalse(scope["selected_case_complete"])
        self.assertIn(
            '"exit_code": result.returncode if selected_case_complete else 1',
            source[end:],
        )
        self.assertIn('stats.get("skipped", 0)', source[:start])

    def test_build_uses_existing_package_and_limits_provider_off(self):
        poison = dict(
            OPENMATES_RUST_FIRST_SESSION_PROVIDER="ambient",
            VITE_OPENMATES_RUST_INITIAL_SYNC_PROTOTYPE="ambient",
            OPENMATES_RUST_CORE_ARTIFACT="a" * 64,
        )
        for target in (
            m.NEW_CHAT_SPEC,
            m.NATIVE_RECOVERY_SPEC,
            m.FIRST_SESSION_SPEC,
            m.SPEC,
            m.STARTUP_SPEC,
            m.PAIRED_SPEC,
            lane.PRODUCTION_BROWSER_SPEC,
        ):
            with (
                patch.object(supplier, "verify_for_e2e", return_value={}) as verify,
                patch.object(
                    supplier, "safe_destination", return_value=Path("/inert/held")
                ),
                patch.object(supplier.subprocess, "run") as run,
            ):
                supplier.build(
                    Path("/inert"), {**poison, "CI_SPECS_JSON": json.dumps([target])}
                )
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
                if target
                in (
                    m.NEW_CHAT_SPEC,
                    m.FIRST_SESSION_SPEC,
                    m.STARTUP_SPEC,
                    m.PAIRED_SPEC,
                )
                else None,
            )
            self.assertEqual(
                env.get("OPENMATES_RUST_METADATA_PROTOTYPE"),
                "1" if m.targets([target]) else None,
            )
        self.assertEqual(lane.BROWSER_BUDGET, 3600)
        self.assertEqual(
            lane.commands(metadata_profile=True)[2],
            lane.commands()[2] + ["--features", m.FEATURE],
        )

    def test_existing_gate_service_selected_only_for_exact_new_singleton(self):
        source = ast.parse((ROOT / "scripts/ci_environment.py").read_text())
        call = next(
            n
            for n in ast.walk(source)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "compose_profile"
        )
        expression = next(
            k.value for k in call.keywords if k.arg == "rust_owned_send_gate"
        )
        expression = compile(ast.Expression(expression), "exact-profile-gate", "eval")
        for selected in (
            [m.NEW_CHAT_SPEC],
            [m.STARTUP_SPEC],
            [m.FIRST_SESSION_SPEC],
            [m.NATIVE_RECOVERY_SPEC],
            [m.NEW_CHAT_SPEC, m.STARTUP_SPEC],
        ):
            self.assertEqual(
                eval(expression, {"selected": selected}), selected == [m.NEW_CHAT_SPEC]
            )
        self.assertTrue(
            eval(
                expression, {"selected": ["rust-core-production-saved-session.spec.ts"]}
            )
        )
        self.assertIn(m.NEW_CHAT_SPEC, environment.PRIVATE_BACKEND_SPECS)
        profile = environment.compose_profile(
            "a" * 40, ai_fixtures=True, private_backend=True, rust_owned_send_gate=True
        )
        self.assertTrue(profile["networks"]["default"]["internal"])
        self.assertEqual(
            profile["services"]["api"]["environment"]["MOCK_EXTERNAL_APIS"], "true"
        )
        self.assertEqual(
            profile["services"]["ai-worker"]["environment"][
                "OPENMATES_CI_RUST_OWNED_SEND_GATE"
            ],
            "1",
        )
        self.assertEqual(
            profile["services"]["ai-worker"]["environment"]["OPENMATES_CI_AI_FIXTURES"],
            "1",
        )
        with self.assertRaises(ValueError):
            environment.compose_profile("a" * 40, rust_owned_send_gate=True)

    def test_original_manifest_fixture_dependency_cannot_be_replaced_by_marker_or_gate(
        self,
    ):
        harness = {
            "groups": {"ai_committed_fixtures": {"specs": ["held-existing.spec.ts"]}}
        }
        with TemporaryDirectory() as directory:
            root = Path(directory)
            file = root / "scripts/ci_coverage_manifest.json"
            file.parent.mkdir(parents=True)
            file.write_text(
                json.dumps(
                    {
                        "groups": {
                            "rust_core_new_chat_send": {"specs": [m.NEW_CHAT_SPEC]}
                        }
                    }
                )
            )
            required = environment.ai_fixture_specs(harness, root)
            self.assertEqual(required, {"held-existing.spec.ts"})
            with self.assertRaises(ValueError):
                environment.compose_profile(
                    "a" * 40,
                    ai_fixtures=m.NEW_CHAT_SPEC in required,
                    private_backend=True,
                    rust_owned_send_gate=True,
                )
            file.write_text(
                json.dumps(
                    {"groups": {"ai_committed_fixtures": {"specs": [m.NEW_CHAT_SPEC]}}}
                )
            )
            required = environment.ai_fixture_specs(harness, root)
            self.assertEqual(required, {"held-existing.spec.ts", m.NEW_CHAT_SPEC})
            profile = environment.compose_profile(
                "a" * 40,
                ai_fixtures=m.NEW_CHAT_SPEC in required,
                private_backend=True,
                rust_owned_send_gate=True,
            )
            self.assertEqual(
                profile["services"]["ai-worker"]["environment"][
                    "OPENMATES_CI_RUST_OWNED_SEND_GATE"
                ],
                "1",
            )

    def test_actual_snapshot_holds_every_fixed_input_and_detects_drift(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            expected = {}
            base = {"packages/openmates-rust/Cargo.toml": "a" * 64}
            for name in m.NEW_CHAT_INPUTS | m.EXTRA_INPUTS:
                file = root / name
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(name.encode())
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
                        root, expected, metadata_profile=True, new_chat_profile=True
                    ),
                    expected,
                )
                for name in sorted(m.NEW_CHAT_INPUTS):
                    missing = dict(expected)
                    missing.pop(name)
                    with self.assertRaises(lane.sdk.Refused):
                        lane.source_snapshot(
                            root, missing, metadata_profile=True, new_chat_profile=True
                        )
                    file = root / name
                    raw = file.read_bytes()
                    file.write_bytes(raw + b"changed")
                    self.assertNotEqual(
                        lane.source_snapshot(
                            root, expected, metadata_profile=True, new_chat_profile=True
                        ),
                        expected,
                    )
                    file.write_bytes(raw)
                with self.assertRaises(lane.sdk.Refused):
                    lane.source_snapshot(root, expected, new_chat_profile=True)

    def test_actual_compiler_receipt_refuses_every_self_consistent_omitted_fixed_input(
        self,
    ):
        fixture_spec = importlib.util.spec_from_file_location(
            "new_chat_receipt_fixture", ROOT / "scripts/tests/test_ci_rust_wasm.py"
        )
        fixture = importlib.util.module_from_spec(fixture_spec)
        fixture_spec.loader.exec_module(fixture)
        _, receipt, job, kwargs = fixture.WasmReceiptTests().fixture()
        c = "snippets/openmates-browser-bindings-0123456789abcdef/inline0.js"
        r = "snippets/openmates-sdk-0123456789abcdef/inline0.js"
        n = "snippets/openmates-sdk-0123456789abcdef/src/platform/browser_metadata_native.js"
        inputs = {
            **kwargs["expected_inputs"],
            **m.SOURCE_PINS,
            **{p: "b" * 64 for p in m.NEW_CHAT_INPUTS | m.EXTRA_INPUTS},
        }
        for file in (
            m.NATIVE_SOURCE,
            m.RECOVERY_SOURCE,
            m.CRYPTO_SOURCE,
            "packages/openmates-rust/src/platform/browser_metadata_native.rs",
            "packages/openmates-rust/Cargo.toml",
        ):
            inputs[file] = lane.sdk.sha((ROOT / file).read_bytes())
        helper_spec = importlib.util.spec_from_file_location(
            "held_native_recovery_helper",
            ROOT / "scripts/tests/test_ci_native_recovery_profile.py",
        )
        helper = importlib.util.module_from_spec(helper_spec)
        helper_spec.loader.exec_module(helper)
        recovery_body = helper.recovery_body
        files = {
            "openmates_browser.js": "".join(
                "import * as import" + str(i) + ' from "./' + v + '"\n'
                for i, v in enumerate((c, r, n), 1)
            ).encode()
            + b"export default function init(){};",
            "openmates_browser_bg.wasm": fixture.WASM,
            "openmates_browser.d.ts": b"export {};",
            c: m.CRYPTO_BYTES,
            r: recovery_body(ROOT / m.RECOVERY_SOURCE),
            n: (ROOT / m.NATIVE_SOURCE).read_bytes(),
        }
        job.update(mode="e2e", specs=json.dumps([m.NEW_CHAT_SPEC]))
        receipt.update(
            runtime_profile="rust-browser-package-for-e2e",
            requestedMode="e2e",
            requestedTargets=[m.NEW_CHAT_SPEC],
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
            requestedTargets=[m.NEW_CHAT_SPEC],
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
        for name in sorted(m.NEW_CHAT_INPUTS):
            value = inputs.pop(name)
            reseal()
            self.assertFalse(
                results.valid_rust_wasm_compiler_receipt(
                    receipt, job, "f" * 40, **kwargs
                ),
                name,
            )
            inputs[name] = value
            reseal()
        kwargs["package_files"]["unknown.js"] = b"export {};"
        self.assertFalse(
            results.valid_rust_wasm_compiler_receipt(receipt, job, "f" * 40, **kwargs)
        )

    def test_malformed_containers_and_unknown_extra_titles_fail_closed(self):
        for malformed in (
            None,
            {},
            "invalid",
            [None],
            [{"specs": None}],
            [{"specs": {}}],
            [{"specs": [], "suites": None}],
        ):
            value = report()
            if isinstance(malformed, list):
                value["suites"] += malformed
            else:
                value["suites"] = malformed
            self.assertFalse(valid(value), malformed)
        value = report()
        value["suites"][0]["specs"].append(
            {
                "title": "unexpected extra case",
                "tests": [
                    {
                        "status": "expected",
                        "results": [{"status": "passed", "retry": 0}],
                    }
                ],
            }
        )
        self.assertFalse(valid(value))
        self.assertFalse(m.new_chat_targets([m.NEW_CHAT_SPEC, m.ACTIVECHAT_SPEC]))
        self.assertFalse(
            lane.production_browser_e2e_targets([m.NEW_CHAT_SPEC, m.ACTIVECHAT_SPEC])
        )

    def test_existing_closure_and_new_only_route_dependency_are_separate(self):
        self.assertEqual(len(m.ACTIVECHAT_INPUTS), 35)
        self.assertEqual(len(m.NEW_CHAT_INPUTS), 36)
        self.assertEqual(
            m.NEW_CHAT_INPUTS - m.ACTIVECHAT_INPUTS,
            {
                "frontend/apps/web_app/tests/" + m.NEW_CHAT_SPEC,
                "frontend/packages/ui/src/services/rustCore/newChatNativeRouting.ts",
            },
        )
        self.assertEqual(
            m.ACTIVECHAT_INPUTS - m.NEW_CHAT_INPUTS,
            {"frontend/apps/web_app/tests/" + m.ACTIVECHAT_SPEC},
        )
        self.assertFalse(m.activechat_targets([m.NEW_CHAT_SPEC]))
        self.assertFalse(m.new_chat_targets([m.ACTIVECHAT_SPEC]))

    def test_actual_workflow_lane_pattern_selects_production_build(self):
        """The workflow selects the lane by rust-core-* pattern; the lane script
        still refuses anything outside its closed target set."""
        import re
        import subprocess
        import yaml

        source = (ROOT / ".github/workflows/isolated-tests.yml").read_text()
        job = next(iter(yaml.safe_load(source)["jobs"].values()))
        expression = job["env"]["CI_LANE_RUST_PRODUCTION_BROWSER"]
        body = re.fullmatch(r"\$\{\{(.*)\}\}", expression.strip(), re.S).group(1)
        python = (
            body.replace("&&", " and ").replace("||", " or ")
            .replace("!contains(", "not contains(").replace("inputs.", "inputs_")
        )
        self.assertNotIn("!", python.replace("!=", ""))

        def selected(mode, specs):
            names = {
                "inputs_mode": mode,
                "inputs_specs_json": json.dumps(specs, separators=(",", ":")),
                "startsWith": str.startswith,
                "contains": lambda haystack, needle: needle in haystack,
            }
            return eval(python, {"__builtins__": {}}, names)  # noqa: S307 - closed workflow expression under test

        build = next(s for s in job["steps"] if s.get("name") == "Build local web app")["run"]
        branch = build[build.index('if [ "$CI_LANE_RUST_PRODUCTION_BROWSER" = true ]'):]
        branch = branch[: branch.index("fi ;;") + 2]
        branch = branch.replace(
            "python3 ../tooling/scripts/ci_production_rust_browser.py build", "printf reviewed"
        ).replace("pnpm --dir frontend/apps/web_app exec vite build", "printf plain")
        for mode, specs, flag, admitted in [
            ("e2e", [m.NEW_CHAT_SPEC], True, True),
            ("e2e", [m.ACTIVECHAT_SPEC], True, True),
            ("e2e", [m.NEW_CHAT_SPEC, m.ACTIVECHAT_SPEC], True, False),
            ("e2e", ["nested/" + m.NEW_CHAT_SPEC], False, False),
            ("component", [m.NEW_CHAT_SPEC], False, False),
        ]:
            self.assertIs(selected(mode, specs), flag)
            self.assertIs(bool(lane.production_browser_e2e_targets(specs)) and mode == "e2e", admitted)
            result = subprocess.run(
                ["bash", "-c", branch],
                env={"PATH": "/usr/bin:/bin", "CI_LANE_RUST_PRODUCTION_BROWSER": str(flag).lower()},
                capture_output=True, text=True, timeout=5, check=True,
            )
            self.assertEqual(result.stdout, "reviewed" if flag else "plain")

if __name__ == "__main__":
    unittest.main()
