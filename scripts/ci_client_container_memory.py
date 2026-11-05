"""Outside-only cgroup-v2 reader for a genuinely managed application container.

No container creation/start/exec/build/cleanup/privilege/namespace mutation. The
existing CI owner supplies the actual container ID and immutable cohort bindings.
The current runner has no such per-arm application-container launch yet; this
collector is usable conditional machinery, not an always-refusing launch wrapper.
"""

from dataclasses import dataclass
from pathlib import PurePosixPath
import ctypes
import json
import math
import os
import re
import select
import subprocess
import time

CGROUP2_SUPER_MAGIC = 0x63677270
HEX = re.compile(r"[a-f0-9]{64}")


class Unavailable(ValueError):
    pass


def require(ok, reason):
    if not ok:
        raise Unavailable(reason)


def count(raw):
    require(
        type(raw) is bytes and re.fullmatch(rb"[0-9]+\n?", raw) is not None,
        "unknown_kernel_counter",
    )
    value = int(raw)
    require(0 <= value < 2**63, "kernel_counter_range")
    return value


def unified(raw):
    require(type(raw) is bytes and len(raw) <= 16384, "cgroup_membership_bound")
    lines = raw.decode("ascii").splitlines()
    require(len(lines) == 1 and lines[0].startswith("0::/"), "cgroup_v2_required")
    text = lines[0][3:]
    path = PurePosixPath(text)
    require(
        str(path) == text
        and not text.startswith("//")
        and path.is_absolute()
        and ".." not in path.parts
        and len(path.parts) > 1,
        "unsafe_cgroup_path",
    )
    return path


def birth(raw):
    require(type(raw) is bytes and len(raw) < 16384, "proc_identity_bound")
    end = raw.rfind(b") ")
    require(end > 0, "proc_identity_unknown")
    parts = raw[end + 2 :].split()
    require(len(parts) > 19 and parts[19].isdigit(), "proc_identity_unknown")
    return int(parts[19])


def cgroup2_fd(fd):
    # Native libc syscall only, no compiler/helper subprocess. No call occurs on import.
    buf = ctypes.create_string_buffer(256)
    libc = ctypes.CDLL(None, use_errno=True)
    require(libc.fstatfs(fd, ctypes.byref(buf)) == 0, "filesystem_identity_unavailable")
    require(
        ctypes.cast(ctypes.byref(buf), ctypes.POINTER(ctypes.c_long))[0]
        == CGROUP2_SUPER_MAGIC,
        "not_kernel_cgroup2",
    )


def read_small(path, maximum=16384):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        out = os.read(fd, maximum + 1)
        require(len(out) <= maximum, "kernel_file_bound")
        return out
    finally:
        os.close(fd)


def open_cgroup(path):
    # Fixed host mount; no caller-controlled mount, remote root or symlink traversal.
    fd = os.open("/sys/fs/cgroup", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        cgroup2_fd(fd)
        for part in path.parts[1:]:
            require(
                part not in ("", ".", "..") and "/" not in part, "unsafe_cgroup_path"
            )
            child = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd
            )
            os.close(fd)
            fd = child
        cgroup2_fd(fd)
        return fd
    except BaseException:
        os.close(fd)
        raise


def at(fd, name):
    require(
        name
        in (
            "memory.peak",
            "memory.current",
            "memory.swap.current",
            "memory.events",
            "cgroup.events",
        ),
        "unknown_metric_file",
    )
    child = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    try:
        cgroup2_fd(child)
        raw = os.read(child, 16385)
        require(len(raw) <= 16384, "kernel_file_bound")
        return raw
    finally:
        os.close(child)


def fields(raw):
    out = {}
    for line in raw.decode("ascii").splitlines():
        parts = line.split()
        require(len(parts) == 2 and parts[0] not in out, "unknown_event_counter")
        out[parts[0]] = count(parts[1].encode())
    return out


# Select only finite ownership/state/image fields; never inspect Config.Env/Args.
TEMPLATE = """{"id":{{json .Id}},"image":{{json .Image}},"pid":{{json .State.Pid}},"running":{{json .State.Running}},"exit":{{json .State.ExitCode}},"oom":{{json .State.OOMKilled}},"restarts":{{json .RestartCount}},"autoremove":{{json .HostConfig.AutoRemove}},"privileged":{{json .HostConfig.Privileged}},"pidMode":{{json .HostConfig.PidMode}},"cgroupParent":{{json .HostConfig.CgroupParent}},"source":{{json (index .Config.Labels "org.openmates.source")}},"project":{{json (index .Config.Labels "com.docker.compose.project")}},"service":{{json (index .Config.Labels "com.docker.compose.service")}},"role":{{json (index .Config.Labels "org.openmates.benchmark.role")}},"owner":{{json (index .Config.Labels "org.openmates.benchmark.owner")}},"arm":{{json (index .Config.Labels "org.openmates.benchmark.arm")}},"pair":{{json (index .Config.Labels "org.openmates.benchmark.pair")}}}"""


