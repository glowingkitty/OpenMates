# contract-test-file: tooling
"""Pure assertions for finite harmless runtime evidence; never run a probe here."""

import copy
import unittest
import json
from pathlib import Path
import signal
import tempfile
import types
from unittest import mock
from scripts.ci_client_contained_probe import (
    evaluate,
    verify_compiler_cleanup,
    new_attempt_root,
    parse_counter_diagnostics,
    counter_diagnostics,
    DIAGNOSTIC_PHASES,
    DIAGNOSTIC_STATUS,
    DIAGNOSTIC_ROLLUP,
)
from scripts import ci_client_owned_lifecycle as lifecycle
from scripts.ci_client_container_launch import Refused


def sample(case="leaf"):
    final = {
        "ownedShutdownConfirmed": True,
        "containedClone3Entries": 0,
        "containedClone3Events": 0,
        "processesEver": 1,
        "threadCreates": 0,
    }
    measured = {
        "authority": "authenticated-pid1-private-channel",
        "acceptanceEligible": False,
        "currentMigrationAcceptance": False,
        "multiprocessTotalRss": "unavailable-no-aggregation-or-subtraction",
        "status": "observed",
        "wholeApplicationPeakRssBytes": 40 * 1024**2,
        "final": final,
    }
    return {
        "case": case,
        "cleanupVerified": True,
        "exitCode": 0,
        "fixtureOutput": {
            "fixture": case,
            "privateFds": 0,
            "selfRssKiB": 1000,
            "acceptanceEligible": False,
        },
        "collection": {
            "cleanupVerified": True,
            "cleanupProblems": [],
            "metric": "kernel-total-container-memory-not-rss",
            "memory": {
                "chargedDiagnosticIncludes": "common-pid1-plus-common-meter-plus-application",
                "containedRss": measured,
            },
        },
    }


def metric(row):
    return row["collection"]["memory"]["containedRss"]


