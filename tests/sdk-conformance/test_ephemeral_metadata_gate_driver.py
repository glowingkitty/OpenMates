"""Exact future Driver/interactive harness lifecycle, with inert descendants only."""

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
CAPABILITY = "session.ephemeral-metadata-startup.v1"


class Refused(Exception):
    pass


def driver_namespace():
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

    ns = {
        "json": json,
        "os": os,
        "selectors": selectors,
        "subprocess": subprocess,
        "sys": sys,
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
            ast.Module(body=nodes, type_ignores=[]),
            "<exact future protected Driver>",
            "exec",
        ),
        ns,
    )
    return ns


def command(language="rust"):
    return [
        sys.executable,
        "tests/sdk-conformance/runners/session-ephemeral-metadata-gate.py",
        "--language",
        language,
        "--fixture",
        str(ROOT / "tests/sdk-conformance/fixtures/session-ephemeral-metadata.json"),
        "--capability",
        CAPABILITY,
    ]


class EphemeralMetadataGateDriverTests(unittest.TestCase):
    def stopped(self, pid):
        path = Path(f"/proc/{pid}/stat")
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            try:
                state = path.read_text().split(") ", 1)[1].split()[0]
            except FileNotFoundError:
                return
            if state == "Z":
                return
            time.sleep(0.01)
        self.fail("owned inert process survived cancellation")

    def exercise(self, mode):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            pids = folder / "pids"
            ownerpid = folder / "owner"
            host = folder / "owner.py"
            native = (
                "import os,subprocess,sys,time,json;from pathlib import Path;p=subprocess.Popen([sys.executable,'-c','import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(30)']);Path("
                + repr(str(pids))
                + ").write_text(json.dumps([os.getpid(),p.pid]));time.sleep(30)"
            )
            harness = (
                ROOT
                / "tests/sdk-conformance/runners/session-ephemeral-metadata-gate.py"
            )
            lines = [
                "import runpy,signal,sys,os,threading,time",
                "from pathlib import Path",
                "Path(" + repr(str(ownerpid)) + ").write_text(str(os.getpid()))",
                "api=runpy.run_path("
                + repr(str(harness))
                + ",run_name='inert_driver_metadata')",
                "api['COMMANDS']['rust']=[sys.executable,'-c'," + repr(native) + "]",
                "for kind in(signal.SIGTERM,signal.SIGHUP,signal.SIGINT):signal.signal(kind,api['cancelled'])",
                "def work():",
                "    try:",
                "        api['execute'](Path("
                + repr(
                    str(
                        ROOT
                        / "tests/sdk-conformance/fixtures/session-ephemeral-metadata.json"
                    )
                )
                + "),"
                + repr(CAPABILITY)
                + ",'rust',Path("
                + repr(str(ROOT))
                + "))",
                "    except ValueError:pass",
            ]
            if mode == "output":
                lines += [
                    "thread=threading.Thread(target=work);thread.start()",
                    "while not Path(" + repr(str(pids)) + ").exists():time.sleep(.01)",
                    "sys.stdout.write('x'*(4*1024*1024+1));sys.stdout.flush()",
                    "thread.join()",
                ]
            else:
                lines += ["work()"]
            host.write_text("\n".join(lines) + "\n")
            ns = driver_namespace()
            fixed = command()

            # Trust/command guards run against the real fixed argv. Only process
            # launch is routed to this native-free inert host in the unit test.
            def launch(actual, **kwargs):
                self.assertEqual(actual, fixed)
                return subprocess.Popen([sys.executable, str(host)], **kwargs)

            ns["subprocess"] = types.SimpleNamespace(
                Popen=launch,
                PIPE=subprocess.PIPE,
                DEVNULL=subprocess.DEVNULL,
                CompletedProcess=subprocess.CompletedProcess,
                TimeoutExpired=subprocess.TimeoutExpired,
            )
            if mode == "interrupt":

                class InterruptSelector(selectors.DefaultSelector):
                    def select(self, timeout=None):
                        if pids.exists():
                            raise KeyboardInterrupt()
                        return super().select(min(timeout or 0.01, 0.01))

                ns["selectors"] = types.SimpleNamespace(
                    DefaultSelector=InterruptSelector, EVENT_READ=selectors.EVENT_READ
                )
            identity = {
                "capability": CAPABILITY,
                "language": "rust",
                "fixtureSha256": "inert-not-a-receipt",
                "vectors": ["inert"],
            }
            driver = ns["Driver"](
                ROOT,
                {},
                [identity],
                time.monotonic() + (1 if mode == "deadline" else 5),
            )
            driver.commands = [fixed]
            unrelated = subprocess.Popen(
                [sys.executable, "-c", "import time;time.sleep(30)"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            try:
                started = time.monotonic()
                with self.assertRaises(
                    KeyboardInterrupt if mode == "interrupt" else Refused
                ):
                    driver.run(
                        fixed, cwd=ROOT, capture_output=True, text=True, timeout=10
                    )
                self.assertLess(time.monotonic() - started, 4)
                self.assertTrue(pids.exists())
                for pid in [int(ownerpid.read_text()), *json.loads(pids.read_text())]:
                    self.stopped(pid)
                self.assertIsNone(unrelated.poll())
                self.assertEqual(driver.launches[0]["status"], "started")
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

    def test_remaining_deadline_terminates_nested_owned_groups(self):
        self.exercise("deadline")

    def test_driver_output_bound_terminates_nested_owned_groups(self):
        self.exercise("output")

    def test_driver_interruption_terminates_nested_owned_groups(self):
        self.exercise("interrupt")

    def test_cleanup_guard_is_only_the_exact_future_capability_and_commands(self):
        tree = ast.parse((ROOT / "scripts/ci_sdk_conformance_exec.py").read_bytes())
        guards = [
            node.test
            for node in ast.walk(tree)
            if isinstance(node, ast.If)
            and isinstance(node.test, ast.BoolOp)
            and CAPABILITY in ast.unparse(node.test)
        ]
        self.assertEqual(len(guards), 1)
        guard = compile(
            ast.Expression(guards[0]), "<actual remote cleanup guard>", "eval"
        )
        identity = {"capability": CAPABILITY, "language": "rust"}
        base = command()
        self_ = types.SimpleNamespace(root=ROOT)

        def accepted(identity, argv):
            return eval(
                guard,
                {"identity": identity, "command": argv, "self": self_, "sys": sys},
            )

        for language in ("rust", "npm", "python"):
            self.assertTrue(
                accepted({**identity, "language": language}, command(language))
            )
        for changed in [
            base + ["--skip"],
            ["different-python", *base[1:]],
            [*base[:5], "other.json", *base[6:]],
        ]:
            self.assertFalse(accepted(identity, changed))
        self.assertFalse(accepted({**identity, "capability": "other"}, base))
        self.assertFalse(accepted({**identity, "language": "other"}, base))
        self.assertFalse(accepted(None, base))


if __name__ == "__main__":
    unittest.main()