def inspect_owned(container, timeout=10):
    require(
        type(timeout) in (int, float) and math.isfinite(timeout) and 0 < timeout <= 10,
        "bounded_inspection_deadline_required",
    )
    from ci_environment import require_runner

    require_runner()  # Existing managed CI guard, before Docker inspection.
    require(
        type(container) is str and HEX.fullmatch(container),
        "full_container_id_required",
    )
    result = subprocess.run(
        ["docker", "inspect", "--type", "container", "--format", TEMPLATE, container],
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    require(
        result.returncode == 0 and len(result.stdout) <= 16384,
        "managed_container_inspection_unavailable",
    )
    return json.loads(result.stdout)


@dataclass(frozen=True)
class Owned:
    container: str
    source: str
    image: str
    project: str
    service: str
    owner: str
    arm: str
    pair: int
    # Immutable matched cohort identity: actual image/tools/platform/limits/cache/security/KDF/lifecycle/work.
    conditions: tuple


def validate_owned(actual, expected, running=True):
    require(
        type(expected) is Owned and HEX.fullmatch(expected.container) is not None,
        "owned_application_identity_required",
    )
    require(
        type(expected.source) is str
        and re.fullmatch("[a-f0-9]{40}", expected.source)
        and type(expected.image) is str
        and re.fullmatch("sha256:[a-f0-9]{64}", expected.image),
        "source_or_image_pin_unknown",
    )
    require(
        dict(expected.conditions).get("image") == expected.image,
        "image_condition_mismatch",
    )
    require(
        expected.arm in ("rust", "typescript")
        and type(expected.pair) is int
        and expected.pair in range(1, 6),
        "arm_pair_identity",
    )
    require(
        expected.project == "openmates-ci"
        and expected.service in ("benchmark-client-rust", "benchmark-client-typescript")
        and expected.service == "benchmark-client-" + expected.arm,
        "application_service_required",
    )
    require(
        type(actual) is dict and actual.get("privileged") is False,
        "container_privilege_unknown",
    )
    require(
        type(actual) is dict
        and all(
            actual.get(k) == v
            for k, v in {
                "id": expected.container,
                "source": expected.source,
                "image": expected.image,
                "project": expected.project,
                "service": expected.service,
                "role": "application-memory",
                "owner": expected.owner,
                "arm": expected.arm,
                "pair": str(expected.pair),
                "privileged": False,
                "pidMode": "",
                "cgroupParent": "",
            }.items()
        ),
        "application_container_ownership_mismatch",
    )
    require(
        type(actual.get("restarts")) is int
        and actual["restarts"] == 0
        and actual.get("autoremove") is False,
        "fresh_nonrestarting_container_required",
    )
    require(
        type(actual.get("running")) is bool
        and actual["running"] is running
        and actual.get("oom") is False,
        "container_lifecycle_or_oom",
    )
    if running:
        require(
            type(actual.get("pid")) is int and actual["pid"] > 1,
            "container_host_pid_unknown",
        )
    else:
        require(type(actual.get("exit")) is int, "container_exit_unknown")
    return actual


class Reader:
    def __init__(self, owned, inspect=inspect_owned, deadline=None):
        require(
            type(deadline) in (int, float)
            and math.isfinite(deadline)
            and deadline > time.monotonic(),
            "original_deadline_required",
        )
        self.deadline = deadline
        self.owned = owned
        self.inspect = inspect
        self.fd = None
        self.pidfd = None
        self.samples = []
        self.final = None
        actual = validate_owned(self.inspect_container(), owned)
        self.pid = actual["pid"]
        self.start = birth(read_small(f"/proc/{self.pid}/stat"))
        try:
            self.pidfd = os.pidfd_open(self.pid)
            self.path = unified(read_small(f"/proc/{self.pid}/cgroup"))
            own_path = unified(read_small("/proc/self/cgroup"))
            require(
                own_path != self.path and self.path not in own_path.parents,
                "collector_inside_measured_container",
            )
            # Docker systemd and cgroupfs leaf names both bind the full inspected ID.
            require(
                self.path.name
                in (owned.container, "docker-" + owned.container + ".scope"),
                "container_cgroup_identity_mismatch",
            )
            self.fd = open_cgroup(self.path)
            self.directory = (os.fstat(self.fd).st_dev, os.fstat(self.fd).st_ino)
            self.recheck()
        except BaseException:
            self.close()
            raise

    def inspect_container(self):
        remaining = self.deadline - time.monotonic()
        require(remaining > 0, "original_deadline_expired")
        return self.inspect(self.owned.container, timeout=min(10, remaining))

    def recheck(self):
        require(
            self.pidfd is not None and not select.select([self.pidfd], [], [], 0)[0],
            "original_container_process_exited",
        )
        actual = validate_owned(self.inspect_container(), self.owned)
        require(
            actual["pid"] == self.pid
            and birth(read_small(f"/proc/{self.pid}/stat")) == self.start,
            "container_pid_changed",
        )
        require(
            unified(read_small(f"/proc/{self.pid}/cgroup")) == self.path,
            "container_cgroup_changed",
        )
        require(
            (os.fstat(self.fd).st_dev, os.fstat(self.fd).st_ino) == self.directory,
            "cgroup_inode_changed",
        )

    def sample(self, phase):
        require(
            phase in ("startup", "steady", "retained", "before-exit")
            and len(self.samples) < 64,
            "unknown_or_unbounded_lifecycle_phase",
        )
        result = {
            "phase": phase,
            "metric": "kernel-cgroup-v2-charged-container-memory",
            "unit": "B",
            "peakSoFarBytes": None,
            "currentBytes": None,
            "swapCurrentBytes": None,
            "status": "unavailable",
        }
        try:
            self.recheck()
            current = count(at(self.fd, "memory.current"))
            result.update(
                currentBytes=current, currentObservedMonotonicNs=time.monotonic_ns()
            )
            peak = count(at(self.fd, "memory.peak"))
            result.update(
                peakSoFarBytes=peak, peakObservedMonotonicNs=time.monotonic_ns()
            )
            swap = count(at(self.fd, "memory.swap.current"))
            result["swapCurrentBytes"] = swap
            events = fields(at(self.fd, "memory.events"))
            population = fields(at(self.fd, "cgroup.events"))
            require(
                peak > 0 and current <= peak and population.get("populated") == 1,
                "counter_or_population_unknown",
            )
            require(
                all(k in events for k in ("oom", "oom_kill", "max"))
                and events["oom"] == 0
                and events["oom_kill"] == 0,
                "oom_or_missing_events",
            )
            self.recheck()
            result.update(
                status="observed",
                peakSoFarBytes=peak,
                currentBytes=current,
                swapCurrentBytes=swap,
                memoryEvents=events,
            )
        except (Unavailable, OSError, ValueError, KeyError):
            result["reason"] = "ownership_kernel_or_lifecycle_unavailable"
        self.samples.append(result)
        return result

    def terminal(self):
        # No stop/remove request: actual existing managed owner controls the lifecycle.
        result = {
            "metric": "kernel-cgroup-v2-charged-container-memory",
            "unit": "B",
            "lifetimePeakBytes": None,
            "status": "unavailable",
        }
        try:
            actual = validate_owned(self.inspect_container(), self.owned, running=False)
            result["exitCode"] = actual["exit"]
            require(
                (os.fstat(self.fd).st_dev, os.fstat(self.fd).st_ino) == self.directory,
                "cgroup_inode_changed",
            )
            require(
                fields(at(self.fd, "cgroup.events")).get("populated") == 0,
                "container_descendants_not_drained",
            )
            peak = count(at(self.fd, "memory.peak"))
            require(peak > 0, "terminal_peak_missing")
            result.update(
                status="observed" if actual["exit"] == 0 else "failed",
                lifetimePeakBytes=peak,
                exitCode=actual["exit"],
            )
        except (Unavailable, OSError, ValueError, KeyError):
            result["reason"] = "complete_lifetime_terminal_cgroup_unavailable"
        self.final = result
        return result

    def report(self):
        return {
            "schemaVersion": 1,
            "status": "unverified",
            "acceptanceEligible": False,
            "currentMigrationAcceptance": False,
            "scope": "isolated-ci-fixture-application-container",
            "metric": "kernel-cgroup-charged-memory-NOT-RSS",
            "backend": self.owned.arm,
            "pair": self.owned.pair,
            "samples": self.samples,
            "terminal": self.final,
            "conditions": dict(self.owned.conditions),
            "composition": "one-container-hierarchy-no-summed-peaks-no-added-heaps",
            "collectorLocation": "outside-application-container",
            "originalCpuAndLatency": "unchanged-separate-evidence-required",
        }

    def close(self):
        for name in ("fd", "pidfd"):
            fd = getattr(self, name, None)
            if fd is not None:
                os.close(fd)
                setattr(self, name, None)


REQUIRED_CONDITIONS = {
    "image",
    "tools",
    "platform",
    "kernel",
    "memoryLimit",
    "swapLimit",
    "cpuLimit",
    "pidsLimit",
    "cache",
    "credentialSecurity",
    "kdf",
    "lifecycle",
    "workload",
    "outputs",
    "durability",
    "recovery",
}


def compare_pairs(rows):
    out = {
        "status": "unverified",
        "acceptanceEligible": False,
        "currentMigrationAcceptance": False,
        "memoryMetric": "kernel-cgroup-charged-container-memory",
        "comparisons": [],
        "blockers": [],
    }
    try:
        expected = [
            (a, p)
            for p in range(1, 6)
            for a in (("rust", "typescript") if p % 2 else ("typescript", "rust"))
        ]
        require(
            type(rows) is list
            and [(r.get("backend"), r.get("pair")) for r in rows] == expected,
            "five_alternating_pairs_required",
        )
        conditions = rows[0].get("conditions")
        require(
            type(conditions) is dict
            and set(conditions) == REQUIRED_CONDITIONS
            and all(
                type(v) is str and v.lower() not in ("", "unknown", "unverified")
                for v in conditions.values()
            ),
            "matched_conditions_required",
        )
        for row in rows:
            require(
                row.get("conditions") == conditions
                and row.get("scope") == "isolated-ci-fixture-application-container"
                and row.get("metric") == "kernel-cgroup-charged-memory-NOT-RSS",
                "cross_arm_scope_or_conditions_mismatch",
            )
            terminal = row.get("terminal")
            require(
                type(terminal) is dict
                and terminal.get("status") == "observed"
                and type(terminal.get("lifetimePeakBytes")) is int
                and terminal["lifetimePeakBytes"] > 0
                and terminal.get("unit") == "B",
                "complete_lifetime_peak_unavailable",
            )
        metrics = {}
        for row in rows:
            values = {"lifetimePeakBytes": row["terminal"]["lifetimePeakBytes"]}
            if conditions["lifecycle"] == "long-lived":
                for phase in ("steady", "retained"):
                    observations = [
                        s.get("currentBytes")
                        for s in row.get("samples", [])
                        if s.get("phase") == phase
                        and s.get("status") == "observed"
                        and s.get("unit") == "B"
                    ]
                    require(
                        len(observations) >= 5
                        and all(type(v) is int and v > 0 for v in observations),
                        "five_matched_" + phase + "_observations_required",
                    )
                    values[phase + "CurrentBytes"] = max(observations)
            else:
                require(
                    conditions["lifecycle"] == "ephemeral-command", "unknown_lifecycle"
                )
            metrics[row["backend"], row["pair"]] = values
        for metric in metrics["rust", 1]:
            for pair in range(1, 6):
                values = {
                    arm: metrics[arm, pair][metric] for arm in ("rust", "typescript")
                }
                out["comparisons"].append(
                    {
                        "metric": metric,
                        "pair": pair,
                        "rustBytes": values["rust"],
                        "typescriptBytes": values["typescript"],
                        "status": "passed"
                        if values["rust"] <= values["typescript"]
                        else "failed",
                    }
                )
            arms = {
                arm: sorted(metrics[arm, pair][metric] for pair in range(1, 6))
                for arm in ("rust", "typescript")
            }
            for name, index in (("median", 2), ("p95NearestRank", 4)):
                out["comparisons"].append(
                    {
                        "metric": metric,
                        "statistic": name,
                        "rustBytes": arms["rust"][index],
                        "typescriptBytes": arms["typescript"][index],
                        "status": "passed"
                        if arms["rust"][index] <= arms["typescript"][index]
                        else "failed",
                    }
                )
        out["status"] = (
            "failed"
            if any(r["status"] == "failed" for r in out["comparisons"])
            else "unverified"
        )
        out["blockers"].append(
            "ci_fixture_not_personal_dev_and_independent_receipt_acceptance_required"
        )
    except (Unavailable, KeyError, TypeError) as error:
        out["blockers"].append(
            str(error) if type(error) is Unavailable else "malformed_cohort"
        )
    return out
