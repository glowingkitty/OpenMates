"""Chat lifecycle for Claude Code chats on the dev host: working, idle-stopped, done.

Every chat holds a Claude Code process (about 0.4 GB with its tool servers) until it
exits. Finished chats used to pile up (40 processes, about 14 GB on 2026-11-14) and
starve the host-resources guard. This script keeps them in check:

  working       the chat runs normally (busy, waiting for a permission or an answer,
                running a background command, or active recently).
  idle-stopped  its turn ended `idle_stop_minutes` ago (default 3) and nothing runs or
                waits in the background: its process gets SIGTERM, a graceful shutdown.
                This includes a chat that waits on the owner's answer (its question is
                kept in stopped.json `open_question` and in the briefing's waiting chats)
                and a parked chat. The transcript stays on disk; a new message (connector
                send_message, which resumes with `claude --resume <id>`) or its waiter
                brings it back with the same history. Owner rule 2026-11-20: only working
                chats and chats waiting on a background job hold one of the `max_running`
                slots (after the usage reset 13 of 20 slots were held by idle chats).
  archived      a chat that reported done with a ✅ push (scripts/agent_question.py done,
                no --paused-until), asks nothing and waits on nothing is closed at the end
                of its turn: a zellij-pane chat gets `/exit` (a clean exit archives its
                Claude app session), otherwise it is stopped and listed as done with
                `reported_done`, and the dev connector archives it without approval.
  continued     owner rule 2026-11-21 (TASK-7707): a chat is closed only when it reported
                done (✅), asked the owner (❓ or a closing question) or registered a waiter.
                A turn that ends any other way ("Next: fix the foreground reconnect") means
                the chat is still at work: a zellij-pane chat gets one continue prompt per
                turn end (scripts/claude_chat_continue.py; retried after 10 minutes, at most
                3 in a row without tool work), and one that cannot be woken or does not act
                keeps running and is listed as stalled. The cap never suspends it; only a host
                short on memory stops it, with a timer waiter that reopens it 30 minutes later.
                On 2026-11-20 the old rule (stop 3 minutes after any turn end) closed
                4b5c74d7, 061eb4be and 18693e46 in the middle of their work.
  done          listed in the status file so the connector archives it in the Claude app
                (one implementation, in the connector) and it stops counting against the
                app's session limit.

Cap: at most `max_running` (default 20) chat processes run at once. Beyond that, the
longest-idle chat that may be suspended is stopped first. `admit` makes room for a
new chat or says why it must wait; claude_dispatch.py queues the chat then, never
drops it.

Activity comes from the session record (~/.claude/sessions/<pid>.json) and the newest
record timestamp in the transcript and sub-agent transcripts. File mtimes are not
used: Claude Code rewrites idle transcripts in place on bridge reconnects, so a chat
idle for 30 hours looked active minutes ago.

A chat is never stopped when any of these hold (hard rules, also for the cap):
  * it is not a managed chat: only Remote Control workers and chats in a zellij pane
    of a configured session (`zellij_sessions`) are managed; a chat started by hand
    in a plain terminal is never touched,
  * it is the chat running this script,
  * its state is not `idle` (working, or waiting for a permission or an answer),
  * a child process other than its tool (MCP) servers runs (a background command),
  * a background sub-agent of its process has not reported back (they run inside the chat's
    own process; 70004807's lane-worker died mid tool call on 2026-11-20),
  * its last turn is a message without a reply, including a prompt a hook refused,
  * it waits on background work: a waiter that has not timed out (a disk-coordinator
    request, a queued or running CI job of its sessions.py session, or a registered
    handoff/background waiter; scripts/claude_chat_waiters.py), or a finished job's
    notification was refused and never reached it (scripts/claude_chat_pending.py).
Waiters: when a wait is over the chat is woken (idle pane chat: one typed line) or, when
it is not running, reopened with `claude --resume` and the line as its next message; a
timed-out waiter is listed as stalled and no longer blocks idle stop.
Waking: the reap pass types one wake prompt into a zellij-pane chat whose job
notifications were refused (once per notification), so finished CI, E2B or heavy_slot
results are always read. Remote Control workers and stopped chats with such pending
work go on the `stalled` list in status.json for the connector (chat_changes).
Unfinished work: before a chat whose session worktree holds files not on dev is stopped
(idle stop, done or the cap), its worktree is snapshotted (scripts/worktree_wip.py,
refs/openmates/wip/<session>) and a zellij-pane chat gets one finish prompt and
FINISH_GRACE_MINUTES to commit, test and deploy or park it. A chat that cannot be woken
or does not act is stopped with its work snapshotted and listed in status.json
(`stopped_with_unfinished_work`, and `unfinished_work` / `stalled` while it stays stopped).
Under memory pressure it is snapshotted and stopped without the grace period.
The cap keeps a chat active in the last `cap_min_idle_minutes` and suspends chats
without an open question first. A chat with an open question is stopped like any
finished turn and stays listed as waiting with its question; the connector resumes it
when the answer comes. Waking after a wait (claude_chat_waiters.deliver) reopens at
most `wake_batch` closed chats per cycle, highest Task priority first, and always leaves
`free_slots` slots for new chats, so the usage-reset wake never fills the cap.
A ❓ Discord push (scripts/agent_question.py ask; its marker in
logs/claude-idle-chats/questions/<chat>.json) is an open question until the user's next
prompt, whatever the chat's last reply says (2026-11-19: chat 602f0aeb pushed a decision,
then ended its reply without a question mark and was stopped as idle after 65 minutes).

Settings: defaults below, overridden by `<repo>/logs/claude-chat-lifecycle/config.json`
(or OPENMATES_CHAT_LIFECYCLE_CONFIG), overridden by flags.

Commands:
  list     every live chat with its idle time and decision
  reap     stop idle chats and enforce the cap (--dry-run prints instead;
           --pressure uses `pressure_idle_minutes`, for the host-resources guard)
  status   write and print the counts (working, idle-stopped, done, running vs cap)
  admit    make room for one new chat; exit 0 when there is room, 3 when not
  mark     --session <id> --state archived|resumed (for the connector)
  release  submit again up to --limit prompts that an older hook version refused:
           a zellij-pane chat whose last turn is a refused prompt that Claude Code
           kept in its input box (promptKept) gets one Enter per refusal (the
           host-resources guard runs this only while the host is healthy); a
           refused job notification is not in the input box and is woken instead
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# The systemd units run this as `python3 -I -S`, which does not put the script's folder on
# sys.path; without this the sibling import fails and the lifecycle (idle stop, cap of 20) stops.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import claude_chat_continue  # noqa: E402  (path set above)
import claude_chat_pending  # noqa: E402  (path set above)
import claude_chat_waiters  # noqa: E402  (path set above)
import worktree_wip  # noqa: E402  (path set above)

DEFAULTS = {
    "idle_stop_minutes": 3.0,  # a finished turn releases its slot this long after its last step
    "done_hours": 24.0,
    "max_running": 20,
    "cap_min_idle_minutes": 1.0,
    "wake_batch": 3,  # closed chats reopened per cycle when their wait is over
    "free_slots": 4,  # slots the wake leaves free for new chats
    "cap_question_idle_hours": 4.0,
    "pressure_idle_minutes": 15.0,
    "zellij_sessions": ["claude"],  # more via config.json
}
TERM_WAIT_SECONDS = 20.0
TAIL_BYTES = 512 * 1024
WORKER_MARKERS = ("--sdk-url", "/code/sessions/")
TOOL_SERVER_MARKER = "mcp"
REFUSED_PREFIX = "UserPromptSubmit operation blocked by hook"
EXIT_NO_ROOM = 3
QUESTION_RE = re.compile(
    r"\?|\b(waiting (on|for) your|your (answer|decision|go-ahead|approval)|let me know|tell me (if|and|whether)|"
    r"reply (\*\*)?ok|shall i|should i|do you want|would you like|approve|decide|confirm|your call|"
    r"read it over|leave comments|review it)\b",
    re.I,
)
URL_OR_CODE_RE = re.compile(r"https?://\S+|`[^`]*`")
NOISE_SUBTYPES = {"bridge_status"}
SCRIPT_ROOT = Path(__file__).resolve().parents[1]


def canonical_root(repo_root: Path = SCRIPT_ROOT) -> Path:
    """The main checkout for a linked worktree, else repo_root (state lives there)."""
    dot_git = repo_root / ".git"
    if dot_git.is_file():
        text = dot_git.read_text(encoding="utf-8").strip()
        if text.startswith("gitdir:"):
            gitdir = Path(text.split(":", 1)[1].strip())
            if gitdir.parent.name == "worktrees":
                return gitdir.parent.parent.parent
    return repo_root


def state_dir() -> Path:
    override = os.environ.get("OPENMATES_CHAT_LIFECYCLE_DIR")
    return Path(override) if override else canonical_root() / "logs" / "claude-chat-lifecycle"


def load_config(path: Path | None = None) -> dict:
    """Defaults, then the optional JSON config file. A broken file is an error, not ignored."""
    config = dict(DEFAULTS)
    path = path or Path(os.environ.get("OPENMATES_CHAT_LIFECYCLE_CONFIG") or state_dir() / "config.json")
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        unknown = set(data) - set(DEFAULTS)
        if unknown:
            raise SystemExit(f"claude_idle_chats: unknown settings in {path}: {sorted(unknown)}")
        config.update(data)
    return config


@dataclass
class Chat:
    """One live chat process as recorded in ``~/.claude/sessions/<pid>.json``."""

    pid: int
    session_id: str
    name: str
    status: str
    kind: str  # rc_worker | pane | terminal
    last_activity: float
    waiting_for: str = ""
    children: list[str] = field(default_factory=list)
    last_speaker: str = ""  # user | assistant | ""
    last_text: str = ""
    title: str = ""
    cwd: str = ""
    zellij_session: str = ""
    pane_id: str = ""
    model: str = ""
    undelivered: list[dict] = field(default_factory=list)  # refused job notifications (claude_chat_pending)
    refusal_kept: bool | None = None
    refusal_at: str = ""
    waiters: list = field(default_factory=list)  # claude_chat_waiters.Waiter: disk, CI, handoff, background
    pushed_question: str = ""  # a ❓ push sent after the user's last prompt (open until they answer)
    pushed_done: str = ""  # "done" (✅ after the last prompt) or "parked" (✅ with --paused-until)
    agents: list[str] = field(default_factory=list)  # background sub-agents still at work (claude_chat_continue)
    transcript: str = ""  # path of its main transcript


@dataclass
class Decision:
    action: str  # keep | continue | stop | done | archive
    reason: str
    hard: bool = False  # kept by a hard rule (the cap may not override it)
    reopen: bool = False  # stopped in the middle of its work: a timer waiter reopens it (claude_chat_continue)

    @property
    def close(self) -> bool:
        return self.action in ("stop", "done", "archive")


def asks_something(text: str) -> bool:
    """Open question or request in the end of a reply (URLs and code spans ignored)."""
    tail = URL_OR_CODE_RE.sub(" ", text.strip()[-1200:])
    return bool(QUESTION_RE.search(tail))


def ends_with_question(text: str) -> bool:
    """The reply's last line asks something ("Shall I also deploy it?"), URLs and code ignored."""
    lines = [line for line in URL_OR_CODE_RE.sub(" ", text).strip().splitlines() if line.strip()]
    return bool(lines) and lines[-1].rstrip(" *_)\"'").endswith("?")


