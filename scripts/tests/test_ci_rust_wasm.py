# contract-test-file: tooling
"""Compilation receipt and runner tests; Cargo/network are mocked throughout."""
import ast
from contextlib import ExitStack
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


lane = load("scripts.ci_rust_wasm", "ci_rust_wasm.py")
retrieval = load("wasm_results", "ci_results.py")
WASM = b"\0asm\x01\0\0\0\0\x01\0"


class WasmReceiptTests(unittest.TestCase):
    def fixture(self):
        inputs = {root + "/Cargo.toml": "a" * 64 for root in lane.ROOTS}
        inputs.update({name: "b" * 64 for name in lane.LOCKS})
        steps = [{"stage": stage, "status": "passed", "started": True, "returncode": 0,
                  "terminatedReturncode": 0, "elapsedSeconds": 1,
                  "command": {"tool": "cargo" if index == 2 else "rustup", "admission": "strict-owner-mode",
                              "entryPackage": None, "argvSha256": hashlib.sha256(json.dumps(command, separators=(",", ":")).encode()).hexdigest(),
                              "executableSha256": "c" * 64, "executableBytes": 100, "executableKind": "elf"}}
                 for index, (stage, command) in enumerate(zip(lane.STAGES, lane.commands()))]
        job = {"source": "d" * 40, "run_id": 123, "mode": "rust-wasm", "specs": '["rust-wasm"]'}
        report = {"runtime_profile": "rust-wasm", "results": [{"suite": "rust-wasm", "exit_code": 0, "failure_code": None}]}
        receipt = {"schemaVersion": 1, "runtime_profile": "rust-wasm", "status": "passed", "code": None,
                   "source_commit": job["source"], "source_tree": "e" * 40, "harness_commit": "f" * 40, "run_id": "123",
                   "compilationProof": True, "browserRuntimeProof": False, "conformanceProof": False, "releaseProof": False,
                   "publication": False, "services": {}, "cleanupVerified": True, "sourceHeld": True, "inputs": inputs,
                   "inputSetSha256": hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest(),
                   "locks": {name: inputs[name] for name in lane.LOCKS}, "artifact": lane.wasm_metadata(WASM), "steps": steps}
        return report, receipt, job, {"expected_inputs": inputs, "expected_tree": "e" * 40, "artifact": WASM}

    def valid(self, values):
        report, receipt, job, kwargs = values
        return retrieval.valid_rust_wasm_receipt(report, receipt, job, "f" * 40, **kwargs)

    def test_exact_target_and_fixed_locked_build(self):
        lane.validate_targets(["rust-wasm"])
        for values in ([], ["sdk-conformance"], ["rust-wasm", "rust-wasm"]):
            with self.assertRaises(lane.sdk.Refused):
                lane.validate_targets(values)
        self.assertEqual(lane.commands()[-1], ["cargo", "+1.98.1", "build", "--locked", "--release", "--manifest-path",
                                               "packages/openmates-browser-bindings/Cargo.toml", "--target", "wasm32-unknown-unknown", "--lib"])
        self.assertEqual(lane.commands()[1], ["rustup", "target", "add", "--toolchain", "1.98.1", "wasm32-unknown-unknown"])
        self.assertTrue(self.valid(self.fixture()))

    def test_receipt_source_identity_and_proof_forgery(self):
        for key, value in (("source_commit", "0" * 40), ("source_tree", "0" * 40), ("harness_commit", "0" * 40),
                           ("run_id", "124"), ("sourceHeld", False), ("cleanupVerified", False), ("compilationProof", False),
                           ("browserRuntimeProof", True), ("conformanceProof", True), ("releaseProof", True), ("locks", {}), ("inputs", {})):
            values = self.fixture()
            values[1][key] = value
            self.assertFalse(self.valid(values), key)

    def test_output_bytes_name_and_command_forgery(self):
        values = self.fixture()
        values[3]["artifact"] = b"not wasm"
        self.assertFalse(self.valid(values))
        for key, value in (("name", "other.wasm"), ("sha256", "0" * 64), ("bytes", 10)):
            values = self.fixture()
            values[1]["artifact"][key] = value
            self.assertFalse(self.valid(values), key)
        for key, value in (("argvSha256", "0" * 64), ("tool", "node"), ("admission", "unchecked"), ("executableSha256", "bad")):
            values = self.fixture()
            values[1]["steps"][-1]["command"][key] = value
            self.assertFalse(self.valid(values), key)
        values = self.fixture()
        values[1]["steps"][-1]["terminatedReturncode"] = -9
        self.assertFalse(self.valid(values))

    def test_all_four_pinned_locks_required(self):
        for name in lane.LOCKS:
            values = self.fixture()
            values[3]["expected_inputs"].pop(name)
            self.assertFalse(self.valid(values), name)

    def test_immutable_source_helper_requires_each_pinned_lock(self):
        names = [root + "/Cargo.toml" for root in lane.ROOTS] + list(lane.LOCKS)
        names += [root + "/src/" + ("main.rs" if root == lane.ROOTS[2] else "lib.rs") for root in lane.ROOTS]
        def attest(selected):
            data, oid = b"fixture", "a" * 40
            listing = b"\0".join(("100644 blob " + oid + "\t" + name).encode() for name in selected) + b"\0"
            check = ((oid + " blob " + str(len(data)) + "\n").encode()) * len(selected)
            batch = ((oid + " blob " + str(len(data)) + "\n").encode() + data + b"\n") * len(selected)
            with patch.object(lane.subprocess, "check_output", return_value=listing), patch.object(
                    lane.subprocess, "run", side_effect=[SimpleNamespace(stdout=check), SimpleNamespace(stdout=batch)]):
                return lane.source_inputs_from_git(Path("/unused-immutable-fixture"), "b" * 40)
        self.assertEqual(set(attest(names)), set(names))
        for lock in lane.LOCKS:
            with self.assertRaises(lane.sdk.Refused):
                attest([name for name in names if name != lock])

    def test_coordinator_refuses_mixed_requests_before_state(self):
        coordinator = load("wasm_coordinator", "ci_coordinator.py")
        queue = object.__new__(coordinator.Queue)
        for fields in ({"specs": []}, {"specs": ["rust-wasm", "rust-wasm"]}, {"preparation": {"id": "x"}},
                       {"runtime_seed_job": "x"}, {"capacity_configuration": {"x": 1}}, {"case_title": "x"}):
            with self.assertRaises(ValueError):
                queue.enqueue(**{"owner": "session", "source": "a" * 40, "specs": ["rust-wasm"], "mode": "rust-wasm", **fields})
        for fields in ({"prepared_builds": True}, {"runtime_seed_job": "x"}, {"capacity_configuration": {"x": 1}}, {"case_title": "x"}):
            with self.assertRaises(ValueError):
                coordinator.enqueue_submission(queue, "session", "a" * 40, ["rust-wasm"], "rust-wasm", **fields)
        for key in ("preparation_id", "prepared_run_id", "runtime_seed", "capacity_configuration", "case_title"):
            values = self.fixture()
            values[2][key] = "unexpected"
            self.assertFalse(self.valid(values), key)

    def test_workflow_no_node_browser_services_and_ast(self):
        import yaml
        workflow = yaml.safe_load((ROOT / ".github/workflows/isolated-tests.yml").read_text())
        steps = next(iter(workflow["jobs"].values()))["steps"]
        for step in steps:
            description = step.get("name", "") + " " + step.get("uses", "")
            if any(word in description for word in ("Node", "setup-node", "pnpm/action", "Install workspace dependencies")) and "cleanup" not in step.get("run", ""):
                self.assertIn("inputs.mode != 'rust-wasm'", step.get("if", ""), description)
        clock = next(step for step in steps if step.get("name") == "Start bounded Rust WASM compilation clock")
        self.assertIn("started + 2700", clock["run"])
        for name in ("Install browser", "Prepare isolated stack"):
            self.assertNotIn("rust-wasm", next(step for step in steps if step.get("name") == name)["if"])
        upload = next(step for step in steps if step.get("uses") == "actions/upload-artifact@v4")
        self.assertIn("subject/test-results/rust-wasm/" + lane.WASM_NAME, upload["with"]["path"])
        self.assertNotIn("rust-wasm/**", upload["with"]["path"])
        for path in (ROOT / "scripts").glob("ci_*.py"):
            ast.parse(path.read_text())


