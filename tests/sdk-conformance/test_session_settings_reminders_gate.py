"""Protocol mutations and inert owned-child lifecycle tests; no SDK/peer/network."""

# contract-test-file: tooling
from __future__ import annotations
import copy
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
import runpy
import unittest

ROOT = Path(__file__).resolve().parents[2]
API = runpy.run_path(
    str(ROOT / "tests/sdk-conformance/runners/session-settings-reminders-gate.py"),
    run_name="pure_gate_tools",
)


class GateProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = (ROOT / API["SOURCE"]).read_bytes()
        cls.projection = (
            ROOT
            / "tests/sdk-conformance/fixtures/session-settings-reminders-read-gate.json"
        ).read_bytes()
        cls.ids = API["validate_projection"](cls.projection, cls.raw)

    def observation(self):
        # Synthetic validator input, never emitted as a runtime conformance receipt.
        return {
            "capability": API["CAPABILITY"],
            "language": "rust",
            "status": "passed",
            "fixtureSha256": API["SOURCE_SHA256"],
            "results": [{"id": identity, "status": "passed"} for identity in self.ids],
        }

    def test_complete_projection_has_all28_pinned_source_ids(self):
        self.assertEqual(len(self.ids), 28)
        self.assertEqual(
            self.ids, [case["id"] for case in json.loads(self.raw)["cases"]]
        )

    def test_any_raw_source_byte_change_is_refused(self):
        with self.assertRaises(ValueError):
            API["validate_projection"](self.projection, self.raw + b"\n")

    def test_missing_duplicate_reordered_or_unknown_projection_is_refused(self):
        original = json.loads(self.projection)
        for mode in ("missing", "duplicate", "reorder", "unknown", "sha", "path"):
            value = copy.deepcopy(original)
            suite = value["capabilities"][API["CAPABILITY"]]
            vectors = suite["vectors"]
            if mode == "missing":
                vectors.pop()
            elif mode == "duplicate":
                vectors[-1] = vectors[0]
            elif mode == "reorder":
                vectors.reverse()
            elif mode == "unknown":
                vectors[-1] = {"id": "invented"}
            elif mode == "sha":
                suite["source_sha256"] = "0" * 64
            else:
                suite["source_fixture"] = "other.json"
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                API["validate_projection"](json.dumps(value).encode(), self.raw)

    def test_validated_observation_is_preserved_by_identity(self):
        value = self.observation()
        self.assertIs(API["validate_observed"](value, "rust", self.ids), value)

    def test_wrong_language_capability_hash_status_is_refused(self):
        for key in ("language", "capability", "fixtureSha256", "status"):
            value = self.observation()
            value[key] = "wrong"
            with self.subTest(key=key), self.assertRaises(ValueError):
                API["validate_observed"](value, "rust", self.ids)

    def test_aggregate_only_missing_duplicate_reordered_failed_results_refused(self):
        for mode in ("aggregate", "missing", "duplicate", "reorder", "failed"):
            value = self.observation()
            rows = value["results"]
            if mode == "aggregate":
                del value["results"]
                value["cases"] = 28
            elif mode == "missing":
                rows.pop()
            elif mode == "duplicate":
                rows[-1] = rows[0]
            elif mode == "reorder":
                rows.reverse()
            else:
                rows[-1]["status"] = "failed"
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                API["validate_observed"](value, "rust", self.ids)

    def test_fixed_commands_select_real_library_runners(self):
        commands = API["COMMANDS"]
        self.assertEqual(set(commands), {"rust", "npm", "python"})
        self.assertIn(
            "sdk-session-settings-reminders-read-conformance", commands["rust"]
        )
        self.assertEqual(
            commands["npm"],
            [
                "node",
                "tests/sdk-conformance/runners/session-settings-reminders-read.mjs",
            ],
        )
        self.assertEqual(
            commands["python"][1],
            "tests/sdk-conformance/runners/session-settings-reminders-read.py",
        )
        self.assertNotIn(
            "openmates", {word for command in commands.values() for word in command}
        )


