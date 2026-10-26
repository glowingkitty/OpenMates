"""Engineering supervisor tests; no model import, download or inference."""
# contract-test-file: tooling
import importlib.util
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest

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


if __name__ == "__main__":
    unittest.main()
