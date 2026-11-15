"""Host-resources guard for the dev server: RAM and disk together, self-healing first.

`host_load_guard.py monitor` (systemd user timer, every minute) samples memory and
calls `tick()`. Each tick:

1. Memory overloaded (host_load_guard: memory pressure, the OOM floor, load):
   stop idle chats now with the shorter pressure limit
   (`claude_idle_chats.py reap --pressure`), at most every REAP_INTERVAL seconds.
2. Host healthy with memory headroom: release up to RELEASE_PER_TICK prompts that
   an older hook version refused (`claude_idle_chats.py release`), a few at a time
   so the released work does not overload the host again.
3. Disk: free space and use of the repository filesystem. Cleanup belongs to the
   disk coordinator (scripts/disk_coordinator.py); this guard checks that its
   service runs and watches whether the space comes back.
4. A problem that persists for ALERT_AFTER_SECONDS although self-healing ran sends
   one "feedback needed" Discord push per incident (scripts/agent_question.py);
   recovery is logged as `resources_recovered`. Nothing else alerts.
5. zellij: every zellij server (one per terminal session; the `claude` session holds
   all pane chats) is checked for RSS over ZELLIJ_RSS_LIMIT_BYTES and CPU over
   ZELLIJ_CPU_LIMIT_PERCENT since the previous tick. Over a limit for
   ZELLIJ_ALERT_AFTER_SECONDS sends one push (TASK-2369: the server grew to 8.5 GiB
   and was OOM-killed with every chat pane in it).

State and events: logs/host-load-guard/resources.json and events.jsonl.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import host_load_guard as guard

REAP_INTERVAL = 300.0
RELEASE_PER_TICK = 2
RELEASE_HEADROOM_BYTES = 4 * guard.GIB  # free memory needed before held prompts are released
ALERT_AFTER_SECONDS = 20 * 60
DISK_MIN_FREE_BYTES = 20 * guard.GIB
DISK_MAX_PERCENT = 92.0
DISK_SERVICE = "openmates-disk-coordinator.service"
ALERT_CHAT_ID = "host-resources-guard"
SUBPROCESS_TIMEOUT = 240
SCRIPTS = Path(__file__).resolve().parent
ZELLIJ_RSS_LIMIT_BYTES = 2 * guard.GIB
ZELLIJ_CPU_LIMIT_PERCENT = 200.0
ZELLIJ_ALERT_AFTER_SECONDS = 5 * 60
ZELLIJ_RECOMMENDATION = (
    "Archive finished chats so their tabs close (claude_idle_chats.py list), check that "
    "~/.config/zellij/config.kdl keeps scroll_buffer_size 2000, and restart the session only after "
    "every chat in it can be resumed (claude --resume) and the remote-control bridge is restarted.")
DEFAULT_RECOMMENDATION = (
    "Look at the idle-but-kept chats (claude_idle_chats.py list) and archive the "
    "finished ones, or stop the biggest process listed in logs/host-load-guard/events.jsonl.")


def disk_problem(path: Path, min_free: int = DISK_MIN_FREE_BYTES, max_percent: float = DISK_MAX_PERCENT) -> str | None:
    stat = os.statvfs(path)
    free = stat.f_bavail * stat.f_frsize
    total = stat.f_blocks * stat.f_frsize
    used_percent = 100.0 * (total - free) / total if total else 0.0
    if free < min_free or used_percent > max_percent:
        return (f"disk {used_percent:.0f}% used, {free / guard.GIB:.0f} GiB free "
                f"(limits {max_percent:g}% / {min_free / guard.GIB:.0f} GiB)")
    return None


def load(directory: Path) -> dict:
    try:
        return json.loads((directory / "resources.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def save(directory: Path, state: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    tmp = directory / f".resources.{os.getpid()}.tmp"
    tmp.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    os.replace(tmp, directory / "resources.json")


def _script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPTS / args[0]), *args[1:]], capture_output=True,
                          text=True, timeout=SUBPROCESS_TIMEOUT, check=False)


def _service_active(unit: str) -> bool:
    result = subprocess.run(["systemctl", "--user", "is-active", unit], capture_output=True, text=True,
                            timeout=20, check=False)
    return result.stdout.strip() == "active"


def zellij_servers(proc: Path = Path("/proc")) -> dict[str, dict]:
    """Running zellij servers by session name: pid, RSS bytes and CPU ticks (utime + stime)."""
    servers: dict[str, dict] = {}
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            args = (entry / "cmdline").read_bytes().split(b"\0")
            if len(args) < 3 or not args[0].endswith(b"zellij") or args[1] != b"--server":
                continue
            stat = (entry / "stat").read_text()
            status = (entry / "status").read_text()
        except OSError:  # the process exited between listing and reading
            continue
        fields = stat.rsplit(")", 1)[1].split()  # fields[0] is the state (stat field 3)
        rss_kib = next((int(line.split()[1]) for line in status.splitlines() if line.startswith("VmRSS:")), 0)
        servers[Path(args[2].decode(errors="replace")).name] = {
            "pid": int(entry.name), "rss_bytes": rss_kib * 1024, "cpu_ticks": int(fields[11]) + int(fields[12])}
    return servers


def zellij_problem(state: dict, now: float, servers: dict[str, dict],
                   clock_ticks: int = os.sysconf("SC_CLK_TCK")) -> str | None:
    """A zellij server over the RAM or CPU limit, or None; keeps this tick's sample in `state`."""
    previous = state.get("zellij_sample") or {}
    elapsed = now - float(previous.get("at", now))
    problems = []
    for name, current in sorted(servers.items()):
        over = []
        if current["rss_bytes"] > ZELLIJ_RSS_LIMIT_BYTES:
            over.append(f"{current['rss_bytes'] / guard.GIB:.1f} GiB RAM (limit {ZELLIJ_RSS_LIMIT_BYTES // guard.GIB} GiB)")
        before = (previous.get("servers") or {}).get(name)
        if before and before["pid"] == current["pid"] and elapsed > 0:
            cpu = (current["cpu_ticks"] - before["cpu_ticks"]) / clock_ticks / elapsed * 100
            if cpu > ZELLIJ_CPU_LIMIT_PERCENT:
                over.append(f"{cpu:.0f}% CPU (limit {ZELLIJ_CPU_LIMIT_PERCENT:.0f}%)")
        if over:
            problems.append(f"zellij session `{name}` (pid {current['pid']}) uses {' and '.join(over)}")
    state["zellij_sample"] = {"at": now, "servers": servers}
    return "; ".join(problems) or None