def hard_blocker(chat: Chat, own_session_id: str, now: float | None = None) -> str | None:
    if chat.kind == "terminal":
        return "not a managed chat (started by hand in a terminal)"
    if own_session_id and chat.session_id == own_session_id:
        return "this chat runs the script"
    if chat.status != "idle":
        return f"state is {chat.status or 'unknown'}"
    if chat.waiting_for:
        return f"waits for {chat.waiting_for}"
    busy = [command for command in chat.children if TOOL_SERVER_MARKER not in command.lower()]
    if busy:
        return f"background process running: {busy[0][:60]}"
    if chat.agents:  # they run inside the chat's process: stopping it kills them (TASK-7707)
        return f"background sub-agent running: {chat.agents[0][:60]}"
    now = time.time() if now is None else now
    if waiting := [waiter for waiter in chat.waiters if waiter.blocks_stop(now)]:
        return "waits on " + "; ".join(waiter.label(now) for waiter in waiting[:3])
    if chat.undelivered:
        return f"background job finished but its result never reached the chat ({chat.undelivered[0]['task_id']})"
    if chat.last_speaker == "user":
        return "its last message has no reply"
    return None


def decide(chat: Chat, now: float, config: dict, own_session_id: str, idle_minutes: float | None = None) -> Decision:
    """Pure rule: what happens to this chat's process now."""
    reason = hard_blocker(chat, own_session_id, now)
    if reason:
        return Decision("keep", reason, hard=True)
    idle = now - chat.last_activity
    limit = 60 * (config["idle_stop_minutes"] if idle_minutes is None else idle_minutes)
    if idle <= limit:
        return Decision("keep", f"idle {idle / 60:.0f} min, limit {limit / 60:.0f} min")
    # The chat's own push decides; the wording of its reply is only a guess. A ✅ chat whose report
    # merely mentions "waiting on your answer" (2026-11-20) is done; only a closing "?" keeps it open.
    if chat.pushed_done and not chat.pushed_question and not ends_with_question(chat.last_text):
        if chat.pushed_done == "done" and not chat.waiters:
            return Decision("archive", "reported done with a ✅ push, nothing open")
        if chat.pushed_done == "parked":
            return Decision("stop", "parked itself (✅ with a resume date)")
    if asks(chat):
        return Decision("stop", "waits on your answer (process stopped; the answer reopens it)")
    if chat.waiters:  # a waiter that timed out: it still reopens the chat when it fires
        return Decision("stop", f"idle {idle / 60:.0f} min, its waiter reopens it")
    # Owner rule 2026-11-21 (TASK-7707): no ✅, no question, no waiter means the chat is still at
    # work ("Next: fix the foreground reconnect"); it is woken to continue, never closed. Only a
    # host short on memory may stop it, and then a timer waiter reopens it.
    if idle_minutes is not None:
        return Decision("stop", f"idle {idle / 60:.0f} min, host short on memory; reopens in "
                        f"{claude_chat_continue.REOPEN_MINUTES:.0f} min to continue", reopen=True)
    return Decision("continue", f"idle {idle / 60:.0f} min without ✅, question or waiter: woken to continue")


def closable(chat: Chat) -> bool:
    """It reported done, asked the owner or waits on a waiter: stopping it loses nothing."""
    return bool(chat.pushed_done or asks(chat) or chat.waiters)


