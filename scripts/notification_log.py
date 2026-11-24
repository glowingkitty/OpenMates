#!/usr/bin/env python3
"""Private log of every Discord notification the dev server sends.

Every sender (agent pushes, usage and token warnings, security alerts, production
incident and post-update checks, AI test user summaries, deploy and CI alerts, cron
jobs) records through ``record`` / ``record_request`` when Discord accepts the message. One entry
holds the time, source, kind, the full text as sent (secrets redacted), the linked
chats and copies of attachments. Entries and attachment copies are kept for 14 days.

The store lives outside the repository (``~/.openmates/notifications`` unless
``OPENMATES_NOTIFICATION_DIR`` is set). The dev connector reads it through
``list_notifications`` / ``read_notification`` or the CLI::

    python3 scripts/notification_log.py list [--since 6h] [--kind alert] [--chat 4b5c74d7] --json
    python3 scripts/notification_log.py read <id> --json
"""

from __future__ import annotations

import argparse
import base64
import email
import email.policy
import fcntl
import hashlib
import json
import os
import re
import secrets
import shutil
import sys
import time
import urllib.request
from urllib.parse import urlsplit
from datetime import datetime, timezone
from contextvars import ContextVar
from contextlib import contextmanager
from pathlib import Path
from typing import Any

SENDING_CHAT: ContextVar[tuple[str, str]] = ContextVar("notification_sending_chat", default=("", ""))

