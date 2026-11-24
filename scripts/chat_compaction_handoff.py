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
import shutil
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
                 "## References\nbranch, worktree and session, relevant commits and files, CI/deploy results, proof references")


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
        "the Task, starts a fresh chat on the same session and Task, and archives this chat. If it succeeds, "
        "end this turn and send no push. If it fails, continue the work in this chat."
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


RESERVE_REASON = "Claude has less than 10% weekly usage left. Keep this handover-only and continue in Codex."


def reserve_handoff_note(payload: dict, handed_path: Path) -> str:
    import claude_weekly_model

    chat_id = payload.get("session_id")
    if (chat_id and not payload.get("codex_thread_id") and chat_id not in _load(handed_path)
            and claude_weekly_model.needs_handoff(
                chat_id, exemption=os.environ.get(claude_weekly_model.RESERVE_EXEMPT_ENV, ""))):
        return handoff_now(RESERVE_REASON)
    return ""


def hook_prompt(raw: str, **paths) -> str:
    """UserPromptSubmit body: the hand-off-now note for a due chat, else ''. Never raises."""
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict) or payload.get("agent_id"):
            return ""
        chat_id = str(payload.get("session_id") or "")
        if not chat_id:
            return ""
        handed_path = paths.get("handed_path") or handed_off_file()
        if chat_id in _load(handed_path.with_name("refused-handovers.json")):
            return ""  # the watchdog owns recovery after a failed handoff
        if note := reserve_handoff_note(payload, handed_path):
            return note
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
        if chat_id not in _load(handed_off_file(root).with_name("refused-handovers.json")):
            if note := reserve_handoff_note(payload, handed_off_file(root)):
                return json.dumps({"decision": "block", "reason": note})
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
        if note := reserve_handoff_note(payload, handed_off_file()):
            return note
        return policy_note(bump_count(chat_id, path or state_file()))
    except (OSError, ValueError, TypeError):
        return ""


def _find_session(chat_id: str, *, include_archived: bool = False) -> str:
    """Find the direct binding, or an unambiguous archived source for host handovers."""
    if not chat_id:
        return ""
    records = _load(canonical_root() / ".claude" / "sessions.json").get("sessions") or {}
    for sid, info in records.items():
        if info.get("agent_task_id") == chat_id:
            return sid
    if include_archived:
        prior = [sid for sid, info in records.items() if info.get("archived_agent_task_id") == chat_id]
        if len(prior) == 1:
            return prior[0]
    return ""

def task_links(chat_id: str) -> set[str]:
    """Both Task link spellings used by the host's Codex tabs."""
    import codex_chats

    links = {f"claude:{chat_id}"}
    if codex_chats.is_codex_chat(chat_id):
        record = codex_chats.load(chat_id) or {}
        if record.get("thread_id"):
            links.add(f"codex:{record['thread_id']}")
    return links


def _tasks_cli() -> str:
    return shutil.which("openmates") or str(Path.home() / ".npm-global" / "bin" / "openmates")


def task_cli(*args: str, timeout: int = 20) -> subprocess.CompletedProcess:
    # The host service and its operator entry point must have the same Task authority.
    env = {key: value for key, value in os.environ.items()
           if key not in ("OPENMATES_CHAT_ID", "CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID")}
    return subprocess.run([_tasks_cli(), "tasks", *args, "--json"], env=env,
                          capture_output=True, text=True, timeout=timeout, check=False)


def _external_link(task: dict) -> str:
    external = task.get("external_chat") or {}
    return f"{external['provider']}:{external['id']}" if external.get("provider") and external.get("id") else ""


def _find_task(chat_id: str, hint: str = "") -> str:
    """Choose a Task mentioned by the waiter or the only active candidate."""
    links = task_links(chat_id)
    candidates = {}
    for link in sorted(links):
        result = task_cli("list", "--external-chat", link)
        if result.returncode:
            return ""  # an unread scope can hide another matching Task
        for task in _reply(result).get("tasks", []):
            if (task.get("task_id") and task.get("status") not in ("done", "cancelled")
                    and _external_link(task) == link):
                candidates[task["task_id"]] = task
    tasks = list(candidates.values())
    words = set(re.findall(r"[\w-]+", hint.casefold()))
    mentioned = [task for task in tasks if {task["task_id"].casefold(), task["task_id"][:8].casefold(),
                                            str(task.get("short_id") or "").casefold()} & words]
    running = [task for task in tasks if task.get("status") == "in_progress"]
    for choices in (mentioned, running, tasks):
        if len(choices) == 1:
            return choices[0]["task_id"]
        if choices is mentioned and len(mentioned) > 1:
            return ""
    return ""


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
        f"You continue the work of chat {old_chat[:8]}, which handed off its work "
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
        steps.append(f"Link this chat to Task {task_id} with "
                     f"`openmates tasks edit {task_id} --external-chat claude:$CLAUDE_CODE_SESSION_ID`. "
                     "The host exposes the same durable chat ID for both engines.")
    steps.append("Use the handoff as context. Verify the current state and carry forward pending decisions "
                 "and approval requirements from the source chat.")
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
        try:
            status = launch_successor(root, chat_id, session_id, task_id, title, prompt, summary)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            print(f"Handoff interrupted ({type(exc).__name__}).", file=sys.stderr)
            status = 2
        if status:
            _update_state(marks.with_name("refused-handovers.json"), chat_id, lambda _: {
                "task": task_id, "reason": "Task handoff could not be confirmed", "at": time.time(),
            })
            print("Continue in this chat. The host watchdog will retry if this chat stops.", file=sys.stderr)
        return status


