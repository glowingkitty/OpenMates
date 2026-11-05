# contract-test-file: tooling
"""Actual SQLite terminal state and wait CLI; artifact verifier is inert."""

from contextlib import ExitStack, redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "coordinator_wait_state_subject", SCRIPTS / "ci_coordinator.py"
)
coordinator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(coordinator)


class WaitResultStateTests(unittest.TestCase):
    def setUp(self):
        owner = tempfile.TemporaryDirectory(prefix="ci-wait-state-")
        self.addCleanup(owner.cleanup)
        self.root = Path(owner.name)
        self.queue = coordinator.Queue(self.root / "queue.db")
        self.job = self.queue.enqueue(
            "fixture", "a" * 40, ["sdk-conformance"], mode="sdk-conformance"
        )

    def state(self, state):
        with self.queue.connect() as db:
            db.execute(
                "UPDATE jobs SET state=?, run_id=9 WHERE id=?", (state, self.job["id"])
            )

    def run_wait(self, result=None, error=None):
        stream = io.StringIO()
        with ExitStack() as stack:
            stack.enter_context(
                patch.object(coordinator, "canonical_root", return_value=self.root)
            )
            stack.enter_context(
                patch.object(coordinator, "Queue", return_value=self.queue)
            )
            stack.enter_context(
                patch.object(coordinator, "GitHub", return_value=object())
            )
            read = stack.enter_context(
                patch.object(
                    self.queue, "result", return_value=result, side_effect=error
                )
            )
            stack.enter_context(
                patch.dict(sys.modules, {"ci_results": SimpleNamespace(fetch=object())})
            )
            stack.enter_context(
                patch.object(
                    sys, "argv", ["ci_coordinator.py", "wait", self.job["id"], "--json"]
                )
            )
            stack.enter_context(redirect_stdout(stream))
            code = coordinator.main()
        return code, json.loads(stream.getvalue()), read.call_count

    def test_validated_native_payload_without_state_keeps_terminal_success(self):
        self.state("success")
        payload = {
            "request_id": self.job["id"],
            "coverage_scope": "compilation-only",
            "native_build": {"status": "passed", "compileProof": True},
        }
        code, printed, calls = self.run_wait(payload)
        self.assertEqual((code, printed, calls), (0, payload, 1))

    def test_exit_status_uses_actual_queue_state_not_result_status_field(self):
        self.state("success")
        code, printed, calls = self.run_wait({"state": "untrusted-result-field"})
        self.assertEqual(code, 0)
        self.assertEqual(printed, {"state": "untrusted-result-field"})
        self.assertEqual(calls, 1)

    def test_validation_exception_still_prevents_success(self):
        self.state("success")
        with self.assertRaisesRegex(RuntimeError, "artifact refused"):
            self.run_wait(error=RuntimeError("artifact refused"))

    def test_failed_and_cancelled_queue_results_stay_nonzero_without_fetch(self):
        for state in ("failure", "cancelled"):
            with self.subTest(state=state):
                self.state(state)
                code, printed, calls = self.run_wait({"state": "success"})
                self.assertEqual(code, 1)
                self.assertEqual(printed["state"], state)
                self.assertIn("result_command", printed)
                self.assertEqual(calls, 0)


if __name__ == "__main__":
    unittest.main()
