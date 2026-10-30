"""Finite private contained-meter admission; no import-time kernel/runtime work.

Namespace containment never repairs missing accounting or multiprocess RSS.
Both control hops use kernel peer credentials, never caller bool/env/file authority.
"""
from dataclasses import dataclass
import ctypes
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import stat
import struct
import time
import threading

NSFS_MAGIC = 0x6E736673
NS_GET_NSTYPE = 0xB703
CLONE_NEWPID = 0x20000000
MAX_FRAME = 32768
MAX_MARKERS = 64
ORIGINAL_METER_SHA256 = "d21233cedd8954ab7e603b27d7d45f6b630b249581e799a7dd113dc13271ebd7"


class Refused(ValueError):
    pass


def need(value, reason):
    if not value:
        raise Refused(reason)


@dataclass(frozen=True)
class MeterSpec:
    binary: Path
    binary_sha256: str
    source_sha256: str
    preparation_receipt: Path
    preparation_receipt_sha256: str
    lifecycle: str = "ephemeral-command"


def digest(path):
    path = Path(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        need(stat.S_ISREG(info.st_mode) and 0 < info.st_size <= 4 * 1024**2, "meter_pin_file")
        data = os.read(fd, info.st_size + 1)
        need(len(data) == info.st_size, "meter_pin_changed")
        return hashlib.sha256(data).hexdigest()
    finally:
        os.close(fd)



def elf_machine(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        raw = os.read(fd, 64)
    finally:
        os.close(fd)
    need(len(raw) == 64 and raw[:6] == b"\x7fELF\x02\x01", "linux_64bit_little_endian_meter")
    machine = int.from_bytes(raw[18:20], "little")
    need(machine in (62, 183), "supported_native_meter_machine")
    return machine


def validate_spec(spec, root):
    need(type(spec) is MeterSpec, "exact_meter_spec")
    need(spec.lifecycle in ("ephemeral-command", "long-lived"), "finite_meter_lifecycle")
    for path in (spec.binary, spec.preparation_receipt):
        need(path.is_absolute() and path.resolve() == path and not path.is_symlink(), "canonical_meter_pin")
    need(digest(spec.binary) == spec.binary_sha256, "compiled_meter_pin")
    info = spec.binary.stat()
    need(info.st_nlink == 1 and stat.S_IMODE(info.st_mode) == 0o500 and os.access(spec.binary, os.X_OK), "private_readonly_meter_elf")
    elf_machine(spec.binary)
    need(digest(Path(root) / "scripts/ci_client_process_meter_original.c") == ORIGINAL_METER_SHA256, "frozen_original_meter_pin")
    source = Path(root) / "scripts/ci_client_process_memory_meter.c"
    need(digest(source) == spec.source_sha256, "actual_meter_source_pin")
    need(digest(spec.preparation_receipt) == spec.preparation_receipt_sha256, "external_preparation_receipt_pin")
    receipt = json.loads(spec.preparation_receipt.read_bytes())
    need(
        receipt.get("status") == "built_pending_harmless_runtime_review"
        and receipt.get("process-memory-meterSha256") == spec.binary_sha256
        and receipt.get("sourceSha256", {}).get("process-memory-meter.c") == spec.source_sha256
        and receipt.get("sourceSha256", {}).get("process-meter-original.c") == ORIGINAL_METER_SHA256
        and receipt.get("flags") == ["-O2", "-std=c11", "-Wall", "-Wextra", "-Werror"]
        and re.fullmatch(r"[a-f0-9]{64}", receipt.get("compilerSha256", "")) is not None,
        "existing_external_tiny_build_proof_required",
    )
    return spec


def ns_identity(fd):
    # /proc/PID/ns/pid is intentionally a kernel magic link, not a regular-file
    # caller path. Require its opened object to be nsfs of the PID namespace type.
    buf = ctypes.create_string_buffer(256)
    libc = ctypes.CDLL(None, use_errno=True)
    need(libc.fstatfs(fd, ctypes.byref(buf)) == 0, "namespace_filesystem")
    magic = ctypes.cast(ctypes.byref(buf), ctypes.POINTER(ctypes.c_long))[0]
    need(magic == NSFS_MAGIC and fcntl.ioctl(fd, NS_GET_NSTYPE) == CLONE_NEWPID, "kernel_pid_namespace_fd")
    info = os.fstat(fd)
    return info.st_dev, info.st_ino


def status_fields(raw):
    need(type(raw) is bytes and 0 < len(raw) <= 32768, "bounded_kernel_status")
    result = {}
    for line in raw.decode("ascii").splitlines():
        name, _, value = line.partition(":")
        if name in ("Uid", "Gid", "NSpid", "CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb", "NoNewPrivs"):
            need(name not in result, "duplicate_kernel_status")
            result[name] = value.split()
    return result


def no_privileges(fields, uid, gid, *, init=False):
    need(fields.get("Uid") == [str(uid)] * 4 and fields.get("Gid") == [str(gid)] * 4, "actual_nonroot_identity")
    need(uid > 0 and gid > 0 and fields.get("NoNewPrivs") == ["1"], "actual_no_new_privileges")
    for name in ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb"):
        values = fields.get(name)
        need(type(values) is list and len(values) == 1 and re.fullmatch(r"0{16}", values[0]) is not None, "actual_zero_capabilities")
    if init:
        ids = fields.get("NSpid", [])
        need(len(ids) >= 2 and all(value.isdecimal() for value in ids) and ids[-1] == "1", "actual_nested_namespace_init")


def peer(sock, pid, uid, gid):
    need(sock.family == socket.AF_UNIX and sock.type == socket.SOCK_STREAM, "private_unix_stream")
    need(sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")) == struct.pack("3i", pid, uid, gid), "kernel_peer_identity")


def send(sock, value):
    data = json.dumps(value, separators=(",", ":")).encode() + b"\n"
    need(len(data) <= MAX_FRAME, "bounded_control_frame")
    sock.sendall(data)


def receive(sock, deadline):
    data = bytearray()
    while time.monotonic() < deadline:
        sock.settimeout(min(1, max(0.001, deadline - time.monotonic())))
        try:
            byte = sock.recv(1)
        except socket.timeout:
            continue
        need(byte, "private_control_eof")
        data += byte
        need(len(data) <= MAX_FRAME, "bounded_control_frame")
        if byte == b"\n":
            return json.loads(data)
    raise Refused("original_control_deadline")


class Outside:
    """Owned init/namespace anchor and authenticated controller socket only."""
    def __init__(self, launch):
        from ci_environment import require_runner
        require_runner()
        self.launch = launch
        self.nsfd = None
        self.dirfd = None
        self.sock = None
        self.markers = []
        self.io_lock = threading.Lock()
        c = launch.c
        self.lifecycle = c.meter.lifecycle
        launch.reader.recheck()
        template = '{"pidMode":{{json .HostConfig.PidMode}},"networkMode":{{json .HostConfig.NetworkMode}},"capAdd":{{json .HostConfig.CapAdd}},"capDrop":{{json .HostConfig.CapDrop}},"securityOpt":{{json .HostConfig.SecurityOpt}},"privileged":{{json .HostConfig.Privileged}},"readonly":{{json .HostConfig.ReadonlyRootfs}},"mounts":{{json .Mounts}}}'
        actual = json.loads(launch.command("inspect", "--format", template, launch.cid).stdout)
        need(actual.get("pidMode") == "" and actual.get("capAdd") in (None, []) and actual.get("capDrop") == ["ALL"] and actual.get("securityOpt") == ["no-new-privileges"] and actual.get("privileged") is False and actual.get("readonly") is True, "actual_container_security")
        need(actual.get("networkMode") == "container:" + c.gateway, "actual_gateway_network_namespace")
        mounts = actual.get("mounts")
        need(type(mounts) is list and len(mounts) <= len(c.readonly_paths) + 6 and all(type(mount) is dict for mount in mounts), "bounded_actual_mounts")
        readonly = {str(path) for path in c.readonly_paths}
        readonly.update((str(c.supervisor), str(c.meter.binary), str(c.source_root / "scripts/ci_client_contained_meter.py")))
        writable = {str(c.state_root), str(launch.control)}
        for path in readonly | writable:
            matches = [mount for mount in mounts if mount.get("Destination") == path]
            need(len(matches) == 1 and matches[0].get("Type") == "bind" and matches[0].get("Source") == path
                 and matches[0].get("RW") is (path in writable), "actual_pinned_bind_mode")
        need(all(mount.get("Destination") in readonly | writable or mount.get("Destination") == "/tmp" and mount.get("Type") == "tmpfs" for mount in mounts), "no_unadmitted_mounts")
        image = json.loads(launch.command("image", "inspect", "--format", '{"id":{{json .Id}},"os":{{json .Os}},"architecture":{{json .Architecture}}}', c.image).stdout)
        need(image.get("id") == c.image and image.get("os") == "linux" and {"amd64": 62, "arm64": 183}.get(image.get("architecture")) == elf_machine(c.meter.binary), "actual_meter_image_platform")
        pid = launch.reader.pid
        no_privileges(status_fields(Path(f"/proc/{pid}/status").read_bytes()), c.uid, c.gid, init=True)
        from scripts import ci_client_container_memory as memory
        bootstrap = os.open("cgroup.procs", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=launch.reader.fd)
        try:
            memory.cgroup2_fd(bootstrap)
            raw = os.read(bootstrap, 65537)
            need(len(raw) <= 65536 and raw.split() == [str(pid).encode()], "only_owned_pid1_before_measured_fork")
        finally:
            os.close(bootstrap)
        try:
            self.nsfd = os.open(f"/proc/{pid}/ns/pid", os.O_RDONLY | os.O_CLOEXEC)
            own = os.open("/proc/self/ns/pid", os.O_RDONLY | os.O_CLOEXEC)
            try:
                self.namespace = ns_identity(self.nsfd)
                need(self.namespace != ns_identity(own), "outside_private_namespace")
            finally:
                os.close(own)
            launch.reader.recheck()
            path = launch.control / "meter.sock"
            info = path.lstat()
            need(stat.S_ISSOCK(info.st_mode) and info.st_uid == c.uid and info.st_nlink == 1 and stat.S_IMODE(info.st_mode) == 0o600, "private_meter_endpoint")
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.settimeout(min(5, max(0.001, c.work_deadline - time.monotonic())))
            # CI checkout paths exceed sockaddr_un.sun_path. An owned directory
            # FD gives a short kernel pathname for the SAME shared socket inode.
            self.dirfd = os.open(launch.control, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            directory = os.fstat(self.dirfd)
            need(stat.S_ISDIR(directory.st_mode) and directory.st_uid == c.uid and stat.S_IMODE(directory.st_mode) == 0o700, "owned_control_directory_fd")
            self.sock.connect(f"/proc/self/fd/{self.dirfd}/meter.sock")
            os.close(self.dirfd)
            self.dirfd = None
            peer(self.sock, pid, c.uid, c.gid)
            self.binding = {"nonce": launch.nonce, "namespaceDev": self.namespace[0], "namespaceInode": self.namespace[1]}
            send(self.sock, self.binding)
            need(receive(self.sock, c.work_deadline) == {**self.binding, "pid1Protected": True}, "protected_pid1_handshake")
        except BaseException:
            self.close()
            raise

    def marker(self, phase, sequence):
        with self.io_lock:
            need(phase in ("steady", "retained") and type(sequence) is int and sequence == len(self.markers) + 1 and sequence <= MAX_MARKERS, "finite_marker_sequence")
            self.launch.reader.recheck()
            send(self.sock, {"marker": sequence, "phase": phase})
            result = receive(self.sock, self.launch.c.work_deadline)
            need(result.get("marker") == sequence and result.get("phase") == phase, "exact_kernel_marker_response")
            self.markers.append(result)
            return result

    def completed(self):
        # Status files are app-writable. Even a forged held flag plus a genuine
        # empty application cgroup can race before PID1's final file overwrite.
        # Only this private peer-authenticated channel supplies final accounting.
        with self.io_lock:
            message = receive(self.sock, self.launch.c.deadline)
            need(type(message) is dict and set(message) == {"nonce", "completed"}
                 and message["nonce"] == self.launch.nonce, "authenticated_final_meter_frame")
            result = self._project(message["completed"])
            result["authority"] = "authenticated-pid1-private-channel"
            return result

    def _project(self, summary):
        self.launch.reader.recheck()
        need(ns_identity(self.nsfd) == self.namespace, "held_namespace_identity")
        need(type(summary) is dict, "private_meter_summary")
        gate = summary.get("kernelGate", {})
        need(gate.get("containedKernelGate") is True and gate.get("namespaceDev") == self.namespace[0] and gate.get("namespaceInode") == self.namespace[1] and gate.get("peerPid") == 1 and gate.get("privateFdsChecked") is True and type(gate.get("namespaceDev")) is int and type(gate.get("namespaceInode")) is int and type(gate.get("peerPid")) is int, "final_kernel_namespace_binding")
        final = summary.get("final", {})
        available = (
            final.get("method") == "owned-memory-v3"
            and final.get("ownedShutdownConfirmed") is True
            and final.get("memoryAvailable") is True
            and final.get("memoryStatus") == "single-process-kernel-hwm"
            and type(final.get("processesEver")) is int and final["processesEver"] == 1
            and type(final.get("execEvents")) is int and final["execEvents"] == 1
            and final.get("units") == "KiB"
            and type(final.get("wholeApplicationPeakRssKiB")) is int
            and 0 < final["wholeApplicationPeakRssKiB"] <= 9007199254740991 // 1024
            and type(final.get("exitCode")) is int and final["exitCode"] == 0
            and type(summary.get("markerCount")) is int
            and summary["markerCount"] == len(self.markers)
            and summary.get("rootObserved") is True
            and type(final.get("markerCount")) is int and final["markerCount"] == len(self.markers)
            and type(final.get("kernelEvents")) is int and final["kernelEvents"] >= 3
            and final.get("topologyObserver") == "ptrace-syscall-entry-exit-and-fork-vfork-clone-exec"
        )
        phases = {}
        valid_phase_rss = []
        for phase in ("steady", "retained"):
            values = [row["rssBytes"] for row in self.markers if row.get("phase") == phase
                and type(row.get("rssBytes")) is int and row["rssBytes"] > 0
                and row.get("method") == "original-process-smaps-rollup-rss"
                and row.get("memoryStatus") == "provisional-single-process"
                and row.get("topologyFinal") is False]
            valid_phase_rss.extend(values)
            phases[phase] = max(values) if available and self.lifecycle == "long-lived" and len(values) >= 5 else None
        inconsistent = available and any(value > final["wholeApplicationPeakRssKiB"] * 1024 for value in valid_phase_rss)
        if inconsistent:
            available = False
            phases = {"steady": None, "retained": None}
        return {
            "status": "observed" if available else "unavailable",
            "acceptanceEligible": False,
            "currentMigrationAcceptance": False,
            "metric": "kernel-waited-one-thread-group-lifetime-rss-highwater",
            "wholeApplicationPeakRssBytes": final["wholeApplicationPeakRssKiB"] * 1024 if available else None,
            "includesSupervisorOrMeter": False,
            "lifecycleKernelSnapshots": list(self.markers) if available else [],
            "rawLifecycleKernelSnapshots": list(self.markers),
            "counterConsistency": "inconsistent-kernel-rss-counters" if inconsistent else "no-observed-conflict",
            "steadyRssBytes": phases["steady"],
            "retainedRssBytes": phases["retained"],
            "phaseMetric": "max-of-authenticated-kernel-current-rss-snapshots-not-lifetime-peak",
            "lifecyclePredicateProof": "required-from-original-source-bound-flow",
            "final": final,
            "kernelGate": gate,
            "multiprocessTotalRss": "unavailable-no-aggregation-or-subtraction",
        }

    def close(self):
        errors = []
        try:
            if self.sock is not None:
                self.sock.close()
        except BaseException as error:
            errors.append(error)
        finally:
            self.sock = None
        try:
            if self.nsfd is not None:
                os.close(self.nsfd)
        except BaseException as error:
            errors.append(error)
        finally:
            self.nsfd = None
        try:
            if self.dirfd is not None:
                os.close(self.dirfd)
        except BaseException as error:
            errors.append(error)
        finally:
            self.dirfd = None
        need(not errors, "contained_handles_close_failed")


class Inside:
    """Trusted nonroot PID1 endpoint and anonymous inherited meter channels."""
    def __init__(self, cfg, root):
        need(os.getpid() == 1 and os.geteuid() > 0 and os.getegid() > 0, "actual_nonroot_pid1")
        self.cfg = cfg
        self.root = root
        self.controller = None
        self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.dirfd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        self.listener.bind(f"/proc/self/fd/{self.dirfd}/meter.sock")
        os.chmod(root / "meter.sock", 0o600)
        self.listener.listen(1)
        self.control = None
        self.measurement = None
        self.buffer = bytearray()
        self.eof = False
        self.gate = None
        self.final = None
        self.root_seen = False
        self.pending = None
        self.sequence = 0
        self.nsfd = os.open("/proc/self/ns/pid", os.O_RDONLY | os.O_CLOEXEC)
        self.namespace = ns_identity(self.nsfd)
        no_privileges(status_fields(Path("/proc/self/status").read_bytes()), os.geteuid(), os.getegid())

    def admit(self):
        self.listener.settimeout(1)
        deadline = self.cfg["workDeadlineNs"] / 1e9
        while time.monotonic() < deadline:
            try:
                candidate, _ = self.listener.accept()
                # The outside process is not visible in this child PID namespace;
                # a same-UID application inside it has a positive kernel PID.
                peer(candidate, 0, os.geteuid(), os.getegid())
                self.controller = candidate
                break
            except socket.timeout:
                continue
        need(self.controller is not None, "outside_controller_required")
        binding = receive(self.controller, deadline)
        need(binding == {"nonce": self.cfg["nonce"], "namespaceDev": self.namespace[0], "namespaceInode": self.namespace[1]}, "outside_namespace_binding")
        libc = ctypes.CDLL(None, use_errno=True)
        need(libc.prctl(4, 0, 0, 0, 0) == 0 and libc.prctl(3, 0, 0, 0, 0) == 0, "pid1_private_fd_protection")
        send(self.controller, {**binding, "pid1Protected": True})
        self.controller.setblocking(False)
        self.listener.close()
        os.close(self.dirfd)
        self.dirfd = None

    def fork_meter(self):
        ctrl_parent, ctrl_child = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        data_parent, data_child = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        for fd in (ctrl_child.fileno(), data_child.fileno(), self.nsfd):
            os.set_inheritable(fd, True)
        child = os.fork()
        if child == 0:
            try:
                ctrl_parent.close()
                data_parent.close()
                self.controller.close()
                args = [self.cfg["meter"]["binary"], str(data_child.fileno()), "--owned-memory-v3-contained", "pinned-typescript-owned-tree", str(ctrl_child.fileno()), self.cfg["meter"]["lifecycle"], str(self.nsfd), "--", *self.cfg["argv"]]
                os.chdir(self.cfg["cwd"])
                os.execvpe(args[0], args, self.cfg["env"])
            except BaseException:
                os._exit(127)
        ctrl_child.close()
        data_child.close()
        os.close(self.nsfd)
        self.nsfd = None
        self.control = ctrl_parent
        self.measurement = data_parent
        self.measurement.setblocking(False)
        self.control.sendall(f'D {self.cfg["workDeadlineNs"]}\n'.encode())
        return child

    def poll(self):
        # One owner consumes private meter frames; stdio is never read here.
        if self.measurement is not None and not self.eof:
            try:
                data = self.measurement.recv(8192)
            except BlockingIOError:
                data = None
            if data == b"":
                self.eof = True
            elif data:
                self.buffer.extend(data)
                need(len(self.buffer) <= MAX_FRAME, "bounded_meter_frame")
                while b"\n" in self.buffer:
                    row, _, rest = self.buffer.partition(b"\n")
                    self.buffer = bytearray(rest)
                    value = json.loads(row)
                    if value.get("containedKernelGate") is True:
                        need(self.gate is None and value.get("namespaceDev") == self.namespace[0] and value.get("namespaceInode") == self.namespace[1] and value.get("privateFdsChecked") is True and value.get("peerPid") == 1, "meter_kernel_gate")
                        self.gate = value
                    elif "marker" in value:
                        need(self.pending == (value.get("phase"), value.get("marker")), "solicited_marker_only")
                        send(self.controller, value)
                        self.pending = None
                    elif "exitCode" in value:
                        need(self.final is None, "one_meter_final")
                        self.final = value
                    else:
                        need(self.gate is not None and not self.root_seen and set(value) == {"pid", "birth", "method"} and value.get("method") == "owned-memory-v3"
                             and type(value.get("pid")) is int and value["pid"] > 1
                             and type(value.get("birth")) is int and value["birth"] >= 0, "finite_meter_frames")
                        self.root_seen = True
        if self.controller is not None:
            # Small finite requests use one complete JSON line. A partial caller
            # request never becomes a lifecycle marker or a sampled peak claim.
            try:
                data = self.controller.recv(MAX_FRAME + 1, socket.MSG_PEEK)
            except BlockingIOError:
                data = None
            if data == b"":
                raise Refused("outside_controller_disconnected")
            if data:
                need(len(data) <= MAX_FRAME, "bounded_control_request")
            if data and b"\n" in data:
                need(data.count(b"\n") == 1 and len(data) <= MAX_FRAME, "single_control_request")
                value = receive(self.controller, self.cfg["workDeadlineNs"] / 1e9)
                self.controller.setblocking(False)
                sequence = value.get("marker")
                need(self.cfg["meter"]["lifecycle"] == "long-lived" and value.get("phase") in ("steady", "retained") and type(sequence) is int and sequence == self.sequence + 1 and sequence <= MAX_MARKERS and self.pending is None, "finite_trusted_marker")
                self.sequence = sequence
                self.pending = value["phase"], sequence
                self.control.sendall(f'M {value["phase"]} {sequence}\n'.encode())

    def completed(self):
        while not self.eof and time.monotonic_ns() < self.cfg["deadlineNs"]:
            self.poll()
            if not self.eof:
                time.sleep(0.001)
        need(self.eof and not self.buffer and self.pending is None and self.gate is not None and self.final is not None, "complete_private_meter_output")
        summary = {"kernelGate": self.gate, "final": self.final, "markerCount": self.sequence, "rootObserved": self.root_seen}
        send(self.controller, {"nonce": self.cfg["nonce"], "completed": summary})
        return summary

    def close(self):
        errors = []
        for item in (self.controller, self.listener, self.control, self.measurement):
            try:
                if item is not None:
                    item.close()
            except BaseException as error:
                errors.append(error)
        try:
            if self.nsfd is not None:
                os.close(self.nsfd)
        except BaseException as error:
            errors.append(error)
        finally:
            self.nsfd = None
        try:
            if self.dirfd is not None:
                os.close(self.dirfd)
        except BaseException as error:
            errors.append(error)
        finally:
            self.dirfd = None
        need(not errors, "inside_handles_close_failed")
