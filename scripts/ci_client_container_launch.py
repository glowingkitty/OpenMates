"""Managed isolated-CI per-arm application launch and outside-memory hold hook.

No service/image build, privileged mode, host PID/network mode or cgroup mount.
Root's existing immutable CI owner supplies verified image/tools/workload/state.
"""

from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import math
import os
import re
import selectors
import signal
import stat
import subprocess
import threading
import time
import uuid
from scripts import ci_client_container_memory as memory


class Refused(ValueError):
    pass


def need(ok, reason):
    if not ok:
        raise Refused(reason)


def canonical(path):
    p = Path(path)
    need(
        p.is_absolute()
        and p.resolve() == p
        and not p.is_symlink()
        and "," not in str(p)
        and "\n" not in str(p),
        "unsafe_bind_path",
    )
    return p


@dataclass(frozen=True)
class Config:
    source_root: Path
    private_root: Path
    source: str
    image: str
    runtime_key: str
    gateway: str
    owner: str
    arm: str
    pair: int
    argv: tuple
    env: dict
    cwd: Path
    readonly_paths: tuple
    state_root: Path
    conditions: tuple
    deadline: float
    work_deadline: float
    memory_limit: int
    pids_limit: int
    cpus: str
    uid: int
    gid: int
    supervisor: Path
    supervisor_sha256: str
    # Bounded whole-application CLI fixture workload; original TUI/renderer adapters stay separate.
    surface: str = "cli"
    max_application_seconds: int = 30  # Original full-application offline_sample bound.
    meter: object = None  # Optional contained path; default flow unchanged.


def validate(c):
    need(type(c) is Config and c.surface == "cli", "exact_cli_fixture_config_required")
    need(
        type(c.max_application_seconds) is int and 0 < c.max_application_seconds <= 30,
        "original_application_timeout_required",
    )
    need(
        c.arm in ("rust", "typescript")
        and type(c.pair) is int
        and c.pair in range(1, 6),
        "arm_pair",
    )
    need(
        re.fullmatch("[a-f0-9]{40}", c.source)
        and re.fullmatch("sha256:[a-f0-9]{64}", c.image)
        and re.fullmatch("[a-f0-9]{64}", c.gateway),
        "pinned_source_image_gateway",
    )
    need(
        type(c.argv) is tuple
        and c.argv
        and all(type(v) is str for v in c.argv)
        and Path(c.argv[0]).is_absolute(),
        "ordinary_absolute_argv_required",
    )
    need(
        not any(
            v in ("--model", "--provider") or v.startswith(("--model=", "--provider="))
            for v in c.argv
        ),
        "automatic_routing_required",
    )
    need(
        type(c.uid) is int
        and c.uid > 0
        and c.uid == os.getuid()
        and type(c.gid) is int
        and c.gid > 0
        and c.gid == os.getgid(),
        "nonroot_runner_identity_required",
    )
    need(
        type(c.owner) is str and re.fullmatch("[a-zA-Z0-9._:-]{1,80}", c.owner),
        "bounded_owner_required",
    )
    need(
        type(c.memory_limit) is int
        and c.memory_limit > 0
        and type(c.pids_limit) is int
        and 1 < c.pids_limit <= 512
        and re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", c.cpus),
        "fixed_resource_limits_required",
    )
    need(
        all(
            type(v) in (int, float) and math.isfinite(v)
            for v in (c.deadline, c.work_deadline)
        )
        and time.monotonic() < c.work_deadline < c.deadline
        and c.deadline - c.work_deadline >= 8,
        "original_budget_cleanup_headroom_required",
    )
    root = canonical(c.source_root)
    private = canonical(c.private_root)
    state = canonical(c.state_root)
    canonical(c.cwd)
    supervisor = canonical(c.supervisor)
    need(
        supervisor.is_file()
        and supervisor.stat().st_size <= 65536
        and hashlib.sha256(supervisor.read_bytes()).hexdigest() == c.supervisor_sha256,
        "pinned_common_supervisor_required",
    )
    need(
        private.is_relative_to(root / "test-results/ci-private/client-memory")
        and state.is_relative_to(private),
        "disposable_ci_state_required",
    )
    for p in c.readonly_paths:
        canonical(p)
        need(
            str(p) != "/"
            and not any(
                Path(p).is_relative_to(Path(base))
                for base in ("/proc", "/sys", "/dev", "/run", "/var/run")
            ),
            "unsafe_runtime_bind",
        )
    need(
        any(
            Path(c.argv[0]).is_relative_to(Path(p)) or Path(c.argv[0]) == Path(p)
            for p in c.readonly_paths
        ),
        "executable_readonly_pin_missing",
    )
    need(
        type(c.env) is dict
        and all(type(k) is str and type(v) is str for k, v in c.env.items()),
        "exact_environment_required",
    )
    if c.meter is not None:
        from scripts.ci_client_contained_meter import validate_spec
        validate_spec(c.meter, root)
        need(not any(key.startswith("LD_") or key in ("GLIBC_TUNABLES", "GCONV_PATH") for key in c.env), "meter_loader_environment_unsupported")
        need(not c.meter.binary.is_relative_to(private), "meter_outside_application_state")
        adapter = root / "scripts/ci_client_contained_meter.py"
        canonical(adapter)
        need(adapter.is_file(), "pinned_contained_adapter_required")
    return c


