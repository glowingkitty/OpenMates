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


def install_bindgen_fixture(private, work, executable=b"inert fixture binary"):
    binary = work / ".ci-bindgen/bin/wasm-bindgen"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(executable)
    binary.chmod(0o700)
    package = private / "cargo/registry/src/inert-index/wasm-bindgen-cli-0.2.129"
    package.mkdir(parents=True)
    (package / "Cargo.toml").write_text('[package]\nname="wasm-bindgen-cli"\nversion="0.2.129"\n')
    (package / "Cargo.lock").write_text('version=4\n[[package]]\nname="wasm-bindgen-cli"\nversion="0.2.129"\n')
    archive = private / "cargo/registry/cache/inert-index/wasm-bindgen-cli-0.2.129.crate"
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b"synthetic published crate fixture")
    (package / ".cargo-checksum.json").write_text(json.dumps({"package": hashlib.sha256(archive.read_bytes()).hexdigest()}))
    return binary


class WasmReceiptTests(unittest.TestCase):
    def fixture(self):
        inputs = {root + "/Cargo.toml": "a" * 64 for root in lane.ROOTS}
        inputs.update({name: "b" * 64 for name in lane.LOCKS})
        steps = [{"stage": stage, "status": "passed", "started": True, "returncode": 0,
                  "terminatedReturncode": 0, "elapsedSeconds": 1,
                  "command": {"tool": "cargo" if index in {2, 3} else "wasm-bindgen" if index in {4, 5} else "rustup", "admission": "strict-owner-mode",
                              "entryPackage": None, "argvSha256": hashlib.sha256(json.dumps(command, separators=(",", ":")).encode()).hexdigest(),
                              "executableSha256": "c" * 64, "executableBytes": 100, "executableKind": "elf"}}
                 for index, (stage, command) in enumerate(zip(lane.STAGES, lane.commands()))]
        job = {"source": "d" * 40, "run_id": 123, "mode": "rust-wasm", "specs": '["rust-wasm"]'}
        report = {"runtime_profile": "rust-wasm", "results": [{"suite": "rust-wasm", "exit_code": 0, "failure_code": None}]}
        receipt = {"schemaVersion": 1, "runtime_profile": "rust-wasm", "status": "passed", "code": None,
                   "source_commit": job["source"], "source_tree": "e" * 40, "harness_commit": "f" * 40, "run_id": "123",
                   "compilationProof": True, "packagingProof": True, "browserRuntimeProof": False, "conformanceProof": False, "releaseProof": False,
                   "publication": False, "services": {}, "cleanupVerified": True, "sourceHeld": True, "inputs": inputs,
                   "requestedMode": "rust-wasm", "requestedTargets": ["rust-wasm"],
                   "inputSetSha256": hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest(),
                   "locks": {name: inputs[name] for name in lane.LOCKS}, "artifact": lane.wasm_metadata(WASM), "steps": steps}
        files = {lane.PACKAGE_FILES[0]: b"export default function init() {}", lane.PACKAGE_FILES[1]: WASM,
                 lane.PACKAGE_FILES[2]: b"export default function init(): Promise<void>;"}
        rows = [{"path": name, "sha256": hashlib.sha256(data).hexdigest(), "rawBytes": len(data)} for name, data in sorted(files.items())]
        inventory = {"files": rows, "rawBytes": sum(len(data) for data in files.values()),
                     "inventorySha256": hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}
        provenance = {"package": "wasm-bindgen-cli", "version": lane.BINDGEN_VERSION, "registry": "crates.io",
                      "url": "https://crates.io/crates/wasm-bindgen-cli/" + lane.BINDGEN_VERSION,
                      "crateSha256": "1" * 64, "publishedCargoLockSha256": "2" * 64, "binarySha256": "c" * 64,
                      "binaryIdentity": {"device": 1, "inode": 1, "bytes": 100, "mtimeNs": 1, "ctimeNs": 1, "mode": 0o100700, "uid": 1000, "links": 1}}
        manifest = {"schemaVersion": 1, "status": "passed", "source_commit": job["source"], "source_tree": "e" * 40,
                    "harness_commit": "f" * 40, "run_id": "123", "inputs": inputs, "inputSetSha256": receipt["inputSetSha256"],
                    "locks": receipt["locks"], "target": "wasm32-unknown-unknown", "toolchain": "1.98.1",
                    "inputWasmSha256": receipt["artifact"]["sha256"], "wasmBindgenVersion": lane.BINDGEN_VERSION,
                    "toolSha256": provenance["binarySha256"], "toolProvenance": provenance, "inventory": inventory,
                    "browserRuntimeProof": False, "requestedMode": "rust-wasm", "requestedTargets": ["rust-wasm"]}
        manifest_bytes = json.dumps(manifest, sort_keys=True).encode()
        receipt["package"] = {"manifestSha256": hashlib.sha256(manifest_bytes).hexdigest(),
                              "inventorySha256": inventory["inventorySha256"], "toolProvenance": provenance}
        return report, receipt, job, {"expected_inputs": inputs, "expected_tree": "e" * 40, "artifact": WASM,
                                     "package_manifest": manifest_bytes, "package_files": files}

    def valid(self, values):
        report, receipt, job, kwargs = values
        return retrieval.valid_rust_wasm_receipt(report, receipt, job, "f" * 40, **kwargs)

    def test_exact_target_and_fixed_locked_build(self):
        lane.validate_targets(["rust-wasm"])
        for values in ([], ["sdk-conformance"], ["rust-wasm", "rust-wasm"]):
            with self.assertRaises(lane.sdk.Refused):
                lane.validate_targets(values)
        self.assertEqual(lane.commands()[2], ["cargo", "+1.98.1", "build", "--locked", "--release", "--manifest-path",
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

    def test_cargo_hardlinked_output_is_copied_to_independent_private_inode(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            release = root / "target/wasm32-unknown-unknown/release"
            deps = release / "deps"
            deps.mkdir(parents=True)
            cached = deps / "openmates_browser_bindings-hash.wasm"
            cached.write_bytes(WASM)
            artifact = release / lane.WASM_NAME
            os.link(cached, artifact)
            self.assertEqual(artifact.stat().st_nlink, 2)
            exported = root / "export"
            exported.mkdir(mode=0o700)
            destination = exported / lane.WASM_NAME
            metadata = lane.copy_compiled_wasm(artifact, destination)
            self.assertEqual(metadata, lane.wasm_metadata(WASM))
            self.assertEqual(destination.read_bytes(), WASM)
            self.assertEqual(destination.stat().st_nlink, 1)
            self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
            self.assertNotEqual(destination.stat().st_ino, artifact.stat().st_ino)
            self.assertEqual(artifact.stat().st_nlink, 2)

    def test_compiler_output_copy_rejects_symlinks_existing_aliases_and_source_mutation(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input.wasm"
            source.write_bytes(WASM)
            alias = root / "alias.wasm"
            alias.symlink_to(source)
            with self.assertRaises(lane.sdk.Refused):
                lane.copy_compiled_wasm(alias, root / "out.wasm")
            os.link(source, root / "existing.wasm")
            with self.assertRaises(FileExistsError):
                lane.copy_compiled_wasm(source, root / "existing.wasm")
            original_regular = lane.sdk.regular
            def read_and_mutate(path, *args):
                data = original_regular(path, *args)
                if path == source:
                    source.write_bytes(WASM + b"changed")
                return data
            with patch.object(lane.sdk, "regular", side_effect=read_and_mutate), self.assertRaises(lane.sdk.Refused):
                lane.copy_compiled_wasm(source, root / "changed-output.wasm")

    def test_compiler_output_copy_rejects_replacement_during_final_destination_read(self):
        for replacement in ("compiler-hardlink", "independent-inode"):
            with TemporaryDirectory() as directory:
                root = Path(directory)
                source = root / "input.wasm"
                destination = root / "output.wasm"
                source.write_bytes(WASM)
                original_regular = lane.sdk.regular
                def read_and_replace(path, *args):
                    data = original_regular(path, *args)
                    if path == destination:
                        destination.unlink()
                        if replacement == "compiler-hardlink":
                            os.link(source, destination)
                        else:
                            destination.write_bytes(WASM)
                    return data
                with patch.object(lane.sdk, "regular", side_effect=read_and_replace), self.assertRaises(lane.sdk.Refused):
                    lane.copy_compiled_wasm(source, destination)

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
    def execute(self, scenario="success", diagnostic_probe=None, browser_e2e=False):
        with TemporaryDirectory() as directory, ExitStack() as stack:
            base = Path(directory)
            subject, runtime = base / "subject", base / "runner"
            subject.mkdir()
            runtime.mkdir()
            (subject / "test-results").mkdir()
            lock = b'version = 4\n[[package]]\nname = "openmates-sdk"\nversion = "0.1.0"\n'
            lock += b'[[package]]\nname = "wasm-bindgen"\nversion = "0.2.129"\n'
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
            budget = lane.BROWSER_BUDGET if browser_e2e else lane.BUDGET
            start = time.monotonic() - (budget + 1 if scenario == "expired" else 0)
            ambient = {"GITHUB_ACTIONS": "true", "RUNNER_ENVIRONMENT": "github-hosted", "OPENMATES_CI_ISOLATED": "1",
                       "CI_SPECS_JSON": '["rust-wasm"]', "BUILD_COMMIT_SHA": source, "CI_CANDIDATE_TREE": tree,
                       "CI_HARNESS_COMMIT": harness, "GITHUB_RUN_ID": "123", "RUNNER_TEMP": str(runtime),
                       "CI_RUST_WASM_STARTED_MONOTONIC": str(start), "CI_RUST_WASM_DEADLINE_MONOTONIC": str(start + lane.BUDGET),
                       "SENTINEL_SECRET": "must-not-reach-cargo"}
            if browser_e2e:
                ambient.update(CI_TEST_MODE="e2e", CI_SPECS_JSON=json.dumps([lane.BROWSER_SPEC]),
                    CI_BROWSER_PACKAGE_STARTED_MONOTONIC=str(start), CI_BROWSER_PACKAGE_DEADLINE_MONOTONIC=str(start + budget))
            unchanged_ambient = dict(ambient)
            observed = []
            _, sample, _, _ = WasmReceiptTests().fixture()
            class FakeCommands:
                def __init__(self, work, private, env, deadline):
                    self.work, self.private, self.env, self.steps = work, private, env, []
                    observed.append((work, dict(env)))
                def run(self, stage, command, **kwargs):
                    index = lane.STAGES.index(stage)
                    row = json.loads(json.dumps(sample["steps"][index]))
                    if stage in {"bindgen-version", "bindgen-package"}:
                        binary = self.work / ".ci-bindgen/bin/wasm-bindgen"
                        row["command"].update(executableSha256=hashlib.sha256(binary.read_bytes()).hexdigest(), executableBytes=binary.stat().st_size)
                    self.steps.append(row)
                    log_path = self.private / (stage + ".log")
                    log_path.write_text("wasm-bindgen 0.2.129\n" if stage == "bindgen-version" else "failed to select a version\n")
                    if stage == "bindgen-install":
                        install_bindgen_fixture(self.private, self.work)
                    if stage == "bindgen-package":
                        generated = self.work / ".ci-packaging/pkg"
                        (generated / lane.PACKAGE_FILES[0]).write_bytes(b"export default function init() {}")
                        (generated / lane.PACKAGE_FILES[1]).write_bytes(WASM)
                        (generated / lane.PACKAGE_FILES[2]).write_bytes(b"export default function init(): Promise<void>;")
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
                    return log_path
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
            original_open = lane.os.open
            def open_file(path, flags, *args, **kwargs):
                if (scenario in {"output", "artifact-cleanup"} and "rust-wasm" in Path(path).parts
                        and Path(path).name == lane.WASM_NAME):
                    raise OSError("fixture output refusal")
                return original_open(path, flags, *args, **kwargs)
            stack.enter_context(patch.object(lane.os, "open", side_effect=open_file))
            original_remove = lane.shutil.rmtree
            def remove(path, *args, **kwargs):
                if ((scenario == "cleanup" and Path(path).parent == runtime)
                        or (scenario == "artifact-cleanup" and Path(path).name == "rust-wasm")):
                    raise OSError("fixture cleanup refusal")
                return original_remove(path, *args, **kwargs)
            stack.enter_context(patch.object(lane.shutil, "rmtree", side_effect=remove))
            if scenario == "receipt-output":
                original_json_write = lane.sdk.write
                def write_json(path, value):
                    if path.name == "ci-rust-wasm.json":
                        raise OSError("fixture receipt refusal")
                    return original_json_write(path, value)
                stack.enter_context(patch.object(lane.sdk, "write", side_effect=write_json))
            results = []
            receipt = lane.run(subject, results, environ=ambient, browser_e2e=browser_e2e)
            self.assertEqual(ambient, unchanged_ambient)
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

    def test_browser_e2e_preparation_preserves_real_selector_and_separate_deadline(self):
        captured = {}
        def probe(subject, receipt):
            captured.update(json.loads((subject / "test-results/rust-wasm/package-manifest.json").read_bytes()))
        receipt, _, _, _, _, original_held, _ = self.execute(diagnostic_probe=probe, browser_e2e=True)
        self.assertEqual(receipt["status"], "passed")
        self.assertEqual(receipt["runtime_profile"], "rust-browser-package-for-e2e")
        self.assertEqual(captured["requestedMode"], "e2e")
        self.assertEqual(captured["requestedTargets"], [lane.BROWSER_SPEC])
        self.assertTrue(original_held)
        self.assertFalse(captured["browserRuntimeProof"])
        failed = self.execute("expired", browser_e2e=True)[0]
        self.assertEqual(failed["code"], "deadline")
        self.assertFalse(failed["packagingProof"])

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
            except (FileNotFoundError, ProcessLookupError):
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


class BrowserPackagingTests(unittest.TestCase):
    def actual_producer(self, variant="valid"):
        with TemporaryDirectory() as directory:
            private = Path(directory)
            work, logs, exported = private / "source", private / "logs", private / "export"
            for folder in (work, logs, exported):
                folder.mkdir(mode=0o700)
            crate = work / lane.ROOTS[-1]
            crate.mkdir(parents=True)
            version = "0.2.128" if variant == "lock-mismatch" else lane.BINDGEN_VERSION
            (crate / "Cargo.lock").write_text('version=4\n[[package]]\nname="wasm-bindgen"\nversion="' + version + '"\n')
            artifact = private / "compiled.wasm"
            artifact.write_bytes(WASM)
            report, receipt, job, kwargs = WasmReceiptTests().fixture()
            receipt["artifact"] = lane.wasm_metadata(WASM)
            if variant == "changed-input":
                artifact.write_bytes(WASM + b"changed")
            script = ("#!" + sys.executable + "\n" +
                "import hashlib,pathlib,sys\n"
                "args=sys.argv[1:]\n"
                "if args==['--version']:\n"
                " print('wasm-bindgen " + ("0.2.128" if variant == "version-mismatch" else lane.BINDGEN_VERSION) + "');sys.exit(0)\n"
                "assert args[1:3]==['--target','web'] and args[-2:]==['--out-name','openmates_browser']\n"
                "raw=pathlib.Path(args[0]).read_bytes()\n"
                "out=pathlib.Path(args[args.index('--out-dir')+1]);out.mkdir(exist_ok=True)\n"
                "(out/'openmates_browser.js').write_text(\"export const inputSha='\"+hashlib.sha256(raw).hexdigest()+\"'; export default async function init() {}\")\n"
                "(out/'openmates_browser_bg.wasm').write_bytes(raw)\n" +
                ("" if variant == "missing-types" else "(out/'openmates_browser.d.ts').write_text('export default function init(): Promise<void>;')\n") +
                ("(out/'undeclared-helper.js').write_text('extra')\n" if variant == "extra-helper" else ""))
            installed = []
            class ProducerRunner(lane.WasmCommands):
                def run(self, stage, command, **options):
                    if stage == "bindgen-install":
                        installed.append(command)
                        install_bindgen_fixture(private, work, script.encode())
                        self.steps.append(json.loads(json.dumps(receipt["steps"][3])))
                        return logs / "bindgen-install.log"
                    result = super().run(stage, command, **options)
                    if variant == "tool-lock-tamper" and stage == "bindgen-version":
                        package = private / "cargo/registry/src/inert-index/wasm-bindgen-cli-0.2.129/Cargo.lock"
                        package.write_text(package.read_text() + "# changed after admission\n")
                    return result
            runner = ProducerRunner(work, logs, {"PATH": os.defpath, "HOME": str(private)}, time.monotonic() + 10)
            runner.steps = receipt["steps"][:3]
            if variant != "valid":
                with self.assertRaises(lane.sdk.Refused):
                    lane.produce_browser_package(runner, private, work, artifact, exported, receipt)
                if variant == "lock-mismatch":
                    self.assertEqual(installed, [])
                return
            package = lane.produce_browser_package(runner, private, work, artifact, exported, receipt)
            receipt["package"], receipt["steps"] = package, runner.steps
            manifest = (exported / "package-manifest.json").read_bytes()
            files = {path.name: path.read_bytes() for path in (exported / "package").iterdir()}
            self.assertIn(hashlib.sha256(WASM).hexdigest().encode(), files[lane.PACKAGE_FILES[0]])
            self.assertEqual(files[lane.PACKAGE_FILES[1]], WASM)
            self.assertTrue(retrieval.valid_rust_wasm_receipt(report, receipt, job, "f" * 40,
                expected_inputs=kwargs["expected_inputs"], expected_tree="e" * 40, artifact=WASM,
                package_manifest=manifest, package_files=files))
            self.assertEqual(installed, [lane.commands()[3]])
            self.assertIn("--locked", installed[0])
            self.assertEqual(json.loads(manifest)["toolProvenance"]["version"], "0.2.129")
            self.assertFalse(json.loads(manifest)["browserRuntimeProof"])
            self.assertEqual((exported / "package-manifest.json").stat().st_mode & 0o777, 0o600)

    def test_real_producer_entry_executes_inert_tool_and_consumes_actual_input_bytes(self):
        self.actual_producer()

    def test_producer_refuses_lock_version_tool_version_and_unexpected_generated_content(self):
        for variant in ("lock-mismatch", "version-mismatch", "missing-types", "extra-helper", "tool-lock-tamper", "changed-input"):
            self.actual_producer(variant)

    def test_package_manifest_identity_provenance_and_byte_forgery_are_rejected(self):
        for fault in ("missing-package", "changed-js", "extra-helper", "manifest-hash", "wrong-source", "wrong-mode", "tool-lock", "tool-binary"):
            values = WasmReceiptTests().fixture()
            report, receipt, job, kwargs = values
            if fault == "missing-package":
                kwargs["package_files"].pop(lane.PACKAGE_FILES[2])
            elif fault == "changed-js":
                kwargs["package_files"][lane.PACKAGE_FILES[0]] += b"changed"
            elif fault == "extra-helper":
                kwargs["package_files"]["helper.js"] = b"extra"
            elif fault == "manifest-hash":
                kwargs["package_manifest"] += b" "
            else:
                manifest = json.loads(kwargs["package_manifest"])
                if fault == "wrong-source":
                    manifest["source_commit"] = "0" * 40
                elif fault == "wrong-mode":
                    manifest["requestedMode"] = "e2e"
                elif fault == "tool-lock":
                    manifest["toolProvenance"]["publishedCargoLockSha256"] = "untrusted"
                else:
                    manifest["toolSha256"] = "0" * 64
                kwargs["package_manifest"] = json.dumps(manifest).encode()
                receipt["package"]["manifestSha256"] = hashlib.sha256(kwargs["package_manifest"]).hexdigest()
            self.assertFalse(retrieval.valid_rust_wasm_receipt(report, receipt, job, "f" * 40, **kwargs), fault)

    def test_same_job_manifest_uses_honest_e2e_identity_and_never_claims_browser_execution(self):
        report, receipt, job, kwargs = WasmReceiptTests().fixture()
        report["runtime_profile"] = job["mode"] = "e2e"
        job["specs"] = json.dumps([lane.BROWSER_SPEC])
        receipt.update(runtime_profile="rust-browser-package-for-e2e", requestedMode="e2e", requestedTargets=[lane.BROWSER_SPEC])
        manifest = json.loads(kwargs["package_manifest"])
        manifest.update(requestedMode="e2e", requestedTargets=[lane.BROWSER_SPEC])
        kwargs["package_manifest"] = json.dumps(manifest).encode()
        receipt["package"]["manifestSha256"] = hashlib.sha256(kwargs["package_manifest"]).hexdigest()
        self.assertTrue(retrieval.valid_rust_wasm_receipt(report, receipt, job, "f" * 40, **kwargs))
        self.assertFalse(receipt["browserRuntimeProof"])
        job["specs"] = '["other.spec.ts"]'
        self.assertFalse(retrieval.valid_rust_wasm_receipt(report, receipt, job, "f" * 40, **kwargs))

    def test_local_same_job_handoff_accepts_only_verified_fixed_package_bytes(self):
        _, receipt, _, kwargs = WasmReceiptTests().fixture()
        receipt.update(runtime_profile="rust-browser-package-for-e2e", requestedMode="e2e", requestedTargets=[lane.BROWSER_SPEC])
        manifest = json.loads(kwargs["package_manifest"])
        manifest.update(requestedMode="e2e", requestedTargets=[lane.BROWSER_SPEC])
        raw = json.dumps(manifest).encode()
        receipt["package"]["manifestSha256"] = hashlib.sha256(raw).hexdigest()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "test-results/rust-wasm"
            (folder / "package").mkdir(parents=True)
            (folder / "package-manifest.json").write_bytes(raw)
            (folder / lane.WASM_NAME).write_bytes(WASM)
            for name, data in kwargs["package_files"].items():
                (folder / "package" / name).write_bytes(data)
            env = {"CI_TEST_MODE": "e2e", "CI_SPECS_JSON": json.dumps([lane.BROWSER_SPEC]), "BUILD_COMMIT_SHA": "d" * 40,
                   "CI_CANDIDATE_TREE": "e" * 40, "GITHUB_RUN_ID": "123", "CI_HARNESS_COMMIT": "f" * 40,
                   "OPENMATES_BROWSER_PACKAGE_MANIFEST": "/untrusted/caller/path"}
            def git(_root, *args):
                return "e" * 40 if args[-1] == "HEAD^{tree}" else "d" * 40
            with patch.object(lane, "run", return_value=receipt) as producer, patch.object(lane.sdk, "git", side_effect=git), \
                    patch.object(lane, "source_inputs_from_git", return_value=kwargs["expected_inputs"]), \
                    patch.object(lane, "snapshot", return_value=kwargs["expected_inputs"]), \
                    patch.dict(sys.modules, {"scripts.ci_results": retrieval}):
                values = lane.prepare_browser_e2e_package(root, environ=env)
                producer.assert_called_once_with(root, [], environ=env, browser_e2e=True)
                self.assertEqual(values["OPENMATES_BROWSER_PACKAGE_MANIFEST"], str(folder / "package-manifest.json"))
                self.assertEqual(values["OPENMATES_BROWSER_PACKAGE_MANIFEST_SHA256"], hashlib.sha256(raw).hexdigest())
                (folder / "package" / lane.PACKAGE_FILES[0]).write_bytes(b"forged")
                with self.assertRaises(lane.sdk.Refused):
                    lane.prepare_browser_e2e_package(root, environ=env)

    def test_managed_result_retrieves_only_attested_real_package_inventory(self):
        from io import BytesIO
        import zipfile
        for fault in (None, "tampered-js", "extra-helper"):
            report, receipt, job, kwargs = WasmReceiptTests().fixture()
            report.update(source_commit=job["source"], harness_commit="f" * 40, run_id=123, success=True)
            job.update(id="managed-inert-package", state="success", url="https://github.com/org/repo/actions/runs/123")
            packed = BytesIO()
            with zipfile.ZipFile(packed, "w") as bundle:
                bundle.writestr("subject/test-results/ci-results.json", json.dumps(report))
                bundle.writestr("subject/test-results/ci-rust-wasm.json", json.dumps(receipt))
                bundle.writestr("subject/test-results/rust-wasm/" + lane.WASM_NAME, WASM)
                bundle.writestr("subject/test-results/rust-wasm/package-manifest.json", kwargs["package_manifest"])
                for name, data in kwargs["package_files"].items():
                    bundle.writestr("subject/test-results/rust-wasm/package/" + name,
                                    data + b"forged" if fault == "tampered-js" and name.endswith(".js") else data)
                if fault == "extra-helper":
                    bundle.writestr("subject/test-results/rust-wasm/package/helper.js", b"extra")
            archive = packed.getvalue()
            class GitHub:
                repo = "org/repo"
                def request(self, endpoint):
                    if endpoint.endswith("/jobs?per_page=100"):
                        return {"jobs": [{"id": 1, "labels": ["ubuntu-latest"], "runner_name": "GitHub Actions inert"}]}
                    if endpoint.endswith("/artifacts?per_page=100"):
                        return {"artifacts": [{"id": 42, "name": "isolated-test-results", "expired": False, "size_in_bytes": len(archive)}]}
                    return {"head_sha": "f" * 40}
            def git(args, **options):
                if args[1] == "show":
                    return b'version=4\n[[package]]\nname="wasm-bindgen"\nversion="0.2.129"\n'
                return "e" * 40 + "\n"
            with TemporaryDirectory() as directory, patch.object(retrieval, "download", side_effect=lambda _cmd, _root, stream: stream.write(archive)), \
                    patch.object(retrieval.shutil, "disk_usage", return_value=SimpleNamespace(free=retrieval.RESERVE * 2)), \
                    patch.object(retrieval.subprocess, "check_output", side_effect=git), \
                    patch.object(lane, "source_inputs_from_git", return_value=kwargs["expected_inputs"]):
                if fault:
                    with self.assertRaises(RuntimeError):
                        retrieval._fetch_reserved(GitHub(), job, Path(directory))
                    self.assertFalse((Path(directory) / "test-results/ci-runs/managed-inert-package").exists())
                else:
                    result = retrieval._fetch_reserved(GitHub(), job, Path(directory))
                    self.assertEqual(result["browser_package"]["status"], "verified")
                    self.assertFalse(result["browser_package"]["browserRuntimeProof"])
                    manifest_path = Path(result["directory"]) / result["browser_package"]["manifest"]
                    self.assertEqual(hashlib.sha256(manifest_path.read_bytes()).hexdigest(), result["browser_package"]["manifestSha256"])

    def test_exact_e2e_hook_clock_private_backend_and_artifact_whitelist(self):
        import yaml
        source = (ROOT / "scripts/ci_run_tests.py").read_text()
        tree = ast.parse(source)
        run = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "run_e2e")
        segment = ast.get_source_segment(source, run)
        self.assertLess(segment.index("prepare_browser_e2e_package(ROOT)"), segment.index("subprocess.Popen"))
        self.assertLess(segment.index("prepare_browser_e2e_package(ROOT)"), segment.index("provision_account"))
        self.assertIn("specs != [RUST_BROWSER_SPEC]", segment)
        self.assertNotIn('os.environ["CI_SPECS_JSON"] =', source)
        environment = (ROOT / "scripts/ci_environment.py").read_text()
        parsed = ast.parse(environment)
        private = next(node for node in parsed.body if isinstance(node, ast.Assign)
                       and any(isinstance(target, ast.Name) and target.id == "PRIVATE_BACKEND_SPECS" for target in node.targets))
        self.assertIn(lane.BROWSER_SPEC, ast.literal_eval(private.value.args[0]))
        steps = next(iter(yaml.safe_load((ROOT / ".github/workflows/isolated-tests.yml").read_text())["jobs"].values()))["steps"]
        clock = next(step for step in steps if step.get("name") == "Start bounded same-source browser package clock")
        self.assertEqual(clock["if"], "inputs.mode == 'e2e' && inputs.specs_json == '[\"rust-core-browser-session.spec.ts\"]'")
        self.assertIn("started + 1800", clock["run"])
        self.assertEqual(lane.BUDGET, 2700)
        upload = next(step for step in steps if step.get("with", {}).get("name") == "isolated-test-results")
        for name in lane.PACKAGE_FILES:
            self.assertIn("subject/test-results/rust-wasm/package/" + name, upload["with"]["path"])
        self.assertNotIn("rust-wasm/**", upload["with"]["path"])



if __name__ == "__main__":
    unittest.main()