class ProbeEvidence(unittest.TestCase):
    # contract-test: tooling
    def test_unavailable_is_not_single_group_success(self):
        row = sample()
        metric(row)["status"] = "unavailable"
        with self.assertRaises(Refused):
            evaluate("leaf", row)

    # contract-test: tooling
    def test_actual_private_descriptor_blocks_success(self):
        row = sample()
        row["fixtureOutput"]["privateFds"] = 1
        with self.assertRaises(Refused):
            evaluate("leaf", row)

    # contract-test: tooling
    def test_namespace_cleanup_does_not_fix_positive_accounting(self):
        row = sample()
        metric(row)["final"]["ownedShutdownConfirmed"] = False
        with self.assertRaises(Refused):
            evaluate("leaf", row)

    # contract-test: tooling
    def test_missing_event_negative_retains_failed_accounting(self):
        row = sample("clone3-untraced")
        row["exitCode"] = 125
        measured = metric(row)
        measured.update(status="unavailable", wholeApplicationPeakRssBytes=None)
        measured["final"].update(
            ownedShutdownConfirmed=False,
            containedClone3Entries=1,
            memoryStatus="missing-creation-event",
        )
        evaluate("clone3-untraced", row)
        self.assertFalse(measured["final"]["ownedShutdownConfirmed"])
        self.assertEqual(row["clone3Outcome"], "kernel-success-missing-event-refused")

    # contract-test: tooling
    def test_error_does_not_prove_clone3_success(self):
        row = sample("clone3")
        metric(row)["final"]["containedClone3Entries"] = 1
        row["fixtureOutput"]["syscallErrno"] = 38
        evaluate("clone3", row)
        self.assertEqual(
            row["clone3Outcome"], "kernel-error-no-success-or-missing-event-proof"
        )

    # contract-test: tooling
    def test_no_errno_and_no_creation_event_cannot_pass(self):
        row = sample("clone3")
        metric(row)["final"]["containedClone3Entries"] = 1
        with self.assertRaises(Refused):
            evaluate("clone3", row)

    # contract-test: tooling
    def test_child_total_must_stay_unavailable(self):
        row = sample("child")
        metric(row)["final"]["processesEver"] = 2
        with self.assertRaises(Refused):
            evaluate("child", row)
        metric(row).update(status="unavailable", wholeApplicationPeakRssBytes=None)
        evaluate("child", row)

    # contract-test: tooling
    def test_late_worker_requires_actual_post_leader_allocation(self):
        row = sample("late-worker")
        metric(row)["final"]["threadCreates"] = 1
        row["fixtureOutput"].update(lateWorker=False, selfRssKiB=32768)
        with self.assertRaises(Refused):
            evaluate("late-worker", row)
        row["fixtureOutput"]["lateWorker"] = True
        evaluate("late-worker", row)

    # contract-test: tooling
    def test_waited_hwm_cannot_be_below_app_report(self):
        row = sample()
        row["fixtureOutput"]["selfRssKiB"] = 50000
        with self.assertRaises(Refused):
            evaluate("leaf", row)

    # contract-test: tooling
    def test_cleanup_failure_always_refuses(self):
        original = sample()
        for field in ("cleanupVerified", "cleanupProblems"):
            row = copy.deepcopy(original)
            row["collection"][field] = (
                False if field == "cleanupVerified" else ["owned_remove_failed"]
            )
            with self.assertRaises(Refused):
                evaluate("leaf", row)

    # contract-test: tooling
    def test_file_receipt_is_not_private_final_authority(self):
        row = sample()
        metric(row)["authority"] = "status-file"
        with self.assertRaises(Refused):
            evaluate("leaf", row)

    # contract-test: tooling
    def test_charged_bytes_label_and_acceptance_must_stay_exact(self):
        row = sample()
        row["collection"]["metric"] = "RSS"
        with self.assertRaises(Refused):
            evaluate("leaf", row)
        row = sample()
        metric(row)["acceptanceEligible"] = True
        with self.assertRaises(Refused):
            evaluate("leaf", row)

    # contract-test: tooling
    def test_disconnected_private_channel_cannot_pass_with_rss(self):
        row = sample("controller-disconnect")
        row["exitCode"] = 1
        row["collection"]["code"] = "held_collection_or_release_failed"
        with self.assertRaises(Refused):
            evaluate("controller-disconnect", row)
        row["collection"]["memory"] = None
        evaluate("controller-disconnect", row)
        self.assertEqual(
            row["accountingUnavailable"], "private-controller-deliberately-disconnected"
        )