RETENTION_SECONDS = 14 * 24 * 3600
PRUNE_INTERVAL_SECONDS = 3600
LOG_NAME = "notifications.jsonl"
ATTACHMENT_DIR = "attachments"
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024
TEXT_SUFFIXES = {".txt", ".log", ".json", ".md", ".yml", ".yaml", ".csv", ".html"}
DISCORD_HOSTS = {"discord.com", "discordapp.com", "canary.discord.com", "ptb.discord.com"}
CHAT_MENTION_RE = re.compile(r"\bchats?\s+([0-9a-f]{8})\b", re.IGNORECASE)
SECRET_PATTERNS = (
    re.compile(r"https?://(?:[\w.-]+\.)?discord(?:app)?\.com/api/webhooks/\S+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"(?i)\b((?:api[_-]?key|token|secret|password|passwd)\s*[=:]\s*)\S{6,}"),
)


@contextmanager
def sending_chat(chat_id: str, title: str):
    """Attribute outgoing pushes to the chat that asked, including queue flushes."""
    token = SENDING_CHAT.set((chat_id, title))
    try:
        yield
    finally:
        SENDING_CHAT.reset(token)


def store_dir() -> Path:
    override = os.environ.get("OPENMATES_NOTIFICATION_DIR")
    return Path(override) if override else Path.home() / ".openmates" / "notifications"


def redact(text: str) -> str:
    """Replace secrets (webhook URLs, API keys, tokens, bearer headers) with a marker."""
    for pattern in SECRET_PATTERNS:
        if pattern.groups:
            text = pattern.sub(lambda m: f"{m.group(1)}[redacted]", text)
        else:
            text = pattern.sub("[redacted]", text)
    return text


def derive_kind(text: str, source: str) -> str:
    """done / ask for agent pushes (✅/❓), otherwise alert, report or other by source and text."""
    head = text.lstrip()[:2]
    if head.startswith("✅"):
        return "done"
    if head.startswith("❓"):
        return "ask"
    lowered = f"{source} {text[:200]}".lower()
    if any(word in lowered for word in ("security", "cve", "vulnerab")):
        return "security"
    if any(word in lowered for word in ("token", "usage", "credits", "sub-agent")):
        return "usage"
    if any(word in lowered for word in ("alert", "failed", "failure", "down", "unreachable", "degraded", "🚨", "⚠")):
        return "alert"
    if source in {"run_tests", "daily_ci_notification"} or "test users" in lowered:
        return "test"
    return "report"


def linked_chats(text: str, explicit: list[str] | None = None) -> list[str]:
    """Chat ids (8-char prefixes) from the explicit list, the running chat and chat mentions."""
    found: list[str] = []
    session = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    for candidate in [*(explicit or []), session]:
        if candidate and not any(c[:8] == candidate[:8] for c in found):
            found.append(candidate)
    for match in CHAT_MENTION_RE.finditer(text):
        if not any(c[:8] == match.group(1).lower() for c in found):
            found.append(match.group(1).lower())
    return found


def _locked(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    handle = os.fdopen(fd, "a+", encoding="utf-8")
    fcntl.flock(handle, fcntl.LOCK_EX)
    return handle


def _save_attachment(root: Path, entry_id: str, name: str, content: bytes) -> dict[str, Any]:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", Path(name).name).strip(".") or "file"
    directory = root / ATTACHMENT_DIR / entry_id
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if len(content) > MAX_ATTACHMENT_BYTES:
        return {"name": safe, "size": len(content), "path": "", "note": "too large, not kept"}
    if Path(safe).suffix.lower() in TEXT_SUFFIXES:
        content = redact(content.decode("utf-8", "replace")).encode("utf-8")
    target = directory / safe
    while target.exists():
        target = directory / f"{secrets.token_hex(3)}-{safe}"
    with os.fdopen(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as handle:
        handle.write(content)
    return {"name": safe, "size": len(content), "path": f"{ATTACHMENT_DIR}/{entry_id}/{target.name}"}


def record(source: str, text: str, *, kind: str = "", chats: list[str] | None = None,
           attachments: list[tuple[str, bytes]] | None = None, destination: str = "",
           delivered: bool | None = None, now: float | None = None, root: Path | None = None,
           chat_id: str = "", title: str = "", entry_id: str = "",
           attachment_metadata: list[dict] | None = None) -> str:
    """Save one notification; returns its id. Never raises into a sender: failures go to stderr."""
    try:
        return _record(source, text, kind=kind, chats=chats, attachments=attachments,
                       destination=destination, delivered=delivered, now=now, root=root,
                       chat_id=chat_id, title=title, entry_id=entry_id, attachment_metadata=attachment_metadata)
    except (OSError, ValueError) as error:
        print(f"[notification_log] could not record {source}: {error}", file=sys.stderr)
        return ""


def _record(source: str, text: str, *, kind: str, chats: list[str] | None, attachments: list[tuple[str, bytes]] | None,
            destination: str, delivered: bool | None, now: float | None, root: Path | None,
            chat_id: str, title: str, entry_id: str, attachment_metadata: list[dict] | None) -> str:
    root = root or store_dir()
    ts = now if now is not None else time.time()
    stable_id = bool(entry_id)
    entry_id = entry_id or f"n{int(ts)}{secrets.token_hex(8)}"
    if not re.fullmatch(r"[a-z0-9]+", entry_id):
        raise ValueError("invalid notification ID")
    origin_chat, origin_title = SENDING_CHAT.get()
    chat_id = chat_id or origin_chat or os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    title = title or origin_title
    text = redact(text)
    entry = {
        "id": entry_id, "ts": ts, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts)),
        "source": source, "kind": kind or derive_kind(text, source), "text": text,
        "chat_id": chat_id, "title": redact(title), "chats": linked_chats(text, [chat_id, *(chats or [])]),
        "destination": destination,
        "delivered": delivered,
    }
    handle = _locked(root / LOG_NAME)
    try:
        if stable_id:
            handle.seek(0)
            if any(row.get("id") == entry_id for row in _decode_lines(handle)):
                return entry_id
        entry["attachments"] = [
            *(_save_attachment(root, entry_id, name, content) for name, content in attachments or []),
            *(attachment_metadata or []),
        ]
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        handle.flush()
    finally:
        handle.close()
    _prune_if_due(root, time.time())
    return entry_id


def _decode_lines(lines):
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            yield row


def _source_from_argv() -> str:
    return Path(sys.argv[0]).stem if sys.argv and sys.argv[0] else "unknown"


def _flatten_payload(payload: dict[str, Any]) -> str:
    parts = [str(payload.get("content") or "")]
    for embed in payload.get("embeds") or []:
        if not isinstance(embed, dict):
            continue
        parts.append(str(embed.get("title") or ""))
        parts.append(str(embed.get("description") or ""))
        for field in embed.get("fields") or []:
            parts.append(f"{field.get('name', '')}: {field.get('value', '')}")
        footer = embed.get("footer")
        if isinstance(footer, dict):
            parts.append(str(footer.get("text") or ""))
    return "\n".join(part for part in parts if part)


def parse_request(request: urllib.request.Request) -> tuple[str, list[tuple[str, bytes]]] | None:
    """Text and files of a Discord webhook request (JSON or multipart); None for other URLs."""
    url = request.full_url if hasattr(request, "full_url") else str(request)
    destination = urlsplit(url)
    if destination.hostname not in DISCORD_HOSTS or not re.match(r"/api/(?:v\d+/)?webhooks/", destination.path):
        return None
    body = request.data or b""
    content_type = request.get_header("Content-type") or ""
    if isinstance(body, str):
        body = body.encode("utf-8")
    if content_type.startswith("multipart/"):
        message = email.message_from_bytes(f"Content-Type: {content_type}\r\n\r\n".encode() + body, policy=email.policy.HTTP)
        text, files = "", []
        for part in message.iter_parts():
            payload = part.get_payload(decode=True) or b""
            if part.get_filename():
                files.append((part.get_filename(), payload))
            elif part.get_param("name", header="content-disposition") == "payload_json":
                try:
                    text = _flatten_payload(json.loads(payload.decode("utf-8")))
                except (ValueError, UnicodeDecodeError):
                    text = payload.decode("utf-8", "replace")
        return text, files
    try:
        return _flatten_payload(json.loads(body.decode("utf-8"))), []
    except (ValueError, UnicodeDecodeError):
        return body.decode("utf-8", "replace"), []


def record_request(request: urllib.request.Request, source: str = "", *, kind: str = "",
                   chats: list[str] | None = None) -> str:
    """Record a urllib request after a Discord webhook accepts it."""
    parsed = parse_request(request)
    if parsed is None:
        return ""
    text, files = parsed
    return record(source or _source_from_argv(), text, kind=kind, chats=chats, attachments=files, destination="discord", delivered=True)


def record_post(source: str, payload: dict[str, Any], files: list[tuple[str, bytes]] | None = None, *,
                kind: str = "", chats: list[str] | None = None,
                chat_id: str = "", title: str = "") -> str:
    """Record a payload (plus files) that Discord accepted."""
    return record(source or _source_from_argv(), _flatten_payload(payload), kind=kind, chats=chats,
                  attachments=files, destination="discord", delivered=True,
                  chat_id=chat_id, title=title)


def ingest_spool(root: Path | None = None) -> int:
    """Move notifications the backend containers spooled (backend/shared/python_utils/notification_spool.py)
    into the log; returns how many were ingested. Unreadable spool files are left in place."""
    root = root or store_dir()
    spool = root / "spool"
    if not spool.is_dir():
        return 0
    count = 0
    for path in sorted(spool.glob("*.json")):
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
            files = [(f["name"], base64.b64decode(f["b64"])) for f in item.get("files", [])]
        except (OSError, ValueError, KeyError):
            continue
        entry_id = "s" + hashlib.sha256(path.name.encode()).hexdigest()
        if record(str(item.get("source") or "backend"), str(item.get("text") or ""), attachments=files,
                  destination="discord", delivered=True, now=float(item.get("ts") or time.time()),
                  root=root, entry_id=entry_id):
            path.unlink(missing_ok=True)
            count += 1
    return count


def _read_entries(root: Path) -> list[dict[str, Any]]:
    ingest_spool(root)
    path = root / LOG_NAME
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_SH)
        return list(_decode_lines(handle))


