#!/usr/bin/env python3
"""Hand a repeatedly compacted Claude or Codex chat off to a fresh chat with a summary.

A chat compacted several times works on a lossy summary and burns tokens re-reading:
after a compaction its context restarts near 94k tokens instead of a fresh chat's 52k,
and each call after the 2nd compaction costs about 11% more (7 days to 23 Nov).
Policy (owner decision, 23 Nov, receipt 5096e6d1abf8b55f; was the 4th since 22 Nov):
the 1st compaction announces the handoff, the 2nd and later, or a clearly oversized
chat (usage watch: TOKEN_NOTICE_UNITS weighted tokens, scripts/chat_usage_watch.py),
tell the chat to hand off now. The compaction limit itself is unchanged.

The handoff note has the sections of NOTE_SECTIONS (done, not done, next step, open
decisions, references to commits and files); `handoff` refuses a note without them,
writes it into the Task's activity, starts the fresh chat with it, and archives the
old chat: it writes the chat's ✅ marker (no Discord push), so the lifecycle
archives the old chat once it is idle (claude_idle_chats.decide).

Subcommands:
  hook      SessionStart hook (matcher `compact`): counts the compaction per chat in
            <canonical repo>/logs/claude-chat-lifecycle/compactions.json and prints
            the policy note on stdout (SessionStart additionalContext). Sub-agents
            (payload has agent_id) are ignored. Fails open: any problem prints nothing.
  hook-prompt  UserPromptSubmit: repeats the hand-off-now note on every prompt of a
            chat that is due (2+ compactions or oversized) and has not handed off yet.
  handoff   --summary-file F [--session S] [--chat C] [--task T] [--dry-run]: starts a fresh chat
            with the summary as its first prompt (scripts/claude_dispatch.launch_claude_chat),
            detaches the sessions.py session from the old chat so the new chat can adopt
            it with `sessions.py worktree bind-task`, and adds a line to the chat's Task.
            Registers no waiter, so the lifecycle never wakes the old chat again.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import subprocess
import time
import sys
from pathlib import Path
import shlex

SCRIPT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_ROOT / "scripts"))

NOTE_AT = 1
HANDOFF_AT = 2
NOTE_SECTIONS = ("Done", "Not done", "Next step", "Open decisions", "References")
ACTIVITY_MAX_CHARS = 6000
TOKEN_NOTICE_UNITS = 100_000_000
CONTEXT_WINDOW_FRACTION = 0.8
CLAUDE_CONTEXT_TOKENS = 180_000
NOTE_TEMPLATE = ("## Done\n...\n## Not done\n...\n## Next step\n...\n## Open decisions\n... (or: none)\n"
                 "## References\ncommits, files, sessions.py session, CI/deploy job ids")


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


def state_file(root: Path | None = None) -> Path:
    return (root or canonical_root()) / "logs" / "claude-chat-lifecycle" / "compactions.json"


def handed_off_file(root: Path | None = None) -> Path:
    """Chats that handed off; the lifecycle never nudges them to continue (claude_idle_chats)."""
    return (root or canonical_root()) / "logs" / "claude-chat-lifecycle" / "handed_off.json"


def mark_handed_off(chat_id: str, successor: str, path: Path | None = None) -> None:
    path = path or handed_off_file()
    _update_state(path, chat_id, lambda _: {"successor": successor})


def bump_count(chat_id: str, path: Path) -> int:
    """Increment and return the compaction count of one chat."""
    return _update_state(path, chat_id, lambda count: int(count or 0) + 1)


def _load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _update_state(path: Path, chat_id: str, update):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = _load(path)
        data[chat_id] = update(data.get(chat_id))
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)
        return data[chat_id]


def policy_note(count: int) -> str:
    """The text injected into the chat after its `count`-th compaction ('' below NOTE_AT)."""
    if count < NOTE_AT:
        return ""
    if count < HANDOFF_AT:
        return (f"This chat was compacted {count} time(s). At the next compaction it hands off to a fresh "
                "chat on the same Task (python3 scripts/chat_compaction_handoff.py handoff).")
    return handoff_now(f"This chat was compacted {count} times and now works on a lossy summary.")


def handoff_now(reason: str) -> str:
    """The hand-off-now instruction with the note format."""
    return (
        f"{reason} Hand off NOW (owner decision, 23 Nov): finish or stop the current step, write the "
        f"handoff note to a file with these Markdown sections: {', '.join(NOTE_SECTIONS)}:\n"
        f"{NOTE_TEMPLATE}\nThen run `python3 scripts/chat_compaction_handoff.py handoff --summary-file "
        "<file>` (add `--task <task-id>` when this chat has several open Tasks). It writes the note into "
        "the Task, starts a fresh chat on the same session and Task, and archives this chat. Then end this "
        "turn and do no further work; send no push."
    )


def due_reason(chat_id: str, counts_path: Path | None = None, usage_path: Path | None = None,
               handed_path: Path | None = None, codex_path: Path | None = None) -> str:
    """Why this chat must hand off now ('' when it need not, or already did)."""
    root = canonical_root() if None in (counts_path, usage_path, handed_path) else None
    if chat_id in _load(handed_path or handed_off_file(root)):
        return ""
    count = int(_load(counts_path or state_file(root)).get(chat_id, 0) or 0)
    usage = _load(usage_path or (root / "logs" / "claude-chat-lifecycle" / "usage-watch.json"))
    if codex_path is not None:
        import codex_chats

        metrics = codex_chats.rollout_metrics(codex_path, (usage.get("files") or {}).get(str(codex_path)))
        count = max(count, metrics.get("compactions", 0))
        window = metrics.get("window", 0)
        if window and metrics.get("context", 0) >= CONTEXT_WINDOW_FRACTION * window:
            return "This chat's context reached 80% of its context window."
        if metrics.get("units", 0) >= TOKEN_NOTICE_UNITS:
            return f"This chat is oversized: {metrics['units'] / 1e6:.0f}M weighted tokens so far."
    if count >= HANDOFF_AT:
        return f"This chat was compacted {count} times and now works on a lossy summary."
    units = (usage.get("oversized") or {}).get(chat_id)
    if units:
        return f"This chat is oversized: {float(units) / 1e6:.0f}M weighted tokens so far."
    return ""


def claude_context(path: Path) -> int:
    """Latest known full input size, including reads and writes to the prompt cache."""
    with path.open("rb") as stream:
        end = stream.seek(0, os.SEEK_END)
        stream.seek(max(0, end - 1024 * 1024))
        if end > 1024 * 1024:
            stream.readline()
        lines = stream.read().splitlines()
    for line in reversed(lines):
        if b'"usage"' not in line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        usage = (record.get("message") or {}).get("usage")
        if record.get("type") == "assistant" and isinstance(usage, dict):
            return sum(int(usage.get(field) or 0) for field in (
                "input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
    return 0


def hook_prompt(raw: str, **paths) -> str:
    """UserPromptSubmit body: the hand-off-now note for a due chat, else ''. Never raises."""
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict) or payload.get("agent_id"):
            return ""
        chat_id = str(payload.get("session_id") or "")
        if not chat_id:
            return ""
        thread = payload.get("codex_thread_id")
        if thread and "codex_path" not in paths:
            import codex_chats

            transcript = payload.get("transcript_path")
            paths["codex_path"] = Path(transcript) if transcript else codex_chats.rollout_path(thread)
        reason = due_reason(chat_id, **paths)
        transcript = payload.get("transcript_path")
        if not reason and not thread and transcript:
            handed_path = paths.get("handed_path") or handed_off_file()
            if chat_id not in _load(handed_path) and claude_context(Path(transcript)) >= CLAUDE_CONTEXT_TOKENS:
                reason = f"This chat's most recent input context reached {CLAUDE_CONTEXT_TOKENS:,} tokens."
        return handoff_now(reason) if reason else ""
    except (OSError, ValueError, TypeError):
        return ""


def hook_stop(raw: str) -> str:
    """When due, interrupt one attempted turn end so the chat can write its handoff."""
    payload = json.loads(raw)
    if not isinstance(payload, dict) or payload.get("stop_hook_active") or payload.get("agent_id"):
        return ""
    chat_id = payload.get("session_id")
    if chat_id:
        import ci_triage_gate

        root = canonical_root()
        brake = ci_triage_gate.active_brake(root, chat_id)
        if brake:
            if ci_triage_gate.already_asked(root, chat_id, brake):
                return ""
            reason = ci_triage_gate.brake_refusal(brake["targets"])
            return json.dumps({"decision": "block", "reason": reason})
        marker_path = root / "logs" / "claude-idle-chats" / "questions" / f"{chat_id}.json"
        marker = _load(marker_path)
        if marker.get("kind") == "❓" or marker.get("paused_until"):
            return ""
    note = hook_prompt(raw)
    return json.dumps({"decision": "block", "reason": note}) if note else ""


_NAMES = r"not done|done|next steps?|open decisions|references"
_HEADING = re.compile(rf"^\s*(?:#+\s*\**\s*({_NAMES})\s*\**\s*:?|\**\s*({_NAMES})\s*\**\s*:\**)\s*(.*)$", re.I)


def missing_sections(note: str) -> list[str]:
    """NOTE_SECTIONS without a heading ('## Done' or 'Done:') that has text under or after it."""
    bodies: dict[str, str] = {}
    current = ""
    for line in note.splitlines():
        match = _HEADING.match(line)
        if match:
            name = (match.group(1) or match.group(2)).lower()
            current = "next step" if name.startswith("next step") else name
            bodies[current] = bodies.get(current, "") + match.group(3).strip()
        elif current:
            bodies[current] += line.strip()
    return [name for name in NOTE_SECTIONS if not bodies.get(name.lower())]


def hook(raw: str, path: Path | None = None) -> str:
    """Hook body: returns the note to print ('' = nothing). Never raises."""
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict) or payload.get("source") != "compact":
            return ""
        chat_id = str(payload.get("session_id") or "")
        if not chat_id:
            return ""
        if payload.get("agent_id"):
            return ""
        if payload.get("codex_thread_id"):
            return hook_prompt(raw)
        return policy_note(bump_count(chat_id, path or state_file()))
    except (OSError, ValueError, TypeError):
        return ""


def _find_session(chat_id: str) -> str:
    """The sessions.py session id bound to this chat, or ''."""
    try:
        data = json.loads((canonical_root() / ".claude" / "sessions.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    for sid, info in (data.get("sessions") or {}).items():
        if chat_id and info.get("agent_task_id") == chat_id:
            return sid
    return ""


def _task_link(chat_id: str) -> str:
    import codex_chats

    if codex_chats.is_codex_chat(chat_id):
        record = codex_chats.load(chat_id) or {}
        if record.get("thread_id"):
            return f"codex:{record['thread_id']}"
    return f"claude:{chat_id}"


def _find_task(chat_id: str) -> str:
    """Full id of this chat's open Task: the one in progress, else its only open one, else ''."""
    result = subprocess.run(["openmates", "tasks", "list", "--external-chat", _task_link(chat_id), "--json"],
                            capture_output=True, text=True, timeout=60, check=False)
    try:
        parsed = json.loads(result.stdout)
    except ValueError:
        return ""
    items = parsed if isinstance(parsed, list) else (parsed.get("tasks") or parsed.get("items") or [])
    items = [t for t in items if isinstance(t, dict)]
    open_items = [t for t in items if t.get("status") not in ("done", "cancelled")]
    running = [t for t in open_items if t.get("status") == "in_progress"]
    pick = running if len(running) == 1 else open_items if len(open_items) == 1 else []
    return str(pick[0].get("task_id") or pick[0].get("id") or "") if pick else ""