class CompilerGroupCleanup(unittest.TestCase):
    def exercise(self, interrupted_wait):
        # The exited driver remains waitable (WNOWAIT), with an inherited live
        # assembler/linker until group SIGKILL. No process or signal is real.
        class Child:
            pid = 31001
            returncode = None
            reaped = False

            def wait(child, timeout):
                self.assertEqual(kills[-1], (child.pid, signal.SIGKILL))
                child.reaped = True
                child.returncode = 0
                return 0

        child = Child()
        clock = [0]
        waits = [0]
        kills = []

        def monotonic():
            clock[0] += 16
            return clock[0]

        def waitid(*args):
            waits[0] += 1
            self.assertTrue(args[-1] & lifecycle.os.WNOWAIT)
            if interrupted_wait and waits[0] == 1:
                raise RuntimeError("compiler wait failed after ownership")
            return None

        def state(group):
            self.assertEqual(group, child.pid)
            if child.reaped:
                return {"live": [], "zombies": [], "inspectionUnknown": False}
            if kills and kills[-1][1] == signal.SIGKILL:
                return {"live": [], "zombies": [child.pid], "inspectionUnknown": False}
            return {
                "live": [child.pid + 1],
                "zombies": [child.pid],
                "inspectionUnknown": False,
            }

        def launch(argv, **kwargs):
            self.assertTrue(kwargs["start_new_session"])
            kwargs["stdout"].write(b"retained compiler failure while linker lives\n")
            kwargs["stdout"].flush()
            return child

        with (
            tempfile.TemporaryDirectory() as temporary,
            mock.patch.object(lifecycle.subprocess, "Popen", side_effect=launch),
            mock.patch.object(lifecycle.os, "waitid", side_effect=waitid),
            mock.patch.object(
                lifecycle.os,
                "killpg",
                side_effect=lambda group, sig: kills.append((group, sig)),
            ),
            mock.patch.object(lifecycle, "group_state", side_effect=state),
            mock.patch.object(lifecycle.time, "monotonic", side_effect=monotonic),
            mock.patch.object(lifecycle.time, "sleep"),
            mock.patch.object(lifecycle.signal, "signal", return_value=signal.SIG_DFL),
            mock.patch.object(
                lifecycle.signal, "getsignal", return_value=signal.SIG_DFL
            ),
        ):
            destination = Path(temporary)
            code = lifecycle.run_owned(
                ["fixed-compiler"],
                cwd=destination,
                env={},
                out=destination,
                attempt={},
                timeout=30,
            )
            receipt = json.loads((destination / "attempt.json").read_bytes())
            self.assertEqual(
                (destination / "process.log").read_bytes(),
                b"retained compiler failure while linker lives\n",
            )
        self.assertEqual(code, 1 if interrupted_wait else 124)
        self.assertEqual(
            receipt["reason"], "lifecycle_failed" if interrupted_wait else "timeout"
        )
        self.assertEqual(
            kills, [(child.pid, signal.SIGTERM), (child.pid, signal.SIGKILL)]
        )
        self.assertTrue(child.reaped)
        self.assertTrue(receipt["cleanup"]["anchorHeld"])
        self.assertTrue(receipt["cleanup"]["liveMembersDrained"])
        self.assertTrue(receipt["cleanup"]["directChildReaped"])
        self.assertTrue(receipt["cleanup"]["groupEmpty"])
        self.assertEqual(receipt["cleanup"]["remainingZombieMembers"], 1)
        verify_compiler_cleanup(receipt)

    # contract-test: tooling
    def test_timeout_kills_descendant_group_before_direct_child_reap(self):
        self.exercise(False)

    # contract-test: tooling
    def test_wait_exception_still_drains_owned_descendants_and_retains_log(self):
        self.exercise(True)

    # contract-test: tooling
    def test_nonempty_or_unknown_compiler_group_never_admits_elf(self):
        base = {
            "cleanupVerified": True,
            "cleanup": {
                "anchorHeld": True,
                "liveMembersDrained": True,
                "directChildReaped": True,
                "inspectionUnknown": False,
                "groupEmpty": True,
                "remainingZombieMembers": 1,
            },
        }
        for changed in (
            {"groupEmpty": False},
            {"inspectionUnknown": True},
            {"directChildReaped": False},
        ):
            value = copy.deepcopy(base)
            value["cleanup"].update(changed)
            original = copy.deepcopy(value)
            with self.assertRaises(Refused):
                verify_compiler_cleanup(value)
            self.assertEqual(value, original)


class AttemptIsolation(unittest.TestCase):
    # contract-test: tooling
    def test_retry_preserves_old_elf_preparation_and_case_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "test-results").mkdir()
            first = new_attempt_root(root)
            (first / "tools").mkdir()
            (first / "tools/process-memory-meter").write_bytes(b"old-elf")
            (first / "tools/preparation.json").write_text("old-preparation")
            (first / "cases").mkdir()
            (first / "cases/leaf").write_text("old-state")
            second = new_attempt_root(root)
            self.assertNotEqual(first, second)
            self.assertEqual(list(second.iterdir()), [])
            self.assertEqual(first.stat().st_mode & 0o777, 0o700)
            self.assertEqual(second.stat().st_mode & 0o777, 0o700)
            self.assertEqual(
                (first / "tools/process-memory-meter").read_bytes(), b"old-elf"
            )
            self.assertEqual(
                (first / "tools/preparation.json").read_text(), "old-preparation"
            )
            self.assertEqual((first / "cases/leaf").read_text(), "old-state")

    # contract-test: tooling
    def test_existing_fixed_directory_is_never_adopted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old = root / "test-results/ci-private/contained-tools"
            old.mkdir(parents=True)
            old.parent.chmod(0o700)
            (old / "process-memory-meter").write_bytes(b"stale")
            created = new_attempt_root(root)
            self.assertNotEqual(created, old)
            self.assertEqual(list(created.iterdir()), [])
            self.assertEqual((old / "process-memory-meter").read_bytes(), b"stale")

    # contract-test: tooling
    def test_symlink_parent_cannot_admit_attempt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "test-results").mkdir()
            target = root / "other"
            target.mkdir()
            (root / "test-results/ci-private").symlink_to(
                target, target_is_directory=True
            )
            with self.assertRaises(Refused):
                new_attempt_root(root)
            self.assertEqual(list(target.iterdir()), [])

    # contract-test: tooling
    def test_writable_parent_cannot_admit_attempt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parent = root / "test-results/ci-private"
            parent.mkdir(parents=True)
            parent.chmod(0o777)
            with self.assertRaises(Refused):
                new_attempt_root(root)
            self.assertEqual(list(parent.iterdir()), [])

    # contract-test: tooling
    def test_foreign_owner_cannot_admit_attempt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "test-results").mkdir()
            with mock.patch(
                "scripts.ci_client_contained_probe.os.geteuid", return_value=-1
            ):
                with self.assertRaises(Refused):
                    new_attempt_root(root)
            self.assertEqual(list((root / "test-results/ci-private").iterdir()), [])


