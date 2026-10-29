# contract-test-file: tooling
"""Inert protected dispatch/source/lifecycle checks; never launches a process."""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
PRIVATE = SCRIPTS.parent.name == "after"
PACKET = SCRIPTS.parents[1] if PRIVATE else None
W = PACKET.parents[2] if PRIVATE else SCRIPTS.parent
CONTROL = PACKET / "reference/protected/scripts" if PRIVATE else SCRIPTS


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def load():
    sdk = module("ci_sdk_conformance", CONTROL / "ci_sdk_conformance.py")
    with patch.dict(sys.modules, {"ci_sdk_conformance": sdk}):
        owner = module("ci_sdk_share_dispatch", CONTROL / "ci_sdk_share_dispatch.py")
        with patch.dict(sys.modules, {"ci_sdk_share_dispatch": owner}):
            workflow = module(
                "workflow_dispatch_inert", SCRIPTS / "ci_sdk_workflow_dispatch.py"
            )
    return workflow, sdk, owner


class WorkflowDispatchTests(unittest.TestCase):
    def setUp(self):
        self.m, self.sdk, self.owner = load()
        self.images = (
            json.loads((PACKET / "basis.json").read_text())["sourceImages"]
            if PRIVATE
            else {}
        )

        def image(path):
            relative = path.relative_to(W).as_posix()
            return (
                Path(self.images[relative]).read_bytes()
                if relative in self.images
                else path.read_bytes()
            )

        # Explicit inert projected source tree. Real unchanged verify_programs
        # checks the actual frozen afterimage bytes, not a fabricated passed flag.
        self.addCleanup(patch.stopall)
        patch.object(self.sdk, "regular", side_effect=image).start()
        patch.object(self.m, "regular", side_effect=image).start()
        programs = {
            name: digest
            for name, digest in self.m.PINS.items()
            if name not in self.m.PROTECTED_ONLY_INPUTS
        }
        self.driver = SimpleNamespace(
            root=W,
            trust={"programs": programs, "contracts": {}},
            plan=copy.deepcopy(self.m.EXPECTED_PLAN),
            launches=[],
            failure=None,
            inputs={},
            deadline=100.0,
        )
        self.driver.commands = [
            self.m.fixed_command(W, language) for language in ("rust", "npm", "python")
        ]
        self.options = dict(
            cwd=W,
            capture_output=True,
            text=True,
            timeout=600,
            env={
                "OPENMATES_SDK_CONFORMANCE_PYTHON": sys.executable,
                "CARGO_INCREMENTAL": "0",
            },
            check=False,
        )

    def admit(self):
        with patch.object(self.m.time, "monotonic", return_value=1):
            return self.m.admit(
                self.driver,
                self.driver.commands[len(self.driver.launches)],
                **self.options,
            )

    def test_three_exact_original_commands_and_real_source_pins_admit(self):
        for index, language in enumerate(("rust", "npm", "python")):
            self.driver.launches = [{}] * index
            self.assertEqual(self.admit()["language"], language)

    def test_unknown_argv_fixture_language_and_timeout_never_launch(self):
        command = self.driver.commands[0]
        with patch.object(
            self.m.subprocess, "Popen", side_effect=AssertionError("must not launch")
        ):
            for changed in (
                ["sh", "-c", "anything"],
                command + ["--case"],
                command[:-1] + ["unknown"],
                [*command[:-3], "/tmp/other", *command[-2:]],
            ):
                with self.subTest(changed=changed), self.assertRaises(self.m.Refused):
                    self.m.admit(self.driver, changed, **self.options)
            for timeout in (0, 599, 601, True, float("nan")):
                with self.subTest(timeout=timeout), self.assertRaises(self.m.Refused):
                    self.m.admit(
                        self.driver, command, **{**self.options, "timeout": timeout}
                    )
            with self.assertRaises(self.m.Refused):
                self.m.fixed_command(W, "unknown")

    def test_missing_duplicate_reordered_or_substituted_plan_refuses(self):
        original = copy.deepcopy(self.driver.plan)
        for changed in (
            [],
            original[:-1],
            original + [original[0]],
            list(reversed(original)),
        ):
            self.driver.plan = changed
            with self.assertRaises(self.m.Refused):
                self.admit()
        self.driver.plan = copy.deepcopy(original)
        self.driver.plan[0]["fixtureSha256"] = "0" * 64
        with self.assertRaises(self.m.Refused):
            self.admit()

    def test_expired_nonfinite_deadline_and_wrong_coordinator_identity_refuse(self):
        for deadline in (0, float("inf"), float("nan"), True):
            self.driver.deadline = deadline
            with self.assertRaises(self.m.Refused):
                self.admit()
        self.driver.deadline = 100
        self.options["env"]["OPENMATES_SDK_CONFORMANCE_PYTHON"] = "/tmp/python"
        with self.assertRaises(self.m.Refused):
            self.admit()

    def test_real_changed_or_untrusted_program_and_controller_self_trust_refuse(self):
        first = next(iter(self.m.PINS))
        self.driver.trust["programs"][first] = "0" * 64
        with self.assertRaises(self.m.Refused):
            self.admit()
        self.setUp()
        with (
            patch.object(self.m, "verify_programs"),
            patch.object(self.m, "regular", return_value=b"changed"),
        ):
            with self.assertRaises(self.m.Refused):
                self.admit()
        self.setUp()
        self.driver.trust["programs"]["scripts/ci_sdk_share_dispatch.py"] = "a" * 64
        with patch.object(self.m, "verify_programs"), self.assertRaises(self.m.Refused):
            self.admit()

    def result(self):
        identity = self.driver.plan[0]
        return {
            "capability": self.m.CAPABILITY,
            "language": "rust",
            "fixtureSha256": identity["fixtureSha256"],
            "status": "passed",
            "results": [
                {"id": value, "status": "passed"} for value in identity["vectors"]
            ],
        }

    def test_exact_twenty_three_results_only_and_duplicate_json_fields_refuse(self):
        original = self.result()
        self.m.validate_result(json.dumps(original), self.driver.plan[0])
        changes = []
        for key, value in (
            ("language", "npm"),
            ("fixtureSha256", "0" * 64),
            ("status", "failed"),
        ):
            row = copy.deepcopy(original)
            row[key] = value
            changes.append(row)
        for rows in (
            [],
            original["results"][:-1],
            original["results"] + [original["results"][0]],
            [original["results"][0]] * 23,
        ):
            row = copy.deepcopy(original)
            row["results"] = rows
            changes.append(row)
        row = copy.deepcopy(original)
        row["results"][0]["id"] = "unknown"
        changes.append(row)
        row = copy.deepcopy(original)
        row["results"][0]["status"] = "skipped"
        changes.append(row)
        for changed in changes:
            with self.subTest(changed=changed), self.assertRaises(self.m.Refused):
                self.m.validate_result(json.dumps(changed), self.driver.plan[0])
        raw = json.dumps(original).replace(
            '"status": "passed"', '"status": "failed", "status": "passed"', 1
        )
        with self.assertRaises(ValueError):
            self.m.validate_result(raw, self.driver.plan[0])

    def child(self, events):
        def channel():
            return SimpleNamespace(close=lambda: events.append("close"))

        child = SimpleNamespace(
            pid=12345, returncode=None, stdout=channel(), stderr=channel()
        )

        def waited(timeout):
            self.assertEqual(timeout, self.owner.REAP_GRACE)
            events.append("reap")
            child.returncode = 0

        child.wait = waited
        return child

    def test_group_anchor_held_through_term_kill_then_reap(self):
        events = []
        child = self.child(events)

        def observed(kind, pid, flags):
            self.assertEqual(pid, child.pid)
            self.assertTrue(flags & self.m.os.WNOWAIT)
            self.assertIsNone(child.returncode)
            events.append("observe")
            return object()

        with (
            patch.object(self.m.os, "getpgid", return_value=child.pid),
            patch.object(self.m.os, "waitid", side_effect=observed),
            patch.object(
                self.m.os,
                "killpg",
                side_effect=lambda pid, kind: events.append(
                    "term" if kind == self.owner.signal.SIGTERM else "kill"
                ),
            ),
            patch.object(
                self.m.time, "sleep", side_effect=lambda seconds: events.append("grace")
            ),
        ):
            self.m.retire(child)
        self.assertEqual(events, ["observe", "term", "grace", "kill", "reap"])

    def test_foreign_or_reaped_group_is_never_signalled(self):
        for reaped, group in ((False, 999), (True, 12345)):
            child = self.child([])
            child.returncode = 0 if reaped else None
            with (
                patch.object(self.m.os, "getpgid", return_value=group),
                patch.object(self.m.os, "killpg") as kill,
                self.assertRaises(self.m.Refused),
            ):
                self.m.retire(child)
            kill.assert_not_called()

    def test_cancel_inside_popen_assignment_is_negative_and_retires_original(self):
        events = []
        child = self.child(events)
        handlers = {}

        def install(kind, handler):
            previous = handlers.get(kind)
            handlers[kind] = handler
            return previous

        def popen(*args, **options):
            self.assertIs(options["start_new_session"], True)
            events.append("spawn")
            handlers[self.owner.signal.SIGTERM](self.owner.signal.SIGTERM, None)
            return child

        def retire(original):
            self.assertIs(original, child)
            handlers[self.owner.signal.SIGHUP](self.owner.signal.SIGHUP, None)
            events.extend(["term", "grace", "kill", "reap"])
            child.returncode = -15

        with (
            patch.object(self.m, "admit", return_value=self.driver.plan[0]),
            patch.object(self.owner.signal, "signal", side_effect=install),
            patch.object(self.m.subprocess, "Popen", side_effect=popen),
            patch.object(self.m, "retire", side_effect=retire),
            patch.object(self.m.time, "monotonic", return_value=1),
            self.assertRaises(self.m.Refused),
        ):
            self.m.run_workflow(self.driver, self.driver.commands[0], **self.options)
        self.assertEqual(events[:5], ["spawn", "term", "grace", "kill", "reap"])
        self.assertEqual(self.driver.launches[0]["status"], "started")
        self.assertEqual(self.driver.failure["code"], "share_cancelled")

    def test_running_deadline_and_output_bound_fail_with_metrics_and_original_cleanup(
        self,
    ):
        for mode in ("deadline", "output"):
            self.setUp()
            events = []
            child = self.child(events)
            key = SimpleNamespace(
                fileobj=SimpleNamespace(fileno=lambda: 55), data="stdout"
            )

            class Selector:
                def register(self, *args):
                    pass

                def get_map(self):
                    return {1: key}

                def select(self, timeout):
                    return [(key, 1)]

                def close(self):
                    events.append("selector-close")

            ticks = iter([1, 101])
            clock = (lambda: next(ticks, 101)) if mode == "deadline" else (lambda: 1)

            def retired(original):
                self.assertIs(original, child)
                events.extend(["term", "grace", "kill", "reap"])
                child.returncode = -9

            with (
                patch.object(self.m, "admit", return_value=self.driver.plan[0]),
                patch.object(self.owner.signal, "signal"),
                patch.object(self.m.subprocess, "Popen", return_value=child),
                patch.object(self.m.os, "getpgid", return_value=child.pid),
                patch.object(self.m, "observed_exit", return_value=None),
                patch.object(self.m.selectors, "DefaultSelector", Selector),
                patch.object(self.m.os, "read", return_value=b"x" * (self.m.LIMIT + 1)),
                patch.object(self.m, "retire", side_effect=retired),
                patch.object(self.m.time, "monotonic", side_effect=clock),
                self.assertRaises(self.m.Refused),
            ):
                self.m.run_workflow(
                    self.driver, self.driver.commands[0], **self.options
                )
            self.assertEqual(events[:4], ["term", "grace", "kill", "reap"])
            self.assertEqual(self.driver.launches[0]["status"], "started")
            self.assertEqual(
                self.driver.failure["code"],
                "driver_deadline" if mode == "deadline" else "driver_output_bound",
            )
            self.assertEqual(
                self.driver.failure["stdoutBytes"],
                0 if mode == "deadline" else self.m.LIMIT + 1,
            )

    def test_full_result_passes_only_after_retire_and_late_cancellation_still_refuses(
        self,
    ):
        for cancelled in (False, True):
            self.setUp()
            events = []
            child = self.child(events)
            handlers = {}
            child.stdout.fileno = lambda: 55
            child.stderr.fileno = lambda: 56

            class Selector:
                def __init__(self):
                    self.keys = {}

                def register(self, channel, mask, name):
                    self.keys[channel.fileno()] = SimpleNamespace(
                        fileobj=channel, data=name
                    )

                def unregister(self, channel):
                    del self.keys[channel.fileno()]

                def get_map(self):
                    return self.keys

                def select(self, timeout):
                    return [(next(iter(self.keys.values())), 1)]

                def close(self):
                    events.append("selector-close")

            chunks = iter([json.dumps(self.result()).encode(), b"", b""])
            ended = SimpleNamespace(si_code=self.m.os.CLD_EXITED, si_status=0)
            observations = iter([None, None, None, ended])

            def install(kind, handler):
                previous = handlers.get(kind)
                handlers[kind] = handler
                return previous

            def retired(original):
                self.assertIs(original, child)
                self.assertEqual(self.driver.launches[0]["status"], "started")
                events.extend(["term", "grace", "kill", "reap"])
                child.returncode = 0
                if cancelled:
                    handlers[self.owner.signal.SIGTERM](self.owner.signal.SIGTERM, None)

            with (
                patch.object(self.m, "admit", return_value=self.driver.plan[0]),
                patch.object(self.owner.signal, "signal", side_effect=install),
                patch.object(self.m.subprocess, "Popen", return_value=child),
                patch.object(self.m.os, "getpgid", return_value=child.pid),
                patch.object(
                    self.m,
                    "observed_exit",
                    side_effect=lambda child: next(observations),
                ),
                patch.object(self.m.selectors, "DefaultSelector", Selector),
                patch.object(self.m.os, "read", side_effect=lambda *args: next(chunks)),
                patch.object(self.m, "retire", side_effect=retired),
                patch.object(self.m.time, "monotonic", return_value=1),
                patch.object(self.m, "verify_programs"),
            ):
                if cancelled:
                    with self.assertRaises(self.m.Refused):
                        self.m.run_workflow(
                            self.driver, self.driver.commands[0], **self.options
                        )
                    self.assertEqual(self.driver.launches[0]["status"], "started")
                else:
                    result = self.m.run_workflow(
                        self.driver, self.driver.commands[0], **self.options
                    )
                    self.assertEqual(result.returncode, 0)
                    self.assertEqual(self.driver.launches[0]["status"], "passed")
            self.assertEqual(events[:4], ["term", "grace", "kill", "reap"])

    def test_old_dispatch_source_restores_exact_and_global_budget_is_held(self):
        after = (SCRIPTS / "ci_sdk_conformance_exec.py").read_text()
        start = after.index(
            "        # Only the three externally admitted fixed Workflow"
        )
        end = after.index("        require(cwd == self.root", start)
        self.assertEqual(
            hashlib.sha256((after[:start] + after[end:]).encode()).hexdigest(),
            "e9de9394fb60ff1531debce8f4709b7abdd168c6ae72a1cf1a4fc2f8484a5fb5",
        )
        source = (CONTROL / "ci_sdk_conformance.py").read_text()
        self.assertIn("BUDGET = 2700", source)
        self.assertIn("str(root), str(report), str(deadline)], 1500)", source)

    def test_existing_work_capability_only_and_all_sixty_nine_vectors_required(self):
        self.assertEqual(self.m.CAPABILITY, "work.project-workflow-file-sync.v1")
        self.assertEqual(sum(len(row["vectors"]) for row in self.m.EXPECTED_PLAN), 69)
        for identity in self.driver.plan:
            value = self.result()
            value["language"] = identity["language"]
            self.m.validate_result(json.dumps(value), identity)
            for wrong in (
                "session.projects.workflow-file-sync.v1",
                "session.embeds.admitted-share-url.v1",
            ):
                value["capability"] = wrong
                with self.assertRaises(self.m.Refused):
                    self.m.validate_result(json.dumps(value), identity)
        command = self.driver.commands[0]
        with self.assertRaises(self.m.Refused):
            self.m.admit(
                self.driver,
                [
                    part.replace(
                        self.m.CAPABILITY, "session.projects.workflow-file-sync.v1"
                    )
                    for part in command
                ],
                **self.options,
            )

    def test_schema_fixture_mirror_and_all_original_ownership_primitives_are_real_inputs(
        self,
    ):
        self.assertIs(self.m.Cancellation, self.owner.Cancellation)
        self.assertIs(self.m.observed_exit, self.owner.observed_exit)
        self.assertIs(self.m.retire, self.owner.retire)
        fixture = "tests/sdk-conformance/fixtures/workflow-file-sync.json"
        mirror = "packages/openmates-rust/tests/fixtures/workflow-file-sync.json"
        self.assertEqual(self.m.PINS[fixture], self.m.PINS[mirror])
        schema = "tests/sdk-conformance/schemas/workflow-file-sync.schema.json"
        for name in (
            fixture,
            mirror,
            schema,
            "packages/openmates-session-bindings/src/session_workflow_files.rs",
        ):
            digest = self.driver.trust["programs"].pop(name)
            with self.assertRaises(self.m.Refused):
                self.admit()
            self.driver.trust["programs"][name] = digest

    def test_unknown_result_fields_cannot_grant_acceptance(self):
        value = self.result()
        value["trusted"] = True
        with self.assertRaises(self.m.Refused):
            self.m.validate_result(json.dumps(value), self.driver.plan[0])
        value = self.result()
        value["results"][0]["skipped"] = False
        with self.assertRaises(self.m.Refused):
            self.m.validate_result(json.dumps(value), self.driver.plan[0])


if __name__ == "__main__":
    unittest.main()