class OwnedProcessTests(unittest.TestCase):
    def inert(self, source, **options):
        return API["run_owned"]([sys.executable, "-c", source], ROOT, **options)

    def assert_stopped(self, pid):
        # A killed orphan may briefly await its init reaper; no runnable survivor is allowed.
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
        self.fail("owned process survived bounded SIGKILL completion")

    def test_success_reaps_leader_and_keeps_only_stdout(self):
        code, output = self.inert(
            "import sys;print('actual-inert-output');sys.stderr.write('discard-me')"
        )
        self.assertEqual(code, 0)
        self.assertEqual(output, b"actual-inert-output\n")

    def test_each_stream_has_independent_closed_limit(self):
        for stream in ("stdout", "stderr"):
            with (
                self.subTest(stream=stream),
                self.assertRaisesRegex(ValueError, "output limit"),
            ):
                self.inert(
                    f"import sys,time;sys.{stream}.write('x'*65537);sys.{stream}.flush();time.sleep(30)",
                    timeout=2,
                )

    def test_nonzero_exit_is_returned_without_private_stderr(self):
        code, output = self.inert(
            "import sys;sys.stderr.write('private-inert-error');sys.exit(7)"
        )
        self.assertEqual(code, 7)
        self.assertEqual(output, b"")

    def test_timeout_kills_descendant_and_preserves_unrelated_process(self):
        unrelated = subprocess.Popen(
            [sys.executable, "-c", "import time;time.sleep(30)"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            with tempfile.TemporaryDirectory() as folder:
                pidfile = Path(folder) / "descendant"
                source = (
                    "import subprocess,sys,time;from pathlib import Path;p=subprocess.Popen([sys.executable,'-c','import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(30)']);Path("
                    + repr(str(pidfile))
                    + ").write_text(str(p.pid));time.sleep(30)"
                )
                with self.assertRaisesRegex(ValueError, "deadline"):
                    self.inert(source, timeout=0.3)
                self.assert_stopped(int(pidfile.read_text()))
                self.assertIsNone(
                    unrelated.poll(), "owned cleanup must preserve unrelated groups"
                )
        finally:
            unrelated.kill()
            unrelated.wait(timeout=2)

    def test_early_leader_exit_with_inherited_pipes_cleans_descendant(self):
        with tempfile.TemporaryDirectory() as folder:
            pidfile = Path(folder) / "descendant"
            source = (
                "import subprocess,sys;from pathlib import Path;p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);Path("
                + repr(str(pidfile))
                + ").write_text(str(p.pid))"
            )
            started = time.monotonic()
            with self.assertRaisesRegex(ValueError, "retained output pipes"):
                self.inert(source, timeout=5)
            self.assertLess(time.monotonic() - started, 2)
            self.assert_stopped(int(pidfile.read_text()))

    def test_owner_cancellation_reaps_group_before_return(self):
        started = time.monotonic()
        with self.assertRaisesRegex(ValueError, "owner cancelled"):
            self.inert(
                "import time;time.sleep(30)",
                timeout=5,
                cancelled=lambda: time.monotonic() - started > 0.1,
            )
        self.assertLess(time.monotonic() - started, 2)

    def test_baseexception_still_reaps_original_group(self):
        with tempfile.TemporaryDirectory() as folder:
            pidfile = Path(folder) / "leader"
            source = (
                "import os,time;from pathlib import Path;Path("
                + repr(str(pidfile))
                + ").write_text(str(os.getpid()));time.sleep(30)"
            )

            def interrupt():
                if pidfile.exists():
                    raise KeyboardInterrupt()
                return False

            with self.assertRaises(KeyboardInterrupt):
                self.inert(source, timeout=5, cancelled=interrupt)
            self.assert_stopped(int(pidfile.read_text()))

    def test_real_owner_sigterm_handler_drains_owned_group(self):
        with tempfile.TemporaryDirectory() as folder:
            pidfile = Path(folder) / "child"
            runner = (
                ROOT
                / "tests/sdk-conformance/runners/session-settings-reminders-gate.py"
            )
            childcode = (
                "import os,time;from pathlib import Path;Path("
                + repr(str(pidfile))
                + ").write_text(str(os.getpid()));time.sleep(30)"
            )
            host = (
                "import runpy,signal,sys;api=runpy.run_path("
                + repr(str(runner))
                + ",run_name='inert_owner');[signal.signal(s,api['cancel_owner']) for s in (signal.SIGTERM,signal.SIGHUP,signal.SIGINT)];api['run_owned']([sys.executable,'-c',"
                + repr(childcode)
                + "],"
                + repr(str(ROOT))
                + ",cancelled=lambda:api['cancel_owner'].__globals__['OWNER_CANCELLED'])"
            )
            owner = subprocess.Popen(
                [sys.executable, "-c", host],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                deadline = time.monotonic() + 2
                while not pidfile.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(pidfile.exists())
                owner.terminate()
                owner.wait(timeout=2)
                self.assertNotEqual(owner.returncode, 0)
                self.assert_stopped(int(pidfile.read_text()))
            finally:
                if owner.poll() is None:
                    owner.kill()
                    owner.wait(timeout=2)


if __name__ == "__main__":
    unittest.main()