def cap_victims(chats: list[Chat], now: float, config: dict, own_session_id: str, room: int = 0) -> list[Chat]:
    """Chats to suspend so that at most max_running - room processes run; longest idle first."""
    excess = len(chats) + room - int(config["max_running"])
    if excess <= 0:
        return []
    minimum = config["cap_min_idle_minutes"] * 60
    question_minimum = config["cap_question_idle_hours"] * 3600
    eligible = [chat for chat in chats if hard_blocker(chat, own_session_id, now) is None
                and now - chat.last_activity > minimum and closable(chat)]
    plain = [chat for chat in eligible if not asks(chat)]
    asking = [chat for chat in eligible if asks(chat) and now - chat.last_activity > question_minimum]
    by_idle = lambda chat: chat.last_activity  # noqa: E731 - sort key, oldest activity first
    return (sorted(plain, key=by_idle) + sorted(asking, key=by_idle))[:excess]


def asks(chat: Chat) -> bool:
    return bool(chat.pushed_question) or (chat.last_speaker == "assistant" and asks_something(chat.last_text))


def open_question(chat: Chat) -> str:
    """What the chat asks the user: its ❓ push, else the end of its last reply ('' when nothing)."""
    if chat.pushed_question:
        return chat.pushed_question
    return " ".join(chat.last_text.split())[-300:] if asks(chat) else ""


def questions_dir() -> Path:
    return state_dir().parent / "claude-idle-chats" / "questions"  # written by scripts/agent_question.py


def pushed(session_id: str, last_prompt_at: float, markers: Path | None = None) -> dict:
    """The chat's last ✅/❓ push marker when it came after the user's last prompt, else {}."""
    try:
        marker = json.loads(((markers or questions_dir()) / f"{session_id}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(marker, dict) or float(marker.get("ts", 0)) <= last_prompt_at:
        return {}  # none, or the user answered (or wrote) after it
    return marker


def pushed_question(session_id: str, last_prompt_at: float, markers: Path | None = None) -> str:
    """The ❓ push this chat sent after the user's last prompt, or '' (none, answered, or a ✅ push)."""
    marker = pushed(session_id, last_prompt_at, markers)
    if not marker or marker.get("kind", "❓") != "❓":
        return ""
    return " ".join(str(marker.get("question", "")).split())[:300] or "a question sent to the user on Discord"


def pushed_done(marker: dict) -> str:
    """'done' or 'parked' for a ✅ marker (from pushed()), else ''."""
    if marker.get("kind") != "✅":
        return ""
    return "parked" if marker.get("paused_until") else "done"


def last_prompt_at(claude_home: Path, session_id: str) -> float:
    """When the user last typed a prompt into the chat (0 when none is in the transcript tail)."""
    newest = 0.0
    for transcript in (claude_home / "projects").glob(f"*/{session_id}.jsonl"):
        for record in _tail_records(transcript):
            if (record.get("type") == "user" and not record.get("isMeta") and not record.get("isCompactSummary")
                    and _text(record).strip()):
                newest = max(newest, _iso(record.get("timestamp")))
    return newest


# ---------------------------------------------------------------------------
# Reading the live chats.
# ---------------------------------------------------------------------------


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _proc_start(pid: int) -> str:
    stat = _read(Path(f"/proc/{pid}/stat"))
    if ")" not in stat:
        return ""
    fields = stat.rsplit(")", 1)[1].split()
    return fields[19] if len(fields) > 19 else ""


def _cmdline_args(pid: int | str) -> list[str]:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return []
    return [part.decode("utf-8", "replace") for part in raw.split(b"\0") if part]


def _environ(pid: int) -> dict[str, str]:
    try:
        raw = Path(f"/proc/{pid}/environ").read_bytes()
    except OSError:
        return {}
    pairs = (item.decode("utf-8", "replace").partition("=") for item in raw.split(b"\0") if b"=" in item)
    return {key: value for key, _, value in pairs if key.startswith("ZELLIJ")}


def _children(pid: int) -> list[str]:
    return [" ".join(args) for child in _read(Path(f"/proc/{pid}/task/{pid}/children")).split()
            if (args := _cmdline_args(child))]


def _flag(args: list[str], name: str) -> str:
    return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else ""


def _iso(stamp: object) -> float:
    if not isinstance(stamp, str) or not stamp:
        return 0.0
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _tail_records(path: Path) -> list[dict]:
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - TAIL_BYTES))
            data = handle.read().decode("utf-8", "replace")
    except OSError:
        return []
    lines = data.splitlines()[1:] if size > TAIL_BYTES else data.splitlines()
    records = []
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def _text(record: dict) -> str:
    content = (record.get("message") or {}).get("content") if isinstance(record.get("message"), dict) else None
    if content is None:
        content = record.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(block.get("text", "") for block in content
                         if isinstance(block, dict) and block.get("type") == "text")
    return ""


def _is_activity(record: dict) -> bool:
    if record.get("type") == "system":
        return record.get("subtype") not in NOISE_SUBTYPES and not _text(record).startswith("Compacted while idle")
    return record.get("type") in ("user", "assistant", "queue-operation")


def last_turn(records: list[dict]) -> tuple[str, str]:
    """(speaker, text) of the last real turn: a typed prompt, a refused prompt or a reply."""
    for record in reversed(records):
        kind = record.get("type")
        if kind == "system" and _text(record).startswith(REFUSED_PREFIX):
            return "user", _text(record)
        if kind not in ("user", "assistant") or record.get("isMeta") or record.get("isCompactSummary"):
            continue
        text = _text(record)
        if text.strip():
            return ("user" if kind == "user" else "assistant"), text
    return "", ""


def transcript_state(claude_home: Path, session_id: str) -> tuple[float, str, str]:
    """(newest activity timestamp, last speaker, last text) from the transcript and its sub-agents."""
    newest, speaker, text = 0.0, "", ""
    for transcript in (claude_home / "projects").glob(f"*/{session_id}.jsonl"):
        records = _tail_records(transcript)
        newest = max([newest, *(_iso(r.get("timestamp")) for r in records if _is_activity(r))])
        speaker, text = last_turn(records) if records else (speaker, text)
        for extra in transcript.with_suffix("").rglob("*.jsonl"):
            newest = max([newest, *(_iso(r.get("timestamp")) for r in _tail_records(extra) if _is_activity(r))])
    return newest, speaker, text


def transcript_pending(claude_home: Path, session_id: str) -> claude_chat_pending.Pending:
    """Refused, undelivered job notifications in the chat's main transcript."""
    for transcript in (claude_home / "projects").glob(f"*/{session_id}.jsonl"):
        return claude_chat_pending.scan(_tail_records(transcript))
    return claude_chat_pending.Pending()


def classify(args: list[str], zellij_env: dict[str, str], sessions: list[str]) -> str:
    command = " ".join(args)
    if all(marker in command for marker in WORKER_MARKERS):
        return "rc_worker"
    if zellij_env.get("ZELLIJ_PANE_ID") and zellij_env.get("ZELLIJ_SESSION_NAME") in sessions:
        return "pane"
    return "terminal"


UNREADABLE = "unreadable"


def gather_waiters(now: float) -> dict[str, list]:
    """chat id -> its waiters; {UNREADABLE: [...]} when a source cannot be read."""
    root = canonical_root()
    sources = claude_chat_waiters.Sources(root=root, state=state_dir(),
                                          sessions=claude_chat_pending.session_ids_by_chat(root))
    try:
        return claude_chat_waiters.collect(sources, now)
    except (RuntimeError, sqlite3.Error) as error:  # never stop blindly: every chat counts as waiting
        print(f"claude_idle_chats: {error}; every chat is kept this cycle", file=sys.stderr)
        return {UNREADABLE: [claude_chat_waiters.Waiter("", "background", "unreadable", str(error)[:120],
                                                        now, now + 3600)]}


