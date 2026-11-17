"""Host-resources guard for the dev server: RAM and disk together, self-healing first.

`host_load_guard.py monitor` (systemd user timer, every minute) samples memory and
calls `tick()`. Each tick:

1. Memory overloaded (host_load_guard: memory pressure, the OOM floor, load):
   stop idle chats now with the shorter pressure limit
   (`claude_idle_chats.py reap --pressure`), at most every REAP_INTERVAL seconds.
2. Host healthy with memory headroom: release up to RELEASE_PER_TICK prompts that
   an older hook version refused (`claude_idle_chats.py release`), a few at a time
   so the released work does not overload the host again.
3. Disk: use of the repository filesystem against two alert levels, DISK_WARN_PERCENT
   (75%) and DISK_HIGH_PERCENT (85%) or less than DISK_FLOOR_BYTES (10 GiB, the
   coordinator's hard floor) available. Each level is its own incident and re-arms
   only DISK_REARM_POINTS below it. Alerts name the largest growers of the last
   24 h from the hourly size log (scripts/host_disk_usage.py). Cleanup belongs to
   the disk coordinator (scripts/disk_coordinator.py); this guard checks that its
   service runs and watches whether the space comes back (TASK-7646).
4. A problem that persists for ALERT_AFTER_SECONDS although self-healing ran sends
   one "feedback needed" Discord push per incident (scripts/agent_question.py);
   recovery is logged as `resources_recovered`. Nothing else alerts.
5. zellij: every zellij server (one per terminal session; the `claude` session holds
   all pane chats) is checked for RSS over ZELLIJ_RSS_LIMIT_BYTES and CPU over
   ZELLIJ_CPU_LIMIT_PERCENT since the previous tick. Over a limit for
   ZELLIJ_ALERT_AFTER_SECONDS sends one push (TASK-2369: the server grew to 8.5 GiB
   and was OOM-killed with every chat pane in it). Self-healing first: an over-limit
   session's bar plugin panes (compact-bar, tab-bar, status-bar) are closed. Their
   event backlog drove the server to 1,400% CPU and 10 GiB (TASK-6763); closing them
   brought it to 4% within a minute. Terminal panes, and so chats, are never touched.

State and events: logs/host-load-guard/resources.json and events.jsonl.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import host_disk_usage
import host_load_guard as guard

REAP_INTERVAL = 300.0
RELEASE_PER_TICK = 2
RELEASE_HEADROOM_BYTES = 4 * guard.GIB  # free memory needed before held prompts are released
ALERT_AFTER_SECONDS = 20 * 60
DISK_FLOOR_BYTES = 10 * guard.GIB
DISK_WARN_PERCENT = 75.0
DISK_HIGH_PERCENT = 85.0
DISK_REARM_POINTS = 2.0
DISK_SERVICE = "openmates-disk-coordinator.service"
ALERT_CHAT_ID = "host-resources-guard"
SUBPROCESS_TIMEOUT = 240
SCRIPTS = Path(__file__).resolve().parent
ZELLIJ_RSS_LIMIT_BYTES = 2 * guard.GIB
ZELLIJ_CPU_LIMIT_PERCENT = 200.0
ZELLIJ_ALERT_AFTER_SECONDS = 5 * 60
ZELLIJ_BIN = os.getenv("ZELLIJ_BIN") or shutil.which("zellij") or "/usr/local/bin/zellij"
# Plugins that only draw bars for an attached client. Headless chat sessions need none;
# scripts/zellij/chat-session.kdl starts new servers without them.
ZELLIJ_BAR_PLUGINS = frozenset({"compact-bar", "tab-bar", "status-bar",
                                "zellij:compact-bar", "zellij:tab-bar", "zellij:status-bar"})
ZELLIJ_RECOMMENDATION = (
    "Find the plugin or pane that still loads the server (zellij -s <session> action list-panes -a; "
    "per-thread CPU in /proc/<pid>/task/*/stat), archive finished chats so their tabs close "
    "(claude_idle_chats.py list), and restart the session only after every chat in it can be resumed "
    "(claude --resume) and the remote-control bridge is restarted.")
DISK_RECOMMENDATION = (
    "Cleanup runs automatically from 75% (disk coordinator, oldest first within each "
    "category's budget). See python3 scripts/host_disk_usage.py status for the category "
    "over budget, then free it or raise its budget.")
DEFAULT_RECOMMENDATION = (
    "Look at the idle-but-kept chats (claude_idle_chats.py list) and archive the "
    "finished ones, or stop the biggest process listed in logs/host-load-guard/events.jsonl.")


def disk_problem(path: Path, min_free: int = DISK_FLOOR_BYTES, max_percent: float = DISK_WARN_PERCENT) -> str | None:
    stat = os.statvfs(path)
    free = stat.f_bavail * stat.f_frsize
    total = stat.f_blocks * stat.f_frsize
    used_percent = 100.0 * (total - free) / total if total else 0.0
    if free < min_free or used_percent > max_percent:
        return (f"disk {used_percent:.0f}% used, {free / guard.GIB:.0f} GiB free "
                f"(limits {max_percent:g}% / {min_free / guard.GIB:.0f} GiB)")
    return None


def disk_levels(path: Path, state: dict) -> dict[str, str | None]:
    """Problem text per disk alert level; an open incident stays open until DISK_REARM_POINTS below its level."""
    levels = {"disk": DISK_WARN_PERCENT, "disk_high": DISK_HIGH_PERCENT}
    return {key: disk_problem(path, DISK_FLOOR_BYTES, level - DISK_REARM_POINTS if key in state else level)
            for key, level in levels.items()}


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


def zellij_over_limit(state: dict, now: float, servers: dict[str, dict],
                      clock_ticks: int = os.sysconf("SC_CLK_TCK")) -> dict[str, str]:
    """zellij sessions over the RAM or CPU limit with their problem text; keeps this
    tick's sample in `state`."""
    previous = state.get("zellij_sample") or {}
    elapsed = now - float(previous.get("at", now))
    problems: dict[str, str] = {}
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
            problems[name] = f"zellij session `{name}` (pid {current['pid']}) uses {' and '.join(over)}"
    state["zellij_sample"] = {"at": now, "servers": servers}
    return problems


