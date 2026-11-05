"""Exact Driver cleanup integration using inert owners/children; no SDK or network."""

# contract-test-file: tooling
from __future__ import annotations
import ast
import hashlib
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import tempfile
import time
import types
import unittest

ROOT = Path(__file__).resolve().parents[2]


class Refused(Exception):
    pass


def driver_namespace():
    # Only source-authentication hooks are inert. The actual Driver class/run/finally
    # is compiled unchanged from the admitted protected afterimage.
    tree = ast.parse((ROOT / "scripts/ci_sdk_conformance_exec.py").read_bytes())
    nodes = [
        node
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef))
        and node.name in {"Driver", "unique_failure_object"}
    ]
    assert len(nodes) == 2

    def require(value, code):
        if not value:
            raise Refused(code)

    namespace = {
        "json": json,
        "os": os,
        "selectors": selectors,
        "subprocess": subprocess,
        "time": time,
        "LIMIT": 4 * 1024**2,
        "Refused": Refused,
        "require": require,
        "sha": lambda raw: hashlib.sha256(raw).hexdigest(),
        "verify_programs": lambda *args: None,
        "compiler_diagnostics": lambda *args: [],
        "project_vector_diagnostic": lambda *args: None,
    }
    exec(
        compile(
            ast.Module(body=nodes, type_ignores=[]), "<actual protected Driver>", "exec"
        ),
        namespace,
    )
    return namespace


class DriverOwnerIntegrationTests(unittest.TestCase):
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
        self.fail("inert owned process survived Driver cleanup")

    def exercise(self, mode):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            pids = folder / "owned.json"
            ownerpid = folder / "owner"
            host = folder / "owner.py"
            native = (
                "import os,subprocess,sys,time,json;from pathlib import Path;p=subprocess.Popen([sys.executable,'-c','import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(30)']);Path("
                + repr(str(pids))
                + ").write_text(json.dumps([os.getpid(),p.pid]));time.sleep(30)"
            )
            wrapper = (
                ROOT
                / "tests/sdk-conformance/runners/session-settings-reminders-gate.py"
            )
            lines = [
                "import runpy,signal,sys,threading,time,os",
                "from pathlib import Path",
                "Path(" + repr(str(ownerpid)) + ").write_text(str(os.getpid()))",
                "api=runpy.run_path("
                + repr(str(wrapper))
                + ",run_name='inert_driver_owner')",
                "for kind in (signal.SIGTERM,signal.SIGHUP,signal.SIGINT):signal.signal(kind,api['cancel_owner'])",
                "def work():",
                "    try:api['run_owned']([sys.executable,'-c',"
                + repr(native)
                + "],"
                + repr(str(ROOT))
                + ",timeout=20,cancelled=lambda:api['cancel_owner'].__globals__['OWNER_CANCELLED'])",
                "    except ValueError:pass",
            ]
            if mode == "output":
                lines += [
                    "thread=threading.Thread(target=work);thread.start()",
                    "while not Path(" + repr(str(pids)) + ").exists():time.sleep(0.01)",
                    "sys.stdout.write('x'*(4*1024*1024+1));sys.stdout.flush()",
                    "thread.join()",
                ]
            else:
                lines += ["work()"]
            host.write_text("\n".join(lines) + "\n")
            namespace = driver_namespace()
            if mode == "interrupt":

                class InterruptSelector(selectors.DefaultSelector):
                    def select(self, timeout=None):
                        if pids.exists():
                            raise KeyboardInterrupt()
                        return super().select(min(timeout or 0.01, 0.01))

                namespace["selectors"] = types.SimpleNamespace(
                    DefaultSelector=InterruptSelector, EVENT_READ=selectors.EVENT_READ
                )
            identity = {
                "capability": "session.settings-reminders-read",
                "language": "rust",
                "fixtureSha256": "inert-not-a-receipt",
                "vectors": ["inert"],
            }
            command = [
                sys.executable,
                str(host),
                "--capability",
                identity["capability"],
            ]
            deadline = time.monotonic() + (0.4 if mode == "deadline" else 5)
            driver = namespace["Driver"](ROOT, {}, [identity], deadline)
            driver.commands = [command]
            unrelated = subprocess.Popen(
                [sys.executable, "-c", "import time;time.sleep(30)"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            try:
                started = time.monotonic()
                expected = KeyboardInterrupt if mode == "interrupt" else Refused
                with self.assertRaises(expected):
                    driver.run(
                        command, cwd=ROOT, capture_output=True, text=True, timeout=10
                    )
                self.assertLess(time.monotonic() - started, 3.5)
                self.assertTrue(pids.exists())
                for pid in [int(ownerpid.read_text()), *json.loads(pids.read_text())]:
                    self.stopped(pid)
                self.assertIsNone(unrelated.poll())
                self.assertEqual(
                    driver.launches[0]["status"],
                    "started",
                    "cleanup must never promote failed/partial launch",
                )
                if mode != "interrupt":
                    self.assertEqual(
                        driver.failure["code"],
                        "driver_deadline"
                        if mode == "deadline"
                        else "driver_output_bound",
                    )
                    self.assertIn("terminatedReturncode", driver.failure)
            finally:
                unrelated.kill()
                unrelated.wait(timeout=2)

    def test_actual_driver_remaining_deadline_cancels_owned_group(self):
        self.exercise("deadline")

    def test_actual_driver_output_limit_cancels_owned_group(self):
        self.exercise("output")

    def test_actual_driver_interruption_cancels_owned_group(self):
        self.exercise("interrupt")


if __name__ == "__main__":
    unittest.main()