def live_chats(claude_home: Path, config: dict, waiters: dict[str, list] | None = None) -> list[Chat]:
    chats: dict[str, Chat] = {}
    waiters = gather_waiters(time.time()) if waiters is None else waiters
    for record_path in sorted((claude_home / "sessions").glob("*.json")):
        try:
            record = json.loads(_read(record_path))
        except json.JSONDecodeError:
            continue
        pid = record.get("pid")
        if not isinstance(pid, int) or not Path(f"/proc/{pid}").exists():
            continue
        # A recycled pid belongs to another program: the start time must match.
        if str(record.get("procStart", "")) != _proc_start(pid):
            continue
        session_id = str(record.get("sessionId", ""))
        args = _cmdline_args(pid)
        zellij_env = _environ(pid)
        newest, speaker, text = transcript_state(claude_home, session_id)
        state_change = float(record.get("statusUpdatedAt") or record.get("startedAt") or 0) / 1000
        pending = transcript_pending(claude_home, session_id)
        chat = Chat(
            pid=pid, session_id=session_id, name=str(record.get("name", "")),
            status=str(record.get("status", "")), kind=classify(args, zellij_env, config["zellij_sessions"]),
            last_activity=max(state_change, newest), waiting_for=str(record.get("waitingFor") or ""),
            children=_children(pid), last_speaker=speaker, last_text=text,
            title=_flag(args, "--remote-control"), cwd=str(record.get("cwd") or ""),
            zellij_session=zellij_env.get("ZELLIJ_SESSION_NAME", ""), pane_id=zellij_env.get("ZELLIJ_PANE_ID", ""),
            model=_flag(args, "--model"), undelivered=pending.undelivered, refusal_kept=pending.refusal_kept,
            refusal_at=pending.refusal_at, waiters=waiters.get(session_id) or waiters.get(UNREADABLE) or [],
        )
        started = float(record.get("startedAt") or 0) / 1000
        for transcript in (claude_home / "projects").glob(f"*/{session_id}.jsonl"):
            chat.transcript = str(transcript)
            chat.agents = claude_chat_continue.running_agents(transcript, started, time.time())
        if (questions_dir() / f"{session_id}.json").exists():
            prompt_at = last_prompt_at(claude_home, session_id)
            chat.pushed_question = pushed_question(session_id, prompt_at)
            chat.pushed_done = pushed_done(pushed(session_id, prompt_at))
        previous = chats.get(session_id)
        if previous is None or previous.pid < pid:  # a resumed chat can leave an older process behind
            chats[session_id] = chat
    return list(chats.values())


# ---------------------------------------------------------------------------
# Acting, and the registry of stopped chats.
# ---------------------------------------------------------------------------


