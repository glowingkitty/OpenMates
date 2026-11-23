#!/usr/bin/env python3
"""Tell the user on Discord, in one compact push, that a chat is done or needs their input.

Usage: agent_question.py done --summary "..." [--paused-until DATE] [--attach FILE]... [--link URL]...
                              [--no-proof "<why>"] [--task TASK-id] [--dry-run] [--force]
       agent_question.py ask --question "..." [--recommendation "..."] [--attach FILE]... [--link URL]...
                             [--no-proof "<why>"] [--task TASK-id] [--dry-run] [--force]

Two formats the user tells apart at a glance, each one or two sentences (details come from the
dev connector, which matches the push to its chat through the push log):
  ✅ <short chat title>: <what changed or the result>        (done; also a parked or paused chat,
                                                              with --paused-until)
  ❓ <short chat title>: <decision needed> Recommendation: …  (ask)
A chat sends exactly one push when it finishes (done) or is blocked on the user (ask), never for
progress and never both for one event; blocked and later finished is one ❓ then one ✅. A ✅ push
never asks the user anything: a done text with a question mark or an ask aimed at the user ("your
go-ahead", "should I", "decisions for you", "waiting on Marco") is refused (exit 1), because the user
reads ✅ as nothing-to-do and misses it; the question goes out as its own ❓ push. The chat
writes the short text itself (scripts/discord_summary.py): done at most SUMMARY_MAX characters, ask
(question plus recommendation) at most ASK_MAX, title shortened to TITLE_MAX; markdown, ids and
icons the chat wrote are stripped (the script adds exactly one icon). Longer text is rejected with a
rewrite instruction (exit 1); after two rejections one cheap model call shortens it, then a cut at a
word boundary with "…". --option values go to the push log only. Every text is scrubbed (secrets,
personal data) before it is sent, logged or given to the model.

Proof (scripts/push_proof.py): ``--attach`` puts screenshots, videos and output files (machine
files, ZIP, PDF) into the push as real Discord files (compressed, or a 7-day private storage link
when over Discord's limit); ``--link``
adds a signed link to our private proof storage. Both come on top of the short text. A chat that
changed UI files or ran end-to-end/visual CI jobs must attach proof; its push is refused without
it unless ``--no-proof "<why>"`` (sent with a loud "No screenshot or video" line). Research,
backend, security, docs and tooling pushes never need proof.

The webhook URL comes from DISCORD_WEBHOOK_AGENT_QUESTIONS, then DISCORD_WEBHOOK_DAILY_MEETING,
then DISCORD_WEBHOOK_DEV_NIGHTLY (environment, then the canonical checkout's ``.env``, the same
lookup as scripts/daily_meeting_briefing.py). The URL is never printed or logged. One push of
each kind per chat per 20 minutes unless ``--force`` or ``--urgent`` (owner, 23 Nov: a rate-limited
❓ about a production problem only reached the chat text). ``--urgent`` is also inferred from
production, outage, release and hotfix wording. A push that is rate-limited or whose delivery is
not confirmed is never dropped: it goes to ``logs/agent-questions/queue.jsonl`` and ``flush``
(every minute from scripts/host_resources.py) sends it when it is due. A marker
``logs/claude-idle-chats/questions/<chat-id>.json`` (ts, text, kind) tells
scripts/claude_idle_nudge.py that the chat already told the user. Every confirmed push (also other
scripts' pushes through ``record_push``) is appended to ``logs/agent-questions/pushes.jsonl``
(time, kind, chat id and title, the text, what it asks), so the dev connector can look a push up
by time and open its chat. An unconfirmed delivery (network error, Discord 429/5xx) is retried
twice after 2 and 5 seconds; a delivery still unconfirmed is queued and retried by ``flush``
every QUEUE_RETRY_SECONDS (the command says so, exit 0).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import discord_summary
import discord_webhook
import push_proof
from pending_work_gate import canonical_root

WEBHOOK_KEYS = ("DISCORD_WEBHOOK_AGENT_QUESTIONS", "DISCORD_WEBHOOK_DAILY_MEETING",
                "DISCORD_WEBHOOK_DEV_NIGHTLY")
RATE_LIMIT_SECONDS = 20 * 60
QUEUE = Path("logs") / "agent-questions" / "queue.jsonl"
QUEUE_RETRY_SECONDS = 5 * 60
URGENT_WORDS = re.compile(r"\b(?:production|prod|outage|outages|down|release|releases|hotfix)\b", re.I)
PUSH_LOG = Path("logs") / "agent-questions" / "pushes.jsonl"
RETRY_DELAYS = (2.0, 5.0)
MAX_CHARS = 1900  # per Discord message (limit 2000); longer pushes go out as several parts
MAX_PARTS = 4
DONE, ASK = "✅", "❓"
SHORTEN_MODEL = "haiku"  # fallback shortener: cheapest Claude model; benchmark in dev-host-resources.md
SHORTEN_BUDGET_USD = "0.25"
SHORTEN_TIMEOUT = 120
REJECTION_LOG = Path("logs") / "agent-questions" / "rejections"
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
_OWNER = r"(?:you|marco|the\s+owner)"
_OWNERS = r"(?:your|marco'?s|the\s+owner'?s)"
# A done text that asks the user something (owner rule, 22 Nov). Links are removed first, so a "?"
# in a signed URL is not a question.
DONE_ASKS_USER = tuple(re.compile(pattern, re.I) for pattern in (
    r"\?",
    rf"\b(?:until|awaits?|awaiting|needs?|for|after|pending|on|with)\s+{_OWNERS}\s+(?:answer|decision|call"
    r"|approval|input|go-ahead|ok|okay|choice|feedback|confirmation|sign-off|reply|pick)\b",
    rf"\b(?:open|questions?|decisions?|choices?)\s+(?:for|to)\s+{_OWNER}\b",
    r"\b(?:one|an?|open|my)\s+question\b",
    r"\b(?:should|shall)\s+(?:i|we)\b",
    r"\b(?:do|would)\s+you\s+(?:want|like|prefer)\b",
    r"\blet\s+me\s+know\b",
    r"\bplease\s+(?:confirm|decide|approve|choose|pick|answer|reply|check)\b",
    rf"\bwait(?:s|ing)?\s+(?:for|on)\s+{_OWNER}\b",
    rf"\bawait(?:s|ing)?\s+(?:{_OWNER}|{_OWNERS})\b",
    rf"\b{_OWNER}\s+(?:decides?|confirms?|approves?|answers?|chooses?|picks?|replies)\b",
    rf"\bneeds?\s+{_OWNERS}\b",
))


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


def done_asks_user(text: str) -> bool:
    """True when a ✅ text asks the user something; that belongs in its own ❓ push."""
    plain = _URL.sub(" ", text)
    return any(pattern.search(plain) for pattern in DONE_ASKS_USER)


def short_title(title: str) -> str:
    return discord_summary.short_title(scrub(title))

def build_body(kind: str, text: str, recommendation: str = "", paused_until: str = "", title: str = "") -> str:
    """The cleaned, scrubbed text after the title: the result, or 'question? Recommendation: …'."""
    body = discord_summary.clean_text(scrub(text), title).rstrip()
    end = "" if body.endswith((".", "?", "!", "…")) else "."
    if kind == ASK and recommendation:
        body = f"{body}{end} Recommendation: {discord_summary.clean_text(scrub(recommendation))}"
    if kind == DONE and paused_until:
        body = f"{body}{end} Paused until {scrub(paused_until)}."
    return body

def build_message(kind: str, title: str, body: str) -> str:
    """One compact push with exactly one icon: '✅ title: result.' or '❓ title: decision. Recommendation: …'."""
    return f"{kind} {short_title(title)}: {body}"

def rejection_path(root: Path, chat_id: str) -> Path:
    return root / REJECTION_LOG / f"{chat_id}.json"

def rejection_count(root: Path, chat_id: str, kind: str) -> int:
    """How many too-long rewrites this chat already got for this kind of push."""
    try:
        return int(json.loads(rejection_path(root, chat_id).read_text(encoding="utf-8")).get(kind, 0))
    except (OSError, ValueError, AttributeError):
        return 0

def write_rejections(root: Path, chat_id: str, kind: str, count: int) -> None:
    path = rejection_path(root, chat_id)
    try:
        counts = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        counts = {}
    counts[kind] = count
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(counts), encoding="utf-8")

def shorten_with_model(text: str, limit: int,
                       run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> str:
    """One cheap model call (headless ``claude -p`` on the platform login, never a user's) that shortens ``text``.

    ``text`` must already be scrubbed. Raises discord_summary.ShortenFailed when the CLI is missing,
    times out, fails or answers nothing."""
    system = (f"Rewrite the user's text as one short sentence of at most {limit} characters, in plain words, "
              "no markdown, no ids, no lists. Keep the outcome and, if present, the 'Recommendation:' part. "
              "Answer with the sentence only.")
    command = ["claude", "-p", "--model", SHORTEN_MODEL, "--no-session-persistence", "--tools", "",
               "--setting-sources", "", "--max-budget-usd", SHORTEN_BUDGET_USD, "--system-prompt", system]
    try:
        with tempfile.TemporaryDirectory() as neutral:  # no project instructions are loaded
            done = run(command, input=text, capture_output=True, text=True, timeout=SHORTEN_TIMEOUT, cwd=neutral)
    except (OSError, subprocess.SubprocessError) as error:
        raise discord_summary.ShortenFailed(type(error).__name__) from error
    answer = done.stdout.strip()
    if done.returncode != 0 or not answer:
        raise discord_summary.ShortenFailed(f"claude exit {done.returncode}")
    return answer

def marker_path(root: Path, chat_id: str) -> Path:
    return root / "logs" / "claude-idle-chats" / "questions" / f"{chat_id}.json"


def recently_sent(root: Path, chat_id: str, now: float, kind: str = ASK) -> bool:
    """A push of this kind from this chat in the last RATE_LIMIT_SECONDS (markers without kind are asks)."""
    try:
        recorded = json.loads(marker_path(root, chat_id).read_text(encoding="utf-8"))
        return recorded.get("kind", ASK) == kind and now - float(recorded.get("ts", 0)) < RATE_LIMIT_SECONDS
    except (OSError, ValueError, AttributeError):
        return False


def is_urgent(args: argparse.Namespace, text: str, recommendation: str = "") -> bool:
    """An urgent push (production outage, release step) is never held by the rate limit."""
    return bool(getattr(args, "urgent", False)) or bool(URGENT_WORDS.search(f"{text} {recommendation}"))


def _queue_lines(root: Path) -> list[dict]:
    try:
        lines = (root / QUEUE).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    return [json.loads(line) for line in lines if line.strip()]


def _write_queue(root: Path, entries: list[dict]) -> None:
    path = root / QUEUE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}")
    tmp.write_text("".join(json.dumps(entry, ensure_ascii=False) + "\n" for entry in entries), encoding="utf-8")
    tmp.replace(path)


def enqueue(root: Path, entry: dict) -> None:
    """Hold one push for `flush` (rate-limited or undelivered); it is sent at entry['due']."""
    _write_queue(root, [*_queue_lines(root), entry])


def flush(root: Path, now: float, post: Callable[..., dict | None] = discord_webhook.post_message,
          sleep: Callable[[float], None] = time.sleep,
          post_files: Callable[..., dict | None] = discord_webhook.post_files) -> list[str]:
    """Send every queued push that is due; returns what was sent. Unconfirmed ones stay queued."""
    entries, kept, sent = _queue_lines(root), [], []
    for entry in entries:
        if float(entry.get("due", 0)) > now:
            kept.append(entry)
            continue
        message = entry["message"]
        files: list[tuple[str, bytes]] = []
        try:
            with push_proof.temporary_workdir() as work:
                try:
                    prepared = push_proof.prepare(entry.get("attach") or [], entry.get("links") or [],
                                                  entry["chat_id"], Path(work), own_link=own_storage_link)
                    files, message = prepared.files, "\n".join([message, *prepared.link_lines()])
                except push_proof.ProofError as error:
                    message += f"\n⚠️ Proof could not be attached when the queued push went out: {error}"[:300]
                deliver(webhook(root), message, post, sleep, files=files, post_files=post_files)
        except QuestionError as error:
            kept.append({**entry, "due": now + QUEUE_RETRY_SECONDS, "attempts": int(entry.get("attempts", 0)) + 1,
                         "last_error": str(error)[:200]})
            continue
        record_push(root, message, now, chat_id=entry["chat_id"], title=entry.get("title", ""),
                    asks=entry.get("asks", ""), recommendation=entry.get("recommendation", ""),
                    options=entry.get("options") or [], task_id=entry.get("task", ""), kind=entry.get("kind", ""),
                    source="agent_question_queue")
        sent.append(message.splitlines()[0][:120])
    _write_queue(root, kept)
    return sent


def deliver(url: str, message: str, post: Callable[..., dict | None],
            sleep: Callable[[float], None] = time.sleep, files: list[tuple[str, bytes]] | None = None,
            post_files: Callable[..., dict | None] = discord_webhook.post_files) -> dict:
    """Post each part of the message (split_message), retrying each after the RETRY_DELAYS entries.

    ``files`` go with the first part as one multipart upload. Returns the last confirmed result;
    raises QuestionError when a part stays unconfirmed."""
    result: dict | None = None
    for index, part in enumerate(split_message(message)):
        for delay in (*RETRY_DELAYS, None):
            if index == 0 and files:
                result = post_files(webhook_url=url, payload={"content": part}, files=files)
            else:
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
                source: str = "agent_question", kind: str = "", proof: dict | None = None) -> Path:
    """Append one delivered push to the push log (one JSON object per line); returns the log path.

    kind: "done" or "ask" (derived from a ✅/❓ prefix when not given; other scripts' alerts: "")."""
    first = next((line for line in message.splitlines()[1:] if line.strip()), message)
    kind = kind or {DONE: "done", ASK: "ask"}.get(message[:1], "")
    entry = {"ts": now, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)), "source": source, "kind": kind,
             "chat_id": chat_id, "title": scrub(title), "asks": scrub(asks or first),
             "recommendation": scrub(recommendation), "options": [scrub(o) for o in options or []],
             "task": scrub(task_id), "text": message}
    if proof:
        entry["proof"] = proof  # attached file names, private links, or the --no-proof reason
    path = root / PUSH_LOG
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return path

