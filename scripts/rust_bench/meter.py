"""Process-tree meter: wall time, CPU (user+sys) and peak memory of a command tree.

Every sample runs through ``launch.c`` (compiled once with ``cc``): a tiny
launcher that forks the CLI from itself, is a child subreaper (orphaned or
daemonized descendants re-parent to it) and reaps every process with wait4().
A child forked directly from Python would inherit Python's resident pages in
its ru_maxrss high-water mark (Linux folds it across exec); the launcher avoids
that.

Two memory/CPU backends, chosen once per run and recorded in the report:

* ``cgroup`` - cgroup v2. The harness runs inside a cgroup it may write to (a
  delegated transient systemd scope, see ``maybe_reexec_in_scope``). Each sample
  gets a fresh leaf cgroup that the target joins *before* exec, so every
  descendant is accounted: CPU = cpu.stat user_usec + system_usec, peak memory =
  memory.peak (highest concurrent charge of the whole tree: anon memory plus
  page cache first charged by the sample).
* ``rusage`` - fallback without a delegated cgroup. CPU = sum over all reaped
  processes of ru_utime+ru_stime (each includes its own waited-for children,
  nothing is counted twice). Peak memory = max ru_maxrss over reaped processes,
  i.e. the largest single-process high-water mark, not the concurrent tree sum.
  Both CLIs are essentially single-process trees (the npm launcher `sh` execs
  `node`; ru_maxrss survives exec), so this is a close approximation.

rusage data (``maxRssKiB``, ``rusageCpuMs``) is recorded in both modes. Wall time
is the launcher's fork -> reap of the main process; descendants still running
after that are reaped (or SIGKILLed after 5 s) without extending wall time.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

CGROUP_ROOT = Path("/sys/fs/cgroup")
SCOPE_MARKER = "RUST_BENCH_IN_SCOPE"
SCOPE_FAILURE = "RUST_BENCH_SCOPE_FAILURE"
LAUNCH_SOURCE = Path(__file__).with_name("launch.c")


class MeterError(RuntimeError):
    pass


def own_cgroup(proc_self: Path = Path("/proc/self/cgroup"), root: Path = CGROUP_ROOT) -> Path | None:
    """Path of this process's cgroup v2 directory, or None on cgroup v1/hybrid."""
    try:
        for line in proc_self.read_text().splitlines():
            if line.startswith("0::"):
                return root / line[3:].lstrip("/")
    except OSError:
        return None
    return None


class CgroupBackend:
    """Per-sample leaf cgroups below a delegated cgroup owned by this user."""

    def __init__(self, base: Path):
        self.base = base
        self.counter = 0

    @classmethod
    def try_create(cls, base: Path | None = None) -> tuple["CgroupBackend | None", str]:
        base = base or own_cgroup()
        if base is None or not (base / "cgroup.controllers").exists():
            return None, "cgroup v2 not mounted"
        if "memory" not in (base / "cgroup.controllers").read_text().split():
            return None, "memory controller not delegated to this cgroup"
        if not os.access(base / "cgroup.procs", os.W_OK) or not os.access(base, os.W_OK):
            return None, "own cgroup is not writable (not a delegated scope)"
        harness = base / "rust-bench-harness"
        try:
            harness.mkdir(exist_ok=True)
            # cgroup v2 "no internal processes": move ourselves into a leaf
            # before enabling the memory controller for sibling sample cgroups.
            (harness / "cgroup.procs").write_text(str(os.getpid()))
            if "memory" not in (base / "cgroup.subtree_control").read_text().split():
                (base / "cgroup.subtree_control").write_text("+memory")
        except OSError as error:
            return None, f"cgroup delegation setup failed: {error.strerror}"
        return cls(base), "delegated cgroup v2"

    def new_sample(self) -> Path:
        self.counter += 1
        path = self.base / f"rust-bench-sample-{os.getpid()}-{self.counter}"
        path.mkdir()
        if not (path / "memory.peak").exists():
            path.rmdir()
            raise MeterError("memory.peak unavailable (kernel < 5.19?)")
        return path

    @staticmethod
    def populated(path: Path) -> bool:
        for line in (path / "cgroup.events").read_text().splitlines():
            if line.startswith("populated "):
                return line.split()[1] == "1"
        return False

    @staticmethod
    def kill(path: Path) -> None:
        kill_file = path / "cgroup.kill"
        if kill_file.exists():
            kill_file.write_text("1")
            return
        for pid in (path / "cgroup.procs").read_text().split():
            try:
                os.kill(int(pid), signal.SIGKILL)
            except ProcessLookupError:
                pass

    @staticmethod
    def read(path: Path) -> dict:
        stat = dict(line.split() for line in (path / "cpu.stat").read_text().splitlines() if line.strip())
        peak = int((path / "memory.peak").read_text().strip())
        return {"userUs": int(stat["user_usec"]), "systemUs": int(stat["system_usec"]), "peakBytes": peak}

    @staticmethod
    def remove(path: Path) -> None:
        deadline = time.monotonic() + 2.0
        while True:
            try:
                path.rmdir()
                return
            except OSError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.01)


