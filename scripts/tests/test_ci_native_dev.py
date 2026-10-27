# contract-test-file: tooling
"""Pure fixtures only: never install toolchains, build Cargo, or contact services."""

import copy
from contextlib import ExitStack
import datetime as dt
import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


lane = load("scripts.ci_native_dev", "scripts/ci_native_dev.py")
coordinator = load("native_test_coordinator", "scripts/ci_coordinator.py")


def elf():
    loader = b"/lib/ld-linux-aarch64.so.1\0"
    data = bytearray(120 + len(loader))
    data[:7] = b"\x7fELF\x02\x01\x01"
    struct.pack_into("<HH", data, 16, 3, 183)
    struct.pack_into("<Q", data, 32, 64)
    struct.pack_into("<HH", data, 54, 56, 1)
    struct.pack_into("<I", data, 64, 3)
    struct.pack_into("<Q", data, 72, 120)
    struct.pack_into("<Q", data, 96, len(loader))
    data[120:] = loader
    return bytes(data)


def job():
    return {
        "id": "a" * 64,
        "token": "ci-" + "b" * 32,
        "source": "c" * 40,
        "run_id": "123",
        "mode": lane.TARGET,
        "specs": json.dumps([lane.TARGET]),
    }


SUPERVISOR_BYTES = b"supervisor-fixture"
SUPERVISOR_SHA = lane.sdk.sha(SUPERVISOR_BYTES)


def isolation_fixture(sandbox=Path("/tmp/openmates-native-dev-" + "a" * 32)):
    toolbin = sandbox / "rustup/toolchains" / (lane.VERSION + "-" + lane.TRIPLE) / "bin"
    tools = {
        name: {
            "path": str(toolbin / name),
            "sha256": "e" * 64,
            "bytes": 256,
            "identity": [1, 2, 0o100555, 0, 0, 1, 256, 1, 1],
            "owner": "root-readonly",
        }
        for name in ("cargo", "rustc")
    }
    rows = []
    for index, (stage, argv) in enumerate(
        zip(
            lane.supervisor.STAGES,
            lane._commands(str(toolbin / "cargo"), str(toolbin / "rustc")),
        )
    ):
        rows.append(
            {
                "stage": stage,
                "passed": True,
                "failure": None,
                "uidEmpty": True,
                "unexpectedDescendants": False,
                "noNewPrivileges": True,
                "capabilitiesDropped": True,
                "tool": tools["rustc" if index == 0 else "cargo"],
                "argv": argv,
                "argvSha256": lane.sdk.sha(
                    json.dumps(argv, separators=(",", ":")).encode()
                ),
                "elapsedSeconds": 0.1,
            }
        )
    return {
        "schemaVersion": 2,
        "uidEmptyBeforeExport": True,
        "unexpectedDescendants": False,
        "sourceRootReadonly": True,
        "toolchainRootReadonly": True,
        "compilerIdentityHeld": True,
        "noNewPrivileges": True,
        "capabilitiesDropped": True,
        "buildUid": 999,
        "uidRemovedBeforeUpload": True,
        "binarySha256": lane.sdk.sha(elf()),
        "binaryBytes": len(elf()),
        "stages": rows,
        "tools": tools,
    }


def fixture():
    j = job()
    inputs = {root + "/Cargo.lock": "d" * 64 for root in lane.ROOTS}
    data = elf()
    sandbox = Path("/tmp/openmates-native-dev-" + "a" * 32)
    commands = [
        [
            "/usr/bin/rustup",
            "toolchain",
            "install",
            lane.VERSION,
            "--profile",
            "minimal",
            "--no-self-update",
        ],
        lane.supervisor_command("prepare", sandbox, deadline=2710),
        *[
            lane.supervisor_command("stage", sandbox, stage=stage)
            for stage in lane.supervisor.STAGES
        ],
        lane.supervisor_command("finish", sandbox),
        lane.supervisor_command("remove", sandbox),
    ]
    steps = []
    for index, (stage, argv) in enumerate(zip(lane.STAGES, commands)):
        steps.append(
            {
                "stage": stage,
                "status": "passed",
                "started": True,
                "returncode": 0,
                "terminatedReturncode": 0,
                "elapsedSeconds": 0.1,
                "argv": argv,
                "command": {
                    "tool": "rustup" if index == 0 else "native-supervisor",
                    "executableKind": "elf",
                    "admission": "strict-owner-mode",
                    "executableSha256": "e" * 64,
                    "executableBytes": 256,
                    "argvSha256": lane.sdk.sha(
                        json.dumps(argv, separators=(",", ":")).encode()
                    ),
                },
            }
        )
    receipt = {
        "schemaVersion": 2,
        "runtime_profile": lane.TARGET,
        "status": "passed",
        "code": None,
        "source_commit": j["source"],
        "source_tree": "f" * 40,
        "harness_commit": "1" * 40,
        "run_id": j["run_id"],
        "job": j["id"],
        "dispatchToken": j["token"],
        "runner": lane.RUNNER,
        "target": lane.TRIPLE,
        "toolchain": lane.VERSION,
        "inputs": inputs,
        "inputSetSha256": lane.sdk.sha(json.dumps(inputs, sort_keys=True).encode()),
        "locks": inputs.copy(),
        "binary": lane.elf_metadata(data),
        "buildLoader": {
            "path": "/usr/lib/aarch64-linux-gnu/ld-linux-aarch64.so.1",
            "sha256": "9" * 64,
            "bytes": 256,
        },
        "sourceHeld": True,
        "cleanupVerified": True,
        "compileProof": True,
        "runtimeProof": False,
        "performanceProof": False,
        "conformanceProof": False,
        "releaseProof": False,
        "publication": False,
        "services": {},
        "packages": {root: ["Cargo.lock"] for root in lane.ROOTS},
        "isolation": isolation_fixture(sandbox),
        "steps": steps,
        "rustcVersionSha256": "2" * 64,
        "supervisorSha256": SUPERVISOR_SHA,
    }
    return receipt, j, inputs, data


