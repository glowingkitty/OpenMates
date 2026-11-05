# contract-test-file: tooling
"""Inert protocol/source controls; never invoke Vite/Chromium/CMS/Cargo."""

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
# Normal protected helper imports, compatible with the installed tooling layout.
import ci_web_paired_profile as paired  # noqa: E402  # Requires the original sys.path bootstrap above.


def fixture():
    ids = [str(uuid.UUID(int=i + 1)) for i in range(123)]
    parents = ids[:20]
    return {
        "event": "startup_performance_ready",
        "chatId": ids[0],
        "ownerId": str(uuid.UUID(int=1000)),
        "parentChatIds": ids[1:121],
        "subchatIds": ids[121:],
        "subchatParentIds": ids[:2],
        "contentParentIds": parents,
        "messageCount": 120,
        "selectedMessageCount": 6,
        "inferenceCalls": 0,
        "metadataJobCount": 0,
        "contentMessageIds": {
            p: [str(uuid.UUID(int=2000 + i * 6 + j)) for j in range(6)]
            for i, p in enumerate(parents)
        },
        "contentPlaintext": {
            p: ["Synthetic question " + str(j) for j in range(6)] for p in parents
        },
    }


class PairedProfileTests(unittest.TestCase):
    def test_exact_selector_and_isolation(self):
        env = {
            "GITHUB_ACTIONS": "true",
            "RUNNER_ENVIRONMENT": "github-hosted",
            "OPENMATES_CI_ISOLATED": "1",
            "CI_TEST_MODE": "e2e",
            "CI_SPECS_JSON": json.dumps([paired.SPEC]),
        }
        paired.admission(env)
        for key, value in [
            ("GITHUB_ACTIONS", "false"),
            ("CI_TEST_MODE", "visual"),
            (
                "CI_SPECS_JSON",
                json.dumps([paired.SPEC, "page-load-performance.spec.ts"]),
            ),
            ("CI_PLAYWRIGHT_CASE_TITLE", "one"),
        ]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                paired.admission({**env, key: value})

    def test_actual_fixture_workload_and_mutations(self):
        original = fixture()
        self.assertIs(paired.validate_fixture(original), original)
        for change in [
            lambda x: x.update(messageCount=39),
            lambda x: x.update(inferenceCalls=1),
            lambda x: x.update(metadataJobCount=1),
            lambda x: x["contentParentIds"].pop(),
            lambda x: x["parentChatIds"].pop(),
            lambda x: x["subchatIds"].append(x["subchatIds"][0]),
            lambda x: x["contentMessageIds"][x["chatId"]].pop(),
            lambda x: x["contentParentIds"].__setitem__(0, x["subchatIds"][0]),
        ]:
            value = copy.deepcopy(original)
            change(value)
            with self.assertRaises(ValueError):
                paired.validate_fixture(value)

    def test_build_environment_never_inherits_activation(self):
        clean = paired.clean_build_environment(
            {
                "OPENMATES_RUST_CORE_ASSETS": "1",
                "VITE_OPENMATES_RUST_INITIAL_SYNC_PROTOTYPE": "1",
                "OPENMATES_PERF_FAKE": "yes",
                "OPENMATES_PAIRED_PROFILE_JSON": "{}",
                "VITE_API_URL": "http://localhost:8000",
            }
        )
        self.assertEqual(clean, {"VITE_API_URL": "http://localhost:8000"})

    def test_controller_refuses_forged_receipts_paths_order_and_duplicate_activation(
        self,
    ):
        profile = object.__new__(paired.Profile)
        profile.closed = False
        profile.active = None
        profile.position = 0
        profile.order = [
            (p, a)
            for p in range(1, 6)
            for a in (paired.ARMS if p % 2 else paired.ARMS[::-1])
        ]
        profile.executable = Path("/fixed/chromium")
        profile.browser_sha = "browser"
        profile.served = {a: a + "-receipt" for a in paired.ARMS}
        for request in [
            {"operation": "activate", "arm": "rust", "pair": 1},
            {
                "operation": "activate",
                "arm": "typescript",
                "pair": 1,
                "receipt": "forged",
            },
            {"operation": "activate", "arm": "/etc", "pair": 1},
            {"operation": "activate", "arm": "typescript", "pair": True},
            {"operation": "describe", "binding": {}},
            {"operation": "build", "path": "/tmp"},
        ]:
            with self.assertRaises(ValueError):
                profile.dispatch(request)
        with (
            patch.object(paired, "read_regular", return_value=b"browser"),
            patch.object(paired, "digest", return_value="browser"),
            patch.object(profile, "verify_served", return_value="typescript-receipt"),
            patch.object(profile, "start_web"),
            patch.object(profile, "stop_web"),
        ):
            self.assertEqual(
                profile.dispatch(
                    {"operation": "activate", "arm": "typescript", "pair": 1}
                )["arm"],
                "typescript",
            )
            with self.assertRaises(ValueError):
                profile.dispatch(
                    {"operation": "activate", "arm": "typescript", "pair": 1}
                )
            self.assertTrue(
                profile.dispatch(
                    {"operation": "release", "arm": "typescript", "pair": 1}
                )["released"]
            )
            with self.assertRaises(ValueError):
                profile.dispatch(
                    {"operation": "release", "arm": "typescript", "pair": 1}
                )
        self.assertEqual(profile.position, 1)

    def test_held_served_or_browser_change_refuses_before_arm(self):
        profile = object.__new__(paired.Profile)
        profile.closed = False
        profile.active = None
        profile.position = 0
        profile.order = [(1, "typescript")]
        profile.executable = Path("/fixed/chromium")
        profile.browser_sha = "expected"
        profile.served = {"typescript": "receipt"}
        with patch.object(paired, "read_regular", return_value=b"changed"):
            with self.assertRaisesRegex(ValueError, "browser_changed"):
                profile.dispatch(
                    {"operation": "activate", "arm": "typescript", "pair": 1}
                )
        with (
            patch.object(paired, "read_regular", return_value=b"expected"),
            patch.object(paired, "digest", return_value="expected"),
            patch.object(profile, "verify_served", return_value="different"),
            patch.object(profile, "start_web"),
            patch.object(profile, "stop_web"),
        ):
            with self.assertRaisesRegex(ValueError, "served_changed"):
                profile.dispatch(
                    {"operation": "activate", "arm": "typescript", "pair": 1}
                )
            self.assertIsNone(profile.active)

    def test_case_proof_missing_duplicate_failed_retry_skip(self):
        row = {
            "title": paired.CASE_TITLE,
            "tests": [
                {"status": "expected", "results": [{"status": "passed", "retry": 0}]}
            ],
        }
        report = {"suites": [{"specs": [row]}]}
        self.assertTrue(paired.case_proof(report))
        for change in [
            lambda r: r["suites"][0]["specs"].clear(),
            lambda r: r["suites"][0]["specs"].append(copy.deepcopy(row)),
            lambda r: r["suites"][0]["specs"][0]["tests"][0]["results"][0].update(
                status="skipped"
            ),
            lambda r: r["suites"][0]["specs"][0]["tests"][0]["results"][0].update(
                retry=1
            ),
            lambda r: r["suites"][0]["specs"][0]["tests"][0]["results"].append(
                {"status": "passed"}
            ),
        ]:
            bad = copy.deepcopy(report)
            change(bad)
            self.assertFalse(paired.case_proof(bad))

    def test_profile_cleanup_attempts_all_owned_resources_and_is_idempotent(self):
        events = []

        class Server:
            def shutdown(self):
                events.append("shutdown")

            def server_close(self):
                events.append("close")

        class Thread:
            def join(self, timeout):
                events.append(("join", timeout))

            def is_alive(self):
                return False

        class Fixture:
            cleanup_verified = True

            def close(self):
                events.append("fixture")

        profile = object.__new__(paired.Profile)
        profile.closed = False
        profile.web = None
        profile.rpc = Server()
        profile.web_thread = Thread()
        profile.rpc_thread = Thread()
        profile.fixture = Fixture()
        profile.close()
        profile.close()
        self.assertEqual(events.count("fixture"), 1)
        self.assertEqual(events.count("close"), 1)

    def test_new_bind_requires_prior_owned_server_closure_and_never_kills_unrelated_listener(
        self,
    ):
        profile = object.__new__(paired.Profile)
        profile.web = object()
        with self.assertRaisesRegex(ValueError, "previous_server_not_closed"):
            profile.start_web("typescript")
        profile.web = None
        with (
            patch.object(paired.socket, "socket") as factory,
            patch.object(paired.subprocess, "Popen") as spawn,
        ):
            factory.return_value.__enter__.return_value.bind.side_effect = OSError(
                "occupied"
            )
            with self.assertRaisesRegex(ValueError, "origin_already_owned"):
                profile.start_web("typescript")
            spawn.assert_not_called()

    def test_exact_harness_source_hold_rejects_mutated_helper_bytes(self):
        harness = "a" * 40
        with tempfile.TemporaryDirectory() as private:
            root = Path(private)
            expected = {
                name: (name + "\n").encode()
                for name in (
                    "scripts/ci_web_paired_profile.py",
                    "scripts/ci_web_performance.py",
                    "scripts/ci_run_tests.py",
                )
            }
            for name, raw in expected.items():
                file = root / name
                file.parent.mkdir(exist_ok=True)
                file.write_bytes(raw)

            def git(argv, **_kwargs):
                if "rev-parse" in argv:
                    return harness.encode()
                return b"".join(
                    b"100644 blob "
                    + paired.hashlib.sha1(
                        b"blob " + str(len(raw)).encode() + b"\0" + raw
                    )
                    .hexdigest()
                    .encode()
                    + b"\t"
                    + name.encode()
                    + b"\0"
                    for name, raw in expected.items()
                )

            with (
                patch.object(
                    paired, "__file__", str(root / "scripts/ci_web_paired_profile.py")
                ),
                patch.object(paired.subprocess, "check_output", side_effect=git),
            ):
                self.assertEqual(set(paired.tooling_snapshot(harness)), set(expected))
                (root / "scripts/ci_web_performance.py").write_text(
                    "modified after Vite"
                )
                with self.assertRaisesRegex(ValueError, "tooling_changed"):
                    paired.tooling_snapshot(harness)
                (root / "scripts/ci_web_performance.py").write_bytes(
                    expected["scripts/ci_web_performance.py"]
                )
                (root / "scripts/__init__.py").write_text("# untrusted shadow")
                with self.assertRaisesRegex(ValueError, "tooling_shadow"):
                    paired.tooling_snapshot(harness)

    def test_owned_command_bounds_both_streams_and_timeout_without_product(self):
        with tempfile.TemporaryDirectory() as private:
            root = Path(private)
            for stream in ("stdout", "stderr"):
                with (
                    self.subTest(stream=stream),
                    self.assertRaisesRegex(ValueError, "output_limit"),
                ):
                    paired.owned_command(
                        [
                            sys.executable,
                            "-c",
                            f'import sys;sys.{stream}.write("x"*4096)',
                        ],
                        root=root,
                        env={},
                        timeout=2,
                        limit=1024,
                    )
            with self.assertRaisesRegex(ValueError, "timeout"):
                paired.owned_command(
                    [sys.executable, "-c", "import time;time.sleep(2)"],
                    root=root,
                    env={},
                    timeout=0.03,
                )

    def test_interruption_restores_exact_prior_handlers(self):
        signals = (paired.signal.SIGTERM, paired.signal.SIGINT, paired.signal.SIGHUP)
        before = {s: paired.signal.getsignal(s) for s in signals}
        with paired.interruption_scope() as state:
            handler = paired.signal.getsignal(paired.signal.SIGTERM)
            self.assertNotEqual(handler, before[paired.signal.SIGTERM])
            handler(paired.signal.SIGTERM, None)
            self.assertTrue(state["requested"])
            with self.assertRaisesRegex(InterruptedError, "paired_interrupted"):
                paired.cancellation_checkpoint()
        self.assertEqual(before, {s: paired.signal.getsignal(s) for s in signals})

    def test_real_signal_during_popen_assignment_and_repeated_cleanup_is_owned(self):
        # Harmless Python sleeper only; signal arrives before Popen returns its
        # new-session child to the caller. A repeated signal arrives in cleanup.
        original_popen, original_terminate = paired.subprocess.Popen, paired.terminate
        children = []

        def created_then_signal(*args, **kwargs):
            child = original_popen(*args, **kwargs)
            children.append(child)
            paired.os.kill(paired.os.getpid(), paired.signal.SIGTERM)
            return child

        def repeated_signal_then_cleanup(child):
            paired.os.kill(paired.os.getpid(), paired.signal.SIGHUP)
            original_terminate(child)

        with (
            tempfile.TemporaryDirectory() as private,
            paired.interruption_scope(),
            patch.object(paired.subprocess, "Popen", side_effect=created_then_signal),
            patch.object(paired, "terminate", side_effect=repeated_signal_then_cleanup),
        ):
            with self.assertRaisesRegex(InterruptedError, "paired_interrupted"):
                paired.owned_command(
                    [sys.executable, "-c", "import time;time.sleep(2)"],
                    root=Path(private),
                    env={},
                    timeout=3,
                )
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].poll())


if __name__ == "__main__":
    unittest.main()
