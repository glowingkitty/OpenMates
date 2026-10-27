"""Engineering supervisor tests; no model import, download or inference."""
# contract-test-file: tooling
import importlib.util
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location("redact_eval", Path(__file__).with_name("redact_linux_evaluation.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class SupervisorTest(unittest.TestCase):
    def test_rejects_wrong_pinned_asset_without_network(self):
        with self.assertRaisesRegex(ValueError, "integrity"):
            module.verify_asset("redact.tflite", b"invalid synthetic artifact")

    def test_supervisor_bounds_affinity_and_stops_a_hung_child(self):
        cpu = sorted(os.sched_getaffinity(0))[0]
        result = module.supervise([sys.executable, "-c", "import time; time.sleep(2)"], [cpu], 128, 0.1, dict(os.environ))
        self.assertEqual(result["stopped_by_supervisor"], "wall-time-limit")
        self.assertLess(result["returncode"], 0)
        self.assertEqual(result["affinity_cpus"], [cpu])

    def test_supervisor_rejects_excess_cpu_budget(self):
        with self.assertRaisesRegex(ValueError, "two CPUs"):
            module.supervise([], [0, 1, 2], 128, 1, {})

    def test_run_and_download_require_parent_web_gate_before_any_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            env = dict(os.environ)
            env.pop("OPENMATES_REDACT_EVALUATION_GO", None)
            for flag in ["--run", "--download"]:
                result = subprocess.run([sys.executable, str(Path(module.__file__)), flag,
                                         "--directory", str(target / "assets"),
                                         "--output", str(target / "result.json")],
                                        env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 2)
                self.assertIn("Parent confirmation", result.stderr)
                self.assertFalse((target / "assets").exists())

    def test_native_run_refuses_missing_patched_prefix_before_sdk_or_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            env = {**os.environ, "OPENMATES_REDACT_EVALUATION_GO": "web-trial-passed"}
            result = subprocess.run([sys.executable, module.__file__, "--run", "--download",
                                     "--directory", str(target / "assets"), "--output", str(target / "result.json")],
                                    env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn("verified patched libraries", result.stderr)
            self.assertFalse((target / "assets").exists())

    def test_unpatched_receipt_is_rejected_before_library_loading(self):
        with tempfile.TemporaryDirectory() as directory:
            prefix = Path(directory)
            (prefix / "security-build.json").write_text('{"schema":1,"version":"1.1.0"}')
            with self.assertRaisesRegex(ValueError, "patched Brotli build receipt"):
                module.brotli_guard.verify_prefix(prefix)

    def test_child_loader_path_overrides_parent_and_rejects_interposition(self):
        prefix = Path("/tmp/synthetic-private-decoder")
        original = {"LD_LIBRARY_PATH": "/synthetic/system"}
        with mock.patch.object(module.brotli_guard, "verify_prefix", return_value={}):
            child = module.brotli_guard.child_environment(prefix, original)
            self.assertEqual(child["LD_LIBRARY_PATH"], str(prefix / "lib"))
            self.assertEqual(original["LD_LIBRARY_PATH"], "/synthetic/system")
            with self.assertRaisesRegex(ValueError, "interposition"):
                module.brotli_guard.child_environment(prefix, {"LD_PRELOAD": "/synthetic/other.so"})

    def test_modified_library_is_rejected_before_any_native_load(self):
        guard = module.brotli_guard
        with tempfile.TemporaryDirectory() as directory:
            prefix = Path(directory)
            (prefix / "lib").mkdir()
            library = prefix / "lib/libbrotlicommon.so.1"
            library.write_bytes(b"modified synthetic library")
            receipt = {"schema": 1, "version": guard.VERSION, "commit": guard.COMMIT,
                       "archive_sha256": guard.ARCHIVE_SHA256,
                       "decoder_source_sha256": guard.DECODER_SOURCE_SHA256,
                       "fixed_block_switch_error_propagation": True,
                       "libraries": {"libbrotlicommon.so.1": {"file": "lib/libbrotlicommon.so.1", "sha256": "0" * 64}}}
            (prefix / "security-build.json").write_text(json.dumps(receipt))
            with mock.patch.object(guard, "verify_source", return_value=None):
                with self.assertRaisesRegex(ValueError, "library hash mismatch"):
                    guard.verify_prefix(prefix)


if __name__ == "__main__":
    unittest.main()
