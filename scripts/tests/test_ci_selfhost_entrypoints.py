# contract-test-file: tooling
"""Mock external operations while executing the real producer/queue/retrieval entrypoints."""
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

STAGED = Path(__file__).parents[1]
CANONICAL = next(parent / "scripts" for parent in STAGED.parents
                 if (parent / "scripts/ci_web_performance.py").is_file())
sys.path.insert(0, str(CANONICAL))
sys.path.insert(0, str(STAGED))


def load(name):
    spec = importlib.util.spec_from_file_location("entrypoint_" + name, STAGED / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


contract = load("ci_selfhost_contract")
sys.modules["scripts.ci_selfhost_contract"] = contract
sys.modules["ci_selfhost_contract"] = contract
coordinator = load("ci_coordinator")
runner = load("ci_run_tests")
retrieval = load("ci_results")
dispatcher = load("ci_dispatch")
SOURCE = "a" * 40
TREE = "b" * 40
HARNESS = "d" * 40


class SelfhostEntrypointTests(unittest.TestCase):
    def test_actual_queue_accepts_three_closed_hosted_jobs_rejects_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            queue = coordinator.Queue(Path(directory) / "queue.sqlite3")
            jobs = coordinator.enqueue_submission(queue, "test-owner", SOURCE, list(contract.TARGETS), "selfhost")
            self.assertEqual(len({job["id"] for job in jobs}), 3)
            self.assertEqual({json.loads(job["specs"])[0] for job in jobs}, set(contract.TARGETS))
            self.assertEqual([coordinator.runner_class(job) for job in jobs], ["hosted"] * 3)
            for target in ("invented", "selfhost-source.spec.ts"):
                with self.assertRaises(ValueError):
                    queue.enqueue("test-owner", SOURCE, [target], "selfhost")
            with self.assertRaises(ValueError):
                queue.enqueue("test-owner", SOURCE, list(contract.TARGETS), "selfhost")
            old = queue.enqueue("historical", SOURCE, ["selfhost-smoke.spec.ts"], "selfhost")
            self.assertEqual(old["mode"], "selfhost")

    def run_producer(self, mode, selection, function):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            results = root / "test-results"
            stack.enter_context(patch.object(runner, "ROOT", root))
            stack.enter_context(patch.object(runner, "RESULTS", results))
            for name in ("require_runner", "verify_pinned_node_runtime", "reject_inherited_accounts", "verify_shared_dev_rejected"):
                stack.enter_context(patch.object(runner, name))
            stack.enter_context(patch.object(runner, "configure_proof_dimensions", return_value=None))
            stack.enter_context(patch.object(runner, "pinned_node", return_value="test-node"))
            stack.enter_context(patch.object(runner.subprocess, "check_output", return_value=SOURCE))
            stack.enter_context(patch.dict(runner.os.environ, {"CI_TEST_MODE": mode, "CI_SPECS_JSON": json.dumps(selection),
                "GITHUB_RUN_ID": "123", "CI_HARNESS_COMMIT": HARNESS, "CI_CASE_TITLE": ""}))
            module_name = {"rust-wasm": "ci_rust_wasm", "sdk-lockfiles": "ci_sdk_lockfiles",
                "sdk-conformance": "ci_sdk_conformance", "selfhost": "ci_selfhost"}[mode]
            stack.enter_context(patch.dict(sys.modules, {module_name: types.SimpleNamespace(run=function)}))
            self.assertEqual(runner.main(), 0)
            return json.loads((results / "ci-results.json").read_text())

    def test_actual_producer_keeps_sdk_call_signatures_unchanged(self):
        for mode in ("rust-wasm", "sdk-lockfiles"):
            calls = []
            def execute(root, results):
                calls.append(root)
                results.append({"suite": mode, "exit_code": 0})
            self.run_producer(mode, [mode], execute)
            self.assertEqual(len(calls), 1)
        calls = []
        def conformance(root, results, node, *, verify_node):
            calls.append((node, verify_node))
            results.append({"suite": "sdk-conformance", "exit_code": 0})
        self.run_producer("sdk-conformance", ["sdk-conformance"], conformance)
        self.assertEqual(calls[0][0], "test-node")


    def test_actual_producer_scope_is_honest_and_legacy_still_runs(self):
        for target in contract.TARGETS:
            def execute(root, results, *, target):
                results.append({"suite": target, "coverage_complete": False, "exit_code": 0})
            report = self.run_producer("selfhost", [target], execute)
            self.assertEqual(report["coverage_scope"], "recipe-target")
            self.assertFalse(report["results"][0]["coverage_complete"])
        def legacy(root, results):
            results.append({"spec": "selfhost-smoke.spec.ts", "exit_code": 0})
        self.assertEqual(self.run_producer("selfhost", ["selfhost-smoke.spec.ts"], legacy)["coverage_scope"], "full-spec")

    def receipt(self, target, recipe):
        fields = contract.identity(SOURCE, TREE, hashlib.sha256(recipe).hexdigest(), HARNESS)
        return {**fields, "run_id": "123", "target": target, "coverage_scope": "recipe-target",
            "coverage_complete": False, "browser_coverage_scope": "full-spec" if target == "selfhost-image" else "none",
            "stats": {"expected": 4, "unexpected": 0, "flaky": 0, "skipped": 0}, "exit_code": 0,
            "cleanup": {"containers_remaining": 0, "volumes_remaining": 0, "private_account_files_removed": True, "errors": []},
            "steps": [{"id": key, "phase": "completed", "exit_code": 0, "run_id": "123", "source_commit": SOURCE}
                for key, value in contract.STEPS.items() if target in value[1]]}

    def test_actual_retrieval_rejects_self_consistent_forgery_and_step_run(self):
        recipe = b"actual immutable recipe"
        target = "selfhost-image"
        row = self.receipt(target, recipe)
        report = {"source_commit": SOURCE, "run_id": "123", "harness_commit": HARNESS,
            "coverage_scope": "recipe-target", "results": [row]}
        job = {"source": SOURCE, "run_id": 123, "specs": json.dumps([target])}
        with patch.object(retrieval.subprocess, "check_output", side_effect=lambda command, **kw:
                          TREE if command[1] == "rev-parse" else recipe):
            self.assertTrue(retrieval.valid_selfhost_result(report, job, Path("/unused"), HARNESS))
            for mutate in (lambda row: row.update(contract.identity(SOURCE, "e" * 40, hashlib.sha256(recipe).hexdigest(), HARNESS)),
                           lambda row: row.update(contract.identity(SOURCE, TREE, "f" * 64, HARNESS)),
                           lambda row: row["steps"][0].update(run_id="124"),
                           lambda row: row["steps"][0].update(source_commit="e" * 40),
                           lambda row: row.update(run_id="124")):
                forged = copy.deepcopy(report)
                mutate(forged["results"][0])
                self.assertFalse(retrieval.valid_selfhost_result(forged, job, Path("/unused"), HARNESS))
            forged = copy.deepcopy(report)
            forged["coverage_scope"] = "full-spec"
            self.assertFalse(retrieval.valid_selfhost_result(forged, job, Path("/unused"), HARNESS))

    def test_cached_retrieval_revalidates_target_but_preserves_historical_monolith(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            path = root / "test-results/ci-runs/testing/receipt.json"
            path.parent.mkdir(parents=True)
            job = {"id": "testing", "source": SOURCE, "run_id": 123, "state": "success",
                "mode": "selfhost", "specs": json.dumps(["selfhost-source"])}
            github = types.SimpleNamespace(repo="test/repo", request=lambda url: {"head_sha": HARNESS})
            stack.enter_context(patch.object(retrieval, "attach_cleanup", side_effect=lambda value, *args: value))
            stack.enter_context(patch.object(retrieval, "attach_visual_evidence", side_effect=lambda value, *args: value))
            path.write_text(json.dumps({"coverage_scope": "full-spec", "report": {}}))
            with self.assertRaises(RuntimeError):
                retrieval._fetch_reserved(github, job, root)
            job["specs"] = json.dumps(["selfhost-smoke.spec.ts"])
            self.assertEqual(retrieval._fetch_reserved(github, job, root)["coverage_scope"], "full-spec")

    def test_actual_dispatcher_activates_only_complete_immutable_source(self):
        recipe = (STAGED.parent / contract.RECIPE).read_bytes()
        for activated in (False, True):
            with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
                root = Path(directory)
                readiness = root / "logs/ci-coordinator/cutover.json"
                readiness.parent.mkdir(parents=True)
                readiness.write_text('{"ready":true}')
                queue = coordinator.Queue(root / "test.sqlite3")
                stack.enter_context(patch.object(dispatcher, "canonical_root", return_value=root))
                stack.enter_context(patch.object(dispatcher, "Queue", return_value=queue))
                stack.enter_context(patch.object(dispatcher, "load_candidate", return_value={}))
                stack.enter_context(patch.object(dispatcher, "select_specs", return_value=["selfhost-smoke.spec.ts"]))
                stack.enter_context(patch.object(dispatcher, "spec_source", return_value=""))
                stack.enter_context(patch.object(dispatcher, "ensure_coordinator", return_value=True))
                def git(command, **kwargs):
                    if command[1] == "rev-parse":
                        return SOURCE
                    path = command[2].split(":", 1)[1]
                    if not activated:
                        raise subprocess.CalledProcessError(128, command)
                    return recipe if path == contract.RECIPE else b"immutable product input"
                stack.enter_context(patch.object(dispatcher.subprocess, "check_output", side_effect=git))
                stdout, stderr = io.StringIO(), io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    result = dispatcher.run(["--worktree", str(root), "--session", "testing",
                        "--expected-commit", SOURCE, "--suite", "playwright", "--spec", "selfhost-smoke.spec.ts", "--detach"])
                self.assertEqual(result, 0)
                jobs = queue.status()
                actual = {json.loads(job["specs"])[0] for job in jobs}
                self.assertEqual(actual, set(contract.TARGETS) if activated else {"selfhost-smoke.spec.ts"})
                self.assertIn("rust-scopes-required" if activated else "not-yet-rust-activated", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