def archive_marker(root: Path, chat_id: str, successor: str, now: float) -> Path:
    """The ✅ marker the lifecycle archives an idle chat by (same file as agent_question.marker_path)."""
    path = root / "logs" / "claude-idle-chats" / "questions" / f"{chat_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"ts": now, "kind": "✅", "question": f"handed off to {successor}",
                                "source": "chat_compaction_handoff"}), encoding="utf-8")
    return path


def build_prompt(summary: str, session_id: str, worktree: str, task_id: str, old_chat: str) -> str:
    """First prompt of the fresh chat: adopt the session, then continue from the summary."""
    steps = [
        f"You continue the work of chat {old_chat[:8]}, which handed off after repeated compaction "
        "(owner decision, 23 Nov). Its handoff note below is also in the Task's activity.",
        f"Workspace: {worktree or 'canonical checkout'}; sessions.py session: {session_id or 'none'}; "
        f"Task: {task_id or 'none'}.",
    ]
    if session_id and worktree:
        workspace = shlex.quote(worktree)
        steps.append(
            f"Adopt the session: `python3 scripts/sessions.py worktree bind-task "
            f"--session {session_id} --agent-task \"$CLAUDE_CODE_SESSION_ID\" --expected-worktree {workspace} "
            f"--previous-owner-stopped`. Run subsequent commands in {workspace} with `--session {session_id}`.")
    if task_id:
        steps.append(f"Link this chat to Task {task_id} using its engine's external chat ID. "
                     "For Claude use `claude:$CLAUDE_CODE_SESSION_ID`. For Codex use "
                     "`codex:$CODEX_THREAD_ID`.")
    steps.append("Handoff note from the old chat:\n\n" + summary.strip())
    return "\n\n".join(steps)