class Launch:
    def __init__(self, c, run=subprocess.run, popen=subprocess.Popen):
        self.c = validate(c)
        self.run = run
        self.popen = popen
        self.cid = None
        self.proxy = None
        self.reader = None
        self.cancelled = False
        self.removed = False
        self.old = {}
        self.measurement = None
        self.nonce = uuid.uuid4().hex
        self.name = "om-ci-memory-" + self.nonce
        self.control = c.private_root / self.nonce
        self.held = None
        self.create_attempted = False
        self.proxyfd = None
        self.identity_owner = c.owner + ":" + self.nonce
        self.container_exit = None
        self.cleanup_started = False
        self.last_cleanup_result = False
        self.bridge = None
        self.cleanup_problems = []
        self.contained = None

    def command(self, *args, timeout=10):
        from ci_environment import require_runner

        require_runner()
        left = self.c.deadline - time.monotonic()
        need(left > 0, "original_deadline")
        result = self.run(
            ["docker", *args],
            capture_output=True,
            timeout=min(timeout, left),
            check=False,
        )
        need(result.returncode == 0, "owned_docker_operation_failed")
        return result

    def check(self):
        need(self.cid is not None, "container_not_created")
        actual = memory.validate_owned(
            memory.inspect_owned(
                self.cid,
                timeout=min(10, max(0.001, self.c.deadline - time.monotonic())),
            ),
            self.owned,
        )
        return actual

    def create_argv(self):
        c = self.c
        labels = {
            "org.openmates.source": c.source,
            "com.docker.compose.project": "openmates-ci",
            "com.docker.compose.service": "benchmark-client-" + c.arm,
            "org.openmates.benchmark.role": "application-memory",
            "org.openmates.benchmark.owner": self.identity_owner,
            "org.openmates.benchmark.arm": c.arm,
            "org.openmates.benchmark.pair": str(c.pair),
        }
        cmd = [
            "create",
            "--name",
            self.name,
            "--interactive",
            "--read-only",
            "--user",
            f"{c.uid}:{c.gid}",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            str(c.pids_limit),
            "--memory",
            str(c.memory_limit),
            "--memory-swap",
            str(c.memory_limit),
            "--cpus",
            c.cpus,
            "--network",
            "container:" + c.gateway,
            "--restart",
            "no",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,size=64m",
            "--entrypoint",
            "/usr/local/bin/python3",
        ]
        for key, value in labels.items():
            cmd += ["--label", key + "=" + value]
        paths = list(c.readonly_paths)
        if c.meter is not None:
            paths += [c.meter.binary, c.source_root / "scripts/ci_client_contained_meter.py"]
        for p in dict.fromkeys(paths):
            cmd += ["--mount", f"type=bind,src={p},dst={p},readonly"]
        cmd += [
            "--mount",
            f"type=bind,src={c.supervisor},dst={c.supervisor},readonly",
            "--mount",
            f"type=bind,src={c.state_root},dst={c.state_root}",
            "--mount",
            f"type=bind,src={self.control},dst={self.control}",
            c.image,
            "-I",
            str(c.supervisor),
            str(self.control / "launch.json"),
        ]
        return cmd

    def prepare(self):
        from ci_environment import require_runner
        from ci_runtime_images import verify_loaded_image

        require_runner()
        validate(self.c)
        verify_loaded_image(self.c.source_root, "api", self.c.image, self.c.runtime_key)
        # Existing private runner-gateway namespace preserves localhost API argv without host networking.
        template = '{"id":{{json .Id}},"running":{{json .State.Running}},"source":{{json (index .Config.Labels "org.openmates.source")}},"project":{{json (index .Config.Labels "com.docker.compose.project")}},"service":{{json (index .Config.Labels "com.docker.compose.service")}}}'
        gateway = json.loads(
            self.command("inspect", "--format", template, self.c.gateway).stdout
        )
        need(
            gateway
            == {
                "id": self.c.gateway,
                "running": True,
                "source": self.c.source,
                "project": "openmates-ci",
                "service": "runner-gateway",
            },
            "managed_gateway_identity",
        )
        self.control.mkdir(mode=0o700, parents=False)
        cfg = {
            "nonce": self.nonce,
            "argv": list(self.c.argv),
            "env": self.c.env,
            "cwd": str(self.c.cwd),
            "deadlineNs": int(self.c.deadline * 1e9),
            "workDeadlineNs": int(
                min(self.c.work_deadline,time.monotonic()+self.c.max_application_seconds)
                * 1e9
            ),
            "termGraceNs": 3_000_000_000,
        }
        if self.c.meter is not None:
            adapter = self.c.source_root / "scripts/ci_client_contained_meter.py"
            cfg["meter"] = {
                "binary": str(self.c.meter.binary),
                "binarySha256": self.c.meter.binary_sha256,
                "sourceSha256": self.c.meter.source_sha256,
                "adapter": str(adapter),
                "adapterSha256": hashlib.sha256(adapter.read_bytes()).hexdigest(),
                "lifecycle": self.c.meter.lifecycle,
            }
        fd = os.open(
            self.control / "launch.json",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
        )
        with os.fdopen(fd, "w") as stream:
            json.dump(cfg, stream)
        self.create_attempted = True
        raw = self.command(*self.create_argv()).stdout.strip().decode("ascii")
        need(re.fullmatch("[a-f0-9]{64}", raw), "created_container_identity")
        self.cid = raw
        self.owned = memory.Owned(
            raw,
            self.c.source,
            self.c.image,
            "openmates-ci",
            "benchmark-client-" + self.c.arm,
            self.identity_owner,
            self.c.arm,
            self.c.pair,
            self.c.conditions,
        )

    def status(self):
        try:
            fd = os.open(
                self.control / "status.json",
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            )
            try:
                info = os.fstat(fd)
                need(
                    stat.S_ISREG(info.st_mode)
                    and info.st_uid == os.getuid()
                    and info.st_nlink == 1
                    and 0 < info.st_size < 4096,
                    "status_identity",
                )
                raw = os.read(fd, 4096)
                need(len(raw) == info.st_size, "status_bound")
                value = json.loads(raw)
                need(value.get("nonce") == self.nonce, "attempt_status_identity")
                return value
            finally:
                os.close(fd)
        except FileNotFoundError:
            return None

    def flag(self, name):
        need(name in ("go", "release"), "control_flag")
        fd = os.open(
            self.control / name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
        )
        os.close(fd)

    def wait_state(self, state):
        while time.monotonic() < self.c.deadline:
            row = self.status()
            if row and row.get("state") == state:
                return row
            if self.cancelled:
                raise Refused("cancelled")
            time.sleep(0.01)
        raise Refused("original_deadline")

    def start(self, stdin, stdout, stderr):
        def stop(signum, frame):
            self.cancelled = True

        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            self.old[sig] = signal.signal(sig, stop)
        try:
            need(not self.cancelled, "cancelled")
            self.prepare()
            need(not self.cancelled, "cancelled")
            self.proxy = self.popen(
                ["docker", "start", "--attach", "--interactive", self.cid],
                stdin=stdin,
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
            )
            self.proxyfd = os.pidfd_open(self.proxy.pid)
            self.wait_state("ready")
            need(not self.cancelled, "cancelled_before_go")
            self.reader = memory.Reader(self.owned, deadline=self.c.deadline)
            if self.c.meter is not None:
                from scripts.ci_client_contained_meter import Outside
                self.contained = Outside(self)
            need(not self.cancelled, "cancelled_before_go")
            self.bridge = HeldTerminalBridge(self)
            self.bridge.start()
            self.flag("go")
            return self.proxy
        except BaseException:
            self.cleanup()
            raise

    def application_peak(self, row):
        # Receipt alone is insufficient: outside kernel cgroup must contain ONLY PID1.
        need(
            row.get("state") == "held"
            and row.get("childrenDrained") is True
            and type(row.get("applicationExit")) is int,
            "application_terminal_status",
        )
        self.reader.recheck()
        fd = os.open(
            "cgroup.procs",
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=self.reader.fd,
        )
        try:
            memory.cgroup2_fd(fd)
            raw = os.read(fd, 65537)
            need(len(raw) <= 65536, "owned_process_list_bound")
            pids = [int(v) for v in raw.split()]
        finally:
            os.close(fd)
        need(pids == [self.reader.pid], "application_descendants_not_drained")
        snap = self.reader.sample("before-exit")
        need(snap.get("status") == "observed", "outside_memory_unavailable")
        result = {
            "status": "observed"
            if row["applicationExit"] == 0 and not row.get("cancelled")
            else "failed",
            "unit": "B",
            "applicationLifetimeContainerPeakBytes": snap["peakSoFarBytes"],
            "containerCurrentBytesAtDrain": snap["currentBytes"],
            "applicationExit": row["applicationExit"],
            "boundary": "application-and-descendants-drained-common-pid1-still-live",
            "includesCommonSupervisor": True,
            "fullContainerTeardownPeakClaimed": False,
        }
        if self.c.meter is not None:
            need(self.contained is not None, "actual_contained_admission_required")
            result["containedRss"] = self.contained.completed()
            result["chargedDiagnosticIncludes"] = "common-pid1-plus-common-meter-plus-application"
        return result

    def marker(self, phase, sequence):
        need(self.contained is not None and self.c.meter.lifecycle == "long-lived", "actual_long_lived_contained_session")
        need((self.status() or {}).get("state") != "held", "application_already_drained")
        return self.contained.marker(phase, sequence)

    def release_once(self):
        path = self.control / "release"
        try:
            info = path.lstat()
            need(
                stat.S_ISREG(info.st_mode)
                and info.st_uid == os.getuid()
                and info.st_nlink == 1
                and info.st_size == 0,
                "release_control_identity",
            )
        except FileNotFoundError:
            self.flag("release")

    def finish(self):
        result = {
            "status": "unverified",
            "acceptanceEligible": False,
            "currentMigrationAcceptance": False,
            "metric": "kernel-total-container-memory-not-rss",
            "scope": "isolated-ci-cli-fixture-plus-common-supervisor",
            "memory": None,
            "cleanupVerified": False,
        }
        try:
            need(
                hashlib.sha256(self.c.supervisor.read_bytes()).hexdigest()
                == self.c.supervisor_sha256,
                "supervisor_changed",
            )
            if self.c.meter is not None:
                from scripts.ci_client_contained_meter import validate_spec
                validate_spec(self.c.meter, self.c.source_root)
            need(
                self.bridge is not None and self.bridge.join(),
                "held_collector_not_drained",
            )
            result["memory"] = self.bridge.memory
            if self.bridge.error:
                result["code"] = self.bridge.error
        except Exception:
            result["code"] = "application_memory_or_identity_unavailable"
        finally:
            # Release/control/inspection failure cannot bypass the independent attach reap.
            result["cleanupVerified"] = self.cleanup()
            result["containerExitCode"] = self.container_exit
            if self.bridge and result["memory"] is None:
                result["memory"] = self.bridge.memory
            if (
                result["memory"]
                and result["memory"]["status"] == "observed"
                and self.container_exit != result["memory"]["applicationExit"]
            ):
                result["memory"]["status"] = "failed"
                result["code"] = "actual_container_terminal_exit_mismatch"
            result["cleanupProblems"] = list(self.cleanup_problems)
            if self.reader:
                result["observations"] = self.reader.report()
        return result

    def cleanup_identity(self, row):
        # OOM is a measurement failure, not loss of this exact container's ownership.
        need(
            type(row) is dict
            and type(row.get("running")) is bool
            and type(row.get("oom")) is bool,
            "cleanup_state_unknown",
        )
        expected = {
            "id": self.cid,
            "source": self.c.source,
            "image": self.c.image,
            "project": "openmates-ci",
            "service": "benchmark-client-" + self.c.arm,
            "role": "application-memory",
            "owner": self.identity_owner,
            "arm": self.c.arm,
            "pair": str(self.c.pair),
            "pidMode": "",
            "cgroupParent": "",
        }
        need(
            all(row.get(k) == v for k, v in expected.items())
            and row.get("privileged") is False
            and row.get("autoremove") is False
            and type(row.get("restarts")) is int
            and row["restarts"] == 0,
            "cleanup_ownership_mismatch",
        )
        return row

    def recover_created(self):
        if self.cid is None and self.create_attempted:
            row = json.loads(
                self.command("inspect", "--format", memory.TEMPLATE, self.name).stdout
            )
            candidate = memory.Owned(
                row.get("id"),
                self.c.source,
                self.c.image,
                "openmates-ci",
                "benchmark-client-" + self.c.arm,
                self.identity_owner,
                self.c.arm,
                self.c.pair,
                self.c.conditions,
            )
            memory.validate_owned(row, candidate, running=row.get("running"))
            self.cid = candidate.container
            self.owned = candidate

    def reap_proxy(self):
        if self.proxy is None:
            return
        for sig, seconds in ((None, 1), (signal.SIGTERM, 1), (signal.SIGKILL, 1)):
            if sig is not None:
                if self.proxyfd is not None:
                    try:
                        signal.pidfd_send_signal(self.proxyfd, sig)
                    except ProcessLookupError:
                        pass
                elif self.proxy.returncode is None:
                    # Original unreaped Popen child; no competing terminal waiter.
                    self.proxy.send_signal(sig)
            try:
                self.proxy.wait(
                    timeout=max(0.001, min(seconds, self.c.deadline - time.monotonic()))
                )
                return
            except subprocess.TimeoutExpired:
                continue
        raise Refused("owned_attach_process_not_reaped")

    def stop_owned_container(self):
        self.recover_created()
        if self.cid is None:
            return False
        for sig, grace in (("TERM", 3), ("KILL", 3)):
            state = json.loads(
                self.command("inspect", "--format", memory.TEMPLATE, self.cid).stdout
            )
            self.cleanup_identity(state)
            if state["running"]:
                self.command("kill", "--signal", sig, self.cid)
                try:
                    self.command("wait", self.cid, timeout=grace)
                except (Refused, subprocess.TimeoutExpired):
                    continue
            final = json.loads(
                self.command("inspect", "--format", memory.TEMPLATE, self.cid).stdout
            )
            self.cleanup_identity(final)
            need(
                final["running"] is False and type(final.get("exit")) is int,
                "container_not_stopped",
            )
            self.container_exit = final["exit"]
            return True
        return False

    def cleanup(self):
        self.cleanup_started = True
        container_stopped = False
        proxy_reaped = False
        collector_drained = True
        contained_handles_closed = True
        # Each resource has an independent cleanup path. A failed file/inspect must not
        # gate our known direct Popen child. Foreign/unknown containers remain untouched.
        try:
            if self.bridge:
                collector_drained = self.bridge.stop_and_join()
        except BaseException:
            collector_drained = False
            self.cleanup_problems.append("collector_join_failed")
        try:
            if self.control.exists():
                self.release_once()
        except BaseException:
            self.cleanup_problems.append("release_control_failed")
        try:
            if collector_drained:
                container_stopped = self.stop_owned_container()
        except BaseException:
            self.cleanup_problems.append("container_ownership_or_stop_failed")
        try:
            self.reap_proxy()
            proxy_reaped = True
        except BaseException:
            self.cleanup_problems.append("owned_attach_reap_failed")
        try:
            if container_stopped and proxy_reaped and collector_drained:
                final = json.loads(
                    self.command(
                        "inspect", "--format", memory.TEMPLATE, self.cid
                    ).stdout
                )
                self.cleanup_identity(final)
                need(final["running"] is False, "container_not_stopped")
                self.command("rm", self.cid)
                self.removed = True
        except BaseException:
            self.cleanup_problems.append("owned_remove_failed")
        finally:
            try:
                if self.reader and collector_drained:
                    self.reader.close()
            except BaseException:
                self.cleanup_problems.append("reader_close_failed")
            try:
                if self.proxyfd is not None:
                    os.close(self.proxyfd)
                    self.proxyfd = None
            except BaseException:
                self.cleanup_problems.append("pidfd_close_failed")
            try:
                if self.contained is not None:
                    self.contained.close()
            except BaseException:
                contained_handles_closed = False
                self.cleanup_problems.append("contained_handles_close_failed")
            for sig, handler in self.old.items():
                try:
                    signal.signal(sig, handler)
                except BaseException:
                    self.cleanup_problems.append("signal_restore_failed")
            self.old = {}
        self.last_cleanup_result = (
            container_stopped and proxy_reaped and collector_drained and self.removed and contained_handles_closed
        )
        return self.last_cleanup_result