def zellij_problem(state: dict, now: float, servers: dict[str, dict],
                   clock_ticks: int = os.sysconf("SC_CLK_TCK")) -> str | None:
    """All over-limit zellij sessions in one line, or None (see zellij_over_limit)."""
    return "; ".join(zellij_over_limit(state, now, servers, clock_ticks).values()) or None


def _zellij_action(session: str, *args: str) -> subprocess.CompletedProcess[str]:
    # Never inherit a caller's zellij session (a guard run by hand inside a pane).
    env = {key: value for key, value in os.environ.items() if not key.startswith("ZELLIJ")}
    return subprocess.run([ZELLIJ_BIN, "--session", session, "action", *args], capture_output=True,
                          text=True, timeout=60, env=env, check=False)


def close_bar_plugins(session: str) -> tuple[list[str], str]:
    """Close the bar plugin panes of a zellij session; returns (closed pane ids, error).

    Only plugin panes whose plugin is in ZELLIJ_BAR_PLUGINS are closed; terminal panes
    (the chats) and background plugins are never touched, so no chat stops.
    """
    listing = _zellij_action(session, "list-panes", "--json", "--all")
    if listing.returncode:
        return [], f"list-panes exited {listing.returncode}: {listing.stderr.strip()[-200:]}"
    try:
        panes = json.loads(listing.stdout)
    except json.JSONDecodeError as err:
        return [], f"list-panes printed no JSON: {err}"
    closed, errors = [], []
    for pane in panes:
        if not pane.get("is_plugin") or pane.get("plugin_url") not in ZELLIJ_BAR_PLUGINS:
            continue
        pane_id = f"plugin_{pane['id']}"
        result = _zellij_action(session, "close-pane", "--pane-id", pane_id)
        if result.returncode:
            errors.append(f"{pane_id}: {result.stderr.strip()[-120:]}")
        else:
            closed.append(pane_id)
    return closed, "; ".join(errors)


def heal_zellij(sessions: list[str], directory: Path) -> str:
    """Self-healing for over-limit zellij sessions; returns what it did, for the alert."""
    done = []
    for session in sessions:
        closed, error = close_bar_plugins(session)
        if closed or error:
            guard.append_event(directory, "zellij_bars_closed", {"session": session, "closed": closed,
                                                                 "error": error})
        done.append(f"closed {len(closed)} bar plugins in `{session}`" if closed
                    else f"no bar plugins left in `{session}`" + (f" ({error})" if error else ""))
    return ", ".join(done)


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

    # Input boxes: typed-but-unsent text vs Claude Code's suggestion, with first-seen age
    # (claude_chat_inputs.py, inputs.json; the dev connector's send_message reads it).
    result = _script("claude_chat_inputs.py", "watch")
    if result.returncode:
        guard.append_event(directory, "inputs_watch_failed", {"code": result.returncode,
                                                               "error": result.stderr.strip()[-300:]})

    disk = disk_levels(repo, state)
    if any(disk.values()):
        extra = ""
        if not _service_active(DISK_SERVICE):
            extra += f"; {DISK_SERVICE} is not running"
        growers = host_disk_usage.growth_summary(repo / "logs" / "host-disk", repo.parent)
        extra += f"; {growers}" if growers else ""
        disk = {key: problem + extra if problem else None for key, problem in disk.items()}
        healed.append("disk cleanup is left to the disk coordinator")

    zellij_over = zellij_over_limit(state, now, zellij_servers())
    zellij = "; ".join(zellij_over.values()) or None
    if zellij:
        guard.append_event(directory, "zellij_over_limit", {"problem": zellij})
        state["zellij_healed"] = heal_zellij(list(zellij_over), directory)

    if healed:
        state["healed"] = healed
    checks = (("memory", memory, ALERT_AFTER_SECONDS, DEFAULT_RECOMMENDATION),
              ("disk", disk["disk"], ALERT_AFTER_SECONDS, DISK_RECOMMENDATION),
              ("disk_high", disk["disk_high"], ALERT_AFTER_SECONDS, DISK_RECOMMENDATION),
              ("zellij", zellij, ZELLIJ_ALERT_AFTER_SECONDS, ZELLIJ_RECOMMENDATION))
    for key, problem, after, recommendation in checks:
        was = state.get(key)
        problem, due = track(state, key, problem, now, after)
        if was and problem is None:
            guard.append_event(directory, "resources_recovered", {"kind": key, "since": was["since"]})
        if due:
            healed_text = (state.get("zellij_healed") or "nothing") if key == "zellij" \
                else ", ".join(state.get("healed") or ["nothing"])
            state[key]["alerted"] = alert(problem, healed_text, directory, after, recommendation)
    save(directory, state)
    return 0
