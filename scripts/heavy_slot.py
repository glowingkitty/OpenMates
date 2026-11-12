#!/usr/bin/env python3
"""Run a build/test/benchmark command on the shared dev server within resource limits.

The dev server (16 cores, 31 GB, no swap) was once driven to load 140-363 by
parallel agents compiling Rust and running browsers at the same time. Heavy
commands are therefore allowed only through this wrapper, which:

- waits until `host_load_guard` reports the host healthy,
- holds one of MAX_SLOTS host-wide slots (flock) for the whole run, so at most
  MAX_SLOTS heavy commands run at once (others wait in line),
- admits a run only when the host has room for its whole memory cap on top of
  the overload threshold, counting the cap of a run in another slot that
  started less than SETTLE_SECONDS ago (its memory is not in use yet). On
  2026-11-11 two runs admitted in the same second grew to ~9 GB together with
  8 GB available and froze the host,
- runs the command in a systemd user scope capped at CPU_QUOTA and MEMORY_MAX,
  at low CPU/IO priority, with CARGO_BUILD_JOBS limited.

Remote runs: `cargo test|check|clippy` and `vitest` (see heavy_remote_plan.py)
run in an E2B sandbox (8 CPUs, 8 GB) instead, without a local slot, through
heavy_remote.py; at most REMOTE_SLOTS at once. On 2026-11-12, 44 of 376 local
runs in 24 hours were OOM-killed by the 6 GB cap; the same `cargo test -p
openmates-sdk` finished in E2B in about 5 minutes. When the remote run is
unavailable (no SDK venv, no key, no sandbox, lost connection) heavy_slot says
so and runs the command locally. `--local`, OPENMATES_HEAVY_REMOTE=0 or the
file REMOTE_DISABLED_FILE force local runs.

Usage:
  python3 scripts/heavy_slot.py run [--timeout S] [--local] -- cargo build --release
  python3 scripts/heavy_slot.py status
  python3 scripts/heavy_slot.py remote-setup      # one-time: E2B SDK venv
  python3 scripts/heavy_slot.py remote-template   # build/refresh the sandbox template

Exit code is the wrapped command's exit code; 3 when the host stayed
overloaded or no slot became free before --timeout.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import host_load_guard  # noqa: E402 - sibling module; path set up above for direct-file loading
import heavy_remote_plan  # noqa: E402 - sibling module, standard library only

MAX_SLOTS = 2
CPU_QUOTA = "400%"
MEMORY_MAX = "6G"
MEMORY_MAX_BYTES = 6 * host_load_guard.GIB
SETTLE_SECONDS = 180
CARGO_JOBS = "4"
DEFAULT_TIMEOUT_SECONDS = 3600
POLL_SECONDS = 5
EXIT_UNAVAILABLE = 3
REMOTE_SLOTS = 6
SCRIPTS_DIR = Path(__file__).resolve().parent


def slot_dir() -> Path:
    path = host_load_guard.state_dir() / "heavy-slots"
    path.mkdir(parents=True, exist_ok=True)
    return path


def try_acquire(directory: Path, count: int = MAX_SLOTS) -> tuple[int, int] | None:
    """Return (fd, slot) for a free slot, or None when all slots are held."""
    directory.mkdir(parents=True, exist_ok=True)
    for slot in range(count):
        fd = os.open(directory / f"slot-{slot}.lock", os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            continue
        return fd, slot
    return None


def holders(directory: Path) -> list[dict]:
    result = []
    for slot in range(MAX_SLOTS):
        path = directory / f"slot-{slot}.lock"
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            result.append({"slot": slot, "busy": True, "command": path.read_text(errors="replace")[:300]})
        else:
            fcntl.flock(fd, fcntl.LOCK_UN)
            result.append({"slot": slot, "busy": False})
        finally:
            os.close(fd)
    return result


def recent_starts(directory: Path, now: float) -> int:
    """Count busy slots whose run started less than SETTLE_SECONDS ago."""
    count = 0
    for slot in holders(directory):
        if slot["busy"]:
            started = (directory / f"slot-{slot['slot']}.lock").stat().st_mtime
            count += now - started < SETTLE_SECONDS
    return count


def memory_shortfall(mem_available_bytes: int, recent: int) -> str | None:
    """Return why a new run does not fit in memory, or None when it does."""
    needed = (host_load_guard.THRESHOLDS.block_mem_available_bytes
              + MEMORY_MAX_BYTES * (1 + recent))
    if mem_available_bytes >= needed:
        return None
    gib = host_load_guard.GIB
    return (f"MemAvailable {mem_available_bytes / gib:.1f} GiB < {needed / gib:.0f} GiB needed "
            f"(run cap {MEMORY_MAX_BYTES // gib} GiB x {1 + recent} + overload threshold)")


def admit(directory: Path) -> tuple[tuple[int, int] | None, str]:
    """Take a slot when the host is healthy and has memory for the run.

    Admission is serialized by a gate lock, and the slot file is stamped before
    the gate is released, so two waiting runs cannot both count the same free memory.
    """
    gate = os.open(directory / "admission.lock", os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(gate, fcntl.LOCK_EX)
        sample, decision = host_load_guard.current_decision()
        if decision.overloaded:
            return None, "host overloaded: " + "; ".join(decision.reasons)
        shortfall = memory_shortfall(sample.mem_available_bytes, recent_starts(directory, time.time()))
        if shortfall:
            return None, shortfall
        acquired = try_acquire(directory)
        if acquired is None:
            return None, "all heavy slots busy"
        os.ftruncate(acquired[0], 0)  # also sets mtime = start time for recent_starts()
        os.utime(acquired[0])
        return acquired, ""
    finally:
        fcntl.flock(gate, fcntl.LOCK_UN)
        os.close(gate)


def wrapped_command(command: list[str]) -> list[str]:
    limited = ["nice", "-n", "10"]
    if shutil.which("ionice"):
        limited = ["ionice", "-c", "3", *limited]
    if shutil.which("systemd-run") is None:
        raise SystemExit("heavy_slot: systemd-run is required to apply CPU and memory limits")
    return [
        "systemd-run", "--user", "--scope", "--quiet", "--collect",
        "-p", f"CPUQuota={CPU_QUOTA}", "-p", f"MemoryMax={MEMORY_MAX}", "-p", "MemorySwapMax=0",
        "--", *limited, *command,
    ]


REMOTE_EXIT_UNAVAILABLE = 75  # heavy_remote.EXIT_REMOTE_UNAVAILABLE (that module needs the E2B SDK)


def remote_venv_python() -> Path:
    return Path.home() / ".cache" / "openmates" / "heavy-remote" / "venv" / "bin" / "python"


def remote_disabled_file() -> Path:
    return host_load_guard.state_dir() / "heavy-remote.disabled"


def remote_disabled_reason(local: bool) -> str | None:
    if local:
        return "--local"
    if os.environ.get("OPENMATES_HEAVY_REMOTE") == "0":
        return "OPENMATES_HEAVY_REMOTE=0"
    if remote_disabled_file().exists():
        return f"{remote_disabled_file()} exists"
    if not remote_venv_python().exists():
        return "E2B SDK venv missing (python3 scripts/heavy_slot.py remote-setup)"
    return None


def worktree_root(cwd: Path) -> Path | None:
    result = subprocess.run(["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
                            capture_output=True, text=True)
    if result.returncode != 0:
        return None
    root = Path(result.stdout.strip())
    return root if (root / "scripts" / "heavy_remote.py").exists() else None


def try_remote(command: list[str], timeout: float, local: bool) -> int | None:
    """Run the command in E2B when eligible; None means run it locally."""
    cwd = Path.cwd()
    root = worktree_root(cwd)
    planned = heavy_remote_plan.plan_command(command, cwd, root) if root else None
    if planned is None:
        return None
    disabled = remote_disabled_reason(local)
    if disabled:
        if not local:
            print(f"heavy_slot: running locally, remote run disabled ({disabled})", file=sys.stderr)
        return None
    acquired = try_acquire(slot_dir() / "remote", REMOTE_SLOTS)
    if acquired is None:
        print(f"heavy_slot: all {REMOTE_SLOTS} remote slots busy; queueing for a local slot", file=sys.stderr)
        return None
    fd, slot = acquired
    os.ftruncate(fd, 0)
    os.write(fd, " ".join(command).encode()[:300])
    started = time.monotonic()
    try:
        code = subprocess.call([
            str(remote_venv_python()), str(SCRIPTS_DIR / "heavy_remote.py"), "--root", str(root),
            "--kind", planned.kind, "--cwd", planned.cwd, "--timeout", str(int(timeout)),
            "--shell", planned.shell,
        ])
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    host_load_guard.append_event(
        host_load_guard.state_dir(), "heavy_remote_run",
        {"slot": slot, "command": " ".join(command)[:500], "cwd": str(cwd), "exit": code,
         "seconds": round(time.monotonic() - started, 1),
         "session": os.environ.get("CLAUDE_CODE_SESSION_ID", "")},
    )
    if code == REMOTE_EXIT_UNAVAILABLE:
        print("heavy_slot: remote run unavailable (reason above); running locally instead", file=sys.stderr)
        return None
    return code


def run(command: list[str], timeout: float, local: bool = False) -> int:
    if not command:
        print("heavy_slot: missing command after --", file=sys.stderr)
        return 2
    remote_code = try_remote(command, timeout, local)
    if remote_code is not None:
        return remote_code
    if shutil.which(command[0]) is None:
        print(f"heavy_slot: command not found on PATH: {command[0]}", file=sys.stderr)
        return 127
    deadline = time.monotonic() + timeout
    directory = slot_dir()
    announced = False
    while True:
        acquired, why = admit(directory)
        if acquired is not None:
            break
        if time.monotonic() >= deadline:
            print(f"heavy_slot: gave up after timeout ({why})", file=sys.stderr)
            return EXIT_UNAVAILABLE
        if not announced:
            print(f"heavy_slot: waiting ({why})", file=sys.stderr)
            announced = True
        time.sleep(POLL_SECONDS)
    fd, slot = acquired
    os.write(fd, " ".join(command).encode()[:300])
    env = dict(os.environ, CARGO_BUILD_JOBS=os.environ.get("CARGO_BUILD_JOBS", CARGO_JOBS))
    host_load_guard.append_event(
        host_load_guard.state_dir(), "heavy_slot_run",
        {"slot": slot, "command": " ".join(command)[:500], "cwd": os.getcwd(),
         "session": os.environ.get("CLAUDE_CODE_SESSION_ID", "")},
    )
    try:
        return subprocess.call(wrapped_command(command), env=env)
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="action", required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    run_parser.add_argument("--local", action="store_true", help="never run in E2B")
    run_parser.add_argument("command", nargs=argparse.REMAINDER)
    sub.add_parser("status")
    sub.add_parser("remote-setup")
    sub.add_parser("remote-template")
    args = parser.parse_args(argv)
    if args.action == "status":
        print(json.dumps({"max_slots": MAX_SLOTS, "cpu_quota": CPU_QUOTA, "memory_max": MEMORY_MAX,
                          "slots": holders(slot_dir()),
                          "remote": {"slots": REMOTE_SLOTS, "disabled": remote_disabled_reason(False)}},
                         indent=2))
        return 0
    if args.action == "remote-setup":
        return remote_setup()
    if args.action == "remote-template":
        if not remote_venv_python().exists():
            print("heavy_slot: run remote-setup first", file=sys.stderr)
            return 2
        return subprocess.call([str(remote_venv_python()), str(SCRIPTS_DIR / "heavy_remote_template.py")])
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    return run(command, args.timeout, args.local)


def remote_setup() -> int:
    """Create the E2B SDK venv used for remote runs (pinned SDK version)."""
    venv = remote_venv_python().parent.parent
    sdk = re.search(r'^E2B_SDK_VERSION = "([^"]+)"', (SCRIPTS_DIR / "heavy_remote.py").read_text(), re.M)
    if sdk is None:
        print("heavy_slot: E2B_SDK_VERSION missing in heavy_remote.py", file=sys.stderr)
        return 2
    if not remote_venv_python().exists():
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    return subprocess.call([str(remote_venv_python()), "-m", "pip", "install", "-q", f"e2b=={sdk.group(1)}"])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