class HeldTerminalBridge:
    'Concurrent outside-reader controller; never reads app output or waits Popen.\n\n It MUST run while the actual IO driver drains/waits terminal output. App drain\n -> outside kernel peak -> release -> attach EOF/exit is the intentional order.\n '

    def __init__(self, launch):
        self.launch = launch
        self.stop_event = threading.Event()
        self.memory = None
        self.error = None
        self.started = False
        self.thread = threading.Thread(target=self.run, daemon=True)

    def start(self):
        self.thread.start()
        self.started = True

    def run(self):
        try:
            while (
                not self.stop_event.is_set()
                and time.monotonic() < self.launch.c.deadline
            ):
                need(not self.launch.cancelled, "cancelled")
                row = self.launch.status()
                if row and row.get("state") == "held":
                    self.launch.held = row
                    self.memory = self.launch.application_peak(row)
                    self.launch.release_once()
                    return
                self.stop_event.wait(0.01)
            if not self.stop_event.is_set():
                raise Refused("original_deadline")
        except BaseException:
            self.error = "held_collection_or_release_failed"
            # Failed collection must still unblock a real terminal-waiting IO driver.
            released = False
            try:
                self.launch.release_once()
                released = True
            except BaseException:
                pass
            if self.launch.cancelled or self.launch.held is None or not released:
                try:
                    self.launch.stop_owned_container()
                except BaseException:
                    pass  # Unknown container ownership never authorizes kill.

    def join(self):
        if not self.started:
            return True
        self.thread.join(timeout=max(0, self.launch.c.deadline - time.monotonic()))
        return not self.thread.is_alive()

    def stop_and_join(self):
        self.stop_event.set()
        return self.join()


