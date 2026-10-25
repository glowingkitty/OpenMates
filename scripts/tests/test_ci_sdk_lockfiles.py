# contract-test-file: tooling
"""Pure unit/AST coverage; no Cargo, network, runner mutation or CI dispatch."""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]

def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name.rsplit(".", 1)[-1] + ".py"))
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value

lane = module("scripts.ci_sdk_lockfiles")
spec = importlib.util.spec_from_file_location("lock_results", ROOT / "scripts/ci_results.py")
retrieval = importlib.util.module_from_spec(spec)
spec.loader.exec_module(retrieval)


class LockPreparationTests(unittest.TestCase):
    def fixture(self, browser_lock=False):
        inputs = {root + "/Cargo.toml": "a" * 64 for root in lane.ROOTS}
        inputs.update({name: "b" * 64 for name in lane.ORIGINAL_LOCKS})
        if browser_lock:
            inputs[lane.LOCKS[-1]] = "a" * 64
        outputs = {name: b'version = 4\n[[package]]\nname = "openmates-sdk"\nversion = "0.1.0"\n' for name in lane.LOCKS}
        steps = []
        argv = [["rustup", "toolchain", "install", "1.98.1", "--profile", "minimal"], *lane.commands()]
        for index, (stage, command) in enumerate(zip(["rust-toolchain", *lane.STAGES], argv)):
            steps.append({"stage": stage, "status": "passed", "started": True, "returncode": 0,
                          "terminatedReturncode": 0, "elapsedSeconds": 1,
                          "command": {"tool": "rustup" if index == 0 else "cargo", "admission": "strict-owner-mode",
                                      "entryPackage": None, "argvSha256": hashlib.sha256(json.dumps(command, separators=(",", ":")).encode()).hexdigest(),
                                      "executableSha256": "c" * 64, "executableBytes": 100, "executableKind": "elf"}})
        job = {"source": "d" * 40, "run_id": 123, "mode": "sdk-lockfiles", "specs": '["sdk-lockfiles"]'}
        report = {"runtime_profile": "sdk-lockfiles", "results": [{"suite": "sdk-lockfiles", "exit_code": 0, "failure_code": None}]}
        receipt = {"schemaVersion": 1, "runtime_profile": "sdk-lockfiles", "status": "passed", "code": None,
                   "source_commit": job["source"], "source_tree": "e" * 40, "harness_commit": "f" * 40,
                   "run_id": "123", "conformanceProof": False, "releaseProof": False, "publication": False,
                   "services": {}, "cleanupVerified": True, "sourceHeld": True, "inputs": inputs,
                   "inputSetSha256": hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest(),
                   "originalLocks": {name: inputs.get(name) for name in lane.LOCKS},
                   "generatedLocks": {name: lane.lock_metadata(data) for name, data in outputs.items()}, "steps": steps}
        return report, receipt, job, {"expected_inputs": inputs, "expected_tree": "e" * 40, "outputs": outputs}

    def valid(self, values):
        report, receipt, job, kwargs = values
        return retrieval.valid_sdk_lockfiles_receipt(report, receipt, job, "f" * 40, **kwargs)

    def test_exact_target_and_commands(self):
        lane.validate_targets(["sdk-lockfiles"])
        for targets in ([], ["sdk-conformance"], ["sdk-lockfiles", "sdk-lockfiles"]):
            with self.assertRaises(lane.sdk.Refused):
                lane.validate_targets(targets)
        self.assertTrue(all(command[2] == "update" and command[-2:] == ["-p", "openmates-sdk"] for command in lane.commands()[:3]))
        self.assertEqual(lane.commands()[-1][2], "generate-lockfile")
        self.assertTrue(all(command[1] == "+1.98.1" for command in lane.commands()))

    def test_source_scope_excludes_state_and_configuration(self):
        for name in (".cargo/config.toml", "backend/apps/secrets.json", "packages/openmates-rust/.env",
                     "packages/openmates-rust/target/file.rs", "packages/openmates-rust/state.json"):
            self.assertFalse(lane.owned(name), name)
        self.assertTrue(lane.owned(lane.ROOTS[-1] + "/src/lib.rs"))

    def test_valid_receipt(self):
        self.assertTrue(self.valid(self.fixture()))

    def test_receipt_identity_and_proof_tampering(self):
        for key, value in (("source_commit", "0" * 40), ("source_tree", "0" * 40), ("harness_commit", "0" * 40),
                           ("run_id", "124"), ("sourceHeld", False), ("cleanupVerified", False),
                           ("conformanceProof", True), ("releaseProof", True), ("originalLocks", {}), ("inputs", {})):
            values = self.fixture()
            values[1][key] = value
            self.assertFalse(self.valid(values), key)

    def test_outputs_missing_extra_or_tampered(self):
        for action in ("missing", "extra", "tamper"):
            values = self.fixture()
            outputs = values[3]["outputs"]
            if action == "missing":
                outputs.pop(lane.LOCKS[-1])
            elif action == "extra":
                outputs["other/Cargo.lock"] = b"secret"
            else:
                outputs[lane.LOCKS[0]] += b"# different\n"
            self.assertFalse(self.valid(values), action)

    def test_unbound_browser_lock_input_tampering_is_refused(self):
        values = self.fixture()
        values[3]["expected_inputs"][lane.LOCKS[-1]] = "a" * 64
        self.assertFalse(self.valid(values))

    def test_existing_browser_lock_receipt_is_bound_and_preserved(self):
        values = self.fixture(browser_lock=True)
        self.assertTrue(self.valid(values))
        self.assertEqual(values[1]["originalLocks"][lane.LOCKS[-1]], values[3]["expected_inputs"][lane.LOCKS[-1]])
        for value in (None, "0" * 64):
            changed = self.fixture(browser_lock=True)
            changed[1]["originalLocks"][lane.LOCKS[-1]] = value
            self.assertFalse(self.valid(changed))
        changed = self.fixture(browser_lock=True)
        changed[1]["sourceHeld"] = False
        self.assertFalse(self.valid(changed))

    def test_three_original_locks_remain_mandatory_with_or_without_browser(self):
        for browser_lock in (False, True):
            for missing in lane.ORIGINAL_LOCKS:
                values = self.fixture(browser_lock=browser_lock)
                inputs = values[3]["expected_inputs"]
                del inputs[missing]
                values[1]["inputs"] = inputs
                values[1]["inputSetSha256"] = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
                values[1]["originalLocks"][missing] = None
                self.assertFalse(self.valid(values), (browser_lock, missing))

    def test_command_identity_and_cleanup_tampering(self):
        for key, value in (("argvSha256", "0" * 64), ("tool", "node"), ("admission", "unchecked"), ("executableSha256", "bad")):
            values = self.fixture()
            values[1]["steps"][1]["command"][key] = value
            self.assertFalse(self.valid(values), key)
        values = self.fixture()
        values[1]["steps"][1]["terminatedReturncode"] = -9
        self.assertFalse(self.valid(values))

    def test_seed_case_capacity_and_preparation_refused(self):
        for key in ("preparation_id", "prepared_run_id", "runtime_seed", "capacity_configuration", "case_title"):
            values = self.fixture()
            values[2][key] = "unexpected"
            self.assertFalse(self.valid(values), key)

    def test_managed_workflow_avoids_node_browser_services(self):
        import yaml
        workflow = yaml.safe_load((ROOT / ".github/workflows/isolated-tests.yml").read_text())
        steps = workflow["jobs"]["isolated"]["steps"] if "isolated" in workflow["jobs"] else next(iter(workflow["jobs"].values()))["steps"]
        for step in steps:
            description = step.get("name", "") + " " + step.get("uses", "")
            if any(word in description for word in ("Node", "setup-node", "pnpm/action", "Install workspace dependencies")):
                if "cleanup" not in step.get("run", ""):
                    self.assertIn("inputs.mode != 'sdk-lockfiles'", step.get("if", ""), description)
        clock = next(step for step in steps if step.get("name") == "Start bounded SDK lock preparation clock")
        self.assertIn("started + 1200", clock["run"])
        install_browser = next(step for step in steps if step.get("name") == "Install browser")
        self.assertNotIn("sdk-lockfiles", install_browser["if"])
        upload = next(step for step in steps if step.get("uses") == "actions/upload-artifact@v4")
        self.assertNotIn("sdk-lockfiles/**", upload["with"]["path"])
        for name in lane.LOCKS:
            self.assertIn("subject/test-results/sdk-lockfiles/" + name, upload["with"]["path"])

    def test_coordinator_refuses_nonexact_and_mixed_requests_before_state(self):
        coordinator = module("scripts.ci_coordinator")
        queue = object.__new__(coordinator.Queue)
        for fields in ({"specs": []}, {"specs": ["sdk-lockfiles", "sdk-lockfiles"]},
                       {"preparation": {"id": "x"}}, {"runtime_seed_job": "x"},
                       {"capacity_configuration": {"x": 1}}, {"case_title": "x"}):
            args = {"owner": "session", "source": "a" * 40, "specs": ["sdk-lockfiles"], "mode": "sdk-lockfiles", **fields}
            with self.assertRaises(ValueError):
                queue.enqueue(**args)
        for fields in ({"prepared_builds": True}, {"runtime_seed_job": "x"},
                       {"capacity_configuration": {"x": 1}}, {"case_title": "x"}):
            with self.assertRaises(ValueError):
                coordinator.enqueue_submission(queue, "session", "a" * 40, ["sdk-lockfiles"], "sdk-lockfiles", **fields)

    def test_ast_and_no_unlock_conformance_fallback(self):
        for path in (ROOT / "scripts").glob("ci_*.py"):
            ast.parse(path.read_text())
        source = (ROOT / "scripts/ci_run_tests.py").read_text()
        self.assertIn('elif mode == "sdk-lockfiles":', source)
        self.assertIn('run(ROOT, results, pinned_node(), verify_node=verify_pinned_node_runtime)', source)
        self.assertNotIn("--unlock", (ROOT / "scripts/ci_sdk_lockfiles.py").read_text())

