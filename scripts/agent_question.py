#!/usr/bin/env python3
"""Send one compact Discord message when a chat is blocked on a decision only the user can make.

Usage: agent_question.py ask --question "..." [--recommendation "..."] [--option "..."]...
                             [--task TASK-id] [--dry-run] [--force]

The webhook URL comes from DISCORD_WEBHOOK_AGENT_QUESTIONS, then DISCORD_WEBHOOK_DAILY_MEETING,
then DISCORD_WEBHOOK_DEV_NIGHTLY (environment, then the canonical checkout's ``.env``, the same
lookup as scripts/daily_meeting_briefing.py). The URL is never printed or logged. One message per
chat per 20 minutes unless ``--force``. A success marker
``logs/claude-idle-chats/questions/<chat-id>.json`` tells scripts/claude_idle_nudge.py that the
chat already asked. Failures exit non-zero with a message; there is no silent fallback.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Callable

import discord_webhook
from pending_work_gate import canonical_root

WEBHOOK_KEYS = ("DISCORD_WEBHOOK_AGENT_QUESTIONS", "DISCORD_WEBHOOK_DAILY_MEETING",
                "DISCORD_WEBHOOK_DEV_NIGHTLY")
RATE_LIMIT_SECONDS = 20 * 60
MAX_CHARS = 1800
SECRET_PATTERNS = (
    re.compile(r"https?://discord(?:app)?\.com/api/webhooks/\S+"),
    re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),
    re.compile(r"\b(?:sk|pk|ghp|gho|xox[abp])[-_][A-Za-z0-9_-]{16,}"),
    re.compile(r"\b[A-Z][A-Z0-9_]{3,}=\S+"),
    re.compile(r"\b[A-Za-z0-9_-]{32,}\b"),
)


class QuestionError(RuntimeError):
    """Delivery or configuration failure that must reach the caller."""


def configured_value(root: Path, key: str) -> str:
    """Environment first, then the checkout's .env (mirrors daily_meeting_briefing)."""
    if os.environ.get(key):
        return os.environ[key]
    env = root / ".env"
    if env.is_file():
        for line in env.read_text().splitlines():
            name, sep, value = line.strip().partition("=")
            if sep and name.strip() == key:
                return value.strip().strip("'\"")
    return ""


def webhook(root: Path) -> str:
    for key in WEBHOOK_KEYS:
        url = configured_value(root, key)
        if url:
            return url
    raise QuestionError("no Discord webhook configured (" + ", ".join(WEBHOOK_KEYS) + ")")


def scrub(text: str) -> str:
    for pattern in SECRET_PATTERNS:
        text = pattern.sub("[removed]", text)
    return " ".join(text.split())


def session_info(root: Path, chat_id: str) -> tuple[str, str]:
    """(sessions.py session id, task text) of the chat's newest session; ('', '') if none."""
    try:
        data = json.loads((root / ".claude" / "sessions.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "", ""
    matches = [(info.get("last_active") or "", key, info.get("task") or "")
               for key, info in (data.get("sessions") or {}).items()
               if chat_id and (info.get("agent_task_id") or info.get("codex_task_id")) == chat_id]
    if not matches:
        return "", ""
    _, key, task = max(matches)
    return key, task


def build_message(question: str, recommendation: str, options: list[str], task_id: str,
                  session_id: str, title: str) -> str:
    lines = [f"Question from Claude chat: {scrub(title) or 'unnamed chat'}", "",
             scrub(question)]
    if recommendation:
        lines += ["", f"Recommendation: {scrub(recommendation)}"]
    if options:
        lines += ["", "Options:"] + [f"{number}. {scrub(option)}" for number, option in enumerate(options, 1)]
    meta = [f"Task: {task_id}" if task_id else "", f"Session: {session_id}" if session_id else ""]
    meta_line = " | ".join(part for part in meta if part)
    if meta_line:
        lines += ["", scrub(meta_line)]
    text = "\n".join(lines)
    return text if len(text) <= MAX_CHARS else text[:MAX_CHARS - 3] + "..."


def marker_path(root: Path, chat_id: str) -> Path:
    return root / "logs" / "claude-idle-chats" / "questions" / f"{chat_id}.json"


def recently_asked(root: Path, chat_id: str, now: float) -> bool:
    try:
        recorded = json.loads(marker_path(root, chat_id).read_text(encoding="utf-8"))
        return now - float(recorded.get("ts", 0)) < RATE_LIMIT_SECONDS
    except (OSError, ValueError, AttributeError):
        return False


def ask(args: argparse.Namespace, root: Path, chat_id: str, now: float,
        post: Callable[..., dict | None] = discord_webhook.post_message) -> str:
    """Send (or, with --dry-run, build) the message; returns the message text."""
    session_id, task_text = session_info(root, chat_id)
    message = build_message(args.question, args.recommendation or "", args.option or [],
                            args.task or "", session_id, os.environ.get("CLAUDE_CHAT_TITLE") or task_text)
    if args.dry_run:
        return message
    if not chat_id:
        raise QuestionError("CLAUDE_CODE_SESSION_ID is not set; cannot identify this chat")
    if not args.force and recently_asked(root, chat_id, now):
        raise QuestionError("this chat already sent a question in the last 20 minutes (use --force)")
    result = post(webhook_url=webhook(root), payload={"content": message})
    if not result:
        raise QuestionError("Discord delivery was not confirmed")
    path = marker_path(root, chat_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"ts": now, "question": scrub(args.question)}), encoding="utf-8")
    return message


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    ask_parser = sub.add_parser("ask", help="send one question to Discord")
    ask_parser.add_argument("--question", required=True)
    ask_parser.add_argument("--recommendation")
    ask_parser.add_argument("--option", action="append")
    ask_parser.add_argument("--task")
    ask_parser.add_argument("--dry-run", action="store_true")
    ask_parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    try:
        message = ask(args, canonical_root(), os.environ.get("CLAUDE_CODE_SESSION_ID", ""), time.time())
    except QuestionError as error:
        print(f"agent_question: {error}", file=sys.stderr)
        return 1
    print(message if args.dry_run else "Question sent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
