#!/usr/bin/env python3
"""Send one compact Discord message when a chat is blocked on a decision only the user can make.

Usage: agent_question.py ask --question "..." [--recommendation "..."] [--option "..."]...
                             [--task TASK-id] [--dry-run] [--force]

The webhook URL comes from DISCORD_WEBHOOK_AGENT_QUESTIONS, then DISCORD_WEBHOOK_DAILY_MEETING,
then DISCORD_WEBHOOK_DEV_NIGHTLY (environment, then the canonical checkout's ``.env``, the same
lookup as scripts/daily_meeting_briefing.py). The URL is never printed or logged. One message per
chat per 20 minutes unless ``--force``. A success marker
``logs/claude-idle-chats/questions/<chat-id>.json`` tells scripts/claude_idle_nudge.py that the
chat already asked. Every confirmed push (also other scripts' pushes through ``record_push``) is
appended to ``logs/agent-questions/pushes.jsonl`` (time, chat id and title, the text, what it asks),
so the dev connector can look a push up by time and open its chat. An unconfirmed delivery (network error, Discord 429/5xx) is retried twice
after 2 and 5 seconds, because this push is how the user learns a chat needs a decision. Failures
that remain exit non-zero with a message; there is no silent fallback.
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
from urllib.parse import urlparse

import discord_webhook
from pending_work_gate import canonical_root

WEBHOOK_KEYS = ("DISCORD_WEBHOOK_AGENT_QUESTIONS", "DISCORD_WEBHOOK_DAILY_MEETING",
                "DISCORD_WEBHOOK_DEV_NIGHTLY")
RATE_LIMIT_SECONDS = 20 * 60
PUSH_LOG = Path("logs") / "agent-questions" / "pushes.jsonl"
RETRY_DELAYS = (2.0, 5.0)
MAX_CHARS = 1900  # per Discord message (limit 2000); longer pushes go out as several parts
MAX_PARTS = 4
# Presigned links to our own buckets on our object storage are meant to be opened and are kept
# whole (bucket name, key path and X-Amz-* query values). Every other URL goes through the filters.
OWN_STORAGE_HOST_SUFFIX = ".your-objectstorage.com"
OWN_BUCKET_PREFIXES = ("openmates-", "dev-openmates-")
_URL = re.compile(r"https?://[^\s<>\"')\]]+")
_PROTECTED = re.compile("\x00(\\d+)\x00")
SECRET_PATTERNS = (
    re.compile(r"https?://(?:canary\.|ptb\.)?discord(?:app)?\.com/api/webhooks/\S+"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)", re.S),
    re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),
    re.compile(r"\beyJ[\w-]{5,}\.[\w-]{5,}\.[\w-]{5,}"),
    re.compile(r"(?i)\bbearer\s+[\w.~+/=-]{12,}"),
    re.compile(r"\b(?:sk|pk|rk|ghp|gho|ghu|ghs|ghr|github_pat|glpat|xox[abprs])[-_][A-Za-z0-9_-]{16,}"),
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b|\bAIza[0-9A-Za-z_-]{30,}"),
)
# NAME=value: the name stays readable, the value is removed.
# Placeholders such as NAME=... or NAME=<value> are instructions, not values, and stay.
_ASSIGNMENT = re.compile(r"\b([A-Z][A-Z0-9_]{3,})=(?!\[removed\]|\.{3}(?![^\s\x00])|<[^>\s]*>(?![^\s\x00]))[^\s\x00]+")
# OpenSSH public keys are public by design (people are asked to paste them) and stay whole.
_SSH_PUBLIC_KEY = re.compile(r"\b(?:ssh-(?:ed25519|rsa)|ecdsa-sha2-nistp(?:256|384|521)|sk-ssh-ed25519@openssh\.com) AAAA[A-Za-z0-9+/]{16,}={0,3}")
_LONG_TOKEN = re.compile(r"(?<![\w-])[A-Za-z0-9_-]{32,}(?![\w-])")
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_GIT_OR_SHA256 = re.compile(r"(?:sha-)?(?:[0-9a-f]{40}|[0-9a-f]{64})")  # sha-<commit> image tags too
_WORDS = re.compile(r"(?:[a-z0-9]{1,20}(?:[_-]+[a-z0-9]{1,20})+|[A-Z0-9]{1,20}(?:[_-]+[A-Z0-9]{1,20})+)")


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


def own_storage_link(url: str) -> bool:
    """True for an https link to one of our buckets on our object storage (path or virtual-host style)."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or "@" in url or not host.endswith(OWN_STORAGE_HOST_SUFFIX):
        return False
    labels = host[: -len(OWN_STORAGE_HOST_SUFFIX)].split(".")
    bucket = labels[0] if len(labels) == 2 else parsed.path.lstrip("/").split("/", 1)[0]
    return bucket.startswith(OWN_BUCKET_PREFIXES)


