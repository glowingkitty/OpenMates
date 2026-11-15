#!/usr/bin/env python3
"""What the input box of each zellij-pane Claude chat holds: typed text or a suggestion.

Claude Code (2.1.3xx) shows its predicted next prompt as grey ghost text in an empty
input box. `zellij action dump-screen` has no colours, so a dump cannot tell that
suggestion from a message someone typed and did not send. On 2026-11-14/15 the dev
connector's send_message refused chats 1f5afa9e, 4b5c74d7, 76c8264a, 0fa759b6,
36f0f2d5 and f7f66f14 for hours with "its input box still holds an earlier unsent
message", and the lifecycle's `release` pressed Enter on them every minute: all of
those "messages" were suggestions over an empty box, and Enter on an empty box does
nothing. The host-load hook held no prompt at all in that time (no `prompt_held`
event); since commit 1661195 it never refuses and releases after at most 9 minutes.

`probe()` tells them apart by typing one letter: a suggestion disappears and the box
shows only that letter; typed text stays and gets the letter appended. The letter is
deleted again either way.

Busy chats are not probed (their box is in use), except for text the dev connector typed
itself: the connector lists its unconfirmed deliveries in connector-deliveries.json in
the same folder (its broker re-presses Enter and flags them undelivered), and `watch`
records a busy chat whose box still shows such a delivery as `typed` with source
`connector` and the time it was typed, so a send that sat in a busy chat's box for two
hours (76c8264a, 2026-11-15) shows up at once.

`watch` (every minute from scripts/host_resources.py) writes
logs/claude-chat-lifecycle/inputs.json: per running pane chat whose box shows text,
{text, since (first seen), verdict, checked_at, title}. Text that stays the same for
PROBE_AFTER_SECONDS in an idle chat is probed once: verdict `typed` (an unsent
message) or `suggestion`; until then `unchecked`. The dev connector reads this file:
`typed` entries are its queue of unsent messages (shown by host_status), and `since`
is the age send_message uses to replace stale held text (older than 30 min) by
default instead of refusing.

Commands:
  watch [--json]   refresh inputs.json and print the typed (unsent) entries
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import claude_idle_chats as lifecycle  # noqa: E402  (path set above)

PROBE = "q"
BACKSPACE = "127"
PROBE_AFTER_SECONDS = 10 * 60  # text unchanged this long in an idle chat is checked once
PROBE_POLLS = 10
PROBE_PAUSE = 0.3
INPUTS_FILE = "inputs.json"
DELIVERIES_FILE = "connector-deliveries.json"  # written by the dev connector's broker
PASTE_MARK = "[Pasted text"  # how Claude Code shows long typed text
RULE_CHARS = set("▔─━")

Zellij = Callable[..., "object"]  # lifecycle.zellij signature: (session, *action args) -> CompletedProcess


def _rule(line: str) -> bool:
    return bool(line.strip()) and set(line.strip()) <= RULE_CHARS


def input_text(screen: str) -> str:
    """Text shown in the prompt box: the `❯` line right under a rule ('' when empty).

    Earlier prompts in the transcript also start with `❯`, so only the boxed line counts.
    Shown is not typed: it may be Claude Code's suggestion (see probe)."""
    lines = [line for line in screen.splitlines() if line.strip()]
    boxed = [line.strip() for prev, line in zip(lines, lines[1:]) if _rule(prev) and line.strip().startswith("❯")]
    return boxed[-1][1:].strip() if boxed else ""


def _shown(zellij: Zellij, session: str, pane: str) -> str | None:
    result = zellij(session, "dump-screen", "--pane-id", pane)
    return None if result.returncode else input_text(result.stdout)


def probe(zellij: Zellij, session: str, pane: str, sleep: Callable[[float], None] | None = None) -> str:
    """`empty`, `suggestion` or `typed` for one pane; `unknown` when zellij fails.

    A screen that does not react to the letter counts as typed: never treat text as
    disposable without seeing it vanish."""
    shown = _shown(zellij, session, pane)
    if shown is None:
        return "unknown"
    if not shown:
        return "empty"
    if zellij(session, "write-chars", "--pane-id", pane, PROBE).returncode:
        return "unknown"
    after, sleep = shown, sleep or time.sleep
    for _ in range(PROBE_POLLS):
        sleep(PROBE_PAUSE)
        after = _shown(zellij, session, pane)
        if after != shown:
            break
    zellij(session, "write", "--pane-id", pane, BACKSPACE)
    return "suggestion" if after == PROBE else "typed"