class LockRunTests(unittest.TestCase):
    def execute(self, scenario="success"):
        from contextlib import ExitStack
        from tempfile import TemporaryDirectory
        from types import SimpleNamespace
        from unittest.mock import patch
        import time
        with TemporaryDirectory() as directory, ExitStack() as stack:
            base = Path(directory)
            subject, runtime = base / "subject", base / "runner"
            subject.mkdir()
            runtime.mkdir()
            (subject / "test-results").mkdir()
            lock = b'version = 4\n[[package]]\nname = "openmates-sdk"\nversion = "0.1.0"\n'
            for root in lane.ROOTS:
                crate = subject / root
                (crate / "src").mkdir(parents=True)
                (crate / "Cargo.toml").write_text('[package]\nname="fixture"\nversion="0.1.0"\n')
                (crate / "src" / ("main.rs" if root == lane.ROOTS[2] else "lib.rs")).write_text("// fixture\n")
            for name in (lane.LOCKS if scenario == "refresh" else lane.ORIGINAL_LOCKS):
                (subject / name).write_bytes(lock)
            before = {str(path.relative_to(subject)): lane.sdk.sha(path.read_bytes())
                      for path in subject.rglob("*") if path.is_file()}
            source, tree, harness = "a" * 40, "b" * 40, "c" * 40
            start = time.monotonic() - (lane.BUDGET + 1 if scenario == "expired" else 0)
            ambient = {"GITHUB_ACTIONS": "true", "RUNNER_ENVIRONMENT": "github-hosted", "OPENMATES_CI_ISOLATED": "1",
                       "CI_SPECS_JSON": '["sdk-lockfiles"]', "BUILD_COMMIT_SHA": source, "CI_CANDIDATE_TREE": tree,
                       "CI_HARNESS_COMMIT": harness, "GITHUB_RUN_ID": "123", "RUNNER_TEMP": str(runtime),
                       "CI_SDK_LOCKFILES_STARTED_MONOTONIC": str(start), "CI_SDK_LOCKFILES_DEADLINE_MONOTONIC": str(start + lane.BUDGET),
                       "SENTINEL_SECRET": "must-not-reach-cargo"}
            observed = []
            _, sample, _, _ = LockPreparationTests().fixture()
            class FakeCommands:
                def __init__(self, work, private, env, deadline):
                    self.work, self.private, self.steps = work, private, []
                    observed.append((work, dict(env)))
                def run(self, stage, command, **kwargs):
                    index = 0 if stage == "rust-toolchain" else lane.STAGES.index(stage) + 1
                    row = json.loads(json.dumps(sample["steps"][index]))
                    self.steps.append(row)
                    (self.private / (stage + ".log")).write_text("failed to select a version\n")
                    if scenario == "cargo" and stage == lane.STAGES[0]:
                        row.update(status="failed", returncode=1, terminatedReturncode=1)
                        raise lane.sdk.Refused("child_failed")
                    if stage in lane.STAGES:
                        name = lane.LOCKS[lane.STAGES.index(stage)]
                        (self.work / name).write_bytes(lock + b"# generated\n")
                    if scenario == "mutation" and stage == lane.STAGES[0]:
                        (subject / lane.ROOTS[0] / "src/lib.rs").write_text("// mutated\n")
            def git(root, *args):
                if root == subject:
                    return tree if args[-1] == "HEAD^{tree}" else source
                return harness
            def snapshot(root, expected):
                return {name: lane.sdk.sha((root / name).read_bytes()) for name in expected}
            stack.enter_context(patch.object(lane, "source_inputs_from_git", return_value=before))
            stack.enter_context(patch.object(lane, "snapshot", side_effect=snapshot))
            stack.enter_context(patch.object(lane.sdk, "git", side_effect=git))
            stack.enter_context(patch.object(lane.subprocess, "run", return_value=SimpleNamespace(returncode=1)))
            stack.enter_context(patch.object(lane.shutil, "which", side_effect=lambda name: "/usr/bin/" + name))
            stack.enter_context(patch.object(lane.shutil, "disk_usage", return_value=SimpleNamespace(free=lane.sdk.RESERVE * 2)))
            stack.enter_context(patch.object(lane.platform, "machine", return_value="x86_64"))
            stack.enter_context(patch.object(lane, "LockCommands", FakeCommands))
            original_write = Path.write_bytes
            def write_bytes(path, data):
                if (scenario in {"output", "artifact-cleanup"} and "sdk-lockfiles" in path.parts
                        and path.as_posix().endswith(lane.LOCKS[1])):
                    raise OSError("fixture output refusal")
                return original_write(path, data)
            stack.enter_context(patch.object(Path, "write_bytes", write_bytes))
            original_remove = lane.shutil.rmtree
            def remove(path, *args, **kwargs):
                if ((scenario == "cleanup" and Path(path).parent == runtime)
                        or (scenario == "artifact-cleanup" and Path(path).name == "sdk-lockfiles")):
                    raise OSError("fixture cleanup refusal")
                return original_remove(path, *args, **kwargs)
            stack.enter_context(patch.object(lane.shutil, "rmtree", side_effect=remove))
            if scenario == "receipt-output":
                stack.enter_context(patch.object(lane.sdk, "write", side_effect=OSError("fixture receipt refusal")))
            results = []
            receipt = lane.run(subject, results, environ=ambient)
            receipt_path = subject / "test-results/ci-sdk-lockfiles.json"
            saved = json.loads(receipt_path.read_text()) if receipt_path.exists() else None
            outputs = {name: (subject / "test-results/sdk-lockfiles" / name).read_bytes()
                       for name in lane.LOCKS if (subject / "test-results/sdk-lockfiles" / name).is_file()}
            original_held = all(lane.sdk.sha((subject / name).read_bytes()) == before[name] for name in lane.LOCKS if name in before)
            private_dirs = [path for path in runtime.iterdir() if path.name.startswith("sdk-lockfiles-") and not path.name.startswith("sdk-lockfiles-failure-")]
            # Remove mocks before TemporaryDirectory performs its own cleanup.
            stack.close()
            return receipt, saved, results, outputs, observed, original_held, private_dirs

    def test_run_success_isolated_copy_and_original_lock_preservation(self):
        receipt, saved, results, outputs, observed, original_held, private_dirs = self.execute()
        self.assertEqual(receipt["status"], "passed")
        self.assertEqual(saved, receipt)
        self.assertEqual(results[0]["exit_code"], 0)
        self.assertEqual(set(outputs), set(lane.LOCKS))
        self.assertTrue(original_held)
        self.assertEqual(private_dirs, [])
        self.assertTrue(receipt["sourceHeld"] and receipt["cleanupVerified"])
        self.assertFalse(receipt["conformanceProof"] or receipt["releaseProof"])
        work, env = observed[0]
        self.assertNotIn("SENTINEL_SECRET", env)
        self.assertNotEqual(env["HOME"], str(Path.home()))
        self.assertTrue(str(work.parent) in env["CARGO_HOME"])

    def test_run_refresh_preserves_existing_browser_lock_and_isolated_outputs(self):
        receipt, saved, results, outputs, observed, original_held, private_dirs = self.execute("refresh")
        self.assertEqual(receipt["status"], "passed")
        self.assertEqual(saved, receipt)
        self.assertEqual(results[0]["exit_code"], 0)
        self.assertEqual(set(outputs), set(lane.LOCKS))
        self.assertTrue(original_held and receipt["sourceHeld"] and receipt["cleanupVerified"])
        self.assertIsNotNone(receipt["originalLocks"][lane.LOCKS[-1]])
        self.assertNotEqual(receipt["originalLocks"][lane.LOCKS[-1]], receipt["generatedLocks"][lane.LOCKS[-1]]["sha256"])
        self.assertEqual(private_dirs, [])
        self.assertNotIn("SENTINEL_SECRET", observed[0][1])
        self.assertFalse(receipt["conformanceProof"] or receipt["releaseProof"] or receipt["publication"])

    def test_run_expired_clock_refuses_before_launch(self):
        receipt, saved, results, outputs, observed, _, _ = self.execute("expired")
        self.assertEqual((receipt["status"], receipt["code"]), ("failed", "deadline"))
        self.assertEqual(observed, [])
        self.assertEqual(outputs, {})
        self.assertEqual(results[0]["exit_code"], 1)
        self.assertEqual(saved, receipt)

    def test_run_cargo_failure_keeps_closed_diagnostics_and_finalizes(self):
        receipt, saved, results, outputs, _, original_held, private_dirs = self.execute("cargo")
        self.assertEqual(receipt["code"], "cargo")
        self.assertEqual(receipt["diagnostics"]["classification"], "version_resolution")
        self.assertFalse(receipt["diagnostics"]["rawUpload"])
        self.assertTrue(original_held and receipt["cleanupVerified"])
        self.assertEqual((outputs, private_dirs), ({}, []))
        self.assertEqual(saved, receipt)
        self.assertEqual(results[0]["exit_code"], 1)

    def test_run_source_mutation_is_failure(self):
        receipt, saved, results, outputs, _, _, _ = self.execute("mutation")
        self.assertEqual(receipt["code"], "source")
        self.assertFalse(receipt["sourceHeld"])
        self.assertEqual(outputs, {})
        self.assertEqual(saved, receipt)
        self.assertEqual(results[0]["exit_code"], 1)

    def test_run_private_cleanup_failure_finalizes_failed_receipt(self):
        receipt, saved, results, outputs, _, _, private_dirs = self.execute("cleanup")
        self.assertEqual(receipt["code"], "cleanup")
        self.assertFalse(receipt["cleanupVerified"])
        self.assertTrue(private_dirs)
        self.assertEqual(outputs, {})
        self.assertEqual(saved, receipt)
        self.assertEqual(results[0]["exit_code"], 1)

    def test_run_partial_output_failure_removes_outputs(self):
        receipt, saved, results, outputs, _, _, _ = self.execute("output")
        self.assertEqual(receipt["code"], "outputs")
        self.assertEqual(outputs, {})
        self.assertEqual(saved, receipt)
        self.assertEqual(results[0]["exit_code"], 1)

    def test_run_failed_artifact_cleanup_still_writes_receipt_and_results(self):
        receipt, saved, results, _, _, _, _ = self.execute("artifact-cleanup")
        self.assertEqual(receipt["code"], "cleanup")
        self.assertFalse(receipt["cleanupVerified"])
        self.assertEqual(saved, receipt)
        self.assertEqual(results[0]["exit_code"], 1)

    def test_run_receipt_output_failure_still_finalizes_failed_results(self):
        receipt, saved, results, _, _, _, _ = self.execute("receipt-output")
        self.assertIsNone(saved)
        self.assertEqual(receipt["code"], "outputs")
        self.assertTrue(receipt["receiptWriteFailed"])
        self.assertEqual(results[0]["exit_code"], 1)

    def test_inert_owned_process_group_deadline_terminates_and_reaps(self):
        from tempfile import TemporaryDirectory
        import os
        import time
        with TemporaryDirectory() as directory:
            private = Path(directory)
            env = {"PATH": os.defpath, "HOME": str(private)}
            runner = lane.sdk.Commands(private, private, env, time.monotonic() + 0.2)
            code = ("import os,subprocess,sys,time; "
                    "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
                    "print(str(os.getpid())+' '+str(child.pid),flush=True); time.sleep(30)")
            with self.assertRaises(lane.sdk.Refused):
                runner.run("inert-deadline", [sys.executable, "-c", code], seconds=5)
            row = runner.steps[0]
            self.assertTrue(row["started"])
            self.assertNotEqual(row["terminatedReturncode"], 0)
            parent, child = map(int, (private / "inert-deadline.log").read_text().split())
            self.assertFalse(Path("/proc", str(parent)).exists(), "owned direct child must be reaped")
            child_stat = Path("/proc", str(child), "stat")
            if child_stat.exists():
                self.assertEqual(child_stat.read_text().split(") ", 1)[1].split()[0], "Z", "owned descendant must not remain live")