def _reply(result: subprocess.CompletedProcess) -> dict:
    try:
        reply = json.loads(result.stdout)
    except (ValueError, TypeError):
        return {}
    return reply if isinstance(reply, dict) else {}


def saved_handoff(result: dict) -> str:
    """Find a full source-authored handover in Task activity, including older pause notes."""
    for entry in result.get("entries") or []:
        note = str(entry.get("message") or "").strip()
        if not re.match(r"^hando(?:ff|ver)\b", note, re.I) or len(note) > ACTIVITY_MAX_CHARS:
            continue
        if not missing_sections(note):
            return note
        lines = note.splitlines()
        headings = {"done": "Done", "not done": "Not done", "next": "Next step", "open": "Open decisions"}
        normalized = [f"## References\n{lines[0]}"]
        for line in lines[1:]:
            match = re.match(r"^(done|not done|next|open)(?: on dev)?:\s*(.*)$", line, re.I)
            if match:
                normalized.append(f"## {headings[match[1].lower()]}\n{match[2]}")
            else:
                normalized.append(line)
        note = "\n".join(normalized)
        if not missing_sections(note):
            return note
    return ""


def source_running(chat_id: str) -> bool:
    """Check processes, not the archived flag, which can lag either engine."""
    import codex_chats
    import worktree_wip

    return chat_id in codex_chats.live() or chat_id in worktree_wip._running_chat_ids()


def owner_is_stopped(root: Path, link: str) -> bool:
    """Only take over a different owner with positive local lifecycle evidence."""
    import codex_chats

    provider, _, external_id = link.partition(":")
    if provider == "claude":
        owners = {external_id}
    elif provider == "codex":
        owners = {record["chat_id"] for record in codex_chats.records()
                  if record.get("thread_id") == external_id}
    else:
        return False
    directory = root / "logs" / "claude-chat-lifecycle"
    registry = _load(directory / "stopped.json")
    handed = _load(handed_off_file(root))
    return bool(owners) and all(
        not source_running(owner) and (owner in handed or
        (registry.get(owner) or {}).get("state") in ("done", "stopped", "archived"))
        for owner in owners
    )