MAX_OUTPUT = 2 * 1024 * 1024  # Unchanged original authenticated CLI bound, per stream.


def drain_complete_output(proxy, deadline, merged_stderr=False):
    'Real bounded stdio consumer, including bytes after app exit until actual EOF.\n\n Bridge controls only cgroup hold/release. This function alone waits the proxy\n terminal result; cleanup only reaps later, after this driver returns/raises.\n '
    output = {"stdout": bytearray(), "stderr": bytearray()}
    selector = selectors.DefaultSelector()
    try:
        need(
            type(merged_stderr) is bool and (not merged_stderr or proxy.stderr is None),
            "original_merged_stdio_required",
        )
        for name in ("stdout",) if merged_stderr else output:
            stream = getattr(proxy, name)
            need(stream is not None, "private_stdio_required")
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, name)
        while selector.get_map():
            left = deadline - time.monotonic()
            need(left > 0, "original_output_deadline")
            for key, _ in selector.select(min(0.01, left)):
                try:
                    chunk = os.read(key.fd, 65536)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                output[key.data].extend(chunk)
                need(len(output[key.data]) <= MAX_OUTPUT, "original_output_bound")
        code = proxy.wait(timeout=max(0.001, deadline - time.monotonic()))
        return {
            "stdout": bytes(output["stdout"]),
            "stderr": bytes(output["stderr"]),
            "exitCode": code,
            "complete": True,
        }
    except BaseException as error:
        # Preserve observed bytes in private memory even for deadline/bound failures.
        private_output = {k: bytes(v) for k, v in output.items()}
        if not isinstance(error, Exception):
            # Keep cancellation/termination exceptional through the actual nested driver.
            # Owned collector finally still records partial output/memory and drains.
            error.private_output = private_output
            raise
        failure = Refused("output_collection_failed")
        failure.private_output = private_output
        raise failure from None
    finally:
        selector.close()
        for stream in (getattr(proxy, "stdout", None), getattr(proxy, "stderr", None)):
            try:
                if stream is not None:
                    stream.close()
            except Exception:
                pass