def send(args: argparse.Namespace, root: Path, chat_id: str, now: float,
         post: Callable[..., dict | None] = discord_webhook.post_message,
         sleep: Callable[[float], None] = time.sleep,
         post_files: Callable[..., dict | None] = discord_webhook.post_files,
         uploader: Callable[[Path, str], str] | None = None) -> str:
    """Send (or, with --dry-run, build) a done or ask push; returns the message text."""
    kind = DONE if args.command == "done" else ASK
    text = args.summary if kind == DONE else args.question
    recommendation = getattr(args, "recommendation", None) or ""
    _, task_text = session_info(root, chat_id)
    title = os.environ.get("CLAUDE_CHAT_TITLE") or task_text
    limit = discord_summary.SUMMARY_MAX if kind == DONE else discord_summary.ASK_MAX
    body = build_body(kind, text, recommendation, getattr(args, "paused_until", None) or "", title)
    if kind == DONE and done_asks_user(text):
        raise QuestionError(
            "a ✅ push must not ask the user anything: the user reads ✅ as nothing to do and misses it. "
            "Send the question as its own push (agent_question.py ask --question '...' --recommendation "
            "'...') and write the ✅ text without it, or wait with the ✅ until the answer is in.")
    rejections = rejection_count(root, chat_id, kind) if chat_id else discord_summary.MAX_REJECTIONS
    try:
        body = discord_summary.fit(
            body, limit, rejections=rejections, shorten=shorten_with_model,
            what="the summary" if kind == DONE else "question plus recommendation",
            note=lambda line: print(f"agent_question: {line}", file=sys.stderr))
    except discord_summary.SummaryTooLong:
        if chat_id and not args.dry_run:
            write_rejections(root, chat_id, kind, rejections + 1)
        raise
    message = build_message(kind, title, body)
    attach, links = getattr(args, "attach", None) or [], getattr(args, "link", None) or []
    no_proof = (getattr(args, "no_proof", None) or "").strip()
    reasons = push_proof.proof_reasons(root, chat_id)
    if reasons and not any(push_proof.is_visual(raw) for raw in attach) and not links and not no_proof:
        raise QuestionError(push_proof.refusal(reasons))
    videos = push_proof.video_reasons(root, chat_id)
    has_video = any(push_proof.is_video(raw) for raw in attach) or any(push_proof.is_video_link(u) for u in links)
    if videos and not has_video and not no_proof:
        raise QuestionError(push_proof.video_refusal(videos))
    if videos and not has_video and no_proof:
        message += f"\n⚠️ No video of the Playwright run: {discord_summary.clean_text(scrub(no_proof))[:160]}"
    elif no_proof and not any(push_proof.is_visual(raw) for raw in attach) and not links:
        message += f"\n⚠️ No screenshot or video: {discord_summary.clean_text(scrub(no_proof))[:160]}"
    if args.dry_run:
        for raw in attach:
            push_proof.check_path(raw)
        return message + "".join(f"\n[attached: {Path(raw).name}]" for raw in attach)
    if not chat_id:
        raise QuestionError("CLAUDE_CODE_SESSION_ID is not set; cannot identify this chat")
    held = dict(message=message, chat_id=chat_id, kind=args.command, title=title, asks=text,
                recommendation=recommendation, options=getattr(args, "option", None) or [], task=args.task or "",
                links=links, queued_at=now)
    if not args.force and not is_urgent(args, text, recommendation) and recently_sent(root, chat_id, now, kind):
        # Never dropped (owner, 23 Nov): held until the 20 minutes are over, then flush sends it.
        last = json.loads(marker_path(root, chat_id).read_text(encoding="utf-8"))
        due = float(last.get("ts", now)) + RATE_LIMIT_SECONDS
        enqueue(root, {**held, "due": due, "attach": _durable(root, attach, chat_id, now)})
        _write_marker(root, chat_id, args, text, kind, now)
        args.queued = True
        print(f"agent_question: this chat sent a {args.command} push less than 20 minutes ago; this one is "
              f"queued and goes out at {time.strftime('%H:%M UTC', time.gmtime(due))} (use --urgent for "
              "production problems and release steps)", file=sys.stderr)
        return message
    url = webhook(root)  # a missing webhook is a setup error, never queued: it fails right here
    try:
        with push_proof.temporary_workdir() as work:
            prepared = push_proof.prepare(attach, links, chat_id, Path(work), own_link=own_storage_link,
                                          **({"uploader": uploader} if uploader else {}))
            for note in prepared.notes:
                print(f"agent_question: {note}", file=sys.stderr)
            sent_message = "\n".join([message, *prepared.link_lines()])
            deliver(url, sent_message, post, sleep, files=prepared.files, post_files=post_files)
            message = sent_message
    except QuestionError as error:
        enqueue(root, {**held, "due": now + QUEUE_RETRY_SECONDS, "attach": _durable(root, attach, chat_id, now),
                       "last_error": str(error)[:200]})
        _write_marker(root, chat_id, args, text, kind, now)
        args.queued = True
        print(f"agent_question: {error}; the push is queued and retried every "
              f"{QUEUE_RETRY_SECONDS // 60} min", file=sys.stderr)
        return message
    proof = {"files": [name for name, _ in prepared.files], "links": [url for _, url in prepared.links]}
    try:
        stored = push_proof.store_copies(root, attach, chat_id, now)
    except (OSError, push_proof.ProofError) as error:  # the push is out; a missing copy only costs the replay
        print(f"agent_question: proof copy not kept ({error})", file=sys.stderr)
        stored = []
    if stored:
        proof["stored"] = stored
    if no_proof and prepared.empty:
        proof = {"no_proof": scrub(no_proof)}
    record_push(root, message, now, chat_id=chat_id, title=title, asks=text, recommendation=recommendation,
                options=getattr(args, "option", None) or [], task_id=args.task or "", kind=args.command,
                proof=proof if (proof.get("files") or proof.get("links") or proof.get("no_proof")) else None)
    _write_marker(root, chat_id, args, text, kind, now)
    write_rejections(root, chat_id, kind, 0)
    return message