def validate(receipt, j, inputs, data):
    return lane.validate_result(
        receipt, j, "1" * 40, "f" * 40, inputs, data, expected_supervisor=SUPERVISOR_SHA
    )


class NativeFixtureTests(unittest.TestCase):
    def test_canonical_like_harness_imports_without_worktree_or_pythonpath_extras(self):
        # Reconstruct the published harness dependency boundary, not the current
        # test interpreter's namespace/PYTHONPATH. First reproduce absent guards,
        # then add only the two proposed trusted suppliers and require success.
        with tempfile.TemporaryDirectory() as temporary:
            harness = Path(temporary)
            scripts = harness / "scripts"
            scripts.mkdir()
            for name in (
                "ci_sdk_conformance.py",
                "ci_preparation_transport.py",
                "ci_candidate_artifact.py",
            ):
                source = Path(lane.sdk.__file__).parent / name
                shutil.copyfile(source, scripts / name)
            for name in (
                "ci_native_dev.py",
                "ci_native_supervisor.py",
                "ci_coordinator.py",
            ):
                shutil.copyfile(ROOT / "scripts" / name, scripts / name)
            code = """
import importlib, json, pathlib, sys
root = pathlib.Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root / 'scripts'))
sys.path.insert(0, str(root))
native = importlib.import_module('ci_native_dev')
coordinator = importlib.import_module('ci_coordinator')
namespaced = importlib.import_module('scripts.ci_native_dev')
modules = [native, namespaced, coordinator, native.sdk, native.transport, native.package, native.assets, native.supervisor]
assert all(pathlib.Path(module.__file__).resolve().is_relative_to(root) for module in modules)
queue = coordinator.Queue(root / 'queue.db')
job = queue.enqueue('fixture', 'c' * 40, [native.TARGET], mode=native.TARGET)
assert job['mode'] == native.TARGET
print(json.dumps(sorted({str(pathlib.Path(module.__file__).resolve().relative_to(root)) for module in modules})))
"""
            command = [sys.executable, "-I", "-S", "-c", code, str(harness)]
            env = {
                "PATH": os.defpath,
                "LANG": "C.UTF-8",
                "PYTHONDONTWRITEBYTECODE": "1",
            }
            missing = subprocess.run(
                command,
                cwd=harness,
                env=env,
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn("check_rust_cli_package", missing.stderr)
            for name in ("check_rust_cli_package.py", "sync_rust_cli_assets.py"):
                shutil.copyfile(ROOT / "scripts" / name, scripts / name)
            complete = subprocess.run(
                command,
                cwd=harness,
                env=env,
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertEqual(complete.returncode, 0, complete.stderr)
            imported = json.loads(complete.stdout)
            self.assertIn("scripts/check_rust_cli_package.py", imported)
            self.assertIn("scripts/sync_rust_cli_assets.py", imported)
            self.assertEqual(len(imported), 7)

    def test_clean_cargo_cache_is_warmed_by_locked_fetch_before_offline_lists(self):
        sandbox = Path("/tmp/openmates-native-dev-" + "a" * 32)
        commands = lane.supervisor.commands(sandbox)
        toolbin = (
            sandbox / "rustup/toolchains" / (lane.VERSION + "-" + lane.TRIPLE) / "bin"
        )
        self.assertEqual(
            commands, lane._commands(str(toolbin / "cargo"), str(toolbin / "rustc"))
        )
        graphs = {
            lane.CLI + "/Cargo.toml": {"shared-locked", "cli-locked"},
            lane.SDK + "/Cargo.toml": {"shared-locked"},
        }

        def run_clean_recipe(recipe):
            cached = set()
            checked = []
            for stage, command in recipe:
                if command[1] not in {"fetch", "package"}:
                    continue
                manifest = command[command.index("--manifest-path") + 1]
                self.assertIn("--locked", command)
                if command[1] == "fetch":
                    self.assertNotIn("--offline", command)
                    cached.update(graphs[manifest])
                else:
                    self.assertIn("--offline", command)
                    self.assertIn("--list", command)
                    if not graphs[manifest].issubset(cached):
                        raise RuntimeError(stage)
                    checked.append(stage)
            return checked

        recipe = list(zip(lane.supervisor.STAGES, commands))
        legacy = [
            (stage, command)
            for stage, command in recipe
            if not stage.endswith("-fetch")
        ]
        with self.assertRaisesRegex(RuntimeError, "cli-package-list"):
            run_clean_recipe(legacy)
        self.assertEqual(
            run_clean_recipe(recipe), ["cli-package-list", "sdk-package-list"]
        )
        self.assertEqual(
            [command[1:] for stage, command in recipe if stage.endswith("-fetch")],
            [
                ["fetch", "--locked", "--manifest-path", lane.CLI + "/Cargo.toml"],
                ["fetch", "--locked", "--manifest-path", lane.SDK + "/Cargo.toml"],
            ],
        )

    def test_receipt_requires_both_fixed_locked_fetch_stages(self):
        receipt, j, inputs, data = fixture()
        missing = copy.deepcopy(receipt)
        missing["isolation"]["stages"] = [
            row for row in missing["isolation"]["stages"] if row["stage"] != "sdk-fetch"
        ]
        with self.assertRaises(lane.sdk.Refused):
            validate(missing, j, inputs, data)
        unlocked = copy.deepcopy(receipt)
        row = next(
            row
            for row in unlocked["isolation"]["stages"]
            if row["stage"] == "native-fetch"
        )
        row["argv"].remove("--locked")
        row["argvSha256"] = lane.sdk.sha(
            json.dumps(row["argv"], separators=(",", ":")).encode()
        )
        with self.assertRaises(lane.sdk.Refused):
            validate(unlocked, j, inputs, data)

    def test_recipe_failure_diagnostics_are_closed_and_do_not_copy_error_text(self):
        self.assertEqual(
            lane.diagnostic(
                "package",
                lane.sdk.Refused("child_failed"),
                recipe_stage="cli-package-list",
            ),
            {
                "stage": "package",
                "reason": "package_command_failed",
                "recipeStage": "cli-package-list",
            },
        )
        self.assertEqual(
            lane.diagnostic(
                "fetch", lane.sdk.Refused("child_failed"), recipe_stage="native-fetch"
            ),
            {
                "stage": "fetch",
                "reason": "fetch_command_failed",
                "recipeStage": "native-fetch",
            },
        )
        result = lane.diagnostic(
            "package",
            ValueError("https://private-signed-url"),
            recipe_stage="../../private-path",
        )
        self.assertEqual(
            result, {"stage": "package", "reason": "package_check_refused"}
        )
        self.assertNotIn("private", json.dumps(result))

    def test_portable_embed_version_fixture_is_synchronized_and_packaged(self):
        target = "tests/fixtures/sdk-embed-version-content.json"
        canonical = "tests/sdk-conformance/fixtures/sdk-embed-version-content.json"
        self.assertEqual(lane.assets.FILES[target], canonical)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in set(lane.assets.FILES.values()):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(("synthetic canonical " + name).encode())
            lane.assets.synchronize(root)
            crate = root / lane.CLI
            source = crate / "src/cli/embed_commands_tests.rs"
            source.parent.mkdir(parents=True)
            names = {
                "Cargo.toml",
                "Cargo.lock",
                "README.md",
                "LICENSE",
                "NOTICE",
                "src/cli/embed_commands_tests.rs",
                target,
            }
            source.write_text(
                'include_str!("../../../../../packages/openmates-rust/tests/fixtures/sdk-embed-version-content.json");'
            )
            with self.assertRaises(lane.package.PackageInputError) as refused:
                lane.package.validate_inputs(crate, names)
            self.assertEqual(refused.exception.predicate, "unpackaged_compile_input")
            self.assertEqual(refused.exception.path, "src/cli/embed_commands_tests.rs")
            source.write_text(
                'include_str!("../../tests/fixtures/sdk-embed-version-content.json");'
            )
            lane.package.validate_inputs(crate, names)
            self.assertEqual(
                (crate / target).read_bytes(), (root / canonical).read_bytes()
            )
            with self.assertRaises(lane.package.PackageInputError):
                lane.package.validate_inputs(crate, names - {target})
            (root / canonical).write_bytes(b"changed fixture")
            with self.assertRaisesRegex(ValueError, "asset drift"):
                lane.assets.synchronize(root, check=True)

    def test_package_predicate_diagnostic_only_projects_held_source_path(self):
        path = lane.CLI + "/src/cli/embed_commands_tests.rs"
        error = lane.package.PackageInputError(
            "untrusted secret https://private-signed-url",
            "unpackaged_compile_input",
            "src/cli/embed_commands_tests.rs",
        )
        result = lane.diagnostic(
            "package",
            error,
            recipe_stage="cli-package-list",
            source_inputs={path: "a" * 64},
        )
        self.assertEqual(
            result,
            {
                "stage": "package",
                "reason": "package_check_refused",
                "recipeStage": "cli-package-list",
                "packagePredicate": "unpackaged_compile_input",
                "sourcePath": path,
            },
        )
        self.assertNotIn("secret", json.dumps(result))
        self.assertNotIn("https", json.dumps(result))
        for unsafe in ("../private-ticket", "unheld.rs", "https://private-signed-url"):
            error.path = unsafe
            result = lane.diagnostic(
                "package",
                error,
                recipe_stage="cli-package-list",
                source_inputs={path: "a" * 64},
            )
            self.assertNotIn("sourcePath", result)
        error.predicate = "arbitrary-secret"
        result = lane.diagnostic("package", error, recipe_stage="cli-package-list")
        self.assertNotIn("packagePredicate", result)

    def test_package_list_source_closure_still_refuses_unknown_or_empty_names(self):
        with tempfile.TemporaryDirectory() as temporary:
            for names, predicate in (
                (set(), "package_list_empty"),
                ({"unheld-private-value"}, "unheld_package_input"),
            ):
                with self.assertRaises(lane.package.PackageInputError) as refused:
                    lane.validate_package_inputs(Path(temporary), lane.CLI, names, {})
                self.assertEqual(refused.exception.predicate, predicate)
                self.assertEqual(refused.exception.path, "")
                result = lane.diagnostic(
                    "package",
                    refused.exception,
                    recipe_stage="cli-package-list",
                    source_inputs={},
                )
                self.assertEqual(result["packagePredicate"], predicate)
                self.assertNotIn("private-value", json.dumps(result))

    def test_exact_target_and_no_side_capabilities(self):
        lane.validate_request([lane.TARGET])
        for selection in (
            [],
            ["rust-wasm"],
            [lane.TARGET, "other"],
            ["../" + lane.TARGET],
        ):
            with self.subTest(selection=selection), self.assertRaises(lane.sdk.Refused):
                lane.validate_request(selection)
        for key in (
            "preparation",
            "runtime_seed",
            "capacity",
            "case_title",
            "proof_profile",
        ):
            with self.subTest(key=key), self.assertRaises(lane.sdk.Refused):
                lane.validate_request([lane.TARGET], **{key: "unexpected"})

    def test_coordinator_admits_single_fixed_lane_without_changing_capacity(self):
        with tempfile.TemporaryDirectory() as temporary:
            queue = coordinator.Queue(Path(temporary) / "queue.db")
            result = queue.enqueue("fixture", "c" * 40, [lane.TARGET], mode=lane.TARGET)
            self.assertEqual(result["mode"], lane.TARGET)
            self.assertEqual(coordinator.runner_class(result), "hosted")
            with self.assertRaises(lane.sdk.Refused):
                queue.enqueue(
                    "fixture", "c" * 40, [lane.TARGET, "arbitrary"], mode=lane.TARGET
                )
            with self.assertRaises((lane.sdk.Refused, ValueError)):
                coordinator.enqueue_submission(
                    queue,
                    "fixture",
                    "c" * 40,
                    [lane.TARGET],
                    lane.TARGET,
                    source_root=Path(temporary),
                    prepared_builds=True,
                )

    def test_coordinator_dispatch_passes_private_ticket_without_runner_override(self):
        j = job()
        j.update(
            candidate_base="",
            candidate_tree="",
            candidate_owner="",
            candidate_patch_sha256="",
            candidate_patch_url="",
        )
        github = coordinator.GitHub.__new__(coordinator.GitHub)
        github.root = Path("/tmp/fixture")
        github.repo = "fixture/repo"
        requests = []
        github.request = lambda endpoint, payload: requests.append((endpoint, payload))
        with patch.object(
            lane, "dispatch_ticket", return_value="fixture-private-ticket"
        ):
            github.dispatch(j)
        inputs = requests[0][1]["inputs"]
        self.assertEqual(inputs["native_dev_transport"], "fixture-private-ticket")
        self.assertEqual(inputs["mode"], lane.TARGET)
        self.assertNotIn("runner", inputs)
        self.assertNotIn("target", inputs)
        self.assertEqual(inputs["source_commit"], j["source"])

    def workflow_context_failure(self, raw_ticket="", *, markers=None, detached=1):
        # Actual run 40232803248 markers; event capabilities are replaced by inert
        # empty/invalid fixtures. No source, supplier or privileged work may start.
        source = "b924ed5c7515b8100808208f74aaebe1590d357f"
        tree = "3938ed5a85b0a789bc59c02234f918684e93a82a"
        harness = "1a68dd59ffd4d6cf2a7fa658e4d9fdbc72eaebb8"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "test-results").mkdir()
            event = root / "event.json"
            event.write_text(
                json.dumps(
                    {
                        "inputs": {
                            "mode": lane.TARGET,
                            "source_commit": source,
                            "specs_json": '["rust-native-dev"]',
                            "dispatch_token": "ci-1df043b91abf4dc88f923d08de55e1a4",
                            "native_dev_transport": raw_ticket,
                        }
                    }
                )
            )
            ambient = {
                "GITHUB_ACTIONS": "true",
                "RUNNER_ENVIRONMENT": "github-hosted",
                "RUNNER_ARCH": "ARM64",
                "OPENMATES_CI_ISOLATED": "1",
                "CI_SPECS_JSON": '["rust-native-dev"]',
                "BUILD_COMMIT_SHA": source,
                "CI_CANDIDATE_TREE": tree,
                "CI_HARNESS_COMMIT": harness,
                "GITHUB_RUN_ID": "40232803248",
                "GITHUB_EVENT_PATH": str(event),
                **(markers or {}),
            }

            def git(path, *args):
                if args == ("rev-parse", "HEAD^{tree}"):
                    return tree
                return source if path == root else harness

            with (
                patch.object(lane.platform, "machine", return_value="aarch64"),
                patch.object(lane.sdk, "git", side_effect=git),
                patch.object(
                    lane.subprocess,
                    "run",
                    return_value=SimpleNamespace(returncode=detached),
                ),
                patch.object(lane, "source_inputs_from_git") as inputs,
                patch.object(lane, "NativeCommands") as commands,
                patch.object(lane.transport, "put_file") as upload,
            ):
                results = []
                receipt = lane.run(root, results, environ=ambient)
            inputs.assert_not_called()
            commands.assert_not_called()
            upload.assert_not_called()
            self.assertFalse(receipt["compileProof"])
            self.assertEqual(receipt["status"], "failed")
            self.assertEqual(results[0]["exit_code"], 1)
            public = json.loads((root / "test-results/ci-native-dev.json").read_text())
            self.assertEqual(public["diagnostic"], receipt["diagnostic"])
            self.assertNotIn("native_dev_transport", json.dumps(public))
            return receipt, event.stat().st_mode & 0o777, public

    def test_actual_workflow_empty_transport_is_attributed_and_stays_closed(self):
        receipt, mode, _ = self.workflow_context_failure()
        self.assertEqual(receipt["code"], "transport")
        self.assertEqual(
            receipt["diagnostic"],
            {"stage": "transport", "reason": "native_transport_missing"},
        )
        self.assertEqual(mode, 0o600)

    def test_invalid_transport_diagnostics_exclude_raw_input(self):
        receipt, _, public = self.workflow_context_failure(
            "private-signed-url-not-json"
        )
        self.assertEqual(
            receipt["diagnostic"],
            {"stage": "transport", "reason": "native_transport_invalid_json"},
        )
        self.assertNotIn("private-signed-url", json.dumps(public))
        self.assertEqual(
            lane.diagnostic("transport", ValueError("private-url")),
            {"stage": "transport", "reason": "transport_rejected"},
        )

    def test_workflow_identity_predicates_remain_strict_and_attributed(self):
        for markers, detached, reason in (
            ({"BUILD_COMMIT_SHA": "0" * 40}, 1, "source_commit_mismatch"),
            ({"CI_CANDIDATE_TREE": "0" * 40}, 1, "source_tree_mismatch"),
            ({"CI_HARNESS_COMMIT": "0" * 40}, 1, "harness_commit_mismatch"),
            ({}, 0, "source_not_detached"),
        ):
            with self.subTest(reason=reason):
                receipt, _, _ = self.workflow_context_failure(
                    markers=markers, detached=detached
                )
                self.assertEqual(receipt["code"], "identity")
                self.assertEqual(
                    receipt["diagnostic"], {"stage": "identity", "reason": reason}
                )

    def test_non_arm_runner_fails_before_supplier_or_source_work(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "test-results").mkdir()
            with (
                patch.object(lane.platform, "machine", return_value="x86_64"),
                patch.object(lane, "source_inputs_from_git") as source,
                patch.object(lane, "NativeCommands") as commands,
            ):
                result = []
                receipt = lane.run(
                    root,
                    result,
                    environ={
                        "GITHUB_ACTIONS": "true",
                        "RUNNER_ENVIRONMENT": "github-hosted",
                        "OPENMATES_CI_ISOLATED": "1",
                        "RUNNER_ARCH": "X64",
                    },
                )
            source.assert_not_called()
            commands.assert_not_called()
            self.assertEqual(receipt["code"], "admission")
            self.assertFalse(receipt["compileProof"])
            self.assertEqual(result[0]["exit_code"], 1)

    def test_exact_elf_machine_and_loader(self):
        self.assertEqual(lane.elf_metadata(elf())["target"], lane.TRIPLE)
        variants = []
        for offset, value in (
            (4, 1),
            (5, 2),
            (18, 62),
            (54, 55),
            (56, 0),
            (120, ord("x")),
        ):
            data = bytearray(elf())
            data[offset] = value
            variants.append(bytes(data))
        variants.extend((b"#!/bin/sh\n", elf()[:-1], elf() + b"x" * lane.MAX_BINARY))
        for data in variants:
            with self.subTest(prefix=data[:20]), self.assertRaises(lane.sdk.Refused):
                lane.elf_metadata(data)

    def test_result_rejects_changed_source_binary_proof_and_tool(self):
        receipt, j, inputs, data = fixture()
        self.assertTrue(validate(receipt, j, inputs, data))
        changes = {
            "source_commit": "0" * 40,
            "source_tree": "0" * 40,
            "harness_commit": "0" * 40,
            "run_id": "124",
            "job": "0" * 64,
            "runner": "ubuntu-latest",
            "toolchain": "stable",
            "runtimeProof": True,
            "releaseProof": True,
            "performanceProof": True,
            "publication": True,
            "sourceHeld": False,
            "cleanupVerified": False,
            "compileProof": False,
            "locks": {},
            "inputs": {},
        }
        for key, value in changes.items():
            broken = copy.deepcopy(receipt)
            broken[key] = value
            with self.subTest(key=key), self.assertRaises(lane.sdk.Refused):
                validate(broken, j, inputs, data)
        for mutate in (
            lambda r: r["steps"].pop(),
            lambda r: r["steps"][2]["argv"].append("--config=evil"),
            lambda r: r["steps"][1]["command"].update(executableKind="script"),
            lambda r: r["steps"][2]["argv"].__setitem__(0, "/usr/bin/cargo"),
        ):
            broken = copy.deepcopy(receipt)
            mutate(broken)
            with self.assertRaises(lane.sdk.Refused):
                validate(broken, j, inputs, data)
        with self.assertRaises(lane.sdk.Refused):
            validate(receipt, j, inputs, data + b"changed")

    def test_private_ticket_exact_inventory_paths_token_and_expiry(self):
        j = job()
        now = dt.datetime.now(dt.timezone.utc)
        calls = []

        def signer(keys, expiry):
            calls.append((keys, expiry))
            return {
                name: {
                    verb
                    + "_url": f"https://nbg1.your-objectstorage.com/{lane.transport.BUCKET_NAME}/{key}?signature=fixture-{verb}"
                    for verb in ("put", "get")
                }
                for name, key in keys.items()
            }

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ticket = json.loads(lane.dispatch_ticket(root, j, signer=signer, now=now))
            self.assertEqual(
                lane.validate_ticket(ticket, j, producer=True, now=now), ticket
            )
            lane.dispatch_ticket(root, j, signer=signer, now=now)
            self.assertEqual(len(calls), 1)
            path = root / lane.TICKET_DIR / j["id"] / (j["token"] + ".json")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            for key, value in (
                ("job", "0" * 64),
                ("token", "ci-" + "0" * 32),
                ("source", "0" * 40),
                ("expires", (now - dt.timedelta(seconds=1)).isoformat()),
            ):
                broken = copy.deepcopy(ticket)
                broken[key] = value
                with self.subTest(key=key), self.assertRaises(lane.sdk.Refused):
                    lane.validate_ticket(broken, j, producer=True, now=now)
            for url in (
                "https://evil.example/openmates?secret=fixture",
                "https://nbg1.your-objectstorage.com/wrong?x=1",
                "http://nbg1.your-objectstorage.com/path?x=1",
            ):
                broken = copy.deepcopy(ticket)
                broken["objects"]["openmates"]["put_url"] = url
                with self.assertRaises(
                    (lane.sdk.Refused, lane.transport.PreparationTransportError)
                ):
                    lane.validate_ticket(broken, j, producer=True, now=now)
            broken = copy.deepcopy(ticket)
            broken["objects"]["account.env"] = {}
            with self.assertRaises(lane.sdk.Refused):
                lane.validate_ticket(broken, j, producer=True, now=now)

    def test_mocked_retrieval_enforces_private_bytes_and_exact_provenance(self):
        receipt, j, inputs, data = fixture()
        now = dt.datetime.now(dt.timezone.utc)
        signed = {
            name: {
                verb
                + "_url": f"https://nbg1.your-objectstorage.com/{lane.transport.BUCKET_NAME}/{key}?fixture={verb}"
                for verb in ("put", "get")
            }
            for name, key in lane._object_keys(j).items()
        }
        ticket = {
            "schemaVersion": 1,
            "job": j["id"],
            "token": j["token"],
            "source": j["source"],
            "expires": (now + dt.timedelta(hours=1)).isoformat(),
            "objects": signed,
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / lane.TICKET_DIR / j["id"] / (j["token"] + ".json")
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(ticket))
            path.chmod(0o600)
            destination = root / "test-results/ci-runs" / j["id"]

            def get(url, path, limit, *, expected_size=None):
                payload = (
                    data if path.name == "openmates" else json.dumps(receipt).encode()
                )
                self.assertLessEqual(len(payload), limit)
                if expected_size is not None:
                    self.assertEqual(len(payload), expected_size)
                path.write_bytes(payload)
                path.chmod(0o600)

            with (
                patch.object(lane.transport, "get_file", get),
                patch.object(lane.sdk, "git", return_value="f" * 40),
                patch.object(lane, "source_inputs_from_git", return_value=inputs),
                patch.object(
                    lane.subprocess, "check_output", return_value=SUPERVISOR_BYTES
                ),
            ):
                result = lane.retrieve(root, j, "1" * 40, destination)
            self.assertEqual(result["coverage_scope"], "compilation-only")
            self.assertEqual(result["private_artifact"]["sha256"], lane.sdk.sha(data))
            self.assertEqual((destination / "openmates").read_bytes(), data)
            self.assertEqual((destination / "openmates").stat().st_mode & 0o777, 0o600)
            self.assertFalse(result["runtimeProof"])
            self.assertNotIn("fixture=get", (destination / "receipt.json").read_text())
            bad = copy.deepcopy(receipt)
            bad["binary"]["sha256"] = "0" * 64
            with self.assertRaises(lane.sdk.Refused):
                validate(bad, j, inputs, data)

    def test_private_export_and_workflow_have_no_public_binary(self):
        workflow = (ROOT / ".github/workflows/isolated-tests.yml").read_text()
        self.assertIn("fromJSON('[\"ubuntu-24.04-arm\"]')", workflow)
        self.assertIn("subject/test-results/ci-native-dev.json", workflow)
        self.assertNotIn("subject/test-results/native-dev/openmates", workflow)
        self.assertNotIn("upload-release-asset", workflow)
        self.assertIn("inputs.mode != 'rust-native-dev'", workflow)
        source = (ROOT / "scripts/ci_native_dev.py").read_text()
        self.assertIn('"RUSTUP_HOME": str(sandbox / "rustup")', source)
        self.assertIn('"CARGO_HOME": str(private / "cargo")', source)
        self.assertNotIn("OPENMATES_API_KEY", source)

    def producer_fixture(self, failure=None):
        # No accounts, chmod/chown of system paths, Cargo or network operations.
        j = job()
        uploads = []
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "subject"
            root.mkdir()
            (root / "test-results").mkdir()
            runner_temp = Path(temporary) / "runner"
            runner_temp.mkdir()
            loader = Path(temporary) / "loader"
            loader.write_bytes(elf())
            loader.chmod(0o700)
            before = {}
            for crate in lane.ROOTS:
                path = root / crate / "Cargo.lock"
                path.parent.mkdir(parents=True)
                path.write_bytes(b"fixture-lock")
                before[crate + "/Cargo.lock"] = lane.sdk.sha(b"fixture-lock")
            ambient = {
                "GITHUB_ACTIONS": "true",
                "RUNNER_ENVIRONMENT": "github-hosted",
                "RUNNER_ARCH": "ARM64",
                "OPENMATES_CI_ISOLATED": "1",
                "CI_SPECS_JSON": j["specs"],
                "BUILD_COMMIT_SHA": j["source"],
                "CI_CANDIDATE_TREE": "f" * 40,
                "CI_HARNESS_COMMIT": "1" * 40,
                "GITHUB_RUN_ID": j["run_id"],
                "RUNNER_TEMP": str(runner_temp),
                "CI_NATIVE_DEV_STARTED_MONOTONIC": "10",
                "CI_NATIVE_DEV_DEADLINE_MONOTONIC": "2710",
            }
            ticket = {"objects": {name: {"put_url": name} for name in lane.OBJECTS}}
            state = {}

            class FakeCommands:
                def __init__(self, work, private, env, deadline):
                    self.root, self.private, self.env, self.steps = (
                        work,
                        private,
                        env,
                        [],
                    )

                def run(self, stage, command, **kwargs):
                    self.steps.append(
                        {
                            "stage": stage,
                            "status": "passed",
                            "started": True,
                            "returncode": 0,
                            "terminatedReturncode": 0,
                            "elapsedSeconds": 0.1,
                            "argv": command,
                            "command": {
                                "tool": "rustup"
                                if stage == "rust-toolchain"
                                else "native-supervisor",
                                "executableKind": "elf",
                                "admission": "strict-owner-mode",
                                "executableSha256": "e" * 64,
                                "executableBytes": 256,
                                "argvSha256": lane.sdk.sha(
                                    json.dumps(command, separators=(",", ":")).encode()
                                ),
                            },
                        }
                    )
                    if stage != "rust-toolchain":
                        state["sandbox"] = Path(command[8])
                    if failure == "package-command" and stage == "cli-package-list":
                        self.steps[-1].update(
                            status="failed", returncode=1, terminatedReturncode=1
                        )
                        raise lane.sdk.Refused("child_failed")
                    text = ""
                    if stage == "rustc-version":
                        text = (
                            "rustc 1.98.1 (fixture)\nrelease: 1.98.1\nhost: "
                            + lane.TRIPLE
                            + "\n"
                        )
                    elif stage == "cargo-version":
                        text = "cargo 1.98.1 (fixture)\n"
                    elif "package-list" in stage:
                        text = "Cargo.lock\n"
                    elif stage == "isolation-remove":
                        import shutil

                        shutil.rmtree(state["sandbox"])
                        state["removed"] = True
                    log = self.private / (stage + ".log")
                    log.write_text(text)
                    return log

            def root_file(path, limit):
                proof = isolation_fixture(state["sandbox"])
                if failure == "compiler-replacement":
                    proof["tools"]["cargo"]["identity"][2] = 0o100755
                if path.name == "openmates":
                    return elf()
                if path.name == "final.json":
                    return json.dumps(proof).encode()
                row = next(
                    row
                    for row in proof["stages"]
                    if row["stage"] + ".json" == path.name
                )
                if failure == "detached-setsid" and row["stage"] == "native-build":
                    row["unexpectedDescendants"] = True
                    row["passed"] = False
                return json.dumps(row).encode()

            original_resolve = Path.resolve

            def resolve(path, *args, **kwargs):
                return (
                    loader
                    if str(path) == "/lib/ld-linux-aarch64.so.1"
                    else original_resolve(path, *args, **kwargs)
                )

            def git(path, *args):
                if args == ("rev-parse", "HEAD^{tree}"):
                    return "f" * 40
                return j["source"] if path == root else "1" * 40

            def upload(url, path, size):
                self.assertTrue(state.get("removed"))
                self.assertEqual(size, path.stat().st_size)
                self.assertEqual(path.stat().st_nlink, 1)
                uploads.append((url, path.read_bytes()))

            def package_check(*args):
                if failure == "package-check":
                    raise lane.package.PackageInputError(
                        "synthetic private error",
                        "unpackaged_compile_input",
                        "Cargo.lock",
                    )

            with ExitStack() as stack:
                for target, value in (
                    ("platform.machine", lambda: "aarch64"),
                    ("source_inputs_from_git", lambda *args: before),
                    ("snapshot", lambda *args: before),
                    ("event_ticket", lambda *args: (ticket, j)),
                    ("validate_manifests", lambda *args: None),
                    ("NativeCommands", FakeCommands),
                    ("root_file", root_file),
                    ("sdk.git", git),
                    ("shutil.which", lambda *args: "/usr/bin/rustup"),
                    ("time.monotonic", lambda: 20),
                    ("package.validate_inputs", package_check),
                    ("transport.put_file", upload),
                ):
                    stack.enter_context(
                        patch.object(lane, target, value)
                        if "." not in target
                        else patch("scripts.ci_native_dev." + target, value)
                    )
                stack.enter_context(
                    patch.object(
                        lane.subprocess,
                        "run",
                        return_value=type("Detached", (), {"returncode": 1})(),
                    )
                )
                stack.enter_context(patch.object(Path, "resolve", resolve))
                results = []
                receipt = lane.run(root, results, environ=ambient)
            self.assertFalse(list(runner_temp.iterdir()))
            if failure:
                self.assertEqual(receipt["status"], "failed")
                self.assertFalse(receipt["compileProof"])
                self.assertEqual(uploads, [])
            else:
                self.assertEqual(receipt["status"], "passed", receipt)
                self.assertEqual(
                    [name for name, _ in uploads], ["openmates", "build.json"]
                )
                self.assertTrue(
                    lane.validate_result(
                        receipt,
                        j,
                        "1" * 40,
                        "f" * 40,
                        before,
                        uploads[0][1],
                        expected_supervisor=lane.sdk.sha(
                            Path(lane.supervisor.__file__).read_bytes()
                        ),
                    )
                )
                public = json.loads(
                    (root / "test-results/ci-native-dev.json").read_text()
                )
                self.assertNotIn("inputs", public)
                self.assertNotIn("binary", public)
            return receipt, uploads

    def test_mocked_producer_exports_only_after_uid_and_sandbox_removal(self):
        self.producer_fixture()

    def test_package_command_failure_retains_only_closed_stage_without_upload(self):
        receipt, uploads = self.producer_fixture("package-command")
        self.assertEqual(uploads, [])
        self.assertEqual(
            receipt["diagnostic"],
            {
                "stage": "package",
                "reason": "package_command_failed",
                "recipeStage": "cli-package-list",
            },
        )

    def test_package_check_failure_is_bounded_and_prevents_upload(self):
        receipt, uploads = self.producer_fixture("package-check")
        self.assertEqual(uploads, [])
        self.assertEqual(
            receipt["diagnostic"],
            {
                "stage": "package",
                "reason": "package_check_refused",
                "recipeStage": "cli-package-list",
                "packagePredicate": "unpackaged_compile_input",
                "sourcePath": lane.CLI + "/Cargo.lock",
            },
        )
        self.assertNotIn("private error", json.dumps(receipt))

    def test_detached_setsid_descendant_prevents_proof_and_upload(self):
        self.producer_fixture("detached-setsid")

    def test_writable_or_replaced_compiler_prevents_proof_and_upload(self):
        self.producer_fixture("compiler-replacement")

    def test_uid_cleanup_covers_new_sessions_and_refuses_success(self):
        supervisor = lane.supervisor
        observations = iter([[222], []])
        killed = []
        with patch.object(supervisor, "reap", lambda: None):
            cleanup = supervisor.stop_uid(
                999,
                clock=lambda: 0,
                sleep=lambda _: None,
                observe=lambda uid: next(observations),
                kill=lambda pid, sig: killed.append(pid),
            )
        self.assertEqual(killed, [222])
        self.assertEqual(cleanup, {"empty": True, "unexpectedDescendants": True})
        with self.assertRaises(supervisor.Refused):
            supervisor.require_no_escape(cleanup)
        # Session IDs do not affect UID discovery; a changed real/saved/fs UID is
        # still selected even if the effective UID differs.
        self.assertIn(
            999,
            supervisor.process_uid_ids(
                "Name:\tsetsid-peer\nUid:\t999\t1000\t999\t999\n"
            ),
        )

    def test_supervisor_rejects_replaced_compiler_before_launch(self):
        supervisor = lane.supervisor
        sandbox = Path("/tmp/openmates-native-dev-" + "a" * 32)
        proof = isolation_fixture(sandbox)
        value = {
            "finished": False,
            "stages": [],
            "protected": {},
            "uid": 999,
            "gid": 999,
            "tools": proof["tools"],
        }
        changed = {**proof["tools"]["rustc"], "sha256": "0" * 64}
        with (
            patch.object(supervisor, "state", return_value=value),
            patch.object(supervisor, "protected_snapshot", return_value={}),
            patch.object(
                supervisor,
                "stop_uid",
                return_value={"empty": True, "unexpectedDescendants": False},
            ),
            patch.object(supervisor, "tool_identity", return_value=changed),
            patch.object(supervisor.subprocess, "Popen") as child,
        ):
            with self.assertRaisesRegex(supervisor.Refused, "compiler-replaced"):
                supervisor.run_stage(sandbox, "rustc-version")
            child.assert_not_called()

    def test_supervisor_detects_setsid_escape_and_scrubs_capabilities(self):
        supervisor = lane.supervisor
        sandbox = Path("/tmp/openmates-native-dev-" + "a" * 32)
        proof = isolation_fixture(sandbox)
        value = {
            "finished": False,
            "stages": [],
            "protected": {},
            "uid": 999,
            "gid": 999,
            "tools": proof["tools"],
            "deadline": 3000,
        }
        clean = {"empty": True, "unexpectedDescendants": False}
        escaped = {"empty": True, "unexpectedDescendants": True}
        child = SimpleNamespace(poll=lambda: 0, returncode=0)
        writes = []
        with (
            patch.object(supervisor, "state", return_value=value),
            patch.object(supervisor, "protected_snapshot", return_value={}),
            patch.object(supervisor, "stop_uid", side_effect=[clean, escaped, clean]),
            patch.object(
                supervisor, "tool_identity", return_value=proof["tools"]["rustc"]
            ),
            patch.object(supervisor.subprocess, "Popen", return_value=child) as launch,
            patch.object(supervisor.resource, "setrlimit"),
            patch.object(
                supervisor.ctypes,
                "CDLL",
                return_value=SimpleNamespace(prctl=lambda *args: 0),
            ),
            patch.object(
                supervisor, "write", side_effect=lambda *args: writes.append(args)
            ),
        ):
            with self.assertRaisesRegex(supervisor.Refused, "escaped-descendant"):
                supervisor.run_stage(sandbox, "rustc-version")
        record = writes[0][1]
        self.assertFalse(record["passed"])
        self.assertTrue(record["unexpectedDescendants"])
        argv = launch.call_args.args[0]
        env = launch.call_args.kwargs["env"]
        self.assertIn("--no-new-privs", argv)
        self.assertIn("--bounding-set=-all", argv)
        self.assertNotIn("GITHUB_EVENT_PATH", env)
        self.assertNotIn("GH_TOKEN", env)
        self.assertNotIn("native_dev_transport", env)
        self.assertNotIn("preparation_transport", env)
        self.assertEqual(env["RUSTC"], proof["tools"]["rustc"]["path"])

    def test_supervisor_refuses_build_uid_owned_compiler_file(self):
        supervisor = lane.supervisor
        with tempfile.TemporaryDirectory() as temporary:
            sandbox = Path(temporary)
            path = (
                sandbox
                / "rustup/toolchains"
                / (lane.VERSION + "-" + lane.TRIPLE)
                / "bin/rustc"
            )
            path.parent.mkdir(parents=True)
            path.write_bytes(elf())
            path.chmod(0o755)
            # Test-owned file is deliberately writable and never chowned.
            with self.assertRaisesRegex(supervisor.Refused, "compiler-writable"):
                supervisor.tool_identity(path, sandbox)

    def test_retokenized_attempts_have_distinct_object_and_ticket_namespaces(self):
        first = job()
        second = {**first, "token": "ci-" + "8" * 32}
        self.assertNotEqual(lane._object_keys(first), lane._object_keys(second))
        self.assertTrue(
            all(first["token"] in key for key in lane._object_keys(first).values())
        )
        with tempfile.TemporaryDirectory() as temporary:

            def signer(keys, expiry):
                return {
                    name: {
                        verb
                        + "_url": f"https://nbg1.your-objectstorage.com/{lane.transport.BUCKET_NAME}/{key}?fixture={verb}"
                        for verb in ("put", "get")
                    }
                    for name, key in keys.items()
                }

            lane.dispatch_ticket(Path(temporary), first, signer=signer)
            lane.dispatch_ticket(Path(temporary), second, signer=signer)
            paths = list(
                (Path(temporary) / lane.TICKET_DIR / first["id"]).glob("*.json")
            )
            self.assertEqual(len(paths), 2)

    def test_source_allowlist_excludes_cargo_config_and_account_files(self):
        for name in (
            lane.CLI + "/src/main.rs",
            lane.SDK + "/src/lib.rs",
            lane.CLI + "/assets/selfhost/Caddyfile",
        ):
            self.assertTrue(lane.owned(name))
        for name in (
            lane.CLI + "/.cargo/config.toml",
            lane.CLI + "/.env",
            lane.CLI + "/target/release/openmates",
            lane.CLI + "/build.rs",
            ".auth/account.json",
        ):
            self.assertFalse(lane.owned(name))


if __name__ == "__main__":
    unittest.main()
