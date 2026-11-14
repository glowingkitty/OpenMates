"""Chat lifecycle for Claude Code chats on the dev host: working, idle-stopped, done.

Every chat holds a Claude Code process (about 0.4 GB with its tool servers) until it
exits. Finished chats used to pile up (40 processes, about 14 GB on 2026-11-14) and
starve the host-resources guard. This script keeps them in check:

  working       the chat runs normally (busy, waiting for a permission or an answer,
                running a background command, or active recently).
  idle-stopped  no activity for `idle_stop_minutes` (default 60) and nothing open:
                its process gets SIGTERM, a graceful shutdown. The transcript stays
                on disk; a new message (connector send_message, which resumes with
                `claude --resume <id>`) brings it back with the same history.
  done          finished with nothing open and idle for `done_hours` (default 24):
                listed in the status file so the connector archives it in the Claude
                app (one implementation, in the connector) and it stops counting
                against the app's session limit.

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
  * its last turn is a message without a reply, including a prompt a hook refused.
The cap keeps a chat active in the last `cap_min_idle_minutes` and suspends chats
without an open question first; a chat whose last reply asks something is suspended
only after `cap_question_idle_hours` without an answer (the connector resumes it
when the answer comes). Idle stop and done never stop a chat with an open question.

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
           a zellij-pane chat whose last turn is a refused prompt still holds it
           in its input box, so Enter sends it (the host-resources guard runs
           this only while the host is healthy)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

DEFAULTS = {
    "idle_stop_minutes": 60.0,
    "done_hours": 24.0,
    "max_running": 20,
    "cap_min_idle_minutes": 10.0,
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


@dataclass
class Decision:
    action: str  # keep | stop | done
    reason: str
    hard: bool = False  # kept by a hard rule (the cap may not override it)

    @property
    def close(self) -> bool:
        return self.action in ("stop", "done")


def asks_something(text: str) -> bool:
    """Open question or request in the end of a reply (URLs and code spans ignored)."""
    tail = URL_OR_CODE_RE.sub(" ", text.strip()[-1200:])
    return bool(QUESTION_RE.search(tail))


def hard_blocker(chat: Chat, own_session_id: str) -> str | None:
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
    if chat.last_speaker == "user":
        return "its last message has no reply"
    return None


def decide(chat: Chat, now: float, config: dict, own_session_id: str, idle_minutes: float | None = None) -> Decision:
    """Pure rule: what happens to this chat's process now."""
    reason = hard_blocker(chat, own_session_id)
    if reason:
        return Decision("keep", reason, hard=True)
    idle = now - chat.last_activity
    limit = 60 * (config["idle_stop_minutes"] if idle_minutes is None else idle_minutes)
    if idle <= limit:
        return Decision("keep", f"idle {idle / 60:.0f} min, limit {limit / 60:.0f} min")
    if asks(chat):
        return Decision("keep", "its last reply asks something")
    if idle > config["done_hours"] * 3600:
        return Decision("done", f"idle {idle / 3600:.1f}h, finished")
    return Decision("stop", f"idle {idle / 60:.0f} min")


def cap_victims(chats: list[Chat], now: float, config: dict, own_session_id: str, room: int = 0) -> list[Chat]:
    """Chats to suspend so that at most max_running - room processes run; longest idle first."""
    excess = len(chats) + room - int(config["max_running"])
    if excess <= 0:
        return []
    minimum = config["cap_min_idle_minutes"] * 60
    question_minimum = config["cap_question_idle_hours"] * 3600
    eligible = [chat for chat in chats if hard_blocker(chat, own_session_id) is None
                and now - chat.last_activity > minimum]
    plain = [chat for chat in eligible if not asks(chat)]
    asking = [chat for chat in eligible if asks(chat) and now - chat.last_activity > question_minimum]
    by_idle = lambda chat: chat.last_activity  # noqa: E731 - sort key, oldest activity first
    return (sorted(plain, key=by_idle) + sorted(asking, key=by_idle))[:excess]


def asks(chat: Chat) -> bool:
    return chat.last_speaker == "assistant" and asks_something(chat.last_text)


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


def classify(args: list[str], zellij_env: dict[str, str], sessions: list[str]) -> str:
    command = " ".join(args)
    if all(marker in command for marker in WORKER_MARKERS):
        return "rc_worker"
    if zellij_env.get("ZELLIJ_PANE_ID") and zellij_env.get("ZELLIJ_SESSION_NAME") in sessions:
        return "pane"
    return "terminal"


def live_chats(claude_home: Path, config: dict) -> list[Chat]:
    chats: dict[str, Chat] = {}
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
        chat = Chat(
            pid=pid, session_id=session_id, name=str(record.get("name", "")),
            status=str(record.get("status", "")), kind=classify(args, zellij_env, config["zellij_sessions"]),
            last_activity=max(state_change, newest), waiting_for=str(record.get("waitingFor") or ""),
            children=_children(pid), last_speaker=speaker, last_text=text,
            title=_flag(args, "--remote-control"), cwd=str(record.get("cwd") or ""),
            zellij_session=zellij_env.get("ZELLIJ_SESSION_NAME", ""), pane_id=zellij_env.get("ZELLIJ_PANE_ID", ""),
            model=_flag(args, "--model"),
        )
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
        "open_question": " ".join(chat.last_text.split())[-300:] if asks(chat) else "",
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
           queued: int = 0) -> dict:
    limit = config["idle_stop_minutes"] * 60
    working = sum(1 for chat in live if chat.status != "idle" or now - chat.last_activity <= limit)
    states = [entry["state"] for entry in registry.values()]
    return {
        "at": _utc(now), "running": len(live), "max_running": int(config["max_running"]),
        "working": working, "idle_running": len(live) - working,
        "idle_stopped": states.count("stopped"), "done_to_archive": states.count("done"),
        "archived": states.count("archived"), "queued_new_chats": queued,
        "idle_stop_minutes": config["idle_stop_minutes"], "done_hours": config["done_hours"],
    }


