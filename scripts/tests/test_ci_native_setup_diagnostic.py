# contract-test-file: tooling
"""Closed native setup diagnostics, inert actual-run fixtures only; no Cargo/CI."""
import errno
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "ci_native_dev.py"
spec = importlib.util.spec_from_file_location("native_setup_diagnostic_supplier", SOURCE)
lane = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = lane
spec.loader.exec_module(lane)


class NativeSetupDiagnostics(unittest.TestCase):
    def actual_run(self, *, disk=None, runner_temp=True, create=None):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "test-results").mkdir()
            ambient = {"GITHUB_ACTIONS": "true", "RUNNER_ENVIRONMENT": "github-hosted",
                       "OPENMATES_CI_ISOLATED": "1", "RUNNER_ARCH": "ARM64",
                       "CI_SPECS_JSON": '["rust-native-dev"]',
                       "BUILD_COMMIT_SHA": "a" * 40, "CI_CANDIDATE_TREE": "b" * 40,
                       "CI_HARNESS_COMMIT": "c" * 40, "GITHUB_RUN_ID": "123",
                       "CI_NATIVE_DEV_STARTED_MONOTONIC": "1",
                       "CI_NATIVE_DEV_DEADLINE_MONOTONIC": "2701"}
            if runner_temp:
                ambient["RUNNER_TEMP"] = str(root)

            def git(path, *args):
                return "b" * 40 if args == ("rev-parse", "HEAD^{tree}") else "a" * 40 if path == root else "c" * 40

            inputs = {name + "/Cargo.lock": "e" * 64 for name in lane.ROOTS}
            with (patch.object(lane.platform, "machine", return_value="aarch64"),
                  patch.object(lane.sdk, "git", side_effect=git),
                  patch.object(lane.subprocess, "run", return_value=SimpleNamespace(returncode=1)),
                  patch.object(lane, "event_ticket", return_value=({}, {"id": "d" * 64, "token": "inert"})),
                  patch.object(lane.time, "monotonic", return_value=2),
                  patch.object(lane, "source_inputs_from_git", return_value=inputs),
                  patch.object(lane, "snapshot", return_value=inputs),
                  patch.object(lane.shutil, "disk_usage", side_effect=disk or [SimpleNamespace(free=lane.sdk.RESERVE)] * 2),
                  patch.object(lane.tempfile, "mkdtemp", side_effect=create or AssertionError("unexpected setup progress")),
                  patch.object(lane, "NativeCommands") as commands,
                  patch.object(lane.transport, "put_file") as upload):
                results = []
                receipt = lane.run(root, results, environ=ambient)
            commands.assert_not_called()
            upload.assert_not_called()
            self.assertEqual(receipt["code"], "disk")
            self.assertEqual(results[0]["exit_code"], 1)
            self.assertFalse(receipt["compileProof"])
            self.assertTrue(receipt["sourceHeld"])
            public = json.loads((root / "test-results/ci-native-dev.json").read_text())
            self.assertEqual(public["diagnostic"], receipt["diagnostic"])
            self.assertNotIn("SECRET", json.dumps(public))
            self.assertNotIn(temporary, json.dumps(public))
            return receipt["diagnostic"]

    def test_actual_output_stat_failure_is_not_a_reserve_refusal(self):
        result = self.actual_run(disk=FileNotFoundError(errno.ENOENT, "SECRET", "/SECRET"))
        self.assertEqual(result, {"stage": "disk", "reason": "operation_failed", "setupSubstage": "output-disk-usage", "exceptionCategory": "os-error", "osCode": "ENOENT"})

    def test_actual_tmp_stat_failure_is_separate(self):
        result = self.actual_run(disk=[SimpleNamespace(free=lane.sdk.RESERVE), PermissionError(errno.EACCES, "SECRET")])
        self.assertEqual(result["setupSubstage"], "tmp-disk-usage")
        self.assertEqual(result["osCode"], "EACCES")

    def test_actual_output_reserve_remains_closed_and_short_circuits(self):
        result = self.actual_run(disk=[SimpleNamespace(free=lane.sdk.RESERVE - 1)])
        self.assertEqual(result, {"stage": "disk", "reason": "guard_refused", "setupSubstage": "reserve-check", "exceptionCategory": "policy-refused"})

    def test_actual_tmp_reserve_remains_closed(self):
        result = self.actual_run(disk=[SimpleNamespace(free=lane.sdk.RESERVE), SimpleNamespace(free=lane.sdk.RESERVE - 1)])
        self.assertEqual(result["exceptionCategory"], "policy-refused")
        self.assertEqual(result["setupSubstage"], "reserve-check")

    def test_actual_missing_runner_temp_is_not_relabelled_capacity(self):
        result = self.actual_run(runner_temp=False)
        self.assertEqual(result["setupSubstage"], "runner-temp-input")
        self.assertEqual(result["exceptionCategory"], "key-error")

    def test_actual_private_directory_error_is_attributed(self):
        result = self.actual_run(create=OSError(errno.ENOSPC, "SECRET", "/SECRET"))
        self.assertEqual(result["setupSubstage"], "private-parent-create")
        self.assertEqual(result["osCode"], "ENOSPC")

    def test_closed_projection_ignores_hostile_class_names_args_paths_and_errno(self):
        class SECRET(Exception):
            pass
        for error, category in [(SECRET("SECRET"), "other"), (KeyError("SECRET"), "key-error"),
                                (TypeError("SECRET"), "type-error"), (AttributeError("SECRET"), "attribute-error"),
                                (ValueError("SECRET"), "value-error")]:
            result = lane.diagnostic("disk", error, setup_substage="manifest-check")
            self.assertEqual(result["exceptionCategory"], category)
            self.assertNotIn("SECRET", json.dumps(result))
        self.assertEqual(lane.setup_exception(OSError(999999, "SECRET")), {"exceptionCategory": "os-error", "osCode": "other"})

    def test_unrecognized_or_other_phase_substage_never_crosses_boundary(self):
        for phase, substage in [("disk", "/SECRET"), ("source", "manifest-check")]:
            result = lane.diagnostic(phase, RuntimeError("SECRET"), setup_substage=substage)
            self.assertNotIn("setupSubstage", result)
            self.assertNotIn("exceptionCategory", result)
            self.assertNotIn("SECRET", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