def load(directory: Path) -> dict[str, dict]:
    try:
        data = json.loads((directory / INPUTS_FILE).read_text())
    except FileNotFoundError:
        return {}
    return data if isinstance(data, dict) else {}


def save(directory: Path, entries: dict[str, dict]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    tmp = directory / f".{INPUTS_FILE}.{os.getpid()}"
    tmp.write_text(json.dumps(entries, indent=1, sort_keys=True))
    tmp.replace(directory / INPUTS_FILE)


def connector_pending(directory: Path) -> dict[str, dict]:
    """The connector's pending deliveries by chat id ({} when the connector wrote none)."""
    try:
        data = json.loads((directory / DELIVERIES_FILE).read_text())
    except FileNotFoundError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {cid: entry for cid, entry in data.items() if isinstance(entry, dict) and entry.get("state") == "pending"}


def connector_typed(shown: str, delivery: dict) -> bool:
    """Whether the box shows the message the connector typed (same rule as its deliveries.ours)."""
    head = str(delivery.get("head", ""))[:40]
    return bool(shown) and ((bool(head) and shown.startswith(head))
                            or (bool(delivery.get("long")) and shown.startswith(PASTE_MARK)))


def watch(live: list, directory: Path, now: float, zellij: Zellij | None = None,
          sleep: Callable[[float], None] | None = None) -> dict[str, dict]:
    """Refresh inputs.json from the live chats (lifecycle.Chat); returns the new entries."""
    zellij = zellij or lifecycle.zellij
    previous = load(directory)
    pending = connector_pending(directory)
    entries: dict[str, dict] = {}
    for chat in live:
        if chat.kind != "pane" or not chat.zellij_session or not chat.pane_id:
            continue
        pane = f"terminal_{chat.pane_id}"
        shown = _shown(zellij, chat.zellij_session, pane)
        if not shown:
            continue
        old = previous.get(chat.session_id, {})
        entry = old if old.get("text") == shown else {"text": shown, "since": now, "verdict": "unchecked"}
        entry["title"] = chat.title or chat.name
        delivery = pending.get(chat.session_id)
        if delivery and connector_typed(shown, delivery):
            # Our own text, busy or idle: no probe needed, age from when it was typed.
            if entry.get("source") != "connector":
                lifecycle.log_event(directory, {"event": "unsent_input", "session_id": chat.session_id,
                                                "title": entry["title"], "source": "connector",
                                                "status": chat.status, "text": shown[:200]})
            entry.update(verdict="typed", source="connector", since=float(delivery.get("typed_at", now)),
                         checked_at=now, status=chat.status)
            entries[chat.session_id] = entry
            continue
        quiet = chat.status == "idle" and not chat.waiting_for
        if entry["verdict"] == "unchecked" and quiet and now - float(entry["since"]) >= PROBE_AFTER_SECONDS:
            verdict = probe(zellij, chat.zellij_session, pane, sleep)
            if verdict in ("typed", "suggestion"):
                entry.update(verdict=verdict, checked_at=now)
                if verdict == "typed":
                    lifecycle.log_event(directory, {"event": "unsent_input", "session_id": chat.session_id,
                                                    "title": entry["title"], "since": entry["since"],
                                                    "text": shown[:200]})
            elif verdict == "empty":
                continue
        entries[chat.session_id] = entry
    save(directory, entries)
    return entries


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("watch",))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--claude-home", type=Path, default=Path.home() / ".claude")
    args = parser.parse_args(argv)
    directory = lifecycle.state_dir()
    entries = watch(lifecycle.live_chats(args.claude_home, lifecycle.load_config()), directory, time.time())
    typed = {sid: entry for sid, entry in entries.items() if entry.get("verdict") == "typed"}
    if args.json:
        print(json.dumps(typed, indent=1))
    for sid, entry in typed.items():
        minutes = int((time.time() - float(entry["since"])) // 60)
        print(f"unsent {entry.get('title') or ''} ({sid[:8]}) for {minutes} min: {entry['text'][:120]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
