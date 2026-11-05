#!/usr/bin/env python3
"""Host load gate for the shared OpenMates dev server.

Reads /proc/loadavg, /proc/meminfo (MemAvailable) and PSI (/proc/pressure/*)
and decides whether the host is overloaded, with hysteresis: once overloaded,
work stays blocked until every resume threshold is met. Used by Claude hooks
(new sub-agents, new prompts), `sessions.py start` and the heavy-command guard,
plus a systemd user timer (`monitor`) that only logs; nothing is ever killed.

Commands:
  status [--json]          print the current sample and decision
  check                    exit 0 when OK, 3 when overloaded (message on stderr)
  wait [--timeout S]       block in one process until the host recovers
  hook --event <name>      Claude hook adapter (pre-agent|prompt|session-start)
  monitor                  sample once and log transitions/overload to logs/

Override (logged): OPENMATES_IGNORE_HOST_LOAD=1.
Stdlib only and no subprocesses so hook calls stay well under 50 ms.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

GIB = 1024**3

# ---------------------------------------------------------------------------
# Thresholds: the single place to tune the gate.
# ---------------------------------------------------------------------------


class Thresholds:
    """Block when ANY block_* trips; resume only when ALL resume_* hold."""

    def __init__(
        self,
        block_mem_available_bytes: int = 3 * GIB,
        block_load1_per_cpu: float = 3.0,
        block_mem_psi_some_avg10: float = 20.0,
        resume_mem_available_bytes: int = 5 * GIB,
        resume_load1_per_cpu: float = 1.5,
        resume_mem_psi_some_avg10: float = 10.0,
    ) -> None:
        self.block_mem_available_bytes = block_mem_available_bytes
        self.block_load1_per_cpu = block_load1_per_cpu
        self.block_mem_psi_some_avg10 = block_mem_psi_some_avg10
        self.resume_mem_available_bytes = resume_mem_available_bytes
        self.resume_load1_per_cpu = resume_load1_per_cpu
        self.resume_mem_psi_some_avg10 = resume_mem_psi_some_avg10


THRESHOLDS = Thresholds()
EXIT_OVERLOADED = 3
IGNORE_ENV = "OPENMATES_IGNORE_HOST_LOAD"
PROMPT_OVERRIDE_MARKER = "[host-load-override]"
WAIT_HINT = (
    "python3 scripts/host_load_guard.py wait --timeout 540 "
    "(one blocking call, or run_in_background; never a sleep/poll loop of turns)"
)


# Plain classes instead of dataclasses: importing dataclasses/inspect costs
# more than the whole hook budget on a loaded host.
class Sample:
    def __init__(
        self,
        load1: float,
        load5: float,
        cpus: int,
        mem_available_bytes: int,
        mem_psi_some_avg10: float | None = None,
        cpu_psi_some_avg10: float | None = None,
        timestamp: float | None = None,
    ) -> None:
        self.load1 = load1
        self.load5 = load5
        self.cpus = cpus
        self.mem_available_bytes = mem_available_bytes
        self.mem_psi_some_avg10 = mem_psi_some_avg10
        self.cpu_psi_some_avg10 = cpu_psi_some_avg10
        self.timestamp = time.time() if timestamp is None else timestamp


class Decision:
    def __init__(self, overloaded: bool, reasons: list[str], was_overloaded: bool) -> None:
        self.overloaded = overloaded
        self.reasons = reasons
        self.was_overloaded = was_overloaded


def asdict(obj: object) -> dict:
    return dict(vars(obj))


# ---------------------------------------------------------------------------
# Paths (canonical checkout, resolved without spawning git).
# ---------------------------------------------------------------------------

SCRIPT_ROOT = Path(__file__).resolve().parents[1]


def canonical_root(repo_root: Path = SCRIPT_ROOT) -> Path:
    """Return the main checkout for a linked worktree, else repo_root."""
    dot_git = repo_root / ".git"
    if dot_git.is_file():
        text = dot_git.read_text(encoding="utf-8").strip()
        if text.startswith("gitdir:"):
            gitdir = Path(text.split(":", 1)[1].strip())
            # <common>/.git/worktrees/<name> -> <common>
            if gitdir.parent.name == "worktrees":
                return gitdir.parent.parent.parent
    return repo_root


def state_dir() -> Path:
    override = os.environ.get("OPENMATES_HOST_LOAD_STATE_DIR")
    return Path(override) if override else canonical_root() / "logs" / "host-load-guard"


# ---------------------------------------------------------------------------
# Sampling.
# ---------------------------------------------------------------------------


def parse_loadavg(text: str) -> tuple[float, float]:
    parts = text.split()
    return float(parts[0]), float(parts[1])


def parse_mem_available(text: str) -> int:
    for line in text.splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) * 1024
    raise ValueError("MemAvailable missing from /proc/meminfo")


def parse_psi_some_avg10(text: str) -> float | None:
    for line in text.splitlines():
        if line.startswith("some "):
            for item in line.split()[1:]:
                key, _, value = item.partition("=")
                if key == "avg10":
                    return float(value)
    return None


def _read_psi(path: str) -> float | None:
    try:
        return parse_psi_some_avg10(Path(path).read_text(encoding="utf-8"))
    except OSError:
        return None  # PSI not enabled on this kernel; the other signals still apply.


def take_sample(proc: Path | None = None) -> Sample:
    # OPENMATES_HOST_LOAD_PROC points tests at a fake /proc tree.
    proc = proc or Path(os.environ.get("OPENMATES_HOST_LOAD_PROC", "/proc"))
    load1, load5 = parse_loadavg((proc / "loadavg").read_text(encoding="utf-8"))
    return Sample(
        load1=load1,
        load5=load5,
        cpus=os.cpu_count() or 1,
        mem_available_bytes=parse_mem_available((proc / "meminfo").read_text(encoding="utf-8")),
        mem_psi_some_avg10=_read_psi(str(proc / "pressure" / "memory")),
        cpu_psi_some_avg10=_read_psi(str(proc / "pressure" / "cpu")),
    )


# ---------------------------------------------------------------------------
# Decision with hysteresis (pure; unit tested).
# ---------------------------------------------------------------------------


def evaluate(sample: Sample, was_overloaded: bool, t: Thresholds = THRESHOLDS) -> Decision:
    gib = sample.mem_available_bytes / GIB
    psi = sample.mem_psi_some_avg10
    block_reasons: list[str] = []
    if sample.mem_available_bytes < t.block_mem_available_bytes:
        block_reasons.append(f"MemAvailable {gib:.1f} GiB < {t.block_mem_available_bytes / GIB:.0f} GiB")
    if sample.load1 > t.block_load1_per_cpu * sample.cpus:
        block_reasons.append(f"load1 {sample.load1:.0f} > {t.block_load1_per_cpu:g}x{sample.cpus} cpus")
    if psi is not None and psi > t.block_mem_psi_some_avg10:
        block_reasons.append(f"memory PSI some avg10 {psi:.0f} > {t.block_mem_psi_some_avg10:g}")
    if block_reasons:
        return Decision(True, block_reasons, was_overloaded)
    if not was_overloaded:
        return Decision(False, [], was_overloaded)

    pending: list[str] = []
    if sample.mem_available_bytes <= t.resume_mem_available_bytes:
        pending.append(f"MemAvailable {gib:.1f} GiB not yet > {t.resume_mem_available_bytes / GIB:.0f} GiB")
    if sample.load1 >= t.resume_load1_per_cpu * sample.cpus:
        pending.append(f"load1 {sample.load1:.0f} not yet < {t.resume_load1_per_cpu:g}x{sample.cpus} cpus")
    if psi is not None and psi >= t.resume_mem_psi_some_avg10:
        pending.append(f"memory PSI some avg10 {psi:.0f} not yet < {t.resume_mem_psi_some_avg10:g}")
    if pending:
        return Decision(True, ["recovering (hysteresis)", *pending], was_overloaded)
    return Decision(False, [], was_overloaded)


# ---------------------------------------------------------------------------
# Hysteresis state + event log.
# ---------------------------------------------------------------------------


def load_state(directory: Path) -> bool:
    try:
        return bool(json.loads((directory / "state.json").read_text(encoding="utf-8")).get("overloaded"))
    except FileNotFoundError:
        return False
    except (OSError, ValueError):
        return False  # Corrupt state: fall back to the strict block thresholds only.


def append_event(directory: Path, name: str, payload: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "event": name, **payload}
    with (directory / "events.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def save_state(directory: Path, sample: Sample, decision: Decision) -> None:
    """Persist only transitions so the hot hook path rarely writes."""
    if decision.overloaded == decision.was_overloaded:
        return
    directory.mkdir(parents=True, exist_ok=True)
    tmp = directory / f".state.{os.getpid()}.tmp"
    tmp.write_text(json.dumps({"overloaded": decision.overloaded, "since": sample.timestamp}), encoding="utf-8")
    os.replace(tmp, directory / "state.json")
    append_event(
        directory,
        "overload_start" if decision.overloaded else "overload_end",
        {"sample": asdict(sample), "reasons": decision.reasons},
    )


def current_decision(directory: Path | None = None) -> tuple[Sample, Decision]:
    directory = directory or state_dir()
    sample = take_sample()
    decision = evaluate(sample, load_state(directory))
    try:
        save_state(directory, sample, decision)
    except OSError as error:
        print(f"host_load_guard: could not persist state: {error}", file=sys.stderr)
    return sample, decision


def describe(sample: Sample, decision: Decision) -> str:
    psi = "n/a" if sample.mem_psi_some_avg10 is None else f"{sample.mem_psi_some_avg10:.0f}"
    head = (
        f"load1={sample.load1:.0f} (cpus={sample.cpus}) "
        f"MemAvailable={sample.mem_available_bytes / GIB:.1f}GiB memPSI10={psi}"
    )
    if not decision.overloaded:
        return f"host OK: {head}"
    return f"HOST OVERLOADED: {head}; " + "; ".join(decision.reasons)


def blocked_message(sample: Sample, decision: Decision, what: str) -> str:
    return (
        f"BLOCKED: {what} while the dev server is overloaded ({describe(sample, decision)}). "
        f"Do not start new agentic work or heavy commands now. Wait for recovery with: {WAIT_HINT}. "
        "Builds/tests belong in isolated CI (sessions.py ci-source -> ci_coordinator.py submit -> wait)."
    )


def ignore_requested(what: str) -> bool:
    if os.environ.get(IGNORE_ENV) != "1":
        return False
    try:
        append_event(state_dir(), "override", {"what": what, "pid": os.getpid(),
                                               "session": os.environ.get("CLAUDE_CODE_SESSION_ID", "")})
    except OSError as error:
        print(f"host_load_guard: could not log override: {error}", file=sys.stderr)
    return True


def gate(what: str) -> str | None:
    """Return a block message when `what` must not start now, else None."""
    sample, decision = current_decision()
    if decision.overloaded and not ignore_requested(what):
        return blocked_message(sample, decision, what)
    return None


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------


def cmd_hook(event: str) -> int:
    raw = sys.stdin.read()
    payload = json.loads(raw) if raw.strip() else {}
    if event == "prompt" and PROMPT_OVERRIDE_MARKER in str(payload.get("prompt", "")):
        os.environ[IGNORE_ENV] = "1"
    what = {
        "pre-agent": "spawning a new sub-agent",
        "prompt": "starting new work from a prompt",
        "session-start": "starting a new Claude session",
    }.get(event)
    if what is None:
        print(f"unknown hook event {event!r}", file=sys.stderr)
        return 1
    message = gate(what)
    if message is None:
        return 0
    if event == "pre-agent":
        out = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                      "permissionDecisionReason": message}}
    elif event == "prompt":
        out = {"decision": "block", "reason": message + f" To proceed anyway (logged), resend the prompt "
               f"containing {PROMPT_OVERRIDE_MARKER}."}
    else:  # SessionStart cannot block; inject a hard instruction instead.
        out = {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": message}}
    print(json.dumps(out))
    return 0


def cmd_wait(timeout: float, interval: float) -> int:
    deadline = time.monotonic() + timeout
    while True:
        sample, decision = current_decision()
        if not decision.overloaded:
            print(describe(sample, decision))
            return 0
        if time.monotonic() >= deadline:
            print(f"timeout: {describe(sample, decision)}", file=sys.stderr)
            return EXIT_OVERLOADED
        time.sleep(min(interval, max(0.0, deadline - time.monotonic())))


def cmd_monitor() -> int:
    directory = state_dir()
    sample, decision = current_decision(directory)
    if decision.overloaded:
        append_event(directory, "overload_sample", {"sample": asdict(sample), "reasons": decision.reasons,
                                                     "top": top_process_groups()})
    return 0


def top_process_groups(proc: Path = Path("/proc"), limit: int = 8) -> list[dict]:
    """Aggregate RSS by command name so overload logs show who is responsible."""
    totals: dict[str, list[int]] = {}
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            comm = (entry / "comm").read_text(encoding="utf-8").strip()
            rss_kb = 0
            for line in (entry / "status").read_text(encoding="utf-8").splitlines():
                if line.startswith("VmRSS:"):
                    rss_kb = int(line.split()[1])
                    break
        except (OSError, ValueError):
            continue  # Process exited while scanning.
        bucket = totals.setdefault(comm, [0, 0])
        bucket[0] += 1
        bucket[1] += rss_kb
    ranked = sorted(totals.items(), key=lambda item: item[1][1], reverse=True)[:limit]
    return [{"comm": name, "count": count, "rss_mib": rss // 1024} for name, (count, rss) in ranked]


def main(argv: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    status = sub.add_parser("status")
    status.add_argument("--json", action="store_true")
    sub.add_parser("check")
    wait = sub.add_parser("wait")
    wait.add_argument("--timeout", type=float, default=540.0, help="seconds (default 540)")
    wait.add_argument("--interval", type=float, default=15.0)
    hook = sub.add_parser("hook")
    hook.add_argument("--event", required=True, choices=["pre-agent", "prompt", "session-start"])
    sub.add_parser("monitor")
    args = parser.parse_args(argv)

    if args.command == "status":
        sample, decision = current_decision()
        if args.json:
            print(json.dumps({"sample": asdict(sample), "decision": asdict(decision),
                              "thresholds": asdict(THRESHOLDS)}, indent=2))
        else:
            print(describe(sample, decision))
        return 0
    if args.command == "check":
        sample, decision = current_decision()
        if decision.overloaded:
            print(describe(sample, decision), file=sys.stderr)
            return EXIT_OVERLOADED
        print(describe(sample, decision))
        return 0
    if args.command == "wait":
        return cmd_wait(args.timeout, args.interval)
    if args.command == "hook":
        return cmd_hook(args.event)
    return cmd_monitor()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