class LockGitSourceTests(unittest.TestCase):
    def inputs(self, browser_lock, missing=None, browser_mode="100644", browser_kind="blob"):
        from types import SimpleNamespace
        from unittest.mock import patch
        names = [root + "/Cargo.toml" for root in lane.ROOTS]
        names += [root + ("/src/main.rs" if root == lane.ROOTS[2] else "/src/lib.rs") for root in lane.ROOTS]
        names += list(lane.LOCKS if browser_lock else lane.ORIGINAL_LOCKS)
        if missing in names:
            names.remove(missing)
        rows = [(name, hashlib.sha1(name.encode()).hexdigest(), name.encode()) for name in sorted(names)]
        listing = b"".join(((browser_mode if name == lane.LOCKS[-1] else "100644") + " "
                           + (browser_kind if name == lane.LOCKS[-1] else "blob") + " " + oid
                           + "\t" + name).encode() + b"\0" for name, oid, _ in rows)
        def run(command, **kwargs):
            self.assertEqual(kwargs["input"], "".join(oid + "\n" for _, oid, _ in rows).encode())
            body = b"".join((oid + " blob " + str(len(raw)) + "\n").encode()
                            + (raw + b"\n" if command[-1] == "--batch" else b"") for _, oid, raw in rows)
            return SimpleNamespace(stdout=body)
        with patch.object(lane.subprocess, "check_output", return_value=listing), patch.object(lane.subprocess, "run", side_effect=run):
            return lane.source_inputs_from_git(Path("/inert-subject"), "a" * 40)

    def test_initial_missing_browser_and_refresh_present_browser_sources_are_accepted(self):
        for browser_lock in (False, True):
            inputs = self.inputs(browser_lock)
            self.assertTrue(all(name in inputs for name in lane.ORIGINAL_LOCKS))
            self.assertEqual(lane.LOCKS[-1] in inputs, browser_lock)
            if browser_lock:
                self.assertEqual(inputs[lane.LOCKS[-1]], lane.sdk.sha(lane.LOCKS[-1].encode()))

    def test_missing_mandatory_lock_refused_for_both_source_shapes(self):
        for browser_lock in (False, True):
            for missing in lane.ORIGINAL_LOCKS:
                with self.subTest(browser_lock=browser_lock, missing=missing), self.assertRaises(lane.sdk.Refused):
                    self.inputs(browser_lock, missing=missing)

    def test_optional_browser_lock_still_requires_regular_blob(self):
        for mode, kind in (("120000", "blob"), ("160000", "commit"), ("100644", "tree")):
            with self.subTest(mode=mode, kind=kind), self.assertRaises(lane.sdk.Refused):
                self.inputs(True, browser_mode=mode, browser_kind=kind)


if __name__ == "__main__":
    unittest.main()
