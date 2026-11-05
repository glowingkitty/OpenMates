"""Inert protocol/process checks only; no SDK worker/native/CLI is executed."""

# contract-test-file: tooling
from __future__ import annotations
from pathlib import Path
import runpy
import subprocess
import sys
import time
import tempfile
from unittest.mock import patch
import unittest

ROOT = Path(__file__).resolve().parents[2]
API = runpy.run_path(
    str(ROOT / "tests/sdk-conformance/runners/project-remote-crypto.py"),
    run_name="inert_harness_tools",
)


class HarnessTests(unittest.TestCase):
    def worker(self, source):
        API["COMMANDS"]["inert"] = [sys.executable, "-c", source]
        return API["Worker"]("inert")

    def test_real_inert_pipe_roundtrip_sequence_and_idempotent_cleanup(self):
        source = "import sys,json\nfor line in sys.stdin:\n x=json.loads(line);print(json.dumps({'ok':True,'value':'inert','sequence':x['sequence']}),flush=True)"
        value = self.worker(source)
        try:
            self.assertEqual(
                value.call({"op": "inert"}), {"ok": True, "value": "inert"}
            )
            self.assertEqual(
                value.call({"op": "inert"}), {"ok": True, "value": "inert"}
            )
        finally:
            value.close()
            value.close()
        self.assertIsNotNone(value.process.returncode)

    def test_stale_sequence_is_refused(self):
        value = self.worker(
            'import sys;sys.stdin.readline();print(\'{"ok":true,"sequence":0}\',flush=True);import time;time.sleep(30)'
        )
        try:
            with self.assertRaisesRegex(ValueError, "shape/order"):
                value.call({"op": "inert"})
        finally:
            value.close()

    def test_stream_and_line_limits(self):
        for stream, size, error in [
            ("stderr", 65537, "diagnostic bound"),
            ("stdout", 1024 * 1024 + 1, "response bound"),
        ]:
            source = f"import sys,time;sys.{stream}.write('x'*{size});sys.{stream}.flush();time.sleep(30)"
            value = self.worker(source)
            try:
                with (
                    self.subTest(stream=stream),
                    self.assertRaisesRegex(ValueError, error),
                ):
                    value.call({"op": "inert"})
            finally:
                value.close()

    def test_deadline_retains_unrelated_process(self):
        unrelated = subprocess.Popen(
            [sys.executable, "-c", "import time;time.sleep(30)"],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        value = self.worker("import time;time.sleep(30)")
        value.deadline = time.monotonic() + 0.1
        try:
            with self.assertRaisesRegex(ValueError, "deadline"):
                value.call({"op": "inert"})
        finally:
            value.close()
        try:
            self.assertIsNone(unrelated.poll())
        finally:
            unrelated.kill()
            unrelated.wait(timeout=2)

    def test_cancelled_owner_is_refused_and_original_reaped(self):
        value = self.worker("import time;time.sleep(30)")
        globals_ = API["cancelled"].__globals__
        try:
            API["cancelled"](None, None)
            with self.assertRaisesRegex(ValueError, "owner cancelled"):
                value.call({"op": "inert"})
        finally:
            value.close()
            globals_["CANCELLED"] = False
        self.assertIsNotNone(value.process.returncode)

    def stopped(self, pid):
        deadline = time.monotonic() + 1
        path = Path(f"/proc/{pid}/stat")
        while time.monotonic() < deadline:
            try:
                state = path.read_text().split(") ", 1)[1].split()[0]
            except FileNotFoundError:
                return
            if state == "Z":
                return
            time.sleep(0.01)
        self.fail("owned inert process survived cleanup")

    def test_first_response_and_blocked_stdin_have_deadlines(self):
        globals_ = API["Worker"].call.__globals__
        for item in [
            {"op": "inert"},
            {"op": "inert", "payload": "x" * (1024 * 1024 - 100)},
        ]:
            with patch.dict(globals_, {"STARTUP_SECONDS": 0.1}):
                value = self.worker("import time;time.sleep(30)")
                try:
                    started = time.monotonic()
                    with self.assertRaisesRegex(ValueError, "response deadline"):
                        value.call(item)
                    self.assertLess(time.monotonic() - started, 1)
                finally:
                    value.close()

    def test_steady_response_deadline_is_separate_from_total(self):
        globals_ = API["Worker"].call.__globals__
        source = "import sys,json,time;x=json.loads(sys.stdin.readline());print(json.dumps({'ok':True,'value':'inert','sequence':x['sequence']}),flush=True);sys.stdin.readline();time.sleep(30)"
        with patch.dict(globals_, {"RESPONSE_SECONDS": 0.1}):
            value = self.worker(source)
            try:
                self.assertTrue(value.call({"op": "first"})["ok"])
                with self.assertRaisesRegex(ValueError, "response deadline"):
                    value.call({"op": "second"})
            finally:
                value.close()

    def test_exited_leader_with_inherited_pipes_cleans_descendant(self):
        with tempfile.TemporaryDirectory() as folder:
            pidfile = Path(folder) / "descendant"
            source = (
                "import subprocess,sys;from pathlib import Path;p=subprocess.Popen([sys.executable,'-c','import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(30)']);Path("
                + repr(str(pidfile))
                + ").write_text(str(p.pid))"
            )
            value = self.worker(source)
            started = time.monotonic()
            try:
                with self.assertRaises((ValueError, BrokenPipeError)):
                    value.call({"op": "inert"})
            finally:
                value.close()
            self.assertLess(time.monotonic() - started, 2)
            self.stopped(int(pidfile.read_text()))

    def test_aggregate_stdout_bound_is_enforced_across_responses(self):
        source = "import sys,json\nfor line in sys.stdin:\n x=json.loads(line);print(json.dumps({'ok':True,'value':'x'*100000,'sequence':x['sequence']}),flush=True)"
        value = self.worker(source)
        try:
            with self.assertRaisesRegex(ValueError, "worker output bound"):
                for index in range(90):
                    value.call({"op": "inert"})
        finally:
            value.close()

    def test_oversized_stdin_is_refused_before_write(self):
        value = self.worker("import time;time.sleep(30)")
        try:
            with self.assertRaisesRegex(ValueError, "protocol bound"):
                value.call({"op": "inert", "payload": "x" * (1024 * 1024)})
        finally:
            value.close()


if __name__ == "__main__":
    unittest.main()
