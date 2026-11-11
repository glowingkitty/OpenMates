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

Usage:
  python3 scripts/heavy_slot.py run [--timeout S] -- cargo build --release
  python3 scripts/heavy_slot.py status

Exit code is the wrapped command's exit code; 3 when the host stayed
overloaded or no slot became free before --timeout.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import host_load_guard  # noqa: E402 - sibling module; path set up above for direct-file loading

MAX_SLOTS = 2
CPU_QUOTA = "400%"
MEMORY_MAX = "6G"
MEMORY_MAX_BYTES = 6 * host_load_guard.GIB
SETTLE_SECONDS = 180
CARGO_JOBS = "4"
DEFAULT_TIMEOUT_SECONDS = 3600
POLL_SECONDS = 5
EXIT_UNAVAILABLE = 3


def slot_dir() -> Path:
    path = host_load_guard.state_dir() / "heavy-slots"
    path.mkdir(parents=True, exist_ok=True)
    return path


def try_acquire(directory: Path) -> tuple[int, int] | None:
    """Return (fd, slot) for a free slot, or None when all slots are held."""
    for slot in range(MAX_SLOTS):
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


def run(command: list[str], timeout: float) -> int:
    if not command:
        print("heavy_slot: missing command after --", file=sys.stderr)
        return 2
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
    run_parser.add_argument("command", nargs=argparse.REMAINDER)
    sub.add_parser("status")
    args = parser.parse_args(argv)
    if args.action == "status":
        print(json.dumps({"max_slots": MAX_SLOTS, "cpu_quota": CPU_QUOTA, "memory_max": MEMORY_MAX,
                          "slots": holders(slot_dir())}, indent=2))
        return 0
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    return run(command, args.timeout)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