def _keep_or_remove_long_token(match: re.Match[str]) -> str:
    """Ids, digests and word-like names stay; random-looking long tokens (keys, signatures) go."""
    token = match.group(0)
    if _UUID.fullmatch(token) or _GIT_OR_SHA256.fullmatch(token) or _WORDS.fullmatch(token):
        return token
    return "[removed]"


def scrub(text: str) -> str:
    """Remove secrets and personal data from push text; keep ids, hashes and our media links readable.

    Removed: Discord webhook URLs, private keys, emails, JWTs, bearer tokens, prefixed API keys, the
    values of NAME=value assignments and other long random tokens. Kept: Task/chat UUIDs, 40/64-char
    hex commit hashes and digests (also sha-<commit> image tags), ENV_VAR / snake_case / kebab-case
    names, NAME=... placeholders, OpenSSH public keys and presigned links to our own storage
    buckets (see own_storage_link)."""
    kept: list[str] = []

    def protect(match: re.Match[str]) -> str:
        url = match.group(0)
        if not own_storage_link(url):
            return url
        kept.append(url)
        return f"\x00{len(kept) - 1}\x00"

    text = _URL.sub(protect, text.replace("\x00", ""))
    text = _SSH_PUBLIC_KEY.sub(lambda m: (kept.append(m.group(0)), f"\x00{len(kept) - 1}\x00")[1], text)
    for pattern in SECRET_PATTERNS:
        text = pattern.sub("[removed]", text)
    text = _ASSIGNMENT.sub(lambda m: f"{m.group(1)}=[removed]", text)
    text = _LONG_TOKEN.sub(_keep_or_remove_long_token, text)
    text = _PROTECTED.sub(lambda m: kept[int(m.group(1))], text)
    return " ".join(text.split())


def split_message(text: str, size: int = MAX_CHARS) -> list[str]:
    """Split at line or word boundaries into parts of at most ``size`` characters (links stay whole)."""
    parts: list[str] = []
    while len(text) > size:
        cut = max(text.rfind("\n", 0, size + 1), text.rfind(" ", 0, size + 1))
        if cut <= 0:
            cut = size
        parts.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    if text or not parts:
        parts.append(text)
    return parts


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
    limit = MAX_CHARS * MAX_PARTS
    if len(text) <= limit:
        return text
    cut = max(text.rfind("\n", 0, limit - 3), text.rfind(" ", 0, limit - 3))
    return text[:cut if cut > 0 else limit - 3].rstrip() + "..."


def marker_path(root: Path, chat_id: str) -> Path:
    return root / "logs" / "claude-idle-chats" / "questions" / f"{chat_id}.json"


def recently_asked(root: Path, chat_id: str, now: float) -> bool:
    try:
        recorded = json.loads(marker_path(root, chat_id).read_text(encoding="utf-8"))
        return now - float(recorded.get("ts", 0)) < RATE_LIMIT_SECONDS
    except (OSError, ValueError, AttributeError):
        return False


def deliver(url: str, message: str, post: Callable[..., dict | None],
            sleep: Callable[[float], None] = time.sleep) -> dict:
    """Post each part of the message (split_message), retrying each after the RETRY_DELAYS entries.

    Returns the last confirmed result; raises QuestionError when a part stays unconfirmed."""
    result: dict | None = None
    for part in split_message(message):
        for delay in (*RETRY_DELAYS, None):
            result = post(webhook_url=url, payload={"content": part})
            if result:
                break
            if delay is not None:
                sleep(delay)
        else:
            raise QuestionError(f"Discord delivery was not confirmed after {len(RETRY_DELAYS) + 1} attempts")
    return result or {}

def record_push(root: Path, message: str, now: float, *, chat_id: str = "", title: str = "", asks: str = "",
                recommendation: str = "", options: list[str] | None = None, task_id: str = "",
                source: str = "agent_question") -> Path:
    """Append one delivered push to the push log (one JSON object per line); returns the log path."""
    first = next((line for line in message.splitlines()[1:] if line.strip()), message)
    entry = {"ts": now, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)), "source": source,
             "chat_id": chat_id, "title": scrub(title), "asks": scrub(asks or first),
             "recommendation": scrub(recommendation), "options": [scrub(o) for o in options or []],
             "task": scrub(task_id), "text": message}
    path = root / PUSH_LOG
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return path

def ask(args: argparse.Namespace, root: Path, chat_id: str, now: float,
        post: Callable[..., dict | None] = discord_webhook.post_message,
        sleep: Callable[[float], None] = time.sleep) -> str:
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
    deliver(webhook(root), message, post, sleep)
    record_push(root, message, now, chat_id=chat_id,
                title=os.environ.get("CLAUDE_CHAT_TITLE") or task_text, asks=args.question,
                recommendation=args.recommendation or "", options=args.option or [], task_id=args.task or "")
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