def _prune_if_due(root: Path, now: float) -> None:
    marker = root / ".last_prune"
    if marker.exists() and now - marker.stat().st_mtime < PRUNE_INTERVAL_SECONDS:
        return
    prune(root=root, now=now)
    marker.touch()


def prune(*, root: Path | None = None, now: float | None = None) -> int:
    """Drop entries and attachment copies older than 14 days; returns the number removed."""
    root = root or store_dir()
    cutoff = (now if now is not None else time.time()) - RETENTION_SECONDS
    path = root / LOG_NAME
    if not path.exists():
        return 0
    handle = _locked(path)
    removed = 0
    try:
        handle.seek(0)
        kept = []
        for line in handle.read().splitlines():
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if float(entry.get("ts", 0)) < cutoff:
                removed += 1
                shutil.rmtree(root / ATTACHMENT_DIR / str(entry.get("id", "x")), ignore_errors=True)
            else:
                kept.append(line)
        handle.seek(0)
        handle.truncate()
        handle.write("".join(f"{line}\n" for line in kept))
    finally:
        handle.close()
    return removed


def parse_since(value: str, now: float | None = None) -> float:
    """'90m', '6h', '2d' (relative to now), an ISO timestamp or epoch seconds."""
    now = now if now is not None else time.time()
    match = re.fullmatch(r"(\d+)([mhd])", value.strip())
    if match:
        return now - int(match.group(1)) * {"m": 60, "h": 3600, "d": 86400}[match.group(2)]
    try:
        return float(value)
    except ValueError:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return stamp.replace(tzinfo=stamp.tzinfo or timezone.utc).timestamp()


