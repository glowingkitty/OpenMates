#!/usr/bin/env python3
"""One owner notice when a Claude chat uses unusually many sub-agents or tokens.

Owner decision (22 Nov, TASK-9435): warnings, not caps. Nothing is stopped or
slowed down; Marco gets one Discord line per chat when it crosses a threshold,
so he can look at it. The thresholds sit near the top 5% of the 7 days before
22 Nov (125 chats: p95 89M weighted tokens and 33 sub-agents, max 572M / 211).

Weighted tokens use the investigation's relative weights (not prices):
input + cache writes + 0.1 x cache reads + 5 x output, summed over the chat's
own transcript and all its sub-agent transcripts.

Reading is incremental: per transcript the byte offset and running total are
kept in `logs/claude-chat-lifecycle/usage-watch.json`, so a scan only reads what
was appended since the last one. The per-minute lifecycle reap calls
`maybe_scan` (at most every SCAN_EVERY_SECONDS); `scan --dry-run` prints the
current totals without notifying.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

PROJECT_DIR = Path.home() / ".claude" / "projects" / "-home-superdev-projects-OpenMates"
TOKEN_NOTICE_UNITS = 100_000_000
AGENT_NOTICE_COUNT = 40
ACTIVE_WITHIN_SECONDS = 24 * 3600
SCAN_EVERY_SECONDS = 600
WEBHOOK_KEYS = ("DISCORD_WEBHOOK_DEV_NIGHTLY", "DISCORD_WEBHOOK_DAILY_MEETING")


def canonical_root() -> Path:
    """The main checkout, also when this runs from a linked worktree."""
    here = Path(__file__).resolve().parents[1]
    try:
        common = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                                cwd=here, capture_output=True, text=True, check=True, timeout=30).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return here
    return Path(common).parent if common else here


def state_path() -> Path:
    override = os.environ.get("OPENMATES_USAGE_WATCH_FILE")
    return Path(override) if override else canonical_root() / "logs" / "claude-chat-lifecycle" / "usage-watch.json"


def load_state(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"files": {}, "notified": {}, "last_scan": 0}
    data.setdefault("files", {}), data.setdefault("notified", {}), data.setdefault("last_scan", 0)
    return data


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state), encoding="utf-8")
    tmp.replace(path)


def record_units(record: dict) -> float:
    """Weighted tokens of one transcript record (0 when it carries no usage)."""
    message = record.get("message")
    usage = message.get("usage") if isinstance(message, dict) else None
    if not isinstance(usage, dict):
        return 0.0
    return (usage.get("input_tokens", 0) + usage.get("cache_creation_input_tokens", 0)
            + 0.1 * usage.get("cache_read_input_tokens", 0) + 5 * usage.get("output_tokens", 0))


def read_new(path: Path, entry: dict) -> dict:
    """Add the usage appended to `path` since `entry['offset']`; complete lines only."""
    offset, units = int(entry.get("offset", 0)), float(entry.get("units", 0.0))
    try:
        size = path.stat().st_size
    except OSError:
        return {"offset": offset, "units": units}
    if size < offset:  # rewritten file: count it again from the start
        offset, units = 0, 0.0
    with path.open("rb") as handle:
        handle.seek(offset)
        chunk = handle.read()
    end = chunk.rfind(b"\n") + 1
    for line in chunk[:end].splitlines():
        if b'"usage"' not in line:
            continue
        try:
            units += record_units(json.loads(line))
        except ValueError:
            continue
    return {"offset": offset + end, "units": units}


def scan(project_dir: Path, state: dict, now: float) -> dict[str, dict]:
    """Per active chat: {'units', 'agents'}; updates the per-file offsets in `state`."""
    totals: dict[str, dict] = {}
    files = state["files"]
    for transcript in project_dir.glob("*.jsonl"):
        try:
            if now - transcript.stat().st_mtime > ACTIVE_WITHIN_SECONDS:
                continue
        except OSError:
            continue
        chat = transcript.stem
        agents = sorted((project_dir / chat / "subagents").glob("agent-*.jsonl"))
        units = 0.0
        for path in [transcript, *agents]:
            files[str(path)] = read_new(path, files.get(str(path), {}))
            units += files[str(path)]["units"]
        totals[chat] = {"units": units, "agents": len(agents)}
    return totals


def notices(totals: dict[str, dict], notified: dict, now: float) -> list[tuple[str, str]]:
    """(chat, text) for each chat that crossed a threshold and was not told about yet."""
    out = []
    for chat, total in sorted(totals.items()):
        if chat in notified:
            continue
        reasons = []
        if total["units"] >= TOKEN_NOTICE_UNITS:
            reasons.append(f"{total['units'] / 1e6:.0f}M weighted tokens")
        if total["agents"] >= AGENT_NOTICE_COUNT:
            reasons.append(f"{total['agents']} sub-agents")
        if reasons:
            notified[chat] = now
            out.append((chat, f"Chat {chat[:8]} uses unusually much: {' and '.join(reasons)}. "
                              f"Nothing was stopped. Look: python3 scripts/agent_peers.py history {chat}"))
    return out


def send(text: str) -> bool:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import agent_question  # noqa: E402  (sibling script)
    import discord_webhook  # noqa: E402  (sibling script)

    root = canonical_root()
    url = next((value for key in WEBHOOK_KEYS if (value := agent_question.configured_value(root, key))), "")
    return bool(url) and bool(discord_webhook.post_message(webhook_url=url, payload={"content": text}))


def run(now: float, *, dry_run: bool = False, project_dir: Path = PROJECT_DIR, post=send) -> list[str]:
    path = state_path()
    state = load_state(path)
    totals = scan(project_dir, state, now)
    if dry_run:
        return [f"{chat[:8]} {t['units'] / 1e6:7.1f}M {t['agents']:4d} agents"
                for chat, t in sorted(totals.items(), key=lambda kv: -kv[1]["units"])]
    found = notices(totals, state["notified"], now)
    sent = []
    if found:  # one Discord message per scan, however many chats crossed
        ok = post("\n".join(text for _, text in found))
        sent = [f"{chat[:8]} notified={ok}" for chat, _ in found]
    state["last_scan"] = now
    save_state(path, state)
    return sent


def maybe_scan(now: float | None = None, *, spawn=None) -> bool:
    """The reap entry point: start a detached scan when one is due; never waits for it."""
    now = time.time() if now is None else now
    path = state_path()
    state = load_state(path)
    if now - max(float(state.get("last_scan", 0)), float(state.get("last_started", 0))) < SCAN_EVERY_SECONDS:
        return False
    state["last_started"] = now
    save_state(path, state)
    command = [sys.executable, str(Path(__file__).resolve()), "scan"]
    (spawn or (lambda cmd: subprocess.Popen(cmd, start_new_session=True, stdout=subprocess.DEVNULL,
                                            stderr=subprocess.DEVNULL)))(command)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    scan_parser = sub.add_parser("scan", help="scan active chats and notify the owner once per chat")
    scan_parser.add_argument("--dry-run", action="store_true", help="print totals, notify nobody")
    args = parser.parse_args(argv)
    for line in run(time.time(), dry_run=args.dry_run):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