def queued_launches() -> int:
    queue = canonical_root() / "logs" / "claude-dispatch" / "pending"
    return len(list(queue.glob("*.json"))) if queue.is_dir() else 0


def write_status(directory: Path, summary: dict, registry: dict[str, dict]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    done = [{"session_id": sid, **entry} for sid, entry in registry.items() if entry["state"] == "done"]
    tmp = directory / f".status.{os.getpid()}.tmp"
    tmp.write_text(json.dumps({**summary, "done": done}, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, directory / "status.json")


def status_line(summary: dict) -> str:
    return (f"Chats: {summary['running']} running of max {summary['max_running']} "
            f"({summary['working']} working, {summary['idle_running']} idle but kept for an open question "
            f"or unanswered message), "
            f"{summary['idle_stopped']} idle-stopped, {summary['done_to_archive']} done to archive, "
            f"{summary['archived']} archived, {summary['queued_new_chats']} new chats queued.")


def run_cycle(args: argparse.Namespace, config: dict, room: int = 0) -> tuple[list[Chat], int]:
    """One reap pass; returns (chats left running, failures)."""
    now = time.time()
    own = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    directory = state_dir()
    live = sorted(live_chats(args.claude_home, config), key=lambda item: item.last_activity)
    registry = load_registry(directory)
    refresh_registry(registry, live, now, config)
    idle_minutes = config["pressure_idle_minutes"] if getattr(args, "pressure", False) else None
    plan: list[tuple[Chat, Decision]] = []
    for chat in live:
        decision = decide(chat, now, config, own, idle_minutes)
        if args.command == "list":
            print(f"{decision.action:5}  {chat.title or chat.name} ({chat.session_id[:8]}, pid {chat.pid}, "
                  f"{chat.kind}): {decision.reason}")
        elif decision.close:
            plan.append((chat, decision))
    if args.command == "list":
        return live, 0
    chosen = {chat.session_id for chat, _ in plan}
    remaining = [chat for chat in live if chat.session_id not in chosen]
    for chat in cap_victims(remaining, now, config, own, room):
        plan.append((chat, Decision("stop", f"over the cap of {config['max_running']} running chats")))
    failed, stopped = 0, set()
    for chat, decision in plan:
        label = f"{chat.title or chat.name} ({chat.session_id[:8]}, pid {chat.pid})"
        if args.dry_run:
            print(f"would stop {label}: {decision.reason}")
            continue
        ok = stop(chat)
        failed += 0 if ok else 1
        print(f"{'stopped' if ok else 'STILL RUNNING'} {label}: {decision.reason}")
        log_event(directory, {"event": "stopped" if ok else "stop_failed", "reason": decision.reason,
                              "session_id": chat.session_id, "pid": chat.pid, "kind": chat.kind,
                              "title": chat.title or chat.name})
        if ok:
            stopped.add(chat.session_id)
            record_stop(registry, chat, "done" if decision.action == "done" else "stopped", decision.reason)
    left = [chat for chat in live if chat.session_id not in stopped]
    if not args.dry_run:
        save_registry(directory, registry)
        write_status(directory, counts(left, registry, now, config, own, queued_launches()), registry)
    return left, failed


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
                   and chat.last_speaker == "user" and chat.last_text.startswith(REFUSED_PREFIX)),
                  key=lambda chat: chat.last_activity)


def release(claude_home: Path, config: dict, limit: int) -> int:
    directory = state_dir()
    released = lost = 0
    for chat in held_prompts(live_chats(claude_home, config)):
        if released >= limit:
            break
        label = f"{chat.title or chat.name} ({chat.session_id[:8]})"
        pane = f"terminal_{chat.pane_id}"
        screen = zellij(chat.zellij_session, "dump-screen", "--pane-id", pane)
        if screen.returncode:
            print(f"skipped {label}: zellij dump-screen failed: {screen.stderr.strip()[:120]}")
            continue
        if not input_line(screen.stdout):
            lost += 1
            print(f"lost {label}: the refused prompt is no longer in its input box; resend it")
            log_event(directory, {"event": "held_prompt_lost", "session_id": chat.session_id, "title": label})
            continue
        sent = zellij(chat.zellij_session, "write", "--pane-id", pane, "13")
        released += 0 if sent.returncode else 1
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
        live = live_chats(args.claude_home, config)
        registry = load_registry(directory)
        refresh_registry(registry, live, now, config)
        save_registry(directory, registry)
        summary = counts(live, registry, now, config, os.environ.get("CLAUDE_CODE_SESSION_ID", ""),
                         queued_launches())
        write_status(directory, summary, registry)
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
