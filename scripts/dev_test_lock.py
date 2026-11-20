#!/usr/bin/env python3
"""Dev deploy and restart lock while a real test runs on dev (TASK-8552, owner decision 2026-11-20).

A real voice call test, a real-inference E2E test or an AI test user run on dev fails or proves
nothing when another chat deploys to dev or restarts dev containers in the middle of it. While such
a test runs it holds this lock; `sessions.py deploy` and `sessions.py docker restart` then do nothing and register a waiter for the calling chat instead. The chat keeps coding;
when the lock is released (the test ended, its process died, or the hard cap of MAX_MINUTES
passed) every waiting chat is woken through the chat waiters (`claude_chat_waiters.py`) and runs
its command again. The lock and its holders show in the dev connector's host_status.

Several tests may hold it at once; dev is free when the last one leaves. A holder is dropped when
its process is gone (checked on every read and by the chat lifecycle each minute) or MAX_MINUTES
after it took the lock, whichever comes first; it cannot be renewed. Temporary: it goes away when
the test setup moves into OpenMates itself.

  python3 scripts/dev_test_lock.py status
  python3 scripts/dev_test_lock.py run --kind voice-call -- node scripts/verify_voice_call_live_smoke.cjs ...
  python3 scripts/dev_test_lock.py release --all        (the owner: drop a stuck lock now)

In Python test runners: `dev_test_lock.hold("real-inference", "my_real_test.py")` once the test
is about to use dev; it is released when the process exits.

State: logs/claude-chat-lifecycle/dev-test-lock.json in the main checkout.
"""
from __future__ import annotations

import argparse
import atexit
import fcntl
import os
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import claude_chat_waiters as waiters  # noqa: E402 - sibling script module

MAX_MINUTES = 45.0
KINDS = {"voice-call": "real voice call test", "real-inference": "real-inference E2E test",
         "ai-test-users": "AI test user run"}
WAITER_PREFIX = "dev-test-lock-"
LOCKED_EXIT = 75  # EX_TEMPFAIL: nothing was done, run again once woken
BERLIN = ZoneInfo("Europe/Berlin")
_held: dict[str, str] = {}  # kind -> holder id taken by this process


def state_dir() -> Path:
    import claude_idle_chats  # imports claude_chat_waiters; only its state location is needed

    return claude_idle_chats.state_dir()


def _berlin(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, BERLIN).strftime("%H:%M")


