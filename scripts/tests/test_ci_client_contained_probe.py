# contract-test-file: tooling
"""Pure assertions for finite harmless runtime evidence; never run a probe here."""
import copy
import unittest
import json
from pathlib import Path
import signal
import tempfile
from unittest import mock
from scripts.ci_client_contained_probe import evaluate, verify_compiler_cleanup, new_attempt_root
from scripts import ci_client_owned_lifecycle as lifecycle
from scripts.ci_client_container_launch import Refused


def sample(case="leaf"):
    final = {"ownedShutdownConfirmed": True, "containedClone3Entries": 0,
             "containedClone3Events": 0, "processesEver": 1, "threadCreates": 0}
    measured = {"authority": "authenticated-pid1-private-channel", "acceptanceEligible": False,
                "currentMigrationAcceptance": False, "multiprocessTotalRss": "unavailable-no-aggregation-or-subtraction",
                "status": "observed", "wholeApplicationPeakRssBytes": 40 * 1024**2, "final": final}
    return {"case": case, "cleanupVerified": True, "exitCode": 0,
            "fixtureOutput": {"fixture": case, "privateFds": 0, "selfRssKiB": 1000, "acceptanceEligible": False},
            "collection": {"cleanupVerified": True, "cleanupProblems": [], "metric": "kernel-total-container-memory-not-rss",
                           "memory": {"chargedDiagnosticIncludes": "common-pid1-plus-common-meter-plus-application", "containedRss": measured}}}


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
        measured["final"].update(ownedShutdownConfirmed=False, containedClone3Entries=1, memoryStatus="missing-creation-event")
        evaluate("clone3-untraced", row)
        self.assertFalse(measured["final"]["ownedShutdownConfirmed"])
        self.assertEqual(row["clone3Outcome"], "kernel-success-missing-event-refused")

    # contract-test: tooling
    def test_error_does_not_prove_clone3_success(self):
        row = sample("clone3")
        metric(row)["final"]["containedClone3Entries"] = 1
        row["fixtureOutput"]["syscallErrno"] = 38
        evaluate("clone3", row)
        self.assertEqual(row["clone3Outcome"], "kernel-error-no-success-or-missing-event-proof")

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
            row["collection"][field] = False if field == "cleanupVerified" else ["owned_remove_failed"]
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
        self.assertEqual(row["accountingUnavailable"], "private-controller-deliberately-disconnected")


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
            return {"live": [child.pid + 1], "zombies": [child.pid], "inspectionUnknown": False}

        def launch(argv, **kwargs):
            self.assertTrue(kwargs["start_new_session"])
            kwargs["stdout"].write(b"retained compiler failure while linker lives\n")
            kwargs["stdout"].flush()
            return child

        with tempfile.TemporaryDirectory() as temporary, \
                mock.patch.object(lifecycle.subprocess, "Popen", side_effect=launch), \
                mock.patch.object(lifecycle.os, "waitid", side_effect=waitid), \
                mock.patch.object(lifecycle.os, "killpg", side_effect=lambda group, sig: kills.append((group, sig))), \
                mock.patch.object(lifecycle, "group_state", side_effect=state), \
                mock.patch.object(lifecycle.time, "monotonic", side_effect=monotonic), \
                mock.patch.object(lifecycle.time, "sleep"), \
                mock.patch.object(lifecycle.signal, "signal", return_value=signal.SIG_DFL), \
                mock.patch.object(lifecycle.signal, "getsignal", return_value=signal.SIG_DFL):
            destination = Path(temporary)
            code = lifecycle.run_owned(["fixed-compiler"], cwd=destination, env={}, out=destination, attempt={}, timeout=30)
            receipt = json.loads((destination / "attempt.json").read_bytes())
            self.assertEqual((destination / "process.log").read_bytes(), b"retained compiler failure while linker lives\n")
        self.assertEqual(code, 1 if interrupted_wait else 124)
        self.assertEqual(receipt["reason"], "lifecycle_failed" if interrupted_wait else "timeout")
        self.assertEqual(kills, [(child.pid, signal.SIGTERM), (child.pid, signal.SIGKILL)])
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
        base = {"cleanupVerified": True, "cleanup": {"anchorHeld": True, "liveMembersDrained": True,
                "directChildReaped": True, "inspectionUnknown": False, "groupEmpty": True,
                "remainingZombieMembers": 1}}
        for changed in ({"groupEmpty": False}, {"inspectionUnknown": True}, {"directChildReaped": False}):
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
            self.assertEqual((first / "tools/process-memory-meter").read_bytes(), b"old-elf")
            self.assertEqual((first / "tools/preparation.json").read_text(), "old-preparation")
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
            (root / "test-results/ci-private").symlink_to(target, target_is_directory=True)
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
            with mock.patch("scripts.ci_client_contained_probe.os.geteuid", return_value=-1):
                with self.assertRaises(Refused):
                    new_attempt_root(root)
            self.assertEqual(list((root / "test-results/ci-private").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