def launcher_binary() -> Path:
    """Compile launch.c once per source digest into the user cache."""
    digest = hashlib.sha256(LAUNCH_SOURCE.read_bytes()).hexdigest()[:16]
    cache = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "openmates-rust-bench"
    binary = cache / f"launch-{digest}"
    if binary.is_file() and os.access(binary, os.X_OK):
        return binary
    compiler = os.environ.get("CC") or shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    if not compiler:
        raise MeterError("a C compiler (cc/gcc/clang) is required to build the rust_bench launcher")
    cache.mkdir(parents=True, exist_ok=True)
    temporary = cache / f".launch-{digest}-{os.getpid()}"
    build = subprocess.run([compiler, "-O2", "-Wall", "-o", str(temporary), str(LAUNCH_SOURCE)],
                           capture_output=True, text=True, timeout=120)
    if build.returncode != 0:
        raise MeterError(f"launcher build failed: {build.stderr.strip()[:500]}")
    os.replace(temporary, binary)
    return binary


class Meter:
    def __init__(self, backend: CgroupBackend | None, reason: str):
        self.cgroup = backend
        self.reason = reason
        self.launcher = launcher_binary()

    def describe(self) -> dict:
        if self.cgroup:
            return {"memory": "cgroup-memory.peak", "cpu": "cgroup-cpu.stat", "detail": self.reason,
                    "launcher": "c-subreaper-wait4"}
        return {"memory": "rusage-max-process-maxrss", "cpu": "rusage-tree-sum", "detail": self.reason,
                "launcher": "c-subreaper-wait4"}

    def run(self, argv: list[str], env: dict, cwd: str | None = None, timeout: float = 300.0,
            stdout_path: Path | None = None, stderr_path: Path | None = None) -> dict:
        sample_cg = self.cgroup.new_sample() if self.cgroup else None
        executable = shutil.which(argv[0], path=env.get("PATH")) or argv[0]
        read_fd, write_fd = os.pipe()
        command = [str(self.launcher), str(write_fd), str(sample_cg / "cgroup.procs") if sample_cg else "-",
                   str(stdout_path or os.devnull), str(stderr_path or os.devnull), cwd or "-",
                   str(int(timeout * 1000)), "--", executable, *argv[1:]]
        try:
            process = subprocess.Popen(command, env=env, pass_fds=(write_fd,), stdin=subprocess.DEVNULL)
        finally:
            os.close(write_fd)
        with os.fdopen(read_fd, "rb") as pipe:
            raw = pipe.read()
        if process.wait() != 0 or not raw:
            if sample_cg:
                CgroupBackend.remove(sample_cg)
            raise MeterError(f"launcher failed (status {process.returncode}) for {Path(argv[0]).name}")
        launch = json.loads(raw)
        if not launch["complete"] or launch["wallNs"] < 0:
            raise MeterError("descendants survived SIGKILL; refusing to continue")
        result = {
            "exitCode": launch["exitCode"],
            "timedOut": launch["timedOut"],
            "wallMs": round(launch["wallNs"] / 1e6, 3),
            "rusageCpuUserMs": round(launch["cpuUserUs"] / 1000, 3),
            "rusageCpuSystemMs": round(launch["cpuSystemUs"] / 1000, 3),
            "rusageCpuMs": round((launch["cpuUserUs"] + launch["cpuSystemUs"]) / 1000, 3),
            "maxRssKiB": launch["maxRssKiB"],
            "processesReaped": launch["processesReaped"],
            "leftoversKilled": launch["leftoversKilled"],
        }
        if sample_cg:
            deadline = time.monotonic() + 2.0
            while CgroupBackend.populated(sample_cg) and time.monotonic() < deadline:
                time.sleep(0.005)
            if CgroupBackend.populated(sample_cg):
                CgroupBackend.kill(sample_cg)
                result["leftoversKilled"] += 1
            usage = CgroupBackend.read(sample_cg)
            CgroupBackend.remove(sample_cg)
            result.update(cpuUserMs=round(usage["userUs"] / 1000, 3),
                          cpuSystemMs=round(usage["systemUs"] / 1000, 3),
                          peakMemKiB=usage["peakBytes"] // 1024)
        else:
            result.update(cpuUserMs=result["rusageCpuUserMs"], cpuSystemMs=result["rusageCpuSystemMs"],
                          peakMemKiB=result["maxRssKiB"])
        result["cpuMs"] = round(result["cpuUserMs"] + result["cpuSystemMs"], 3)
        return result


def systemd_scope_prefix() -> tuple[list[str] | None, str]:
    """Command prefix that re-runs the harness inside a delegated transient scope."""
    if shutil.which("systemd-run") is None:
        return None, "systemd-run not installed"
    user = ["systemd-run", "--user", "--scope", "--quiet", "--collect", "-p", "Delegate=yes", "--"]
    if subprocess.run([*user, "true"], capture_output=True, timeout=30).returncode == 0:
        return user, "systemd-run --user scope"
    if shutil.which("sudo") and subprocess.run(["sudo", "-n", "true"], capture_output=True, timeout=30).returncode == 0:
        system = ["sudo", "-n", "-E", "systemd-run", "--scope", "--quiet", "--collect", "-p", "Delegate=yes",
                  f"--uid={os.getuid()}", f"--gid={os.getgid()}", "--"]
        if subprocess.run([*system, "true"], capture_output=True, timeout=30).returncode == 0:
            return system, "sudo systemd-run system scope (delegated to this uid)"
    return None, "no systemd user bus and no passwordless sudo"


def _own_cgroup_writable() -> bool:
    base = own_cgroup()
    return bool(base and os.access(base, os.W_OK) and os.access(base / "cgroup.procs", os.W_OK))


def maybe_reexec_in_scope(mode: str, argv: list[str]) -> None:
    """For auto/cgroup modes, re-exec this harness once inside a delegated scope."""
    if mode == "rusage" or os.environ.get(SCOPE_MARKER) or os.environ.get(SCOPE_FAILURE):
        return
    if _own_cgroup_writable():
        return
    prefix, reason = systemd_scope_prefix()
    if prefix is None:
        os.environ[SCOPE_FAILURE] = reason
        return
    os.environ[SCOPE_MARKER] = reason
    os.execvp(prefix[0], [*prefix, sys.executable, *argv])


def build_meter(mode: str) -> Meter:
    """mode: auto | cgroup | rusage (auto = cgroup when available, else rusage)."""
    if mode == "rusage":
        return Meter(None, "rusage requested")
    backend, reason = CgroupBackend.try_create()
    if backend is None and mode == "cgroup":
        raise MeterError(f"cgroup meter required but unavailable: {reason}")
    if backend is None:
        hint = os.environ.get(SCOPE_FAILURE, "")
        return Meter(None, f"cgroup unavailable ({reason}{'; ' + hint if hint else ''}); rusage fallback")
    via = os.environ.get(SCOPE_MARKER)
    return Meter(backend, reason + (f" via {via}" if via else ""))