class CliJsonDriver:
    'Concrete memory-only CLI IO adapter; source/fixture/output verifier is existing harness code.\n\n Full bytes stay private in outputs. Only byte counts go into attempt reports.\n No traced/Docker timing replaces the original untraced latency/CPU cohort.\n '

    def __init__(self, verify_complete_output):
        need(callable(verify_complete_output), "existing_full_output_verifier_required")
        self.verify = verify_complete_output
        self.outputs = {}
        self.values = {}

    def open(self, cfg):
        return subprocess.DEVNULL, subprocess.PIPE, subprocess.PIPE

    def drive(self, cfg, proxy):
        key = (cfg.arm, cfg.pair)
        try:
            data = drain_complete_output(proxy, cfg.deadline)
            self.outputs[key] = data
            need(
                type(data["exitCode"]) is int and data["exitCode"] == 0,
                "actual_app_or_container_nonzero",
            )
            value = json.loads(data["stdout"])
            self.verify(cfg, value)
            self.values[key] = value
        except BaseException as error:
            if hasattr(error, "private_output"):
                self.outputs[key] = {
                    **error.private_output,
                    "complete": False,
                    "exitCode": getattr(proxy, "returncode", None),
                }
            raise


def fixed_cohort(configs):
    """Pure preflight for the existing five-pair fixed workload; no runtime operations."""
    expected = [
        (arm, pair)
        for pair in range(1, 6)
        for arm in (("rust", "typescript") if pair % 2 else ("typescript", "rust"))
    ]
    need(
        type(configs) is list
        and len(configs) == 10
        and all(type(c) is Config for c in configs)
        and [(c.arm, c.pair) for c in configs] == expected,
        "five_alternating_pairs_required",
    )

    def common(c):
        return (
            c.image,
            c.runtime_key,
            c.supervisor_sha256,
            c.uid,
            c.gid,
            c.memory_limit,
            c.pids_limit,
            c.cpus,
            c.conditions,
            c.deadline,
            c.work_deadline,
            c.max_application_seconds,
            c.meter,
        )

    need(
        all(common(c) == common(configs[0]) for c in configs),
        "identical_container_tool_security_lifecycle_conditions_required",
    )
    need(
        set(dict(configs[0].conditions)) == memory.REQUIRED_CONDITIONS
        and all(
            type(v) is str and v.lower() not in ("", "unknown", "unverified")
            for _, v in configs[0].conditions
        ),
        "complete_matched_conditions_required",
    )
    return tuple(configs)


