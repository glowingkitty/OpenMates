#!/usr/bin/env python3
"""One owner notice when a Claude or Codex chat uses unusually many sub-agents or tokens.

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

The notice names each chat by its title in plain words (its sessions.py task, else
its first prompt) and says whether it already handed off to a fresh chat (owner,
23 Nov). Chats over TOKEN_NOTICE_UNITS are listed under `oversized` in the state
file; scripts/chat_compaction_handoff.py tells such a chat to hand off now.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import codex_chats

PROJECT_DIR = Path.home() / ".claude" / "projects" / "-home-superdev-projects-OpenMates"
TOKEN_NOTICE_UNITS = 100_000_000
AGENT_NOTICE_COUNT = 40
TITLE_CHARS = 80
HANDOFF_AFTER_COMPACTIONS = 2  # chat_compaction_handoff.HANDOFF_AT
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
        return {"files": {}, "notified": {}, "oversized": {}, "last_scan": 0}
    for key, empty in (("files", {}), ("notified", {}), ("oversized", {}), ("last_scan", 0)):
        data.setdefault(key, empty)
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


def scan_codex(state: dict, now: float) -> dict[str, dict]:
    totals = {}
    files = state["files"]
    for record in codex_chats.records():
        path = codex_chats.rollout_path(record.get("thread_id") or "")
        if path is None:
            continue
        try:
            if now - path.stat().st_mtime > ACTIVE_WITHIN_SECONDS:
                continue
            metrics = codex_chats.rollout_metrics(path, files.get(str(path)))
        except OSError:
            continue
        files[str(path)] = metrics
        totals[record["chat_id"]] = {
            "units": metrics.get("units", 0), "agents": 0, "title": record.get("title", ""),
            "compactions": metrics.get("compactions", 0),
        }
    return totals


def _load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _transcript_title(transcript: Path) -> tuple[str, str]:
    title = first_prompt = ""
    try:
        with transcript.open(encoding="utf-8", errors="replace") as handle:
            for _, line in zip(range(400), handle):
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if record.get("type") == "custom-title" and record.get("customTitle"):
                    title = str(record["customTitle"])
                content = (record.get("message") or {}).get("content") if record.get("type") == "user" else None
                if isinstance(content, list):
                    content = " ".join(b.get("text", "") for b in content if isinstance(b, dict))
                if isinstance(content, str) and content.strip() and not content.lstrip().startswith("<"):
                    first_prompt = first_prompt or content
    except OSError:
        pass
    return title, first_prompt


def chat_title(chat: str, root: Path, project_dir: Path, title: str = "") -> str:
    """The chat in plain words: its sessions.py task text, else its first prompt, else ''."""
    sessions = _load(root / ".claude" / "sessions.json").get("sessions") or {}
    text = next((str(info.get("task") or "") for info in sessions.values()
                 if isinstance(info, dict) and info.get("agent_task_id") == chat and info.get("task")), "")
    transcript_title, first_prompt = _transcript_title(project_dir / f"{chat}.jsonl") if not title else ("", "")
    text = " ".join((title or transcript_title or text or first_prompt).split())
    return text if len(text) <= TITLE_CHARS else text[:TITLE_CHARS - 1].rstrip() + "…"


def handoff_state(chat: str, root: Path, units: float, compactions: int = 0) -> str:
    """Whether the chat already handed off to a fresh chat (scripts/chat_compaction_handoff.py)."""
    lifecycle = root / "logs" / "claude-chat-lifecycle"
    if chat in _load(lifecycle / "handed_off.json"):
        return "It already handed off to a fresh chat."
    count = int(_load(lifecycle / "compactions.json").get(chat, 0) or 0)
    count = max(count, compactions)
    if count >= HANDOFF_AFTER_COMPACTIONS or units >= TOKEN_NOTICE_UNITS:
        return "No handoff yet; it is told to hand off to a fresh chat now."
    return f"No handoff yet (compacted {count} times, handoff after {HANDOFF_AFTER_COMPACTIONS})."


def notices(totals: dict[str, dict], notified: dict, now: float, *, root: Path | None = None,
            project_dir: Path = PROJECT_DIR) -> list[tuple[str, str]]:
    """(chat, text) for each chat that crossed a threshold and was not told about yet."""
    root = root or canonical_root()
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
            title = chat_title(chat, root, project_dir, total.get("title") or "")
            name = f"\"{title}\"" if title else "Untitled work chat"
            out.append((chat, f"{name} uses unusually much: {' and '.join(reasons)}. "
                              f"{handoff_state(chat, root, total['units'], total.get('compactions', 0))}"))
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
    totals.update(scan_codex(state, now))
    if dry_run:
        return [f"{chat[:8]} {t['units'] / 1e6:7.1f}M {t['agents']:4d} agents"
                for chat, t in sorted(totals.items(), key=lambda kv: -kv[1]["units"])]
    state["oversized"] = {chat: round(t["units"]) for chat, t in totals.items() if t["units"] >= TOKEN_NOTICE_UNITS}
    found = notices(totals, state["notified"], now, project_dir=project_dir)
    sent = []
    if found:  # one Discord message per scan, however many chats crossed
        ok = post("\n".join(text for _, text in found))
        sent = [f"{chat[:8]} notified={ok}" for chat, _ in found]
        if not ok:
            for chat, _ in found:
                state["notified"].pop(chat, None)
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