def list_notifications(*, since: float | None = None, until: float | None = None, kind: str = "", source: str = "",
                       chat: str = "", text: str = "", limit: int = 50, root: Path | None = None,
                       unanswered: bool = False, owner_replied_at=None) -> list[dict[str, Any]]:
    """Newest-first summaries (id, time, source, kind, chats, preview, attachment names), filtered."""
    results = []
    for entry in sorted(_read_entries(root or store_dir()), key=lambda row: row["ts"], reverse=True):
        ts = float(entry.get("ts", 0))
        if (since and ts < since) or (until and ts > until):
            continue
        if kind and entry.get("kind") != kind:
            continue
        if source and source not in entry.get("source", ""):
            continue
        if chat and not any(c.startswith(chat) for c in entry.get("chats", [])):
            continue
        if text and text.lower() not in entry.get("text", "").lower():
            continue
        status = answer_status(entry, owner_replied_at)
        if unanswered and (status != "unanswered" or entry.get("delivered") is not True):
            continue
        results.append({"id": entry["id"], "at": entry["at"], "ts": ts, "source": entry["source"], "kind": entry["kind"],
                        "chat_id": entry.get("chat_id", ""), "title": entry.get("title", ""), "answer_status": status,
                        "chats": entry.get("chats", []), "preview": entry["text"][:160].replace("\n", " "),
                        "attachments": [a["name"] for a in entry.get("attachments", [])]})
        if len(results) >= limit:
            break
    return results


def answer_status(entry: dict, owner_replied_at=None) -> str | None:
    """Use the latest owner-authored turn in the asking chat as evidence of a reply."""
    if entry.get("kind") != "ask":
        return None
    if not entry.get("chat_id") or owner_replied_at is None:
        return "unknown"
    reply_time = owner_replied_at(entry["chat_id"])
    if reply_time is None:
        return "unknown"
    return "answered" if reply_time > entry["ts"] else "unanswered"


def backfill_pushes(path: Path, since: float, *, until: float | None = None,
                    chats: list[str] | None = None, root: Path | None = None) -> list[str]:
    """Import confirmed sends from the legacy push log without re-sending them."""
    result = []
    with path.open(encoding="utf-8") as handle:
        for row in _decode_lines(handle):
            ts = row.get("ts")
            if not isinstance(ts, (int, float)) or ts < since or (until is not None and ts > until):
                continue
            chat_id = row.get("chat_id", "")
            if chats and not any(chat_id.startswith(chat) for chat in chats):
                continue
            text = row.get("text")
            if not isinstance(text, str):
                continue
            proof = row.get("proof") or {}
            metadata = [{"name": redact(name), "path": "", "note": "legacy delivery"}
                        for name in proof.get("files", [])]
            metadata.extend({"name": f"Proof link {index}", "path": "", "note": "link in Discord text"}
                            for index, _ in enumerate(proof.get("links", []), 1))
            entry_id = "b" + hashlib.sha256(json.dumps([ts, chat_id, text]).encode()).hexdigest()
            saved_id = record(row.get("source", "agent_question"), text, kind=row.get("kind", ""),
                              chat_id=chat_id, title=row.get("title", ""), delivered=True, now=ts,
                              destination="discord", entry_id=entry_id, attachment_metadata=metadata, root=root)
            if saved_id:
                result.append(saved_id)
    return result


def read_notification(entry_id: str, *, root: Path | None = None) -> dict[str, Any] | None:
    """Full entry (complete text, chats, attachment names with absolute paths) or None."""
    root = root or store_dir()
    for entry in _read_entries(root):
        if entry.get("id") == entry_id:
            for attachment in entry.get("attachments", []):
                if attachment.get("path"):
                    attachment["path"] = str(root / attachment["path"])
            return entry
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    listing = sub.add_parser("list")
    listing.add_argument("--since", default="")
    listing.add_argument("--until", default="")
    listing.add_argument("--kind", default="")
    listing.add_argument("--source", default="")
    listing.add_argument("--chat", default="")
    listing.add_argument("--text", default="")
    listing.add_argument("--limit", type=int, default=50)
    reading = sub.add_parser("read")
    reading.add_argument("id")
    sub.add_parser("prune")
    backfill = sub.add_parser("backfill")
    backfill.add_argument("push_log", type=Path)
    backfill.add_argument("--since", required=True)
    backfill.add_argument("--until")
    backfill.add_argument("--chat", action="append")
    recording = sub.add_parser("record", help="record a notification sent by a shell script")
    recording.add_argument("--source", required=True)
    recording.add_argument("--kind", default="")
    recording.add_argument("--chat", action="append", default=[])
    recording.add_argument("--text", required=True)
    args = parser.parse_args(argv)
    if args.command == "list":
        result: Any = list_notifications(
            since=parse_since(args.since) if args.since else None, until=parse_since(args.until) if args.until else None,
            kind=args.kind, source=args.source, chat=args.chat, text=args.text, limit=args.limit)
    elif args.command == "read":
        result = read_notification(args.id)
        if result is None:
            print(f"no notification {args.id}", file=sys.stderr)
            return 1
    elif args.command == "record":
        result = {"id": record(args.source, args.text, kind=args.kind, chats=args.chat, destination="discord")}
    elif args.command == "backfill":
        result = {"ids": backfill_pushes(args.push_log, parse_since(args.since),
                                        until=parse_since(args.until) if args.until else None, chats=args.chat)}
    else:
        result = {"removed": prune()}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