def track(state: dict, key: str, problem: str | None, now: float,
          after: float = ALERT_AFTER_SECONDS) -> tuple[str | None, bool]:
    """Record an incident; returns (problem, whether it is due for an alert now)."""
    incident = state.get(key)
    if problem is None:
        state.pop(key, None)
        return None, False
    if not incident:
        state[key] = {"since": now, "alerted": False, "problem": problem}
        return problem, False
    incident["problem"] = problem
    return problem, not incident["alerted"] and now - incident["since"] >= after


def alert(problem: str, healed: str, directory: Path, after: float = ALERT_AFTER_SECONDS,
          recommendation: str = DEFAULT_RECOMMENDATION) -> bool:
    question = (f"The dev server is short on resources and could not fix it itself for "
                f"{int(after) // 60} min: {problem}. Self-healing tried: {healed}.")
    env = dict(os.environ, CLAUDE_CODE_SESSION_ID=ALERT_CHAT_ID, CLAUDE_CHAT_TITLE="Host resources guard")
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "agent_question.py"), "ask", "--force", "--question", question,
         "--recommendation", recommendation],
        capture_output=True, text=True, timeout=60, env=env, check=False)
    guard.append_event(directory, "resources_alert", {"problem": problem, "healed": healed,
                                                      "sent": result.returncode == 0,
                                                      "error": result.stderr.strip()[-300:]})
    return result.returncode == 0


def tick(sample: guard.Sample, decision: guard.Decision, directory: Path | None = None,
         repo: Path | None = None, now: float | None = None) -> int:
    directory = directory or guard.state_dir()
    repo = repo or guard.canonical_root()
    now = time.time() if now is None else now
    state = load(directory)
    healed: list[str] = []

    memory = "; ".join(decision.reasons) if decision.overloaded else None
    if memory and now - float(state.get("last_reap", 0)) >= REAP_INTERVAL:
        result = _script("claude_idle_chats.py", "reap", "--pressure")
        state["last_reap"] = now
        stopped = [line for line in result.stdout.splitlines() if line.startswith("stopped")]
        healed.append(f"stopped {len(stopped)} idle chats")
        guard.append_event(directory, "resources_reap", {"stopped": stopped, "code": result.returncode,
                                                         "error": result.stderr.strip()[-300:]})
    elif not decision.overloaded and sample.mem_available_bytes > RELEASE_HEADROOM_BYTES:
        result = _script("claude_idle_chats.py", "release", "--limit", str(RELEASE_PER_TICK))
        released = [line for line in result.stdout.splitlines() if line.startswith("released")]
        if released or result.returncode:
            guard.append_event(directory, "prompts_released", {"released": released, "code": result.returncode,
                                                               "error": result.stderr.strip()[-300:]})

    disk = disk_problem(repo)
    if disk and not _service_active(DISK_SERVICE):
        disk += f"; {DISK_SERVICE} is not running"
    if disk:
        healed.append("disk cleanup is left to the disk coordinator")

    zellij = zellij_problem(state, now, zellij_servers())
    if zellij:
        guard.append_event(directory, "zellij_over_limit", {"problem": zellij})

    if healed:
        state["healed"] = healed
    checks = (("memory", memory, ALERT_AFTER_SECONDS, DEFAULT_RECOMMENDATION),
              ("disk", disk, ALERT_AFTER_SECONDS, DEFAULT_RECOMMENDATION),
              ("zellij", zellij, ZELLIJ_ALERT_AFTER_SECONDS, ZELLIJ_RECOMMENDATION))
    for key, problem, after, recommendation in checks:
        was = state.get(key)
        problem, due = track(state, key, problem, now, after)
        if was and problem is None:
            guard.append_event(directory, "resources_recovered", {"kind": key, "since": was["since"]})
        if due:
            healed_text = "nothing (zellij is only watched)" if key == "zellij" else ", ".join(state.get("healed") or ["nothing"])
            state[key]["alerted"] = alert(problem, healed_text, directory, after, recommendation)
    save(directory, state)
    return 0