def stop(chat: Chat) -> bool:
    """SIGTERM (graceful shutdown; never SIGKILL); True when the process is gone within the wait."""
    expected_start = _proc_start(chat.pid)
    try:
        os.kill(chat.pid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    deadline = time.monotonic() + TERM_WAIT_SECONDS
    while time.monotonic() < deadline:
        if _proc_start(chat.pid) != expected_start:
            return True
        time.sleep(0.5)
    return False


def _utc(ts: float | None = None) -> str:
    return datetime.fromtimestamp(time.time() if ts is None else ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log_event(directory: Path, event: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "events.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"ts": _utc(), **event}, sort_keys=True) + "\n")


def load_registry(directory: Path) -> dict[str, dict]:
    path = directory / "stopped.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_registry(directory: Path, registry: dict[str, dict]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    tmp = directory / f".stopped.{os.getpid()}.tmp"
    tmp.write_text(json.dumps(registry, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, directory / "stopped.json")


def resume_command(chat: Chat) -> str:
    title = chat.title or chat.name
    model = f" --model {chat.model}" if chat.model else ""
    return f"claude --resume {chat.session_id} --remote-control {json.dumps(title)}{model}"


def record_stop(registry: dict[str, dict], chat: Chat, state: str, reason: str) -> None:
    registry[chat.session_id] = {
        "open_question": open_question(chat),
        "state": state, "reason": reason, "stopped_at": _utc(), "last_activity": _utc(chat.last_activity),
        "title": chat.title or chat.name, "cwd": chat.cwd, "kind": chat.kind, "model": chat.model,
        "zellij_session": chat.zellij_session, "resume": resume_command(chat),
    }


def refresh_registry(registry: dict[str, dict], live: list[Chat], now: float, config: dict) -> None:
    """Live again means resumed; stopped and idle past done_hours means done (to archive)."""
    live_ids = {chat.session_id for chat in live}
    for session_id in [sid for sid, entry in registry.items() if sid in live_ids and entry["state"] != "archived"]:
        del registry[session_id]
    for entry in registry.values():
        if entry["state"] == "stopped" and now - _iso(entry["last_activity"]) > config["done_hours"] * 3600:
            entry["state"] = "done"


def counts(live: list[Chat], registry: dict[str, dict], now: float, config: dict, own: str,
           queued: int = 0, waiting: list[dict] | None = None) -> dict:
    limit = config["idle_stop_minutes"] * 60
    working = sum(1 for chat in live if chat.status != "idle" or now - chat.last_activity <= limit)
    states = [entry["state"] for entry in registry.values()]
    return {
        "at": _utc(now), "running": len(live), "max_running": int(config["max_running"]),
        "working": working, "idle_running": len(live) - working,
        "idle_stopped": states.count("stopped"), "done_to_archive": states.count("done"),
        "archived": states.count("archived"), "queued_new_chats": queued,
        "waiting_running": sum(1 for entry in waiting or [] if entry["running"]),
        "waiting_closed": sum(1 for entry in waiting or [] if not entry["running"]),
        "idle_stop_minutes": config["idle_stop_minutes"], "done_hours": config["done_hours"],
    }


def queued_launches() -> int:
    queue = canonical_root() / "logs" / "claude-dispatch" / "pending"
    return len(list(queue.glob("*.json"))) if queue.is_dir() else 0


def write_status(directory: Path, summary: dict, registry: dict[str, dict], stalled: list[dict] | None = None,
                 unfinished_stops: list[dict] | None = None, waiting: list[dict] | None = None) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    done = [{"session_id": sid, **entry} for sid, entry in registry.items() if entry["state"] == "done"]
    stalled = stalled or []
    unfinished = [entry for entry in stalled if entry.get("unfinished_session")]
    tmp = directory / f".status.{os.getpid()}.tmp"
    tmp.write_text(json.dumps({**summary, "stalled_chats": len(stalled), "done": done, "stalled": stalled,
                               "unfinished_work": unfinished, "stopped_with_unfinished_work": unfinished_stops or [],
                               "waiting": waiting or []},
                              indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, directory / "status.json")


STALLED_MINUTES = 30


def load_marks(directory: Path, name: str) -> dict[str, str]:
    path = directory / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_marks(directory: Path, name: str, marks: dict[str, str]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    tmp = directory / f".{name}.{os.getpid()}.tmp"
    tmp.write_text(json.dumps(dict(sorted(marks.items())[-500:]), indent=1), encoding="utf-8")
    os.replace(tmp, directory / name)


def exit_cleanly(chat: Chat) -> bool:
    """Type /exit into a zellij-pane chat; True when its process ended (a clean exit archives its app session)."""
    if chat.kind != "pane" or not chat.pane_id:
        return False
    expected_start = _proc_start(chat.pid)
    if not wake(chat, "/exit"):
        return False
    deadline = time.monotonic() + TERM_WAIT_SECONDS
    while time.monotonic() < deadline:
        if _proc_start(chat.pid) != expected_start:
            zellij(chat.zellij_session, "close-pane", "--pane-id", f"terminal_{chat.pane_id}")
            return True
        time.sleep(0.5)
    return False


SETUP_OFFER = "Teach auto mode about your environment"  # Claude Code's onboarding offer; Esc declines it
DEAD_PANE_SECONDS = 120.0


def close_setup_offer(chat: Chat, directory: Path) -> bool:
    """Esc on the auto-mode setup offer of a pane chat; True when closed.

    The offer is no question for the owner (the dev connector's dialogs.py closes it too),
    but a chat behind it reports `waiting` and was never stopped: d2a774d9 sat behind it
    for 3.5 days with 1.4 GiB and, on 2026-11-20, about 250% CPU.
    """
    if chat.kind != "pane" or chat.waiting_for != "dialog open" or not chat.pane_id:
        return False
    pane = f"terminal_{chat.pane_id}"
    screen = zellij(chat.zellij_session, "dump-screen", "--pane-id", pane)
    if screen.returncode or SETUP_OFFER not in "\n".join(screen.stdout.splitlines()[-40:]):
        return False
    closed = not zellij(chat.zellij_session, "write", "--pane-id", pane, "27").returncode
    log_event(directory, {"event": "setup_offer_closed" if closed else "setup_offer_close_failed",
                          "session_id": chat.session_id, "title": chat.title or chat.name})
    return closed


def pane_owners() -> dict[str, set[str]]:
    """zellij session -> ids of its panes that still have a live process."""
    owners: dict[str, set[str]] = {}
    for proc in Path("/proc").iterdir():
        if proc.name.isdigit():
            env = _environ(int(proc.name))
            if "ZELLIJ_PANE_ID" in env:
                owners.setdefault(env.get("ZELLIJ_SESSION_NAME", ""), set()).add(env["ZELLIJ_PANE_ID"])
    return owners


HEADLESS_PLUGINS = frozenset({"zellij:link"})  # background plugins nobody needs in a session nobody attaches to


def close_dead_panes(sessions: list[str], directory: Path, now: float, owners: dict[str, set[str]] | None = None,
                     run=None, protected: dict[str, set[str]] | None = None) -> list[str]:
    """Tidy the managed zellij sessions; returns what was closed.

    * A terminal pane whose process ended (exited, held, or no live process with its
      pane id) is closed once seen dead in two cycles DEAD_PANE_SECONDS apart (a new tab
      has no process for a moment). The tab goes with it when it was the tab's only pane:
      `close-pane` from the CLI leaves an empty tab behind.
    * Empty tabs are closed once seen empty in two cycles DEAD_PANE_SECONDS apart.
    * The `zellij:link` background plugin is closed.
    * A session whose pane listing is incomplete is left alone this cycle: no terminal pane, a
      pane without its tab, or a live pane (a process with its ZELLIJ_PANE_ID, or a live chat
      the lifecycle knows: `protected`) missing from it. 2026-11-20 18:32 and 22:14 the tidy
      closed every tab of the `claude` session as "empty", with chats 70004807 and 4508e325
      working in them (TASK-7707).
    2026-11-20: the `claude` session held 58 dead panes and 57 empty tabs of 72 and its
    link plugin thread had used 43 CPU hours; closing them took the server from about 110%
    CPU and 900 MB to 29% and 180 MB, with every chat still running.
    """
    run = run or zellij
    owners = pane_owners() if owners is None else owners
    marks, seen, closed = load_marks(directory, "dead_panes.json"), {}, []
    for session in sessions:
        listing = run(session, "list-panes", "--json", "--tab")
        tabs = run(session, "list-tabs")
        if listing.returncode or tabs.returncode:
            continue
        try:
            panes = json.loads(listing.stdout or "[]")
        except ValueError:
            continue
        terminals = [pane for pane in panes if not pane.get("is_plugin")]
        listed = {str(pane.get("id")) for pane in terminals}
        live = owners.get(session, set()) | (protected or {}).get(session, set())
        if not terminals or any(pane.get("tab_id") is None for pane in terminals) or not live <= listed:
            log_event(directory, {"event": "zellij_tidy_skipped", "session": session,
                                  "why": "pane listing incomplete", "missing": sorted(live - listed)[:20]})
            continue
        per_tab: dict[int, int] = {}
        for pane in panes:
            per_tab[pane.get("tab_id")] = per_tab.get(pane.get("tab_id"), 0) + 1
        for pane in panes:
            if pane.get("is_plugin"):
                if pane.get("plugin_url") in HEADLESS_PLUGINS and not run(
                        session, "close-pane", "--pane-id", f"plugin_{pane['id']}").returncode:
                    closed.append(f"{session} plugin_{pane['id']} ({pane['plugin_url']})")
                continue
            pane_id = f"terminal_{pane['id']}"
            if str(pane["id"]) in (protected or {}).get(session, set()):
                continue  # a live chat the lifecycle knows, whatever the listing says
            if str(pane["id"]) in owners.get(session, set()) and not (pane.get("exited") or pane.get("is_held")):
                continue
            key = f"{session} {pane_id}"
            first = marks.get(key)
            if not first or now - _iso(first) < DEAD_PANE_SECONDS:
                seen[key] = first or _utc(now)
                continue
            alone = per_tab.get(pane.get("tab_id"), 0) <= 1 and pane.get("tab_id") is not None
            result = (run(session, "close-tab", "--tab-id", str(pane["tab_id"])) if alone
                      else run(session, "close-pane", "--pane-id", pane_id))
            if result.returncode:
                seen[key] = first
                continue
            closed.append(key)
            if alone:
                per_tab[pane["tab_id"]] = 0
        used = {pane.get("tab_id") for pane in panes}
        for line in tabs.stdout.splitlines()[1:]:
            tab = line.split()[0] if line.split() else ""
            if not tab.isdigit() or int(tab) in used:
                continue
            key = f"{session} tab {tab}"
            first = marks.get(key)
            if not first or now - _iso(first) < DEAD_PANE_SECONDS:
                seen[key] = first or _utc(now)
                continue
            if not run(session, "close-tab", "--tab-id", tab).returncode:
                closed.append(f"{session} empty tab {tab}")
    save_marks(directory, "dead_panes.json", seen)
    if closed:
        log_event(directory, {"event": "zellij_tidied", "closed": closed[:50], "count": len(closed)})
    return closed


def wake(chat: Chat, text: str = "") -> bool:
    """Type a wake prompt (default: its undelivered results) into the chat's pane; True when sent."""
    pane = f"terminal_{chat.pane_id}"
    for _ in range(30):
        screen = zellij(chat.zellij_session, "dump-screen", "--pane-id", pane)
        if screen.returncode:
            return False
        if not input_line(screen.stdout):
            break
        zellij(chat.zellij_session, "write", "--pane-id", pane, "21")  # Ctrl+U clears one input line
    else:
        return False
    typed = zellij(chat.zellij_session, "write-chars", "--pane-id", pane,
                   text or claude_chat_pending.wake_prompt(chat.undelivered))
    return not typed.returncode and not zellij(chat.zellij_session, "write", "--pane-id", pane, "13").returncode


def _stalled_entry(session_id: str, title: str, kind: str, last_activity: float, reason: str, **extra) -> dict:
    return {"session_id": session_id, "title": title, "kind": kind, "last_activity": _utc(last_activity),
            "reason": reason, **extra}


def stalled_chats(live: list[Chat], registry: dict[str, dict], claude_home: Path, now: float, directory: Path,
                  act: bool) -> list[dict]:
    """Chats owed background results or quiet while working; with act, wakes pane chats first."""
    woken = load_marks(directory, "woken.json")
    stalled: list[dict] = []
    for chat in live:
        title = chat.title or chat.name
        quiet = now - chat.last_activity
        if chat.undelivered:
            key = f"{chat.session_id} {','.join(item['task_id'] for item in chat.undelivered)}"
            if (act and key not in woken and chat.kind == "pane" and chat.status == "idle"
                    and not chat.waiting_for):
                sent = wake(chat)
                log_event(directory, {"event": "woken" if sent else "wake_failed", "session_id": chat.session_id,
                                      "title": title, "tasks": [i["task_id"] for i in chat.undelivered]})
                if sent:
                    woken[key] = _utc(now)
                    continue
            how = "woken, no reply yet" if key in woken else "needs a wake: send it a message"
            stalled.append(_stalled_entry(chat.session_id, title, chat.kind, chat.last_activity,
                                          f"finished background work never reached it ({how})",
                                          tasks=chat.undelivered))
        elif quiet > STALLED_MINUTES * 60 and not chat.waiters and (chat.status == "busy" or any(
                TOOL_SERVER_MARKER not in command.lower() for command in chat.children)):
            # A chat with waiters is reported as waiting (status.json `waiting`), and as
            # stalled only when a waiter times out (claude_chat_waiters.stalled_entries).
            doing = "working" if chat.status == "busy" else "runs a background command"
            stalled.append(_stalled_entry(chat.session_id, title, chat.kind, chat.last_activity,
                                          f"{doing}, no activity for {quiet / 60:.0f} min"))
    for session_id, entry in registry.items():
        if entry.get("state") not in ("stopped", "done"):
            continue
        pending = transcript_pending(claude_home, session_id)
        if pending.undelivered:
            stalled.append(_stalled_entry(
                session_id, entry.get("title", ""), entry.get("kind", ""), _iso(entry.get("last_activity")),
                f"stopped by the chat lifecycle at {entry.get('stopped_at')} ({entry.get('reason')}) with "
                "background results it never read: resume it (connector send_message)",
                tasks=pending.undelivered, stopped=True, resume=entry.get("resume", "")))
    if act:
        save_marks(directory, "woken.json", woken)
    return stalled


CONTINUE_MARKS = "continue_woken.json"


def continue_unfinished(chats: list[Chat], directory: Path, now: float, keep: set[str]) -> list[dict]:
    """Wake chats whose turn ended without ✅, question or waiter; returns the stalled ones (TASK-7707).

    A zellij-pane chat gets claude_chat_continue.CONTINUE_PROMPT once per turn end (again after
    RETRY_MINUTES when the line did not take, at most MAX_WAKES in a row without tool work).
    A chat that cannot be woken here, or did not act on MAX_WAKES wakes, stays running and is
    listed as stalled for the owner. `keep`: chats still marked (the rest are forgotten)."""
    marks = load_marks(directory, CONTINUE_MARKS)
    marks = {chat_id: mark for chat_id, mark in marks.items() if chat_id in keep}
    # Chats that handed off to a fresh chat (scripts/chat_compaction_handoff.py) are done here.
    handed_off = load_marks(directory, "handed_off.json")
    stalled = []
    for chat in chats:
        if chat.session_id in handed_off:
            continue
        mark = marks.get(chat.session_id) or {}
        worked = bool(mark) and bool(chat.transcript) and claude_chat_continue.worked_since(
            Path(chat.transcript), float(mark.get("at", 0)))
        step = claude_chat_continue.next_wake(marks, chat.session_id, chat.last_activity, now, worked)
        if step == "wait":
            continue
        if step == "wake" and chat.kind == "pane" and wake(chat, claude_chat_continue.CONTINUE_PROMPT):
            claude_chat_continue.record_wake(marks, chat.session_id, chat.last_activity, now)
            log_event(directory, {"event": "woken_to_continue", "session_id": chat.session_id,
                                  "title": chat.title or chat.name,
                                  "count": marks[chat.session_id]["count"]})
            continue
        why = (f"ended {claude_chat_continue.MAX_WAKES} turns in a row without ✅, question or waiter "
               "although woken to continue" if step == "stalled"
               else "ended its turn without ✅, question or waiter and cannot be woken here (no zellij pane)"
               if chat.kind != "pane" else "ended its turn without ✅, question or waiter; the wake failed")
        stalled.append(_stalled_entry(chat.session_id, chat.title or chat.name, chat.kind, chat.last_activity,
                                      f"{why}: it keeps running; look at it or answer it (connector send_message)"))
    save_marks(directory, CONTINUE_MARKS, marks)
    return stalled


FINISH_GRACE_MINUTES = 60.0


def guard_unfinished(plan: list[tuple[Chat, Decision]], directory: Path, now: float, *, pressure: bool,
                     dry_run: bool, finder=None) -> tuple[list[tuple[Chat, Decision]], list[dict]]:
    """Before a chat with unfinished worktree work is stopped: wake it once to finish.

    Every such worktree is snapshotted first (worktree_wip, refs/openmates/wip/<session>).
    A zellij-pane chat gets one finish prompt per worktree state and FINISH_GRACE_MINUTES
    to act; it is kept running meanwhile. When it cannot be woken (Remote Control
    worker, wake failed), the grace is over or the host is short on memory, it is
    stopped with its work snapshotted and flagged. Parked work is not woken.
    Returns (chats still to stop, flagged unfinished-work entries).
    """
    if not plan:
        return plan, []
    wanted = {chat.session_id for chat, _ in plan}
    rows = [row for row in worktree_wip.session_worktrees() if row["chat_id"] in wanted]
    by_chat: dict[str, list[dict]] = {}
    for entry in (finder or worktree_wip.unfinished)(rows=rows):
        if not entry.get("error") and not entry.get("parked"):
            by_chat.setdefault(entry["chat_id"], []).append(entry)
    marks = load_marks(directory, "finish_woken.json")
    to_stop, flagged = [], []
    for chat, decision in plan:
        entries = by_chat.get(chat.session_id)
        if not entries:
            to_stop.append((chat, decision))
            continue
        if dry_run:
            print(f"would wake or snapshot {chat.title or chat.name}: unfinished work in "
                  f"{', '.join(e['session_id'] for e in entries)}")
            continue
        trees = [worktree_wip.snapshot(entry, "lifecycle").get("tree", "") for entry in entries]
        key = f"{chat.session_id}:{'+'.join(trees)}"
        woken_at = _iso(marks[key]) if key in marks else 0.0
        if not pressure and woken_at and now - woken_at < FINISH_GRACE_MINUTES * 60:
            continue  # woken to finish; give it the grace period
        if not pressure and not woken_at and chat.kind == "pane" and wake(chat, worktree_wip.finish_prompt(entries)):
            marks[key] = _utc(now)
            log_event(directory, {"event": "woken_to_finish", "session_id": chat.session_id,
                                  "title": chat.title or chat.name, "worktrees": [e["session_id"] for e in entries]})
            continue
        why = ("host short on memory" if pressure else "no reply within the grace period" if woken_at
               else "cannot be woken here (no zellij pane)" if chat.kind != "pane" else "wake failed")
        flagged += [{"session_id": chat.session_id, "title": chat.title or chat.name, "worktree": e["session_id"],
                     "files": len(e["files"]), "wip_ref": worktree_wip.wip_ref(e["session_id"]), "why": why}
                    for e in entries]
        log_event(directory, {"event": "stopping_with_unfinished_work", "session_id": chat.session_id,
                              "why": why, "worktrees": [e["session_id"] for e in entries]})
        to_stop.append((chat, Decision(decision.action, f"{decision.reason}; unfinished work snapshotted ({why})")))
    save_marks(directory, "finish_woken.json", marks)
    return to_stop, flagged


def unfinished_stalled(registry: dict[str, dict], status: dict | None = None) -> list[dict]:
    """Stopped chats whose worktrees hold unfinished, unparked work (from worktree_wip status.json)."""
    if status is None:
        try:
            status = json.loads((worktree_wip.state_dir() / "status.json").read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
    stalled = []
    for entry in status.get("unfinished") or []:
        stopped = registry.get(entry.get("chat_id") or "")
        if entry.get("parked") or not stopped or stopped.get("state") not in ("stopped", "done"):
            continue
        stalled.append(_stalled_entry(
            entry["chat_id"], stopped.get("title", ""), stopped.get("kind", ""), _iso(stopped.get("last_activity")),
            f"stopped with unfinished work in session {entry['session_id']} ({entry['files']} files not on dev, "
            f"WIP snapshot {worktree_wip.wip_ref(entry['session_id'])}): resume it to commit, test and deploy "
            "(connector send_message); the nightly worktree check resumes it automatically",
            stopped=True, resume=stopped.get("resume", ""), unfinished_session=entry["session_id"]))
    return stalled


def status_line(summary: dict) -> str:
    return (f"Chats: {summary['running']} running of max {summary['max_running']} "
            f"({summary['working']} working, {summary['idle_running']} idle but kept for an open question "
            f"or unanswered message), "
            f"{summary['idle_stopped']} idle-stopped, {summary['done_to_archive']} done to archive, "
            f"{summary['archived']} archived, {summary['queued_new_chats']} new chats queued, "
            f"{summary.get('waiting_running', 0)} running and {summary.get('waiting_closed', 0)} closed chats "
            "waiting on disk, CI or a handoff"
            + (f", {summary['stalled_chats']} stalled." if "stalled_chats" in summary else "."))


def run_cycle(args: argparse.Namespace, config: dict, room: int = 0) -> tuple[list[Chat], int]:
    """One reap pass; returns (chats left running, failures)."""
    now = time.time()
    own = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    directory = state_dir()
    waiters = gather_waiters(now)
    live = sorted(live_chats(args.claude_home, config, waiters), key=lambda item: item.last_activity)
    registry = load_registry(directory)
    refresh_registry(registry, live, now, config)
    if args.command != "list" and not args.dry_run:
        for chat in live:
            close_setup_offer(chat, directory)  # declined; the next cycle sees its real state
    idle_minutes = (min(config["pressure_idle_minutes"], config["idle_stop_minutes"])
                    if getattr(args, "pressure", False) else None)
    plan: list[tuple[Chat, Decision]] = []
    continuing: list[Chat] = []
    for chat in live:
        decision = decide(chat, now, config, own, idle_minutes)
        if args.command == "list":
            print(f"{decision.action:5}  {chat.title or chat.name} ({chat.session_id[:8]}, pid {chat.pid}, "
                  f"{chat.kind}): {decision.reason}")
        elif decision.close:
            plan.append((chat, decision))
        elif decision.action == "continue":
            continuing.append(chat)
    if args.command == "list":
        return live, 0
    unfinished = [chat.session_id for chat in live if not closable(chat)]  # their wake counts stay
    continue_stalled = ([] if args.dry_run else continue_unfinished(continuing, directory, now, set(unfinished)))
    for chat in continuing if args.dry_run else []:
        print(f"would wake {chat.title or chat.name} ({chat.session_id[:8]}) to continue")
    chosen = {chat.session_id for chat, _ in plan}
    remaining = [chat for chat in live if chat.session_id not in chosen]
    for chat in cap_victims(remaining, now, config, own, room):
        plan.append((chat, Decision("stop", f"over the cap of {config['max_running']} running chats")))
    plan, flagged = guard_unfinished(plan, directory, now, pressure=bool(getattr(args, "pressure", False)),
                                     dry_run=args.dry_run)
    failed, stopped = 0, set()
    for chat, decision in plan:
        label = f"{chat.title or chat.name} ({chat.session_id[:8]}, pid {chat.pid})"
        if args.dry_run:
            print(f"would stop {label}: {decision.reason}")
            continue
        exited = decision.action == "archive" and exit_cleanly(chat)
        ok = exited or stop(chat)
        failed += 0 if ok else 1
        print(f"{'archived' if exited else 'stopped' if ok else 'STILL RUNNING'} {label}: {decision.reason}")
        log_event(directory, {"event": "archived" if exited else "stopped" if ok else "stop_failed",
                              "reason": decision.reason, "session_id": chat.session_id, "pid": chat.pid,
                              "kind": chat.kind, "title": chat.title or chat.name})
        if ok:
            stopped.add(chat.session_id)
            state = "archived" if exited else "stopped" if decision.action == "stop" else "done"
            record_stop(registry, chat, state, decision.reason)
            if decision.action == "archive":
                registry[chat.session_id]["reported_done"] = True  # the connector archives it without approval
            if exited:
                registry[chat.session_id]["archived_at"] = _utc(now)
            if decision.reopen and claude_chat_waiters.UUID_RE.match(chat.session_id):
                claude_chat_waiters.add(directory, chat.session_id, "timer", claude_chat_continue.REOPEN_MESSAGE,
                                        at=now + claude_chat_continue.REOPEN_MINUTES * 60)
    left = [chat for chat in live if chat.session_id not in stopped]
    if not args.dry_run:
        save_registry(directory, registry)
        protected: dict[str, set[str]] = {}
        for chat in left:
            if chat.pane_id:
                protected.setdefault(chat.zellij_session, set()).add(chat.pane_id)
        close_dead_panes(list(config["zellij_sessions"]), directory, now, protected=protected)
        waiters.pop(UNREADABLE, None)
        wake_failures = wake_waiting(waiters, left, registry, directory, now, config)
        try:  # chat mailbox: stale messages wake their recipient; an error here never breaks reap
            import chat_mailbox  # noqa: E402  (sibling script)
            chat_mailbox.deliver_stale(now=now, chats=left, log=lambda event: log_event(directory, event))
        except Exception as error:  # noqa: BLE001  (best effort side channel)
            log_event(directory, {"event": "mailbox_error", "error": str(error)[:200]})
        stalled = stalled_chats(left, registry, args.claude_home, now, directory, act=True)
        live_map = {chat.session_id: chat for chat in left}
        for entry in (continue_stalled + unfinished_stalled(registry) + wake_failures
                      + claude_chat_waiters.stalled_entries(waiters, live_map, registry, now)):
            if entry["session_id"] not in {item["session_id"] for item in stalled}:
                stalled.append(entry)
        waiting = claude_chat_waiters.status_entries(waiters, live_map, registry, now)
        write_status(directory, counts(left, registry, now, config, own, queued_launches(), waiting), registry,
                     stalled, flagged, waiting)
    return left, failed


PRIORITY_RANK = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
TASKS_CACHE = Path.home() / ".local/state/openmates/tasks-cache.json"  # scripts/daily_meeting_tasks_cache.py


def task_priorities(cache: Path | None = None) -> dict[str, int]:
    """chat id -> rank of its most urgent open Task (0 urgent .. 3 low), from the hourly Tasks copy."""
    try:
        data = json.loads((cache or TASKS_CACHE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}  # no copy yet: wakes go in chat order
    ranks: dict[str, int] = {}
    for task in ((data.get("data") or {}).get("tasks") or []) if isinstance(data, dict) else []:
        link = task.get("external_chat") or {}
        if task.get("status") == "done" or link.get("provider") != "claude" or not link.get("id"):
            continue
        rank = PRIORITY_RANK.get(str(task.get("priority_level") or "").lower(), 4)
        ranks[link["id"]] = min(rank, ranks.get(link["id"], 4))
    return ranks


def wake_waiting(waiters: dict[str, list], left: list[Chat], registry: dict[str, dict], directory: Path,
                 now: float, config: dict) -> list[dict]:
    """Wake or reopen every chat whose wait is over (claude_chat_waiters.deliver); returns failures."""
    import claude_dispatch  # noqa: E402  (sibling script; imports nothing from here)

    resumed: list[str] = []

    def reopen(chat_id: str, text: str) -> str:
        try:
            outcome = claude_dispatch.resume_chat(chat_id, text, title=f"wake {chat_id[:8]}", admitted=True)
        except (claude_dispatch.DispatchError, subprocess.SubprocessError, OSError) as error:
            return f"resume failed: {error}"[:200]
        if outcome == "ok":
            resumed.append(chat_id)
        return outcome

    free = int(config["max_running"]) - len(left) - int(config["free_slots"])
    delivered, failures = claude_chat_waiters.deliver(
        waiters, {chat.session_id: chat for chat in left}, registry, directory, now, type_into=wake,
        resume=reopen, room=max(0, min(int(config["wake_batch"]), free)),
        log=lambda event: log_event(directory, event), asks=asks, priority=task_priorities())
    claude_chat_waiters.remember(directory, waiters, delivered)
    if resumed:  # resume_chat marked them resumed on disk; keep this cycle's copy in step
        for chat_id in resumed:
            registry.pop(chat_id, None)
        save_registry(directory, registry)
    return failures


def zellij(session: str, *args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    return subprocess.run(["zellij", "--session", session, "action", *args], capture_output=True, text=True,
                          timeout=30, env=env, check=False)


def input_line(screen: str) -> str:
    """Text after the last prompt marker on a Claude Code screen ('' when the input box is empty)."""
    prompts = [line.strip() for line in screen.splitlines() if line.strip().startswith("\u276f")]
    return prompts[-1][1:].strip() if prompts else ""


def held_prompts(live: list[Chat]) -> list[Chat]:
    """Idle pane chats whose last turn is a prompt the hook refused, oldest refusal first."""
    return sorted((chat for chat in live if chat.kind == "pane" and chat.status == "idle" and not chat.waiting_for
                   and chat.last_speaker == "user" and chat.last_text.startswith(REFUSED_PREFIX)
                   and chat.refusal_kept is not False and not chat.undelivered),
                  key=lambda chat: chat.last_activity)


def release(claude_home: Path, config: dict, limit: int) -> int:
    directory = state_dir()
    released = lost = 0
    done = load_marks(directory, "released.json")
    for chat in held_prompts(live_chats(claude_home, config)):
        if released >= limit:
            break
        label = f"{chat.title or chat.name} ({chat.session_id[:8]})"
        key = f"{chat.session_id} {chat.refusal_at}"
        if key in done:
            continue  # one Enter per refusal: pressing it every minute changed nothing on 2026-11-14
        pane = f"terminal_{chat.pane_id}"
        screen = zellij(chat.zellij_session, "dump-screen", "--pane-id", pane)
        if screen.returncode:
            print(f"skipped {label}: zellij dump-screen failed: {screen.stderr.strip()[:120]}")
            continue
        import claude_chat_inputs  # imports this module, so not at the top

        # The box may show only Claude Code's grey suggestion over an empty box: Enter does
        # nothing there (2026-11-15), so it counts as lost, never as released.
        if claude_chat_inputs.probe(zellij, chat.zellij_session, pane) != "typed":
            lost += 1
            print(f"lost {label}: the refused prompt is no longer in its input box; resend it")
            log_event(directory, {"event": "held_prompt_lost", "session_id": chat.session_id, "title": label})
            continue
        sent = zellij(chat.zellij_session, "write", "--pane-id", pane, "13")
        released += 0 if sent.returncode else 1
        done[key] = _utc()
        save_marks(directory, "released.json", done)
        print(f"{'released' if not sent.returncode else 'FAILED to release'} {label}")
        log_event(directory, {"event": "held_prompt_released" if not sent.returncode else "held_prompt_failed",
                              "session_id": chat.session_id, "title": label})
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("list", "reap", "status", "admit", "mark", "release"))
    parser.add_argument("--limit", type=int, default=2)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--pressure", action="store_true", help="host short on memory: shorter idle limit")
    parser.add_argument("--idle-minutes", type=float)
    parser.add_argument("--done-hours", type=float)
    parser.add_argument("--max-running", type=int)
    parser.add_argument("--session", default="")
    parser.add_argument("--state", choices=("archived", "resumed"))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--claude-home", type=Path, default=Path.home() / ".claude")
    args = parser.parse_args(argv)
    config = load_config()
    for key, value in (("idle_stop_minutes", args.idle_minutes), ("done_hours", args.done_hours),
                       ("max_running", args.max_running)):
        if value is not None:
            config[key] = value

    if args.command == "mark":
        return mark(args.session, args.state)
    if args.command == "release":
        return release(args.claude_home, config, args.limit)
    if args.command == "status":
        now, directory = time.time(), state_dir()
        waiters = gather_waiters(now)
        live = live_chats(args.claude_home, config, waiters)
        waiters.pop(UNREADABLE, None)
        registry = load_registry(directory)
        refresh_registry(registry, live, now, config)
        save_registry(directory, registry)
        live_map = {chat.session_id: chat for chat in live}
        waiting = claude_chat_waiters.status_entries(waiters, live_map, registry, now)
        summary = counts(live, registry, now, config, os.environ.get("CLAUDE_CODE_SESSION_ID", ""),
                         queued_launches(), waiting)
        stalled = stalled_chats(live, registry, args.claude_home, now, directory, act=False)
        stalled += [entry for entry in claude_chat_waiters.stalled_entries(waiters, live_map, registry, now)
                    if entry["session_id"] not in {item["session_id"] for item in stalled}]
        write_status(directory, summary, registry, stalled, waiting=waiting)
        summary["stalled_chats"] = len(stalled)
        print(json.dumps(summary, indent=1) if args.json else status_line(summary))
        return 0
    if args.command == "admit":
        args.command = "reap"
        left, _ = run_cycle(args, config, room=1)
        if len(left) < int(config["max_running"]):
            return 0
        print(f"no room: {len(left)} chats run (max {config['max_running']}) and none may be suspended now "
              "(all working, waiting or recently active)")
        return EXIT_NO_ROOM
    _, failed = run_cycle(args, config)
    return 1 if failed else 0


def mark(session_id: str, state: str | None) -> int:
    if not session_id or not state:
        raise SystemExit("mark needs --session and --state")
    directory = state_dir()
    registry = load_registry(directory)
    if state == "resumed":
        registry.pop(session_id, None)
    elif session_id in registry:
        registry[session_id]["state"] = "archived"
        registry[session_id]["archived_at"] = _utc()
    else:
        registry[session_id] = {"state": "archived", "archived_at": _utc(), "last_activity": _utc()}
    save_registry(directory, registry)
    log_event(directory, {"event": f"marked_{state}", "session_id": session_id})
    return 0


if __name__ == "__main__":
    sys.exit(main())