def _write_marker(root: Path, chat_id: str, args: argparse.Namespace, text: str, kind: str, now: float) -> None:
    """The chat told the user (sent or queued): scripts/claude_idle_nudge.py and the lifecycle read it."""
    path = marker_path(root, chat_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    marker = {"ts": now, "question": scrub(text), "kind": kind}
    if getattr(args, "paused_until", None):
        marker["paused_until"] = args.paused_until  # parked: the chat lifecycle stops it but does not archive it
    path.write_text(json.dumps(marker), encoding="utf-8")


def _durable(root: Path, attach: list[str], chat_id: str, now: float) -> list[str]:
    """Attachments a queued push can still send later: owner-only copies of screenshots and videos."""
    try:
        stored = [str(root / rel) for rel in push_proof.store_copies(root, attach, chat_id, now)]
    except (OSError, push_proof.ProofError) as error:
        print(f"agent_question: proof copy for the queued push not kept ({error})", file=sys.stderr)
        stored = []
    return stored + [raw for raw in attach if not push_proof.is_visual(raw)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("flush", help="send queued pushes that are due (scripts/host_resources.py, every minute)")
    done_parser = sub.add_parser("done", help="✅ the chat finished (or parked / paused itself); put open "
                                 "follow-ups in its Task first: a done chat is archived when its turn ends")
    done_parser.add_argument("--summary", required=True, help="one short sentence, under 110 characters: the result, no ids or markdown")
    done_parser.add_argument("--paused-until", help="parked or paused: the date it resumes")
    ask_parser = sub.add_parser("ask", help="❓ the chat is blocked on a decision of the user")
    ask_parser.add_argument("--question", required=True, help="the decision as one short question; question plus recommendation under 120 characters")
    ask_parser.add_argument("--recommendation")
    ask_parser.add_argument("--option", action="append", help="logged for the connector; not sent")
    for each in (done_parser, ask_parser):
        each.add_argument("--attach", action="append", metavar="FILE",
                          help="screenshot, video or output file (zip, machine files, pdf, svg, stl, csv) sent as a "
                               "Discord file (repeatable); a screenshot or video is required when the chat "
                               "changed UI files or ran end-to-end/visual CI jobs")
        each.add_argument("--link", action="append", metavar="URL",
                          help="signed link to our private proof storage, sent on top of the text (repeatable)")
        each.add_argument("--no-proof", metavar="WHY",
                          help="nothing visual to show despite UI changes or E2E runs; the push says so loudly")
        each.add_argument("--task")
        each.add_argument("--dry-run", action="store_true")
        each.add_argument("--force", action="store_true")
        each.add_argument("--urgent", action="store_true",
                          help="production outage or release step: never held by the 20-minute limit")
    args = parser.parse_args(argv)
    if args.command == "flush":
        try:
            for line in flush(canonical_root(), time.time()):
                print(f"sent queued push: {line}")
        except (OSError, ValueError) as error:
            print(f"agent_question: queue unreadable: {error}", file=sys.stderr)
            return 1
        return 0
    try:
        message = send(args, canonical_root(), os.environ.get("CLAUDE_CODE_SESSION_ID", ""), time.time())
    except (QuestionError, discord_summary.SummaryTooLong, push_proof.ProofError) as error:
        print(f"agent_question: {error}", file=sys.stderr)
        return 1
    print(message if args.dry_run else "Push queued (see above)." if getattr(args, "queued", False)
          else ("Done push sent." if args.command == "done" else "Question sent."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