def resume_on_codex(chat_id: str, prompt: str, *, admitted: bool = False, task_id: str = "",
                    force: bool = False) -> str:
    """Recover a stopped source, preserving its Task and worktree when known."""
    import claude_dispatch

    if not re.fullmatch(r"[0-9a-fA-F-]{36}", chat_id):
        return "Invalid handover source chat"
    if source_running(chat_id):
        return "The source chat is still running"
    root = canonical_root()
    path = handed_off_file(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with (path.parent / f"handoff-{chat_id}.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return "A handoff is already in progress"
        if chat_id in _load(path):
            return "ok"
        if source_running(chat_id):
            return "The source chat is still running"
        if why := claude_dispatch.codex_wait_reason():
            return why
        session_id = _find_session(chat_id, include_archived=True)
        sessions = _load(root / ".claude" / "sessions.json").get("sessions") or {}
        session = sessions.get(session_id) or {}
        successor = session.get("agent_task_id")
        if successor not in (None, chat_id):
            # Another chat adopted this exact worktree. Route the notification there.
            return claude_dispatch.resume_chat(successor, prompt, admitted=admitted, force=force)
        handovers = path.with_name("pending-task-handovers.json")
        hint = str(session.get("task") or "")
        short_ids = set(re.findall(r"\bTASK-\d+\b", hint))
        task_id = task_id or _load(handovers).get(chat_id)
        if not task_id and len(short_ids) == 1:
            task_id = short_ids.pop()
        if not task_id:
            task_id = _find_task(chat_id, prompt)
        if not task_id:
            return "No unambiguous open Task for the stopped source"
        details = _reply(task_cli("show", task_id)).get("task") or {}
        if not details or details.get("status") in ("done", "cancelled") or details.get("primary_chat_id"):
            return "The linked Task is closed, unavailable or owned by an OpenMates chat"
        task_id = details.get("task_id") or task_id
        activity = task_cli("activity", "list", task_id, "--newest-first", "--max-entries", "20")
        note = saved_handoff(_reply(activity)) if activity.returncode == 0 else ""
        if not session_id and details.get("short_id"):
            # Earlier archives could clear the owner without retaining its history.
            short_id = str(details["short_id"])
            orphaned = [(sid, record) for sid, record in sessions.items()
                        if not record.get("agent_task_id") and not record.get("archived_agent_task_id")
                        and (record.get("worktree") or {}).get("status") == "active"
                        and short_id in re.findall(r"\bTASK-\d+\b", record.get("task") or "")]
            if len(orphaned) == 1:
                session_id, session = orphaned[0]
        worktree = str((session.get("worktree") or {}).get("path") or "")
        if not note:
            note = (f"No complete handoff note was available. Reconstruct the pending step from Task activity "
                    f"and the source chat's local transcript ({chat_id}) before making changes. "
                    "Continue only the approved dev scope and preserve all pending owner decisions.")
        continuation = build_prompt(note, session_id, worktree, task_id, chat_id)
        continuation += "\n\nNotification that initiated recovery:\n" + prompt
        task_title = str(details.get("title") or session.get("task") or "Work chat")
        title = f"{task_title[:64]} · continuation {chat_id[:8]}"
        _update_state(handovers, chat_id, lambda _: task_id)
        options = {"force": True} if force else {}
        status = launch_successor(root, chat_id, session_id, task_id, title, continuation, note,
                                  codex=True, admitted=admitted, note_already_saved=True, task=details, **options)
        return "ok" if status == 0 else "The Task transfer could not be confirmed"


def launch_successor(root: Path, chat_id: str, session_id: str, task_id: str,
                     title: str, prompt: str, summary: str, *, codex: bool = False, admitted: bool = False,
                     note_already_saved: bool = False, task: dict | None = None, force: bool = False) -> int:
    import claude_dispatch

    task = task if task is not None else _reply(task_cli("show", task_id)).get("task")
    if not task or task.get("primary_chat_id") or task.get("status") in ("done", "cancelled"):
        print("Refused: Task unavailable, closed or owned by an OpenMates chat.", file=sys.stderr)
        return 2
    task_id = task.get("task_id") or task_id
    owner = _external_link(task)
    if owner and owner not in task_links(chat_id) and not owner_is_stopped(root, owner):
        print("Refused: a different Task owner is still live or could not be verified.", file=sys.stderr)
        return 2
    if not note_already_saved:
        delivery = hashlib.sha256(f"handoff:{chat_id}:{task_id}:{summary}".encode()).hexdigest()
        note = task_cli("activity", "add", task_id, "--message",
                        f"Handoff note of chat {chat_id[:8]}:\n\n{summary}", "--delivery-id", delivery, timeout=60)
        if note.returncode or not _reply(note).get("entry"):
            print("Refused: could not confirm the Task handoff note.", file=sys.stderr)
            return 2

    _update_state(handed_off_file(root).with_name("pending-task-handovers.json"), chat_id, lambda _: task_id)
    if owner:
        # This scope is part of the CLI's lookup, and its update uses the version it read.
        # An intervening claim either no longer matches that lookup or conflicts on write.
        released = task_cli("release", task_id, "--external-chat", owner, timeout=60)
        reply = _reply(released).get("task")
        if released.returncode or not reply or reply.get("external_chat") or reply.get("primary_chat_id"):
            print("Refused: could not confirm release of the expected Task link.", file=sys.stderr)
            return 2

    def detach_session(restore: bool = False) -> bool:
        import sessions

        def change(state: dict) -> bool:
            record = state["sessions"][session_id]
            expected = None if restore else chat_id
            owner = record.get("agent_task_id")
            if not restore and note_already_saved and owner is None:
                if record.get("archived_agent_task_id") not in (None, chat_id):
                    raise ValueError("The archived session binding changed during handoff.")
                record["archived_agent_task_id"] = chat_id
                return False
            if owner != expected:
                raise ValueError("The session binding changed during handoff.")
            record["agent_task_id"] = chat_id if restore else None
            if not restore:
                record["archived_agent_task_id"] = chat_id
            return True

        return sessions._mutate_sessions(change)

    detached = bool(session_id) and detach_session()
    try:
        if codex:
            import claude_weekly_model

            options = {"force": True} if force else {}
            where = claude_dispatch.launch_claude_chat(title, prompt, model=claude_weekly_model.CODEX_MODEL,
                                                        admitted=admitted, **options)
        else:
            where = claude_dispatch.launch_claude_chat(title, prompt)
    except claude_dispatch.ChatQueued as queued:
        where = str(queued)
    except (OSError, subprocess.SubprocessError, claude_dispatch.DispatchError):
        if detached:
            detach_session(restore=True)
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
