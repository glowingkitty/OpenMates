"""Pure contained admission/accounting negatives; no socket/proc/fork/runtime probes."""
# contract-test-file: tooling
from pathlib import Path
from types import SimpleNamespace
import socket
import struct
import threading
import unittest
from unittest.mock import Mock, patch
from scripts import ci_client_contained_meter as meter


def fields():
    return {"Uid": ["1001"] * 4, "Gid": ["1001"] * 4, "NSpid": ["4321", "1"],
            "CapInh": ["0000000000000000"], "CapPrm": ["0000000000000000"], "CapEff": ["0000000000000000"],
            "CapBnd": ["0000000000000000"], "CapAmb": ["0000000000000000"], "NoNewPrivs": ["1"]}


def outside():
    obj = object.__new__(meter.Outside)
    obj.namespace = (1, 2)
    obj.nsfd = 9
    obj.dirfd = None
    obj.markers = []
    obj.lifecycle = "ephemeral-command"
    obj.launch = SimpleNamespace(reader=SimpleNamespace(recheck=Mock()))
    return obj


def summary():
    return {"kernelGate": {"containedKernelGate": True, "namespaceDev": 1, "namespaceInode": 2,
            "peerPid": 1, "privateFdsChecked": True}, "markerCount": 0, "rootObserved": True,
            "final": {"method": "owned-memory-v3", "ownedShutdownConfirmed": True,
                      "memoryAvailable": True, "memoryStatus": "single-process-kernel-hwm",
                      "processesEver": 1, "execEvents": 1, "units": "KiB", "exitCode": 0,
                      "wholeApplicationPeakRssKiB": 200, "markerCount": 0, "kernelEvents": 10,
                      "topologyObserver": "ptrace-syscall-entry-exit-and-fork-vfork-clone-exec"}}