def handoff(args: argparse.Namespace) -> int:
    chat_id = args.chat or os.environ.get("OPENMATES_CHAT_ID") or os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    if not re.fullmatch(r"[a-zA-Z0-9-]+", chat_id):
        print("Refused: a valid chat ID is required.", file=sys.stderr)
        return 2
    summary = Path(args.summary_file).read_text(encoding="utf-8").strip()
    missing = missing_sections(summary)
    if missing:
        print(f"Refused: the handoff note lacks {', '.join(missing)}. Use these sections:\n{NOTE_TEMPLATE}",
              file=sys.stderr)
        return 2
    if len(summary) > ACTIVITY_MAX_CHARS:
        print(f"Refused: shorten the handoff note to {ACTIVITY_MAX_CHARS} characters.", file=sys.stderr)
        return 2
    root = canonical_root()
    session_id = args.session or _find_session(chat_id)
    worktree = ""
    if session_id:
        data = _load(root / ".claude" / "sessions.json")
        record = (data.get("sessions") or {}).get(session_id) or {}
        if record.get("agent_task_id") != chat_id:
            print("Refused: this session belongs to another chat.", file=sys.stderr)
            return 2
        worktree = str((record.get("worktree") or {}).get("path") or "")
    task_id = getattr(args, "task", "") or _find_task(chat_id)
    if not task_id:
        print("Refused: no single open Task found for this chat; pass --task <full task id>.", file=sys.stderr)
        return 2
    prompt = build_prompt(summary, session_id, worktree, task_id, chat_id)
    import chat_usage_watch
    import codex_chats

    registry = codex_chats.load(chat_id) if codex_chats.is_codex_chat(chat_id) else {}
    old_title = chat_usage_watch.chat_title(chat_id, root, chat_usage_watch.PROJECT_DIR,
                                            (registry or {}).get("title") or "")
    title = f"{old_title or 'Work chat'} · continuation {chat_id[:8]}"
    if args.dry_run:
        print(json.dumps({"title": title, "session": session_id, "worktree": worktree, "task": task_id,
                          "detach_old_binding": bool(session_id), "prompt": prompt}, indent=2))
        return 0

    marks = handed_off_file(root)
    marks.parent.mkdir(parents=True, exist_ok=True)
    with (marks.parent / f"handoff-{chat_id}.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if prior := _load(marks).get(chat_id):
            print(f"Already handed off to {prior['successor']}. End this turn now.")
            return 0
        return launch_successor(root, chat_id, session_id, task_id, title, prompt, summary)


def _reply(result: subprocess.CompletedProcess) -> dict:
    try:
        reply = json.loads(result.stdout)
    except (ValueError, TypeError):
        return {}
    return reply if isinstance(reply, dict) else {}


def launch_successor(root: Path, chat_id: str, session_id: str, task_id: str,
                     title: str, prompt: str, summary: str) -> int:
    import claude_dispatch

    delivery = hashlib.sha256(f"handoff:{chat_id}:{task_id}:{summary}".encode()).hexdigest()
    note = subprocess.run(["openmates", "tasks", "activity", "add", task_id, "--message",
                           f"Handoff note of chat {chat_id[:8]}:\n\n{summary}", "--delivery-id", delivery, "--json"],
                          capture_output=True, text=True, timeout=60, check=False)
    if note.returncode or not _reply(note).get("entry"):
        print(f"Refused: could not write the Task handoff note: {note.stderr.strip()}", file=sys.stderr)
        return 2

    released = subprocess.run(["openmates", "tasks", "release", task_id, "--json"],
                              capture_output=True, text=True, timeout=60, check=False)
    reply = _reply(released)
    if released.returncode or not reply.get("task") or reply["task"].get("external_chat"):
        print(f"Refused: the Task link has not been released: {released.stderr.strip()}", file=sys.stderr)
        return 2

    def bind(expected, owner):
        import sessions

        def change(state: dict) -> None:
            record = state["sessions"][session_id]
            if record.get("agent_task_id") != expected:
                raise ValueError("The session binding changed during handoff.")
            record["agent_task_id"] = owner

        sessions._mutate_sessions(change)

    if session_id:
        bind(chat_id, None)
    try:
        where = claude_dispatch.launch_claude_chat(title, prompt)
    except claude_dispatch.ChatQueued as queued:
        where = str(queued)
    except (OSError, subprocess.SubprocessError, claude_dispatch.DispatchError):
        if session_id:
            bind(None, chat_id)
        raise
    mark_handed_off(chat_id, str(where), handed_off_file(root))
    archive_marker(root, chat_id, str(where), time.time())
    print(f"Handed off to {where}. This chat is archived once idle. End this turn now.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("hook")
    sub.add_parser("hook-prompt")
    sub.add_parser("hook-stop")
    p = sub.add_parser("handoff")
    p.add_argument("--summary-file", required=True)
    p.add_argument("--session", default="")
    p.add_argument("--chat", default="")
    p.add_argument("--task", default="", help="full Task id when the chat has several open Tasks")
    p.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    handlers = {"hook": hook, "hook-prompt": hook_prompt, "hook-stop": hook_stop}
    if args.cmd in handlers:
        try:
            note = handlers[args.cmd](sys.stdin.read())
        except (OSError, ValueError, TypeError):
            return 0
        if note:
            print(note)
        return 0
    return handoff(args)


if __name__ == "__main__":
    sys.exit(main())