class AttemptLaunchBoundary(unittest.TestCase):
    # contract-test: tooling
    def config(self, root, attempt):
        import hashlib
        import os
        import time
        from scripts.ci_client_container_launch import Config

        private = attempt / "cases"
        private.mkdir(mode=0o700)
        state = private / "leaf"
        state.mkdir(mode=0o700)
        executable = root / "fixed-supervisor"
        executable.write_bytes(b"synthetic pinned supervisor")
        now = time.monotonic()
        return Config(
            source_root=root, private_root=private, source="a" * 40,
            image="sha256:" + "b" * 64, runtime_key="c" * 64,
            gateway="d" * 64, owner="synthetic-contained-unit", arm="rust", pair=1,
            argv=(str(executable),), env={"HOME": str(state)}, cwd=state,
            readonly_paths=(executable,), state_root=state, conditions=(),
            deadline=now + 30, work_deadline=now + 18, memory_limit=1024,
            pids_limit=8, cpus="1", uid=os.getuid(), gid=os.getgid(),
            supervisor=executable,
            supervisor_sha256=hashlib.sha256(executable.read_bytes()).hexdigest(),
        )

    # contract-test: tooling
    def test_each_fresh_retry_passes_actual_unchanged_launch_validator(self):
        from scripts.ci_client_container_launch import validate

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "test-results").mkdir()
            first = new_attempt_root(root)
            second = new_attempt_root(root)
            self.assertNotEqual(first, second)
            for attempt in (first, second):
                cfg = self.config(root, attempt)
                self.assertIs(validate(cfg), cfg)
                self.assertEqual(attempt.stat().st_mode & 0o777, 0o700)

    # contract-test: tooling
    def test_previous_sibling_layout_is_refused_by_actual_validator(self):
        from scripts.ci_client_container_launch import validate

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old = root / "test-results/ci-private/contained-attempt-old"
            old.mkdir(parents=True, mode=0o700)
            cfg = self.config(root, old)
            with self.assertRaisesRegex(Refused, "disposable_ci_state_required"):
                validate(cfg)

    # contract-test: tooling
    def test_symlink_memory_parent_is_refused_before_child_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parent = root / "test-results/ci-private"
            parent.mkdir(parents=True, mode=0o700)
            target = root / "other"
            target.mkdir()
            (parent / "client-memory").symlink_to(target, target_is_directory=True)
            with self.assertRaises(Refused):
                new_attempt_root(root)
            self.assertEqual(list(target.iterdir()), [])

    # contract-test: tooling
    def test_writable_memory_parent_is_refused_before_child_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parent = root / "test-results/ci-private/client-memory"
            parent.mkdir(parents=True, mode=0o700)
            parent.parent.chmod(0o700)
            parent.chmod(0o777)
            with self.assertRaises(Refused):
                new_attempt_root(root)
            self.assertEqual(list(parent.iterdir()), [])


