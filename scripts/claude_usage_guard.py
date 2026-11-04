#!/usr/bin/env python3
"""Weekly Claude usage guard: tell active chats to wrap up before the budget runs out.

Deterministic decision, minimal model use. Every check:
  1. reads the subscription's weekly (seven_day) usage from the account endpoint
     Claude Code's /usage uses (read-only, undocumented, failures are reported),
  2. triggers when used >= THRESHOLD percent AND more than MIN_HOURS remain until the
     reset (close to the reset it is cheaper to just wait),
  3. at most once per weekly window, lists the active chats and delivers one fixed
     message to each through a restricted headless ``claude -p`` that may only call
     ListAgents/SendMessage (the supported way to reach a running, mid-turn chat).

Commands:
  status   Print usage, the decision and this window's delivery record.
  check    One evaluation; delivers when triggered (--dry-run prints instead).
  watch    Repeat ``check`` every --interval seconds (run in the background).
  message  Print the wrap-up message that would be sent.
  resend   One-time follow-up with the current message to the chats already messaged this window.
  ping     Delivery self-test: send a harmless test line to one chat (--to NAME).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from agent_peers import repository_root, transcripts

THRESHOLD_PERCENT = 90.0
MIN_HOURS_TO_RESET = 24.0
ACTIVE_MINUTES = 30
MAX_ATTEMPTS = 3
WRAPUP_MINUTES = 10
WINDOW_TOLERANCE = timedelta(hours=12)
DEFAULT_INTERVAL_SECONDS = 600
SENDER_MODEL = "haiku"
SENDER_MODES = {"acceptEdits", "auto", "bypassPermissions", "dontAsk", "plan"}  # `claude -p --permission-mode` choices
FALLBACK_MODE = "auto"
MODE_SCAN_BYTES = 2_000_000
SENDER_BUDGET_USD = "0.5"
SENDER_TIMEOUT_SECONDS = 300
LOCAL_TZ = ZoneInfo("Europe/Berlin")
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"


class UsageUnavailable(RuntimeError):
    """The usage endpoint or credentials could not be read."""


class DeliveryFailed(RuntimeError):
    """The headless sender did not run or reported an error."""


@dataclass(frozen=True)
class Decision:
    action: str  # trigger | below_threshold | near_reset | already_sent | gave_up
    used_percent: float
    hours_to_reset: float
    window: str  # resets_at floored to the hour; identifies the weekly window


def state_dir() -> Path:
    return Path(os.environ.get("OPENMATES_USAGE_GUARD_DIR") or Path.home() / ".cache/openmates/usage-guard")


def log(text: str) -> None:
    print(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} usage-guard: {text}", flush=True)


def parse_ts(value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as error:
        raise UsageUnavailable(f"unparseable reset time {value!r}") from error
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def fetch_weekly_usage() -> tuple[float, datetime]:
    """(used percent, reset time) of the weekly window."""
    try:
        token = json.loads((Path.home() / ".claude/.credentials.json").read_text())["claudeAiOauth"]["accessToken"]
        request = urllib.request.Request(USAGE_URL, headers={
            "Authorization": f"Bearer {token}", "anthropic-beta": "oauth-2025-04-20"})
        data = json.loads(urllib.request.urlopen(request, timeout=30).read())
        week = data["seven_day"]
        return float(week["utilization"]), parse_ts(week["resets_at"])
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise UsageUnavailable(f"{type(error).__name__}: {error}") from error


def window_key(resets: datetime) -> str:
    return resets.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0).isoformat()


def same_window(record: dict | None, resets: datetime) -> bool:
    """True when the stored record belongs to the weekly window ending at ``resets``.

    The endpoint's reset time wobbles by about a minute (10:59 vs 11:00), which flips an
    hour-floored key, so windows are matched by a tolerance far below the 7-day length.
    """
    if not record or not record.get("window"):
        return False
    return abs(parse_ts(record["window"]) - resets) < WINDOW_TOLERANCE


def decide(used: float, resets: datetime, now: datetime, record: dict | None,
           threshold: float = THRESHOLD_PERCENT, min_hours: float = MIN_HOURS_TO_RESET) -> Decision:
    """Pure decision: what this check should do for the current weekly window."""
    hours = (resets - now).total_seconds() / 3600
    window = window_key(resets)
    if same_window(record, resets):
        if record.get("sent_at"):
            action = "already_sent"
        elif record.get("attempts", 0) >= MAX_ATTEMPTS:
            action = "gave_up"
        else:
            action = None
    else:
        action = None
    if action is None:
        if used < threshold:
            action = "below_threshold"
        elif hours <= min_hours:
            action = "near_reset"
        else:
            action = "trigger"
    return Decision(action, used, hours, window)


def wrapup_message(used: float, resets: datetime, hours: float) -> str:
    reset_text = resets.astimezone(LOCAL_TZ).strftime("%a %d %b %H:%M")
    return (
        f"Weekly Claude usage is at {used:.0f}% with {hours:.0f}h until the reset - please wind this chat down "
        f"in an orderly way within about {WRAPUP_MINUTES} minutes.\n"
        f"Automated by scripts/claude_usage_guard.py (set up by the user). The weekly limit resets {reset_text}; "
        "the remaining budget has to last until then, so no new work starts now.\n"
        "1. Do not start new work, sub-agents, CI runs or long waits.\n"
        f"2. Finish what is nearly done: if a deploy, verification or merge can be completed in about {WRAPUP_MINUTES} "
        "minutes (the work is verified and only publishing or a short CI wait is left), complete it properly, then stop. "
        "Anything longer: stop at the next safe point. Never rush or push unverified work.\n"
        "3. Leave the workspace consistent (no half-applied edits). No raw git commit/push/stash.\n"
        "4. Before you stop, update your linked OpenMates Task(s) so anyone can continue without reading this chat: "
        "honest status (never Done while incomplete), session id and workspace, commits/deploys already made, what is "
        "verified and how, what is not, blockers, and the exact next command or file to resume from. "
        "If unfinished work has no Task, create one with /new-task.\n"
        "5. Your final reply is a short overview of what remains open and the recommended next steps in order.\n"
        "Then stop and do nothing further until the user writes to you or the limit resets. "
        "An explicit newer instruction from the user overrides this message."
    )


def list_background_agents() -> list[dict]:
    try:
        result = subprocess.run(["claude", "agents", "--json"], capture_output=True, text=True,
                                timeout=60, check=True)
        rows = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        raise DeliveryFailed(f"claude agents --json failed: {type(error).__name__}: {error}") from error
    return [row for row in rows if isinstance(row, dict) and row.get("name")]


def chat_permission_mode(path: Path | None) -> str:
    """Latest permission mode recorded in a chat transcript ('' when unknown)."""
    if path is None:
        return ""
    with path.open("rb") as handle:
        size = handle.seek(0, os.SEEK_END)
        handle.seek(max(0, size - MODE_SCAN_BYTES))
        lines = handle.read().decode("utf-8", errors="replace").splitlines()
    for line in reversed(lines):
        if '"permissionMode"' not in line:
            continue
        try:
            mode = json.loads(line).get("permissionMode")
        except ValueError:
            continue
        if isinstance(mode, str) and mode:
            return mode
    return ""


def sender_mode(targets: list[dict]) -> tuple[str, str]:
    """Permission mode for the sender plus a warning ('' if fine).

    Claude Code holds cross-session messages for approval when the receiver runs in a
    different mode than the sender, so the sender must mirror the targets' mode.
    """
    modes = {t["permissionMode"] for t in targets}
    if len(modes) == 1 and next(iter(modes)) in SENDER_MODES:
        return next(iter(modes)), ""
    return FALLBACK_MODE, (f"targets run in mixed or unsupported permission modes {sorted(modes)}; "
                           f"sending as {FALLBACK_MODE}, some may hold the message for approval")


def active_targets(rows: list[dict], root: Path, now: float, active_minutes: int = ACTIVE_MINUTES,
                   exclude_session: str = "") -> list[dict]:
    """Chats working now, or recently active and not finished; idle/done ones stay asleep."""
    paths = transcripts(root)
    targets = []
    for row in rows:
        session = row.get("sessionId", "")
        if session == exclude_session:
            continue
        path = paths.get(session)
        recent = path is not None and now - path.stat().st_mtime <= active_minutes * 60
        working = row.get("status") == "busy" or row.get("state") == "working"
        if working or (recent and row.get("state") != "done"):
            targets.append({"name": row["name"], "sessionId": session, "status": row.get("status", ""),
                            "kind": row.get("kind", ""), "permissionMode": chat_permission_mode(path)})
    return targets


def sender_prompt(targets: list[dict], message: str) -> str:
    lines = "\n".join(f"- {t['name']} (currently {t['status']})" for t in targets)
    return (
        "You are a message relay. Do nothing except the steps below.\n"
        "1. If ListAgents is not callable, load it with ToolSearch query 'select:ListAgents,SendMessage'. "
        "Call ListAgents once.\n"
        "2. For each target below, find the ListAgents rows whose name equals the target name exactly. "
        "If exactly one row has that name, call SendMessage with `to` set to the bare name. "
        "If several rows share it, call SendMessage once per row with `to` set to 'name [ref]' using the ref shown. "
        "Skip a target with no row.\n"
        "3. The `message` is the text between the markers, byte for byte, identical for every target. "
        "Do not summarize, translate or add to it. Do not send to anyone not listed.\n"
        "4. Finish with one JSON line: {\"sent\": [names], \"skipped\": [names]}.\n\n"
        f"TARGETS:\n{lines}\n\n=== MESSAGE START ===\n{message}\n=== MESSAGE END ==="
    )


def deliver(targets: list[dict], message: str, root: Path, mode: str) -> str:
    command = ["claude", "-p", "--model", SENDER_MODEL, "--permission-mode", mode, "--no-session-persistence",
               "--setting-sources", "user", "--tools", "ListAgents,SendMessage,ToolSearch",
               "--allowedTools", "ListAgents", "SendMessage", "ToolSearch",
               "--max-budget-usd", SENDER_BUDGET_USD, "--output-format", "json", sender_prompt(targets, message)]
    try:
        result = subprocess.run(command, capture_output=True, text=True, cwd=root,
                                timeout=SENDER_TIMEOUT_SECONDS, check=True)
        outcome = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        raise DeliveryFailed(f"headless sender failed: {type(error).__name__}: {error}") from error
    if outcome.get("is_error"):
        raise DeliveryFailed(f"headless sender reported an error: {outcome.get('result')}")
    return str(outcome.get("result", ""))


def load_record(directory: Path) -> dict | None:
    try:
        return json.loads((directory / "state.json").read_text())
    except FileNotFoundError:
        return None


def save_record(directory: Path, record: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = directory / "state.json.tmp"
    temporary.write_text(json.dumps(record, indent=2, sort_keys=True))
    temporary.replace(directory / "state.json")


def run_check(dry_run: bool, threshold: float, min_hours: float, active_minutes: int,
              directory: Path | None = None, now: datetime | None = None) -> Decision:
    directory = directory or state_dir()
    now = now or datetime.now(timezone.utc)
    used, resets = fetch_weekly_usage()
    record = load_record(directory)
    decision = decide(used, resets, now, record, threshold, min_hours)
    log(f"weekly usage {used:.1f}%, {decision.hours_to_reset:.1f}h to reset -> {decision.action}")
    if decision.action != "trigger":
        return decision
    root = repository_root(Path.cwd())
    targets = active_targets(list_background_agents(), root, time.time(), active_minutes,
                             os.environ.get("CLAUDE_CODE_SESSION_ID", ""))
    message = wrapup_message(used, resets, decision.hours_to_reset)
    if dry_run:
        log(f"dry run: would message {len(targets)} chats: {[t['name'] for t in targets]}")
        print(message)
        return decision
    attempts = record.get("attempts", 0) if same_window(record, resets) else 0
    record = {"window": decision.window, "attempts": attempts + 1, "used_percent": used,
              "targets": targets, "triggered_at": now.isoformat(timespec="seconds")}
    if not targets:
        record["sent_at"] = now.isoformat(timespec="seconds")
        record["result"] = "no active chats at trigger time"
        save_record(directory, record)
        log("no active chats; window marked handled")
        return decision
    mode, warning = sender_mode(targets)
    record["sender_mode"] = mode
    if warning:
        record["warning"] = warning
        log(warning)
    try:
        record["result"] = deliver(targets, message, root, mode)
        record["sent_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        log(f"delivered to {len(targets)} chats: {record['result'][:300]}")
    except DeliveryFailed as error:
        record["error"] = str(error)
        log(f"delivery attempt {record['attempts']}/{MAX_ATTEMPTS} failed: {error}")
    save_record(directory, record)
    return decision


def run_ping(name: str) -> int:
    """Delivery self-test: one harmless message to the chat called ``name`` through the real path."""
    root = repository_root(Path.cwd())
    paths = transcripts(root)
    targets = [{"name": row["name"], "sessionId": row.get("sessionId", ""), "status": row.get("status", ""),
                "kind": row.get("kind", ""), "permissionMode": chat_permission_mode(paths.get(row.get("sessionId", "")))}
               for row in list_background_agents() if row["name"] == name]
    if not targets:
        raise DeliveryFailed(f"no running chat named {name!r}")
    mode, warning = sender_mode(targets)
    if warning:
        log(warning)
    text = ("Usage guard delivery test (no action needed): scripts/claude_usage_guard.py ping reached this chat. "
            "Reply nothing and continue what you were doing.")
    log(f"ping {name!r} ({len(targets)} match) as {mode}")
    print(deliver(targets, text, root, mode))
    return 0


def run_resend(directory: Path | None = None, now: datetime | None = None) -> int:
    """One-time follow-up with the current message to the chats of this window's first message."""
    directory = directory or state_dir()
    now = now or datetime.now(timezone.utc)
    used, resets = fetch_weekly_usage()
    record = load_record(directory)
    if not same_window(record, resets) or not record.get("sent_at"):
        raise DeliveryFailed("nothing was sent in this weekly window, so there is nothing to follow up")
    if record.get("resent_at"):
        raise DeliveryFailed(f"follow-up already sent at {record['resent_at']}")
    own = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    targets = [t for t in record.get("targets", []) if t.get("sessionId") != own]
    if not targets:
        raise DeliveryFailed("the first message had no targets")
    root = repository_root(Path.cwd())
    mode, warning = sender_mode(targets)
    if warning:
        record["warning"] = warning
        log(warning)
    hours = (resets - now).total_seconds() / 3600
    record["resent_result"] = deliver(targets, wrapup_message(used, resets, hours), root, mode)
    record["resent_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    save_record(directory, record)
    log(f"follow-up delivered to {len(targets)} chats: {record['resent_result'][:300]}")
    return 0


def run_status(threshold: float, min_hours: float) -> int:
    used, resets = fetch_weekly_usage()
    record = load_record(state_dir())
    decision = decide(used, resets, datetime.now(timezone.utc), record, threshold, min_hours)
    print(f"weekly usage {used:.1f}% | resets {resets.astimezone(LOCAL_TZ):%a %d %b %H:%M} "
          f"({decision.hours_to_reset:.1f}h) | action now: {decision.action}")
    print(f"rule: >= {threshold:.0f}% used and > {min_hours:.0f}h to reset, once per weekly window")
    current = record if same_window(record, resets) else None
    print("this window: " + (json.dumps({k: v for k, v in current.items() if k != "targets"}, indent=2)
                              if current else "nothing sent"))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["status", "check", "watch", "message", "ping", "resend"])
    parser.add_argument("--to", help="chat name for ping")
    parser.add_argument("--threshold", type=float, default=THRESHOLD_PERCENT)
    parser.add_argument("--min-hours", type=float, default=MIN_HOURS_TO_RESET)
    parser.add_argument("--active-minutes", type=int, default=ACTIVE_MINUTES)
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL_SECONDS)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "message":
        print(wrapup_message(args.threshold, datetime.now(timezone.utc) + timedelta(hours=args.min_hours + 1),
                             args.min_hours + 1))
        return 0
    try:
        if args.command == "status":
            return run_status(args.threshold, args.min_hours)
        if args.command == "resend":
            return run_resend()
        if args.command == "ping":
            return run_ping(args.to or "")
        if args.command == "check":
            run_check(args.dry_run, args.threshold, args.min_hours, args.active_minutes)
            return 0
        while True:
            try:
                run_check(args.dry_run, args.threshold, args.min_hours, args.active_minutes)
            except (UsageUnavailable, DeliveryFailed) as error:
                log(f"check failed, will retry: {error}")
            time.sleep(args.interval)
    except (UsageUnavailable, DeliveryFailed) as error:
        print(f"claude_usage_guard: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