class Admission(unittest.TestCase):
    def test_no_bool_or_environment_can_replace_actual_kernel_status(self):
        data = fields()
        meter.no_privileges(data, 1001, 1001, init=True)
        for key, value in (("CapBnd", ["00000001"]), ("CapEff", ["1"]),
                           ("NoNewPrivs", ["0"]), ("NSpid", ["1"]), ("Uid", ["0"] * 4)):
            bad = dict(data)
            bad[key] = value
            with self.subTest(key=key), self.assertRaises(meter.Refused):
                meter.no_privileges(bad, 1001, 1001, init=True)

    def test_duplicate_kernel_status_never_overwrites_first_value(self):
        with self.assertRaises(meter.Refused):
            meter.status_fields(b"CapEff:\t0\nCapEff:\t0\n")

    def test_peer_requires_kernel_namespace_pid_and_same_nonroot_identity(self):
        sock = SimpleNamespace(family=socket.AF_UNIX, type=socket.SOCK_STREAM,
                               getsockopt=Mock(return_value=struct.pack("3i", 1, 1001, 1001)))
        meter.peer(sock, 1, 1001, 1001)
        for actual in ((2, 1001, 1001), (1, 0, 1001), (0, 1001, 1001)):
            sock.getsockopt.return_value = struct.pack("3i", *actual)
            with self.assertRaises(meter.Refused):
                meter.peer(sock, 1, 1001, 1001)

    def test_outside_guard_precedes_docker_proc_or_socket_work(self):
        with patch("ci_environment.require_runner", side_effect=RuntimeError("real guard")), \
             patch.object(Path, "read_bytes") as read, patch.object(meter.socket, "socket") as sock:
            with self.assertRaisesRegex(RuntimeError, "real guard"):
                meter.Outside(SimpleNamespace())
            read.assert_not_called()
            sock.assert_not_called()

    def test_exact_one_thread_group_peak_is_kernel_hwm_not_samples(self):
        obj = outside()
        obj.markers = [{"rssBytes": 99999999}]
        data = summary()
        data["markerCount"] = 1
        data["final"]["markerCount"] = 1
        with patch.object(meter, "ns_identity", return_value=(1, 2)):
            result = obj._project(data)
        self.assertEqual(result["wholeApplicationPeakRssBytes"], 200 * 1024)
        self.assertFalse(result["acceptanceEligible"])
        self.assertFalse(result["includesSupervisorOrMeter"])

    def test_missing_events_or_multiprocess_never_get_rss_aggregation(self):
        for changes in ({"processesEver": 2}, {"memoryAvailable": False},
                        {"ownedShutdownConfirmed": False}, {"processesEver": True},
                        {"memoryStatus": "missing-creation-event"}, {"execEvents": 2},
                        {"wholeApplicationPeakRssKiB": 0}, {"units": "B"}, {"exitCode": 125}):
            data = summary()
            data["final"].update(changes)
            with self.subTest(changes=changes), patch.object(meter, "ns_identity", return_value=(1, 2)):
                result = outside()._project(data)
            self.assertIsNone(result["wholeApplicationPeakRssBytes"])
            self.assertEqual(result["lifecycleKernelSnapshots"], [])

    def test_no_self_report_can_replace_owned_namespace_fd(self):
        data = summary()
        for actual in ((1, 3), (2, 2)):
            with patch.object(meter, "ns_identity", return_value=actual), self.assertRaises(meter.Refused):
                outside()._project(data)
        data["kernelGate"]["peerPid"] = 2
        with patch.object(meter, "ns_identity", return_value=(1, 2)), self.assertRaises(meter.Refused):
            outside()._project(data)

    def test_marker_counter_must_match_actual_authenticated_requests(self):
        data = summary()
        data["markerCount"] = 1
        with patch.object(meter, "ns_identity", return_value=(1, 2)):
            self.assertEqual(outside()._project(data)["status"], "unavailable")


    def test_phase_snapshots_never_become_lifetime_peak_or_multiprocess_memory(self):
        obj = outside()
        obj.lifecycle = "long-lived"
        obj.markers = [{"phase": "steady" if i < 5 else "retained", "rssBytes": 1000 + i,
                        "method": "original-process-smaps-rollup-rss", "topologyFinal": False,
                        "memoryStatus": "provisional-single-process"} for i in range(10)]
        data = summary()
        data["markerCount"] = data["final"]["markerCount"] = 10
        with patch.object(meter, "ns_identity", return_value=(1, 2)):
            result = obj._project(data)
            self.assertEqual(result["steadyRssBytes"], 1004)
            self.assertEqual(result["retainedRssBytes"], 1009)
            self.assertEqual(result["wholeApplicationPeakRssBytes"], 204800)
            data["final"]["processesEver"] = 2
            result = obj._project(data)
            self.assertIsNone(result["steadyRssBytes"])
            self.assertIsNone(result["retainedRssBytes"])
            self.assertIsNone(result["wholeApplicationPeakRssBytes"])

    def test_socket_cleanup_failure_does_not_skip_namespace_fd_close(self):
        obj = outside()
        obj.sock = SimpleNamespace(close=Mock(side_effect=OSError("socket close")))
        with patch.object(meter.os, "close") as close, self.assertRaises(meter.Refused):
            obj.close()
        close.assert_called_once_with(9)

    def test_actual_container_security_failure_precedes_namespace_open(self):
        launch = SimpleNamespace(reader=SimpleNamespace(recheck=Mock()),
            c=SimpleNamespace(meter=SimpleNamespace(lifecycle="ephemeral-command")),
            cid="a" * 64, command=Mock(return_value=SimpleNamespace(stdout='{"pidMode":"host"}')))
        with patch("ci_environment.require_runner"), patch.object(meter.os, "open") as opened:
            with self.assertRaises(meter.Refused):
                meter.Outside(launch)
            opened.assert_not_called()

    def test_host_c_mode_keeps_refusal_and_contained_gate_precedes_fork(self):
        source = Path(meter.__file__).with_name("ci_client_process_memory_meter.c").read_text()
        creation = source.split("static int m_creation(", 1)[1].split("static int m_syscall(", 1)[0]
        self.assertIn("if(m_contained_verified){m_contained_clone3_entries++;return 3;}", creation)
        self.assertIn("return -2;", creation)
        gate = source.split("static int m_contained_entry(", 1)[1].split("#endif", 1)[0]
        self.assertLess(gate.index("m_gate_socket"), gate.index("m_contained_verified=1"))
        self.assertLess(gate.index("m_gate_privileges"), gate.index("m_contained_verified=1"))
        self.assertLess(gate.index("NS_GET_NSTYPE"), gate.index("m_contained_verified=1"))
        self.assertLess(gate.index("m_contained_verified=1"), gate.index("memory_v3(argc-1,adapted)"))
        self.assertNotIn("getenv(", source)


    def test_final_rss_comes_only_from_authenticated_socket_not_status_file(self):
        obj = outside()
        obj.sock = object()
        obj.io_lock = threading.Lock()
        obj.launch.c = SimpleNamespace(deadline=123)
        obj.launch.nonce = "owned-nonce"
        with patch.object(meter, "receive", return_value={"nonce": "owned-nonce", "completed": summary()}) as received,              patch.object(meter, "ns_identity", return_value=(1, 2)):
            result = obj.completed()
        received.assert_called_once_with(obj.sock, 123)
        self.assertEqual(result["authority"], "authenticated-pid1-private-channel")
        with patch.object(meter, "receive", return_value={"nonce": "foreign", "completed": summary()}), self.assertRaises(meter.Refused):
            obj.completed()

    def test_inconsistent_snapshot_cannot_replace_lifetime_kernel_hwm(self):
        obj = outside()
        obj.lifecycle = "long-lived"
        obj.markers = [{"phase": "steady", "rssBytes": 999999999,
                        "method": "original-process-smaps-rollup-rss", "topologyFinal": False,
                        "memoryStatus": "provisional-single-process"}]
        data = summary()
        data["markerCount"] = data["final"]["markerCount"] = 1
        with patch.object(meter, "ns_identity", return_value=(1, 2)):
            result = obj._project(data)
        self.assertIsNone(result["wholeApplicationPeakRssBytes"])
        self.assertEqual(result["counterConsistency"], "inconsistent-kernel-rss-counters")
        self.assertEqual(result["rawLifecycleKernelSnapshots"], obj.markers)


if __name__ == "__main__":
    unittest.main()
