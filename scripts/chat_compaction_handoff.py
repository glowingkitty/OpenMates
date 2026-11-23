#!/usr/bin/env python3
"""Hand a repeatedly compacted Claude chat off to a fresh chat with a summary.

A chat compacted several times works on a lossy summary and burns tokens re-reading.
Policy (owner decision, 22 Nov): compactions 1-2 are silent, the 3rd announces that
the next compaction should hand off, the 4th and later tell the chat to hand off now.

Subcommands:
  hook      SessionStart hook (matcher `compact`): counts the compaction per chat in
            <canonical repo>/logs/claude-chat-lifecycle/compactions.json and prints
            the policy note on stdout (SessionStart additionalContext). Sub-agents
            (payload has agent_id) are ignored. Fails open: any problem prints nothing.
  handoff   --summary-file F [--session S] [--chat C] [--dry-run]: starts a fresh chat
            with the summary as its first prompt (scripts/claude_dispatch.launch_claude_chat),
            detaches the sessions.py session from the old chat so the new chat can adopt
            it with `sessions.py worktree bind-task`, and adds a line to the chat's Task.
            Registers no waiter, so the lifecycle never wakes the old chat again.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_ROOT / "scripts"))

NOTE_AT = 3
HANDOFF_AT = 4


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
    try:
        marks = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        marks = {}
    if not isinstance(marks, dict):
        marks = {}
    marks[chat_id] = {"successor": successor}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(marks, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def bump_count(chat_id: str, path: Path) -> int:
    """Increment and return the compaction count of one chat."""
    try:
        counts = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        counts = {}
    if not isinstance(counts, dict):
        counts = {}
    counts[chat_id] = int(counts.get(chat_id, 0)) + 1
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(counts, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    return counts[chat_id]


def policy_note(count: int) -> str:
    """The text injected into the chat after its `count`-th compaction ('' for 1-2)."""
    if count < NOTE_AT:
        return ""
    if count == NOTE_AT:
        return (f"This chat was compacted {count} times; at the next compaction hand off "
                "to a fresh chat (python3 scripts/chat_compaction_handoff.py handoff).")
    return (
        f"This chat was compacted {count} times and now works on a lossy summary. Hand off NOW: "
        "write a summary (goal, done, open items, sessions.py session id, workspace path, CI/deploy "
        "job ids) to a file, add it to this chat's Task activity "
        "(`openmates tasks activity add <task-id> --message ...`), run "
        "`python3 scripts/chat_compaction_handoff.py handoff --summary-file <file>` (it starts a "
        "fresh chat on the same session and Task), then end this turn and do no further work."
    )


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


def _find_task(chat_id: str) -> str:
    """Full id of the Task linked to `claude:<chat_id>`, or ''."""
    result = subprocess.run(["openmates", "tasks", "list", "--external-chat", f"claude:{chat_id}", "--json"],
                            capture_output=True, text=True, timeout=60, check=False)
    try:
        parsed = json.loads(result.stdout)
    except ValueError:
        return ""
    items = parsed if isinstance(parsed, list) else (parsed.get("tasks") or parsed.get("items") or [])
    return str(items[0].get("id") or "") if items and isinstance(items[0], dict) else ""


def build_prompt(summary: str, session_id: str, worktree: str, task_id: str, old_chat: str) -> str:
    """First prompt of the fresh chat: adopt the session, then continue from the summary."""
    steps = [
        f"You continue the work of chat {old_chat[:8]}, which was compacted several times and handed off.",
        f"Workspace: {worktree or 'canonical checkout'}; sessions.py session: {session_id or 'none'}; "
        f"Task: {task_id or 'none'}.",
    ]
    if session_id and worktree:
        steps.append(
            f"First `cd {worktree}` and adopt the session: `python3 scripts/sessions.py worktree bind-task "
            f"--session {session_id} --agent-task \"$CLAUDE_CODE_SESSION_ID\" --expected-worktree {worktree} "
            "--previous-owner-stopped` (the old chat has stopped). Pass `--session` on later commands.")
    if task_id:
        steps.append(f"Link this chat to the Task: `openmates tasks edit {task_id} --external-chat "
                     "claude:$CLAUDE_CODE_SESSION_ID`.")
    steps.append("Summary from the old chat:\n\n" + summary.strip())
    return "\n\n".join(steps)


def handoff(args: argparse.Namespace) -> int:
    chat_id = args.chat or os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    summary = Path(args.summary_file).read_text(encoding="utf-8")
    session_id = args.session or _find_session(chat_id)
    worktree = ""
    if session_id:
        data = json.loads((canonical_root() / ".claude" / "sessions.json").read_text(encoding="utf-8"))
        worktree = str(((data.get("sessions") or {}).get(session_id) or {}).get("worktree", {}).get("path") or "")
    task_id = _find_task(chat_id) if chat_id else ""
    prompt = build_prompt(summary, session_id, worktree, task_id, chat_id)
    title = f"continue {session_id or chat_id[:8]}"
    if args.dry_run:
        print(json.dumps({"title": title, "session": session_id, "worktree": worktree, "task": task_id,
                          "detach_old_binding": bool(session_id), "prompt": prompt}, indent=2))
        return 0
    import claude_dispatch
    where = claude_dispatch.launch_claude_chat(title, prompt)
    if chat_id:
        mark_handed_off(chat_id, str(where))
    if session_id:
        import sessions  # same module that owns the binding; detach pattern of `start --new`

        def detach(state: dict) -> None:
            state["sessions"][session_id]["agent_task_id"] = None
        sessions._mutate_sessions(detach)
    if task_id:
        subprocess.run(["openmates", "tasks", "activity", "add", task_id, "--message",
                        f"Chat {chat_id[:8]} handed off after repeated compaction to a fresh chat ({where})."],
                       capture_output=True, text=True, timeout=60, check=False)
    print(f"Handed off to {where}. End this turn now.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("hook")
    p = sub.add_parser("handoff")
    p.add_argument("--summary-file", required=True)
    p.add_argument("--session", default="")
    p.add_argument("--chat", default="")
    p.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.cmd == "hook":
        note = hook(sys.stdin.read())
        if note:
            print(note)
        return 0
    return handoff(args)


if __name__ == "__main__":
    sys.exit(main())