class WasmRunTests(unittest.TestCase):
    def execute(self, scenario="success", diagnostic_probe=None):
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
                (crate / "Cargo.toml").write_text('[package]\nname="openmates-browser-bindings"\nversion="0.1.0"\n')
                (crate / "src" / ("main.rs" if root == lane.ROOTS[2] else "lib.rs")).write_text("// fixture\n")
            for name in lane.LOCKS:
                (subject / name).write_bytes(lock)
            before = {str(path.relative_to(subject)): lane.sdk.sha(path.read_bytes())
                      for path in subject.rglob("*") if path.is_file()}
            source, tree, harness = "a" * 40, "b" * 40, "c" * 40
            start = time.monotonic() - (lane.BUDGET + 1 if scenario == "expired" else 0)
            ambient = {"GITHUB_ACTIONS": "true", "RUNNER_ENVIRONMENT": "github-hosted", "OPENMATES_CI_ISOLATED": "1",
                       "CI_SPECS_JSON": '["rust-wasm"]', "BUILD_COMMIT_SHA": source, "CI_CANDIDATE_TREE": tree,
                       "CI_HARNESS_COMMIT": harness, "GITHUB_RUN_ID": "123", "RUNNER_TEMP": str(runtime),
                       "CI_RUST_WASM_STARTED_MONOTONIC": str(start), "CI_RUST_WASM_DEADLINE_MONOTONIC": str(start + lane.BUDGET),
                       "SENTINEL_SECRET": "must-not-reach-cargo"}
            observed = []
            _, sample, _, _ = WasmReceiptTests().fixture()
            class FakeCommands:
                def __init__(self, work, private, env, deadline):
                    self.work, self.private, self.steps = work, private, []
                    observed.append((work, dict(env)))
                def run(self, stage, command, **kwargs):
                    index = lane.STAGES.index(stage)
                    row = json.loads(json.dumps(sample["steps"][index]))
                    self.steps.append(row)
                    (self.private / (stage + ".log")).write_text("failed to select a version\n")
                    if scenario in {"cargo", "large-cargo"} and stage == "wasm-build":
                        if scenario == "large-cargo":
                            (self.private / (stage + ".log")).write_bytes(b"x" * (lane.DIAGNOSTIC_LIMIT + 16) + b"final compiler failure\n")
                        row.update(status="failed", returncode=1, terminatedReturncode=1)
                        raise lane.sdk.Refused("child_failed")
                    if stage == "wasm-build" and scenario != "missing-output":
                        target = Path(observed[0][1]["CARGO_TARGET_DIR"]) / lane.WASM_PATH
                        target.parent.mkdir(parents=True)
                        target.write_bytes(b"invalid" if scenario == "invalid-output" else WASM)
                    if stage == "wasm-build" and scenario == "copy-lock":
                        (self.work / lane.LOCKS[0]).write_bytes(lock + b"# changed\n")
                    if scenario == "mutation" and stage == "wasm-build":
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
            stack.enter_context(patch.object(lane, "WasmCommands", FakeCommands))
            original_write = Path.write_bytes
            def write_bytes(path, data):
                if (scenario in {"output", "artifact-cleanup"} and "rust-wasm" in path.parts
                        and path.name == lane.WASM_NAME):
                    raise OSError("fixture output refusal")
                return original_write(path, data)
            stack.enter_context(patch.object(Path, "write_bytes", write_bytes))
            original_remove = lane.shutil.rmtree
            def remove(path, *args, **kwargs):
                if ((scenario == "cleanup" and Path(path).parent == runtime)
                        or (scenario == "artifact-cleanup" and Path(path).name == "rust-wasm")):
                    raise OSError("fixture cleanup refusal")
                return original_remove(path, *args, **kwargs)
            stack.enter_context(patch.object(lane.shutil, "rmtree", side_effect=remove))
            if scenario == "receipt-output":
                stack.enter_context(patch.object(lane.sdk, "write", side_effect=OSError("fixture receipt refusal")))
            results = []
            receipt = lane.run(subject, results, environ=ambient)
            receipt_path = subject / "test-results/ci-rust-wasm.json"
            saved = json.loads(receipt_path.read_text()) if receipt_path.exists() else None
            artifact = subject / "test-results/rust-wasm" / lane.WASM_NAME
            outputs = artifact.read_bytes() if artifact.is_file() else b""
            original_held = all(lane.sdk.sha((subject / name).read_bytes()) == before[name] for name in lane.LOCKS)
            private_dirs = [path for path in runtime.iterdir() if path.name.startswith("rust-wasm-") and not path.name.startswith("rust-wasm-failure-")]
            if diagnostic_probe is not None:
                diagnostic_probe(subject, receipt)
            # Remove mocks before TemporaryDirectory performs its own cleanup.
            stack.close()
            return receipt, saved, results, outputs, observed, original_held, private_dirs

    def test_success_isolated_compilation_preserves_four_source_locks(self):
        receipt, saved, results, wasm, observed, original_held, private_dirs = self.execute()
        self.assertEqual(receipt["status"], "passed")
        self.assertEqual(saved, receipt)
        self.assertTrue(receipt["compilationProof"] and receipt["sourceHeld"] and receipt["cleanupVerified"])
        self.assertFalse(receipt["browserRuntimeProof"] or receipt["conformanceProof"] or receipt["releaseProof"])
        self.assertEqual(wasm, WASM)
        self.assertEqual(results[0]["exit_code"], 0)
        self.assertTrue(original_held)
        self.assertEqual(private_dirs, [])
        work, env = observed[0]
        self.assertNotIn("SENTINEL_SECRET", env)
        self.assertNotEqual(env["HOME"], str(Path.home()))
        self.assertIn(str(work.parent), env["CARGO_HOME"])

    def test_expired_clock_refuses_before_launch(self):
        receipt, saved, results, wasm, observed, _, _ = self.execute("expired")
        self.assertEqual((receipt["status"], receipt["code"]), ("failed", "deadline"))
        self.assertFalse(receipt["compilationProof"])
        self.assertEqual((wasm, observed), (b"", []))
        self.assertEqual(saved, receipt)
        self.assertEqual(results[0]["exit_code"], 1)

    def test_compile_failure_source_mutation_and_copied_lock_mutation(self):
        for scenario, code in (("cargo", "compile"), ("mutation", "source"), ("copy-lock", "source")):
            receipt, saved, results, wasm, _, original_held, private_dirs = self.execute(scenario)
            self.assertEqual(receipt["code"], code, scenario)
            self.assertFalse(receipt["compilationProof"], scenario)
            self.assertTrue(original_held and receipt["cleanupVerified"], scenario)
            self.assertEqual((wasm, private_dirs), (b"", []), scenario)
            self.assertEqual(saved, receipt, scenario)
            self.assertEqual(results[0]["exit_code"], 1, scenario)
        self.assertFalse(self.execute("mutation")[0]["sourceHeld"])
        self.assertTrue(self.execute("copy-lock")[0]["sourceHeld"])

    def test_missing_invalid_and_write_failed_output_never_proves_compilation(self):
        for scenario in ("missing-output", "invalid-output", "output", "receipt-output"):
            receipt, saved, results, _, _, _, _ = self.execute(scenario)
            self.assertEqual(receipt["code"], "outputs", scenario)
            self.assertFalse(receipt["compilationProof"], scenario)
            self.assertEqual(results[0]["exit_code"], 1, scenario)
            if scenario == "receipt-output":
                self.assertIsNone(saved)
            else:
                self.assertEqual(saved, receipt)

    def test_private_and_failed_artifact_cleanup_still_finalize_failed_results(self):
        for scenario in ("cleanup", "artifact-cleanup"):
            receipt, saved, results, _, _, _, _ = self.execute(scenario)
            self.assertEqual(receipt["code"], "cleanup", scenario)
            self.assertFalse(receipt["cleanupVerified"] or receipt["compilationProof"], scenario)
            self.assertEqual(saved, receipt, scenario)
            self.assertEqual(results[0]["exit_code"], 1, scenario)

    def test_failed_compiler_log_is_private_bounded_and_survives_source_cleanup(self):
        for scenario in ("cargo", "large-cargo"):
            captured = {}
            def probe(subject, receipt):
                folder = subject / "test-results/ci-rust-wasm-private"
                captured["tail"] = (folder / "cargo-tail.log").read_bytes()
                captured["identity"] = (folder / "identity.json").read_bytes()
                captured["modes"] = [(folder / name).stat().st_mode & 0o777 for name in ("cargo-tail.log", "identity.json")]
            receipt, saved, results, wasm, _, _, private_dirs = self.execute(scenario, probe)
            self.assertEqual(receipt["code"], "compile")
            self.assertTrue(receipt["cleanupVerified"])
            self.assertFalse(receipt["compilationProof"])
            self.assertEqual((private_dirs, wasm), ([], b""))
            self.assertEqual(captured["modes"], [0o600, 0o600])
            self.assertLessEqual(len(captured["tail"]), lane.DIAGNOSTIC_LIMIT)
            self.assertEqual(json.loads(captured["identity"])["truncated"], scenario == "large-cargo")
            self.assertTrue(retrieval.valid_rust_wasm_diagnostic(receipt["diagnostics"], captured["identity"], captured["tail"],
                            {"source": "a" * 40, "run_id": "123"}, "c" * 40, "b" * 40))
            self.assertNotIn("final compiler failure", json.dumps(saved))
            self.assertEqual(results[0]["exit_code"], 1)

    def test_inert_owned_process_group_deadline_terminates_and_reaps(self):
        with TemporaryDirectory() as directory:
            private = Path(directory)
            runner = lane.sdk.Commands(private, private, {"PATH": os.defpath, "HOME": str(private)}, time.monotonic() + 0.2)
            code = ("import os,subprocess,sys,time; "
                    "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
                    "print(str(os.getpid())+' '+str(child.pid),flush=True); time.sleep(30)")
            with self.assertRaises(lane.sdk.Refused):
                runner.run("inert-deadline", [sys.executable, "-c", code], seconds=5)
            row = runner.steps[0]
            self.assertTrue(row["started"])
            self.assertNotEqual(row["terminatedReturncode"], 0)
            parent, child = map(int, (private / "inert-deadline.log").read_text().split())
            self.assertFalse(Path("/proc", str(parent)).exists())
            try:
                child_stat = Path("/proc", str(child), "stat").read_text()
            except FileNotFoundError:
                child_stat = None
            if child_stat is not None:
                self.assertEqual(child_stat.split(") ", 1)[1].split()[0], "Z")