@contextmanager
def _locked(state: Path):
    state.mkdir(parents=True, exist_ok=True)
    with (state / ".dev-test-lock.lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield state / "dev-test-lock.json"
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _live(holders: dict, now: float) -> dict:
    return {hid: h for hid, h in holders.items() if now < h["expires_at"] and _alive(int(h["pid"]))}


def holders(state: Path | None = None, now: float | None = None) -> dict:
    """The live holders (expired and dead ones are dropped and, if dev became free, waiters fired)."""
    state = state or state_dir()
    sweep(state, now)
    return waiters._read_json(state / "dev-test-lock.json").get("holders", {})


def take(kind: str, label: str = "", *, pid: int | None = None, chat: str = "", session: str = "",
         state: Path | None = None, now: float | None = None, minutes: float = MAX_MINUTES) -> str:
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    state = state or state_dir()
    now = time.time() if now is None else now
    holder = uuid.uuid4().hex[:10]
    with _locked(state) as path:
        data = waiters._read_json(path)
        data["holders"] = _live(data.get("holders", {}), now) | {holder: {
            "kind": kind, "label": label[:120], "pid": pid or os.getpid(), "since": now,
            "expires_at": now + min(minutes, MAX_MINUTES) * 60,
            "chat": chat or os.environ.get("CLAUDE_CODE_SESSION_ID", ""), "session": session}}
        waiters._write_json(path, data)
    return holder


def release(holder: str = "", *, everyone: bool = False, state: Path | None = None,
            now: float | None = None) -> list[str]:
    """Drop one holder (or all); returns the chats woken because dev became free."""
    state = state or state_dir()
    with _locked(state) as path:
        data = waiters._read_json(path)
        before = data.get("holders", {})
        kept = {} if everyone else {k: v for k, v in before.items() if k != holder}
        if kept != before:
            gone = before.get(holder) or {}
            data["holders"] = kept
            data["last_ended"] = {"at": time.time() if now is None else now, "why": (
                "the owner released the lock" if everyone
                else f"the {KINDS.get(gone.get('kind'), 'test')} ended")}
            waiters._write_json(path, data)
    return sweep(state, now)


def sweep(state: Path | None = None, now: float | None = None) -> list[str]:
    """Drop expired and dead holders; once none is left, wake every chat waiting on the lock."""
    state = state or state_dir()
    now = time.time() if now is None else now
    with _locked(state) as path:
        data = waiters._read_json(path)
        before = data.get("holders", {})
        live = _live(before, now)
        if live != before:
            data["holders"] = live
            data["last_ended"] = {"at": now, "why": _why_ended(before, live, now)}
            waiters._write_json(path, data)
        why = data.get("last_ended", {}).get("why", "the tests ended")
    if live:
        return []
    woken = []
    for key, entry in waiters._read_json(state / "registered.json").items():
        if key.startswith(WAITER_PREFIX) and not entry.get("fired_at"):
            try:
                waiters.fire(state, entry["chat_id"], key, f"Dev is free again ({why}). Run your command again.",
                             now=now)
            except KeyError:
                continue  # cleared meanwhile
            woken.append(entry["chat_id"])
    return woken


def _why_ended(before: dict, live: dict, now: float) -> str:
    gone = [h for hid, h in before.items() if hid not in live]
    if not gone:
        return "the tests ended"
    h = gone[-1]
    what = KINDS.get(h["kind"], h["kind"])
    if now >= h["expires_at"]:
        return f"the {what} lock expired after {MAX_MINUTES:.0f} minutes"
    return f"the {what} ended"


def describe(live: dict) -> list[str]:
    rows = []
    for h in sorted(live.values(), key=lambda h: h["since"]):
        who = ", ".join(x for x in (h.get("label"), f"chat {h['chat'][:8]}" if h.get("chat") else "",
                                    f"session {h['session']}" if h.get("session") else "") if x)
        rows.append(f"{KINDS.get(h['kind'], h['kind'])} ({who or 'pid ' + str(h['pid'])}) since "
                    f"{_berlin(h['since'])} Berlin, expires {_berlin(h['expires_at'])} at the latest")
    return rows


def hold(kind: str, label: str = "", session: str = "") -> str:
    """Take the lock for this process once; released at exit (a killed process is swept within a minute)."""
    if kind not in _held:
        state = state_dir()
        _held[kind] = take(kind, label, session=session, state=state)
        atexit.register(release, _held[kind], state=state)
    return _held[kind]


def gate(action: str, session: str = "", chat: str = "") -> None:
    """Stop `action` (deploy / docker restart) while a real test holds dev; the chat is woken on release."""
    state = state_dir()
    live = holders(state)
    if not live:
        return
    chat = os.environ.get("CLAUDE_CODE_SESSION_ID", "") or chat
    expires = max(h["expires_at"] for h in live.values())
    lines = [f"DEV TEST LOCK — {action} waits: nothing was done. Dev is held by:", *("  " + r for r in describe(live))]
    if waiters.UUID_RE.match(chat or ""):
        waiters.add(state, chat, "handoff", f"the dev test lock to be released, to run: {action}"
                    + (f" --session {session}" if session else ""), key=WAITER_PREFIX + chat[:8],
                    timeout_minutes=(expires - time.time()) / 60 + 15)
        lines.append("Keep coding. This chat is woken when the lock is released; then run the same command again.")
    else:
        lines.append("No chat id to wake (CLAUDE_CODE_SESSION_ID unset): run it again after "
                     f"{_berlin(expires)} Berlin or check `python3 scripts/dev_test_lock.py status`.")
    print("\n".join(lines), file=sys.stderr)
    sys.exit(LOCKED_EXIT)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    run = sub.add_parser("run", help="hold the lock while a command runs")
    run.add_argument("--kind", choices=sorted(KINDS), required=True)
    run.add_argument("--label", default="")
    run.add_argument("--session", default="")
    run.add_argument("cmd", nargs=argparse.REMAINDER)
    rel = sub.add_parser("release")
    rel.add_argument("holder", nargs="?", default="")
    rel.add_argument("--all", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "status":
        live = holders()
        print("\n".join(describe(live)) if live else "Dev is free: no real test holds the deploy and restart lock.")
        return 0
    if args.command == "release":
        if not (args.holder or args.all):
            parser.error("give a holder id or --all")
        woken = release(args.holder, everyone=args.all)
        print(f"Released. Woke {len(woken)} waiting chat(s)." if woken else "Released.")
        return 0
    cmd = args.cmd[1:] if args.cmd[:1] == ["--"] else args.cmd
    if not cmd:
        parser.error("run needs a command after --")
    holder = take(args.kind, args.label or Path(cmd[0]).name, session=args.session)
    try:
        return subprocess.run(cmd).returncode
    finally:
        release(holder)


if __name__ == "__main__":
    sys.exit(main())