def collect_fixed_cli_memory(configs, driver, *, attempts=None):
    'Use original admitted fixture IO/output driver, with no retry or source rewrite.\n\n driver.open(cfg) supplies existing private stdio; driver.drive(cfg, proxy) does\n exactly the original bounded work/output/cancel assertions. Its failures remain\n failed attempts. It is trusted existing harness code, never serialized policy.\n '
    configs = fixed_cohort(configs)
    need(
        attempts is None or (type(attempts) is list and not attempts),
        "fresh_private_attempt_sink_required",
    )
    rows = [] if attempts is None else attempts
    for cfg in configs:
        launch = None
        row = {
            "backend": cfg.arm,
            "pair": cfg.pair,
            "status": "unverified",
            "acceptanceEligible": False,
            "memory": None,
        }
        try:
            launch = Launch(cfg)
            stdio = driver.open(cfg)
            proxy = launch.start(*stdio)
            driver.drive(cfg, proxy)
            row.update(launch.finish())
        except Exception:
            row.update(status="failed", code="fixed_memory_attempt_failed")
        except BaseException:
            row.update(status="interrupted", code="fixed_memory_attempt_interrupted")
            raise
        finally:
            if launch:
                if not launch.cleanup_started:
                    launch.cleanup()
                row["cleanupVerified"] = launch.last_cleanup_result
                if getattr(launch, "bridge", None):
                    row.setdefault("memory", None)
                    if row["memory"] is None:
                        row["memory"] = launch.bridge.memory
                    if launch.bridge.error:
                        row["collectionError"] = launch.bridge.error
            data = getattr(driver, "outputs", {}).get((cfg.arm, cfg.pair))
            if data:
                row["output"] = {
                    "stdoutBytes": len(data["stdout"]),
                    "stderrBytes": len(data["stderr"]),
                    "complete": data["complete"],
                    "exitCode": data["exitCode"],
                }
            rows.append(row)
        if launch and launch.cancelled:
            break  # Partial cohort stays partial; no retries.
    return {
        "status": "unverified",
        "acceptanceEligible": False,
        "currentMigrationAcceptance": False,
        "scope": "isolated-ci-cli-fixture-plus-common-supervisor",
        "attempts": rows,
        "originalCpuAndWall": "separate-unchanged-original-cohort-required",
    }
