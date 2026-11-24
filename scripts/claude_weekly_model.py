#!/usr/bin/env python3
"""Route dev work chats by the weekly Claude usage and the owner's named model.

Default routes preserve Opus and Sonnet below 70% used. At 70% used new chats
start on Codex, with security and encryption staying on Claude until it reaches
90% used. Above 90% used existing Claude chats hand off before their next run.
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
RESERVE_PERCENT = 90.0
RESERVE_EXEMPT_ENV = "OPENMATES_CLAUDE_RESERVE_EXEMPT"
SONNET_MODEL = "claude-sonnet-5-5"
CODEX_MODEL = "gpt-6.2-sol"
# Security work and encryption stay on Claude while more than 10% remains.
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


def reserve_active(now: datetime | None = None, record: dict | None = None) -> bool:
    """True strictly below 10% Claude usage remaining, until this week's reset."""
    record = load() if record is None else record
    return switch_active(now, record) and float(record.get("used") or 0) > RESERVE_PERCENT


def needs_handoff(chat_id: str, now: datetime | None = None, *, exemption: str = "") -> bool:
    """Existing Claude work must move engines when the reserve is active."""
    record = load()
    if exemption in ("owner-model", "live-voice") or not reserve_active(now, record):
        return False
    try:
        finisher = json.loads(state_path().with_name("reserve-finisher.json").read_text())
    except (OSError, ValueError):
        finisher = {}
    return not (finisher.get("chat") == chat_id and finisher.get("resets_at") == record.get("resets_at"))


def allow_finisher(chat_id: str) -> None:
    """Allow one already-running chat to finish in the current weekly window."""
    record = load()
    if not reserve_active(record=record) or not re.fullmatch(r"[0-9a-fA-F-]{36}", chat_id):
        raise ValueError("The reserve finisher requires an active reserve and a full chat ID")
    path = state_path().with_name("reserve-finisher.json")
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps({"chat": chat_id, "resets_at": record["resets_at"]}))
    tmp.replace(path)


def claude_only(text: str) -> bool:
    """Security or encryption work with the Claude preference above the reserve."""
    return bool(CLAUDE_ONLY_RE.search(text or ""))


def route(default: str, explicit_model: bool = False, text: str = "", now: datetime | None = None,
          *, live_voice: bool = False) -> tuple[str, str]:
    """(engine, model) of a new chat: 'claude' or 'codex' per the routing rule in the module doc."""
    if explicit_model:
        return ("codex" if default.lower().startswith(("gpt-", "codex")) else "claude"), default
    if default.lower().startswith(("gpt-", "codex")):
        return "codex", default
    if live_voice:
        return "claude", default
    record = load()
    if switch_active(now, record) and (float(record.get("used") or 0) >= RESERVE_PERCENT or not claude_only(text)):
        return "codex", CODEX_MODEL
    return "claude", default


def queued_route(model: str, now: datetime | None = None, record: dict | None = None) -> tuple[str, str]:
    """Scheduled and pending starts follow the usage policy, including saved model choices."""
    if switch_active(now, record):
        return "codex", CODEX_MODEL
    return route(model, explicit_model=True, now=now)


def new_chat_model(default: str, explicit_model: bool = False, now: datetime | None = None) -> str:
    """The Claude model a new Claude chat starts on (the switch now moves chats to Codex, not Sonnet)."""
    return default


def _when(resets: datetime) -> str:
    return resets.astimezone(LOCAL_TZ).strftime("%a %H:%M")


def on_message(used: float, resets: datetime) -> str:
    return (f"Weekly Claude usage is at {used:.0f}%: new chats go to Codex until the weekly "
            f"reset ({_when(resets)}), with Claude reserved by the weekly usage rules.")


def off_message() -> str:
    return "Weekly Claude usage reset: new chats start on Claude again."


def push(text: str) -> str:
    """One ✅ push to the owner; '' or the error (never raises)."""
    command = [sys.executable, str(REPO_ROOT / "scripts" / "agent_question.py"), "done", "--force",
               "--summary", text]
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
    parser.add_argument("command", choices=("status", "check", "allow-finisher"))
    parser.add_argument("--chat", default="")
    args = parser.parse_args(argv)
    if args.command == "allow-finisher":
        allow_finisher(args.chat)
        print("The designated running Claude chat may finish in this weekly window.")
        return 0
    if args.command == "check":
        from claude_usage_guard import fetch_weekly_usage

        used, resets = fetch_weekly_usage()
        print(f"used {used:.1f}%, resets {resets.isoformat()}: {update(used, resets) or 'no change'}")
    record = load()
    print(json.dumps({**record, "codex_active": switch_active(record=record), "reserve_active": reserve_active(record=record)}, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
