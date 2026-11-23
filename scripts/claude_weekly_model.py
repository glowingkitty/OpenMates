#!/usr/bin/env python3
"""New chats go to Codex while 30% or less of the weekly Claude usage is left (owner, 2026-11-23).

Routing rule for every NEW chat the host starts (claude_dispatch.launch_claude_chat: issue
and prod-errors chats, the dev connector's start_chat, queued starts):
  * more than 30% of the weekly Claude usage left: Claude, Opus by default (Sonnet when the
    caller asks for it for simple work), as before;
  * 30% or less left (SWITCH_PERCENT used) until the weekly reset: Codex on CODEX_MODEL;
  * always Claude: security work and anything touching encryption (CLAUDE_ONLY_RE on the
    title and prompt), until the owner decides Codex has proven itself;
  * an explicit model choice of the owner (Fable, Astra, any named model) always wins.
This replaces the rule of 2026-11-22 (Sonnet from 70% used). Running and resumed chats
keep their engine and model.

The usage guard (scripts/claude_usage_guard.py, a user service checking every 5 minutes)
calls `update` with each reading. The switch is recorded in STATE_NAME next to the guard's
own records; `update` sends one short ✅ push to the owner when the switch turns on and one
when it ends at the reset. `switch_active` is what launchers read: the recorded switch,
off once its reset time has passed.

Commands:
  status   Print the recorded switch.
  check    Read the usage now and update the switch (pushes on a change).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

SWITCH_PERCENT = 70.0
SONNET_MODEL = "claude-sonnet-5-5"
CODEX_MODEL = "gpt-6.2-sol"
# Security work and encryption stay on Claude (owner, 2026-11-23).
CLAUDE_ONLY_RE = re.compile(
    r"\b(security|secur(e|ity)[- ]fix|vulnerab\w*|cve-\d+|exploit\w*|pentest\w*|encrypt\w*|decrypt\w*|"
    r"crypto\w*|e2ee|end-to-end|cipher\w*|master[- ]key|chat[- ]key|key[- ](mismatch|rotation|derivation|wrap\w*)|"
    r"zero[- ]knowledge)\b", re.IGNORECASE)
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


def switch_active(now: datetime | None = None, record: dict | None = None) -> bool:
    """True while new chats go to Codex: the switch is on and its reset has not passed."""
    record = load() if record is None else record
    resets = _resets(record)
    now = now or datetime.now(timezone.utc)
    return bool(record.get("active")) and resets is not None and now < resets


sonnet_active = switch_active  # name used by older callers (dev connector)


def claude_only(text: str) -> bool:
    """Security or encryption work: never routed to Codex."""
    return bool(CLAUDE_ONLY_RE.search(text or ""))


def route(default: str, explicit_model: bool = False, text: str = "", now: datetime | None = None) -> tuple[str, str]:
    """(engine, model) of a new chat: 'claude' or 'codex' per the routing rule in the module doc."""
    if explicit_model:
        return ("codex" if default.lower().startswith(("gpt-", "codex")) else "claude"), default
    if default.lower().startswith(("gpt-", "codex")):
        return "codex", default
    if switch_active(now) and not claude_only(text):
        return "codex", CODEX_MODEL
    return "claude", default


def new_chat_model(default: str, explicit_model: bool = False, now: datetime | None = None) -> str:
    """The Claude model a new Claude chat starts on (the switch now moves chats to Codex, not Sonnet)."""
    return default


def _when(resets: datetime) -> str:
    return resets.astimezone(LOCAL_TZ).strftime("%a %H:%M")


def on_message(used: float, resets: datetime) -> str:
    return (f"Weekly Claude usage is at {used:.0f}%: new chats go to Codex until the weekly "
            f"reset ({_when(resets)}), except security and encryption work.")


def off_message() -> str:
    return "Weekly Claude usage reset: new chats start on Claude again."


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
    if is_on and not switch_active(now, record):
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
    print(json.dumps({**record, "codex_active": switch_active(record=record)}, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