class WasmDiagnosticTests(unittest.TestCase):
    def fixture(self):
        tail = b"actual compiler failure diagnostic\n"
        job, harness, tree = {"source": "a" * 40, "run_id": "123"}, "b" * 40, "c" * 40
        identity = {"schemaVersion": 1, "source_commit": job["source"], "source_tree": tree, "harness_commit": harness,
                    "run_id": "123", "stage": "wasm-build", "path": "cargo-tail.log", "bytes": len(tail),
                    "originalBytes": len(tail), "sha256": hashlib.sha256(tail).hexdigest(), "truncated": False}
        raw = (json.dumps(identity, sort_keys=True, indent=2) + "\n").encode()
        descriptor = {"artifactName": lane.DIAGNOSTIC_ARTIFACT, "identity": identity,
                      "identitySha256": hashlib.sha256(raw).hexdigest(), "publicRawUpload": False}
        return descriptor, raw, tail, job, harness, tree

    def test_private_diagnostic_identity_path_bounds_and_hash_tampering(self):
        self.assertTrue(retrieval.valid_rust_wasm_diagnostic(*self.fixture()))
        for key, value in (("source_commit", "0" * 40), ("source_tree", "0" * 40), ("harness_commit", "0" * 40),
                           ("run_id", "124"), ("path", "../cargo-tail.log"), ("bytes", 0), ("truncated", True)):
            descriptor, _, tail, job, harness, tree = self.fixture()
            descriptor["identity"][key] = value
            raw = json.dumps(descriptor["identity"]).encode()
            descriptor["identitySha256"] = hashlib.sha256(raw).hexdigest()
            self.assertFalse(retrieval.valid_rust_wasm_diagnostic(descriptor, raw, tail, job, harness, tree), key)
        descriptor, raw, tail, job, harness, tree = self.fixture()
        self.assertFalse(retrieval.valid_rust_wasm_diagnostic(descriptor, raw, tail + b"changed", job, harness, tree))
        self.assertFalse(retrieval.valid_rust_wasm_diagnostic(descriptor, raw, b"x" * (lane.DIAGNOSTIC_LIMIT + 1), job, harness, tree))
        self.assertFalse(retrieval.valid_rust_wasm_diagnostic(descriptor, raw + b" ", tail, job, harness, tree))

    def test_authenticated_private_retrieval_checks_archive_and_keeps_tail_mode_private(self):
        from io import BytesIO
        import zipfile
        descriptor, raw, tail, job, harness, tree = self.fixture()
        for variant in ("valid", "unsafe-path", "tampered-tail", "oversized", "extra"):
            packed = BytesIO()
            with zipfile.ZipFile(packed, "w") as bundle:
                bundle.writestr("identity.json", raw)
                bundle.writestr("../cargo-tail.log" if variant == "unsafe-path" else "cargo-tail.log",
                                tail + b"changed" if variant == "tampered-tail" else b"x" * (lane.DIAGNOSTIC_LIMIT + 1) if variant == "oversized" else tail)
                if variant == "extra":
                    bundle.writestr("extra.log", b"not admitted")
            archive = packed.getvalue()
            artifacts = [{"id": 42, "name": lane.DIAGNOSTIC_ARTIFACT, "expired": False, "size_in_bytes": len(archive)}]
            with TemporaryDirectory() as directory:
                folder = Path(directory)
                def download(command, root, stream, *, limit):
                    self.assertEqual(command, ["gh", "api", "repos/org/repo/actions/artifacts/42/zip"])
                    self.assertEqual(limit, 256 * 1024)
                    stream.write(archive)
                with patch.object(retrieval, "download", side_effect=download):
                    if variant != "valid":
                        with self.assertRaises(RuntimeError):
                            retrieval.fetch_rust_wasm_diagnostic(SimpleNamespace(repo="org/repo"), job, folder,
                                artifacts, descriptor, harness, tree, folder / "rust-wasm-private")
                        continue
                    result = retrieval.fetch_rust_wasm_diagnostic(SimpleNamespace(repo="org/repo"), job, folder,
                        artifacts, descriptor, harness, tree, folder / "rust-wasm-private")
                self.assertEqual(result["status"], "verified")
                self.assertEqual((folder / result["path"]).read_bytes(), tail)
                self.assertEqual((folder / result["path"]).stat().st_mode & 0o777, 0o600)
                self.assertNotIn(tail.decode().strip(), json.dumps(result))

    def test_missing_or_expired_private_artifact_is_reported_without_raw_content(self):
        descriptor, _, _, job, harness, tree = self.fixture()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for artifacts in ([], [{"name": lane.DIAGNOSTIC_ARTIFACT, "expired": True}]):
                result = retrieval.fetch_rust_wasm_diagnostic(SimpleNamespace(repo="org/repo"), job, root,
                    artifacts, descriptor, harness, tree, root / "rust-wasm-private")
                self.assertEqual(result["status"], "unavailable")
                self.assertFalse((root / "rust-wasm-private").exists())
            with self.assertRaises(RuntimeError):
                retrieval.fetch_rust_wasm_diagnostic(SimpleNamespace(repo="org/repo"), job, root,
                    [{"name": lane.DIAGNOSTIC_ARTIFACT}], None, harness, tree, root / "rust-wasm-private")

    def test_workflow_uploads_only_two_exact_private_diagnostic_files(self):
        import yaml
        steps = next(iter(yaml.safe_load((ROOT / ".github/workflows/isolated-tests.yml").read_text())["jobs"].values()))["steps"]
        private = next(step for step in steps if step.get("with", {}).get("name") == lane.DIAGNOSTIC_ARTIFACT)
        self.assertEqual(private["with"]["path"].splitlines(), [
            "subject/test-results/ci-rust-wasm-private/cargo-tail.log", "subject/test-results/ci-rust-wasm-private/identity.json"])
        public = next(step for step in steps if step.get("with", {}).get("name") == "isolated-test-results")
        self.assertNotIn("ci-rust-wasm-private", public["with"]["path"])



if __name__ == "__main__":
    unittest.main()