class CounterDiagnostics(unittest.TestCase):
    # contract-test: tooling
    def records(self):
        return [
            {
                "kind": "contained-rss-v1",
                "phase": phase,
                "pid": 7,
                "startTicks": "123",
                "beginNs": str(1000 + index * 100),
                "endNs": str(1010 + index * 100),
                "ruMaxKiB": 19000,
                "statusKiB": dict.fromkeys(DIAGNOSTIC_STATUS, 18000),
                "rollupKiB": dict.fromkeys(DIAGNOSTIC_ROLLUP, 18100),
            }
            for index, phase in enumerate(DIAGNOSTIC_PHASES)
        ]

    def encoded(self, records):
        return b"".join(
            (json.dumps(row, separators=(",", ":")) + "\n").encode() for row in records
        )

    # contract-test: tooling
    def test_complete_observations_never_authorize_or_replace_metrics(self):
        rows = self.records()
        result = parse_counter_diagnostics(self.encoded(rows))
        self.assertEqual(result["status"], "complete-diagnostic")
        self.assertEqual(result["samples"], rows)
        self.assertEqual(
            result["authority"], "none-application-claimed-diagnostic-only"
        )
        self.assertFalse(result["acceptanceEligible"])
        self.assertFalse(result["currentMigrationAcceptance"])
        self.assertFalse(result["simultaneous"])
        self.assertFalse(
            {
                "memory",
                "final",
                "wholeApplicationPeakRssBytes",
                "steadyRssBytes",
                "retainedRssBytes",
            }
            & result.keys()
        )

    # contract-test: tooling
    def test_incomplete_and_missing_kernel_categories_remain_diagnostic_only(self):
        rows = self.records()[:2]
        rows[0]["ruMaxKiB"] = None
        rows[0]["statusKiB"] = dict.fromkeys(DIAGNOSTIC_STATUS)
        rows[0]["rollupKiB"] = dict.fromkeys(DIAGNOSTIC_ROLLUP)
        result = parse_counter_diagnostics(self.encoded(rows))
        self.assertEqual(result["status"], "incomplete-diagnostic")
        self.assertEqual(result["samples"], rows)
        self.assertFalse(result["acceptanceEligible"])

    # contract-test: tooling
    def test_hostile_or_unclosed_frames_never_raise_or_supply_authority(self):
        mutations = []
        for field, value in [
            ("pid", True),
            ("pid", -1),
            ("startTicks", "01"),
            ("beginNs", "18446744073709551616"),
            ("endNs", "1"),
            ("phase", "ready"),
            ("ruMaxKiB", -1),
            ("ruMaxKiB", 18446744073709551616),
            ("acceptanceEligible", True),
        ]:
            rows = self.records()
            rows[0][field] = value
            mutations.append(self.encoded(rows))
        rows = self.records()
        rows[1]["pid"] = 8
        mutations.append(self.encoded(rows))
        rows = self.records()
        rows[1]["startTicks"] = "124"
        mutations.append(self.encoded(rows))
        rows = self.records()
        rows[1]["beginNs"] = "999"
        mutations.append(self.encoded(rows))
        rows = self.records()
        rows[0]["statusKiB"]["hostname"] = 1
        mutations.append(self.encoded(rows))
        mutations += [
            b"x" * 3841,
            self.encoded(self.records() + [self.records()[0]]),
            b"[" * 1500 + b"]" * 1500,
            b'{"kind":1,"kind":2}\n',
            b"\xff",
            b"[]\n",
        ]
        for raw in mutations:
            with self.subTest(raw_length=len(raw)):
                result = parse_counter_diagnostics(raw)
                self.assertEqual(result["status"], "unavailable-diagnostic")
                self.assertEqual(result["samples"], [])
                self.assertFalse(result["acceptanceEligible"])

    # contract-test: tooling
    def test_worst_case_finite_frames_fit_one_linux_pipe_page(self):
        rows = self.records()
        for index, row in enumerate(rows):
            row.update(
                pid=2147483647,
                startTicks="18446744073709551615",
                beginNs="18446744073709551615",
                endNs="18446744073709551615",
                ruMaxKiB=9223372036854775807,
            )
            row["statusKiB"] = dict.fromkeys(DIAGNOSTIC_STATUS, 18446744073709551615)
            row["rollupKiB"] = dict.fromkeys(DIAGNOSTIC_ROLLUP, 18446744073709551615)
        raw = self.encoded(rows)
        self.assertTrue(all(len(line) < 768 for line in raw.splitlines()))
        self.assertLessEqual(len(raw), 3840)
        self.assertEqual(
            parse_counter_diagnostics(raw)["status"], "complete-diagnostic"
        )

    # contract-test: tooling
    def test_context_configuration_omits_hostname_and_remains_non_authorizing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = root / "fixture"
            fixture.write_bytes(b"synthetic-elf-only")
            cfg = types.SimpleNamespace(
                source="a" * 40,
                private_root=root / "attempt/cases",
                source_root=root,
                argv=[str(fixture)],
            )
            launch = types.SimpleNamespace(
                reader=types.SimpleNamespace(fd=40, directory=(1, 2))
            )
            values = {
                "cpu.max": b"100000 100000\n",
                "cpuset.cpus.effective": b"1-2\n",
                "cpuset.mems.effective": b"0\n",
                "memory.max": b"268435456\n",
                "memory.high": b"max\n",
                "memory.swap.max": b"0\n",
            }
            with (
                mock.patch(
                    "scripts.ci_client_contained_probe.os.uname",
                    return_value=types.SimpleNamespace(
                        release="6.8.0-test",
                        nodename="NEVER_EMIT_HOSTNAME",
                        version="NEVER_EMIT_VERSION",
                    ),
                ),
                mock.patch(
                    "scripts.ci_client_contained_probe.os.sysconf",
                    side_effect=lambda name: {
                        "SC_PAGESIZE": 4096,
                        "SC_NPROCESSORS_ONLN": 8,
                        "SC_NPROCESSORS_CONF": 16,
                        "SC_CLK_TCK": 100,
                    }[name],
                ),
                mock.patch(
                    "scripts.ci_client_contained_probe.os.sched_getaffinity",
                    return_value={0, 1},
                ),
                mock.patch(
                    "scripts.ci_client_contained_probe.os.fstat",
                    return_value=types.SimpleNamespace(st_dev=1, st_ino=2),
                ),
                mock.patch(
                    "scripts.ci_client_contained_probe.os.open",
                    side_effect=lambda name, *args, **kwargs: name,
                ),
                mock.patch(
                    "scripts.ci_client_contained_probe.os.read",
                    side_effect=lambda fd, size: values[fd],
                ),
                mock.patch("scripts.ci_client_contained_probe.os.close"),
            ):
                value = counter_diagnostics(cfg, launch, self.encoded(self.records()))
            self.assertEqual(
                value["environmentDiagnostic"]["kernelRelease"], "6.8.0-test"
            )
            self.assertEqual(value["environmentDiagnostic"]["pageSizeBytes"], 4096)
            self.assertEqual(
                value["cgroupConfigurationDiagnostic"]["cpu.max"], "100000 100000"
            )
            self.assertNotIn("NEVER_EMIT", json.dumps(value))
            self.assertFalse(value["acceptanceEligible"])
            self.assertEqual(value["context"]["sourceCommit"], "a" * 40)
            self.assertEqual(value["context"]["case"], "long-lived")

    # contract-test: tooling
    def test_optional_unreadable_context_does_not_change_primary_measurement(self):
        with (
            mock.patch(
                "scripts.ci_client_contained_probe.os.uname", side_effect=OSError
            ),
            mock.patch(
                "scripts.ci_client_contained_probe.os.sysconf", side_effect=OSError
            ),
            mock.patch(
                "scripts.ci_client_contained_probe.os.sched_getaffinity",
                side_effect=OSError,
            ),
        ):
            value = counter_diagnostics(
                types.SimpleNamespace(), types.SimpleNamespace(), b""
            )
        self.assertEqual(value["contextStatus"], "unavailable")
        self.assertEqual(
            value["cgroupConfigurationDiagnostic"]["status"], "unavailable"
        )
        self.assertEqual(value["status"], "incomplete-diagnostic")
        self.assertFalse(value["acceptanceEligible"])


if __name__ == "__main__":
    unittest.main()
