#!/usr/bin/env python3
"""New chats start on Sonnet while the weekly Claude usage is at or above 70% (owner, 2026-11-22).

From the moment the subscription's weekly (seven_day) usage reaches SWITCH_PERCENT until
the weekly reset, every NEW chat the host starts (claude_dispatch.launch_claude_chat:
issue and prod-errors chats, the dev connector's start_chat, queued starts) runs on
SONNET_MODEL, unless the owner named a model explicitly (`explicit_model`). Running and
resumed chats keep their model.

The usage guard (scripts/claude_usage_guard.py, a user service checking every 5 minutes)
calls `update` with each reading. The switch is recorded in STATE_NAME next to the guard's
own records; `update` sends one short ✅ push to the owner when the switch turns on and one
when it ends at the reset. `sonnet_active` is what launchers read: the recorded switch,
off once its reset time has passed.

Commands:
  status   Print the recorded switch.
  check    Read the usage now and update the switch (pushes on a change).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

SWITCH_PERCENT = 70.0
SONNET_MODEL = "claude-sonnet-5-5"
STATE_NAME = "weekly-model.json"
PUSH_CHAT_ID = "claude-weekly-model"
PUSH_TITLE = "Weekly model switch"
PUSH_TIMEOUT = 90
LOCAL_TZ = ZoneInfo("Europe/Berlin")
REPO_ROOT = Path(__file__).resolve().parents[1]


def state_path() -> Path:
    base = os.environ.get("OPENMATES_USAGE_GUARD_DIR") or Path.home() / ".cache/openmates/usage-guard"
    return Path(base) / STATE_NAME


def load() -> dict:
    try:
        data = json.loads(state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(record: dict) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(record, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _resets(record: dict) -> datetime | None:
    try:
        value = datetime.fromisoformat(str(record.get("resets_at", "")))
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def sonnet_active(now: datetime | None = None, record: dict | None = None) -> bool:
    """True while new chats must start on Sonnet: the switch is on and its reset has not passed."""
    record = load() if record is None else record
    resets = _resets(record)
    now = now or datetime.now(timezone.utc)
    return bool(record.get("active")) and resets is not None and now < resets


def new_chat_model(default: str, explicit_model: bool = False, now: datetime | None = None) -> str:
    """The model a new chat starts on: Sonnet while the switch is on, unless the owner named one."""
    if explicit_model or not sonnet_active(now):
        return default
    return SONNET_MODEL


def _when(resets: datetime) -> str:
    return resets.astimezone(LOCAL_TZ).strftime("%a %H:%M")


def on_message(used: float, resets: datetime) -> str:
    return (f"Weekly Claude usage is at {used:.0f}%: new chats start on Sonnet until the weekly "
            f"reset ({_when(resets)}).")


def off_message() -> str:
    return "Weekly Claude usage reset: new chats start on Opus again."


def push(text: str) -> str:
    """One ✅ push to the owner; '' or the error (never raises)."""
    command = [sys.executable, str(REPO_ROOT / "scripts" / "agent_question.py"), "done", "--force",
               "--summary", text, "--no-proof", "a usage reading, nothing to show"]
    env = dict(os.environ, CLAUDE_CODE_SESSION_ID=PUSH_CHAT_ID, CLAUDE_CHAT_TITLE=PUSH_TITLE)
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=PUSH_TIMEOUT, env=env,
                                check=False, cwd=str(REPO_ROOT))
    except (OSError, subprocess.TimeoutExpired) as error:
        return f"{type(error).__name__}: {error}"
    return "" if result.returncode == 0 else (result.stderr.strip() or result.stdout.strip())[-300:]


def update(used: float, resets: datetime, now: datetime | None = None, notify=push) -> str:
    """Record one usage reading; returns 'on', 'off' or '' (no change). Pushes on a change.

    The switch ends when the recorded reset time passes or a reading of a new weekly
    window is below the threshold (usage only falls at the reset)."""
    now = now or datetime.now(timezone.utc)
    record = load()
    was_on = bool(record.get("active"))
    is_on = used >= SWITCH_PERCENT and now < resets
    record.update({"used": used, "checked_at": now.isoformat(timespec="seconds")})
    change = ""
    if is_on and not sonnet_active(now, record):
        change = "on"
        record.update({"active": True, "since": now.isoformat(timespec="seconds"), "resets_at": resets.isoformat()})
        record["push_error"] = notify(on_message(used, resets))
    elif not is_on and was_on:
        change = "off"
        record.update({"active": False, "ended_at": now.isoformat(timespec="seconds")})
        record["push_error"] = notify(off_message())
    _save(record)
    return change


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("status", "check"))
    args = parser.parse_args(argv)
    if args.command == "check":
        from claude_usage_guard import fetch_weekly_usage

        used, resets = fetch_weekly_usage()
        print(f"used {used:.1f}%, resets {resets.isoformat()}: {update(used, resets) or 'no change'}")
    record = load()
    print(json.dumps({**record, "sonnet_active": sonnet_active(record=record)}, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
