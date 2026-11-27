#!/usr/bin/env python3
"""Codex work chats on the dev host: registry, launch command, live state, transcripts, usage.

Codex (OpenAI's CLI) is the second engine for work chats next to Claude Code (owner,
2026-11-23, TASK-4476). A Codex chat runs exactly like a Claude pane chat: in its own tab
of the persistent zellij session, started by scripts/claude_dispatch.py, counted against
the same `max_running` slots (scripts/claude_idle_chats.py) and bound by the same hooks
(.codex/hooks.json runs .claude/settings.json hooks through scripts/codex_hook_adapter.py).

Identity: every Codex chat gets an OpenMates chat id (a UUID made at launch) exported as
OPENMATES_CHAT_ID and CLAUDE_CODE_SESSION_ID, so sessions.py, agent_question.py, waiters
and the mailbox key it like a Claude chat. The Codex thread id is learnt from the first
hook payload (SessionStart) and stored in the chat's registry record; Tasks link it as
`codex:<thread id>`.

Records (all private, under ~/.openmates/codex-chats, never in the repo):
  <chat id>.json        registry: title, model, effort, cwd, started_at, tab, thread_id
  transcripts/<id>.jsonl the chat mirrored into Claude Code transcript records (user and
                        assistant text, tool calls, titles) so the dev connector's
                        list_chats, chat_detail, search, housekeeping and the briefing read
                        Codex chats with the code they use for Claude chats.

Usage: Codex writes its plan's rate-limit windows into every `token_count` event of its
session files (~/.codex/sessions/**/rollout-*.jsonl); `usage` reads the newest one.

Commands:
  list                 Codex chats with live state (JSON).
  mirror [--chat ID]   Refresh transcript mirrors (all chats, or one).
  usage                Remaining Codex plan usage (JSON).
Tests: scripts/tests/test_codex_chats.py
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import tempfile
import time
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterator

DEFAULT_MODEL = "gpt-6.2-sol"
# Owner, 2026-11-23: Astra only when Marco names it, like Fable for Claude.
EXPLICIT_ONLY_MODELS = ("gpt-6.2-astra",)
MAX_EFFORT = "medium"
MIRROR_VERSION = 2
UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
ROLLOUT_ID_RE = re.compile(r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\.jsonl$")


def state_dir() -> Path:
    return Path(os.environ.get("OPENMATES_CODEX_CHATS_DIR") or Path.home() / ".openmates" / "codex-chats")


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def codex_bin() -> str:
    return os.environ.get("CODEX_BIN") or str(Path.home() / ".local" / "bin" / "codex")


class CodexChatError(RuntimeError):
    """A Codex chat could not be started, found or resumed."""


# ── Models ───────────────────────────────────────────────────────────────────

def is_codex_model(model: str) -> bool:
    lowered = model.lower().strip()
    return lowered.startswith(("gpt-", "codex")) or lowered in ("sol", "astra")


def normalize_model(model: str) -> str:
    """Spoken or short names to Codex model ids ('Sol' -> gpt-6.2-sol, 'codex' -> default)."""
    lowered = model.lower().strip().replace(" ", "-")
    if lowered in ("", "codex", "sol", "gpt-sol", "gpt-6.2-sol"):
        return DEFAULT_MODEL
    if lowered in ("astra", "gpt-astra", "gpt-6.2-astra"):
        return "gpt-6.2-astra"
    return lowered


def check_model(model: str, explicit_model: bool) -> str:
    model = normalize_model(model)
    if model in EXPLICIT_ONLY_MODELS and not explicit_model:
        raise CodexChatError(f"refusing to start a chat on {model}: it runs only when the owner names it "
                             f"(the Codex default is {DEFAULT_MODEL})")
    return model


# ── Registry ─────────────────────────────────────────────────────────────────

def _registry_path(chat_id: str) -> Path:
    if not UUID_RE.match(chat_id):
        raise CodexChatError(f"not a chat id: {chat_id!r}")
    return state_dir() / f"{chat_id}.json"


def load(chat_id: str) -> dict[str, Any] | None:
    try:
        record = json.loads(_registry_path(chat_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) else None


def save(record: dict[str, Any]) -> None:
    path = _registry_path(str(record["chat_id"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(record, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def records() -> list[dict[str, Any]]:
    found = []
    for path in sorted(state_dir().glob("*.json")) if state_dir().is_dir() else []:
        if UUID_RE.match(path.stem) and (record := load(path.stem)):
            found.append(record)
    return found


def is_codex_chat(chat_id: str) -> bool:
    return bool(UUID_RE.match(chat_id)) and _registry_path(chat_id).is_file()


def record_thread(chat_id: str, thread_id: str) -> bool:
    """Store the Codex thread id of a chat (first hook payload); True when it changed."""
    record = load(chat_id)
    if record is None or not UUID_RE.match(thread_id) or record.get("thread_id") == thread_id:
        return False
    record["thread_id"] = thread_id
    save(record)
    return True


def new_record(title: str, model: str, effort: str, cwd: str, explicit_model: bool) -> dict[str, Any]:
    return {"chat_id": str(uuid.uuid4()), "engine": "codex", "title": title, "model": model, "effort": effort,
            "cwd": cwd, "explicit_model": explicit_model, "thread_id": "",
            "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def register_native_thread(thread_id: str) -> str:
    """Resolve a native terminal thread and register it from its own rollout."""
    thread_id = thread_id.strip()
    if not UUID_RE.fullmatch(thread_id):
        return ""
    for record in records():
        if record.get("thread_id") == thread_id:
            return str(record["chat_id"])
    path = rollout_path(thread_id)
    if path is None:
        return ""
    try:
        with path.open(encoding="utf-8") as handle:
            header = json.loads(handle.readline())
    except (OSError, ValueError):
        return ""
    meta = header.get("payload") if header.get("type") == "session_meta" else None
    if not isinstance(meta, dict) or meta.get("id") != thread_id:
        return ""
    cwd = meta.get("cwd")
    if not isinstance(cwd, str) or not Path(cwd).is_absolute():
        return ""
    record = new_record(str(meta.get("title") or os.getenv("CLAUDE_CHAT_TITLE") or "Terminal Codex chat"),
                        DEFAULT_MODEL, MAX_EFFORT, cwd, False)
    record.update(chat_id=thread_id, thread_id=thread_id, started_at=meta.get("timestamp") or record["started_at"])
    save(record)
    return thread_id


# ── Launch command ───────────────────────────────────────────────────────────

def chat_env(record: dict[str, Any]) -> dict[str, str]:
    """Variables every process of the chat sees (hooks, sessions.py, agent_question.py)."""
    return {"OPENMATES_CHAT_ID": record["chat_id"], "CLAUDE_CODE_SESSION_ID": record["chat_id"],
            "OPENMATES_CHAT_ENGINE": "codex", "OPENMATES_CHAT_MODEL": record["model"],
            "OPENMATES_CODEX_CHATS_DIR": str(state_dir()), "CLAUDE_CHAT_TITLE": record["title"]}


def codex_args(record: dict[str, Any], prompt: str = "", resume_thread: str = "",
               images: tuple[str, ...] = ()) -> list[str]:
    """Codex TUI arguments: fixed model and effort, no approval prompts, no OS sandbox.

    Parity with Claude chats, which run in auto mode without an OS sandbox: the repository
    hooks (codex_hook_adapter.py) are the guard for both engines. Codex's workspace-write
    sandbox is not used because it makes the checkout's .git read-only, which breaks
    sessions.py worktree commits and deploys. The self guard (codex_hook_adapter.py
    self guard) refuses edits of the Codex hooks and config.
    """
    args = [codex_bin()]
    if resume_thread:
        args += ["resume", resume_thread]
    args += [
        "--model", record["model"],
        "-c", f'model_reasoning_effort="{MAX_EFFORT}"',
        "-c", 'approval_policy="never"',
        "-c", 'sandbox_mode="danger-full-access"',
        "-c", "features.hooks=true",
        "--cd", record["cwd"],
    ]
    args.extend(f"--image={path}" for path in images)
    if prompt:
        args.extend(("--", prompt) if images else (prompt,))
    return args


def tab_command(record: dict[str, Any], prompt: str = "", resume_thread: str = "",
                images: tuple[str, ...] = ()) -> list[str]:
    """Command for the chat's zellij tab: user bins first on PATH plus the chat identity."""
    user_bins = [str(Path.home() / ".npm-global/bin"), str(Path.home() / ".local/bin")]
    inherited = [p for p in os.environ.get("PATH", os.defpath).split(os.pathsep) if p and p not in user_bins]
    env = [f"{k}={v}" for k, v in sorted(chat_env(record).items())]
    return ["/usr/bin/env", f"PATH={os.pathsep.join([*user_bins, *inherited])}", *env,
            *codex_args(record, prompt, resume_thread, images)]


# ── Live state ───────────────────────────────────────────────────────────────

def _proc_env(pid: int) -> dict[str, str]:
    try:
        raw = Path(f"/proc/{pid}/environ").read_bytes()
    except OSError:
        return {}
    pairs = (item.split(b"=", 1) for item in raw.split(b"\0") if b"=" in item)
    return {k.decode(errors="replace"): v.decode(errors="replace") for k, v in pairs}


def _is_codex_process(pid: int) -> bool:
    try:
        cmd = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
    except OSError:
        return False
    # Only the host's interactive launcher passes --cd. Inherited variables
    # also reach the app server and its workers, which may outlive the pane.
    return b"--cd" in cmd and b"app-server" not in cmd[:4] and any(
        part.endswith((b"/codex", b"codex.js")) or part == b"codex" for part in cmd[:3])


def live(proc: Path = Path("/proc")) -> dict[str, dict[str, Any]]:
    """chat id -> {pid} for every running Codex chat process started by the host (top process only)."""
    found: dict[str, dict[str, Any]] = {}
    for entry in proc.iterdir() if proc.is_dir() else []:
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if not _is_codex_process(pid):
            continue
        env = _proc_env(pid)
        chat_id = env.get("OPENMATES_CHAT_ID", "")
        if env.get("OPENMATES_CHAT_ENGINE") != "codex" or not UUID_RE.match(chat_id):
            continue
        if chat_id not in found or pid < found[chat_id]["pid"]:
            found[chat_id] = {"pid": pid}
    return found


# ── Session files and transcripts ────────────────────────────────────────────

@lru_cache(maxsize=256)
def _find_rollout(sessions: Path, thread_id: str) -> Path:
    matches = sorted(sessions.glob(f"**/rollout-*-{thread_id}.jsonl"))
    if not matches:
        raise FileNotFoundError(thread_id)
    return matches[-1]


def rollout_path(thread_id: str) -> Path | None:
    """Resolve a unique thread's rollout without walking all archived sessions on each poll."""
    if not UUID_RE.match(thread_id):
        return None
    sessions = codex_home() / "sessions"
    try:
        path = _find_rollout(sessions, thread_id)
        if not path.is_file():
            _find_rollout.cache_clear()
            return _find_rollout(sessions, thread_id)
    except FileNotFoundError:
        return None
    return path


def _rollout_lines(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if isinstance(item, dict):
                yield item


def rollout_metrics(path: Path, entry: dict | None = None) -> dict:
    """Read complete new rollout rows and keep the latest cumulative usage counters."""
    metrics = dict(entry or {})
    with path.open("rb") as handle:
        if handle.seek(0, os.SEEK_END) < metrics.get("offset", 0):
            metrics = {}
        handle.seek(metrics.get("offset", 0))
        while line := handle.readline():
            if not line.endswith(b"\n"):
                break
            metrics["offset"] = handle.tell()
            if b'"compacted"' not in line and b'"token_count"' not in line:
                continue
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if item.get("type") == "compacted":
                metrics["compactions"] = metrics.get("compactions", 0) + 1
            payload = item.get("payload") or {}
            if item.get("type") == "event_msg" and payload.get("type") == "token_count":
                info = payload.get("info") or {}
                totals = info.get("total_token_usage") or {}
                if totals:
                    cached = totals.get("cached_input_tokens", 0)
                    uncached = max(0, totals.get("input_tokens", 0) - cached)
                    metrics["units"] = (uncached + 0.1 * cached + 5 * totals.get("output_tokens", 0)
                                        + totals.get("cache_write_input_tokens", 0))
                    metrics["context"] = (info.get("last_token_usage") or {}).get("input_tokens", 0)
                    metrics["window"] = info.get("model_context_window") or 0
    return metrics


def _texts(content: Any) -> str:
    if isinstance(content, str):
        return content
    parts = [b.get("text", "") for b in content if isinstance(b, dict)] if isinstance(content, list) else []
    return "\n".join(p for p in parts if p)


def _message_blocks(content: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blocks = []
    for block in content:
        if block.get("type") in ("input_text", "output_text"):
            text = block.get("text", "")
            if text and not text.startswith(("<image name=", "</image>")):
                blocks.append({"type": "text", "text": text})
        elif block.get("type") == "input_image":
            header, _, data = (block.get("image_url") or "").partition(",")
            if header.startswith("data:image/") and header.endswith(";base64") and data:
                blocks.append({"type": "image", "source": {"type": "base64",
                               "media_type": header.removeprefix("data:").removesuffix(";base64"), "data": data}})
    if blocks and all(block["type"] == "image" for block in blocks):
        blocks.insert(0, {"type": "text", "text": "Attached image"})
    return blocks


def to_claude_records(items: Iterator[dict[str, Any]], record: dict[str, Any]) -> list[dict[str, Any]]:
    """Codex session items as Claude Code transcript records (what the connector reads)."""
    chat_id, cwd, model = record["chat_id"], record.get("cwd", ""), f"codex:{record.get('model', DEFAULT_MODEL)}"
    out: list[dict[str, Any]] = [{"type": "custom-title", "customTitle": record.get("title", ""),
                                 "sessionId": chat_id, "openmatesMirrorVersion": MIRROR_VERSION}]
    previous_message: tuple[str, str, str, int] | None = None
    for index, item in enumerate(items):
        stamp, payload = item.get("timestamp"), item.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        base = {"timestamp": stamp, "sessionId": chat_id, "cwd": cwd, "engine": "codex"}
        kind, ptype = item.get("type"), payload.get("type")
        role = payload.get("role")
        is_message = kind == "response_item" and ptype == "message" and role in ("user", "assistant")
        is_event = kind == "event_msg" and ptype in ("user_message", "agent_message")
        if is_message or is_event:
            if is_event:
                role = "user" if ptype == "user_message" else "assistant"
                text = str(payload.get("message") or "")
                blocks = [{"type": "text", "text": text}] if text else []
            else:
                content = payload.get("content") or []
                if (role == "user" and len(content) == 2
                        and content[0].get("text", "").startswith("# AGENTS.md instructions for ")
                        and content[1].get("text", "").startswith("<environment_context>")):
                    continue  # Initial workspace context is recorded as a synthetic user message.
                blocks = _message_blocks(content)
                text = _texts(blocks)
            if not blocks:
                continue
            message = {"role": role, "content": blocks}
            row_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{chat_id}:{index}"))
            if role == "assistant":
                message["model"] = model
            row = {**base, "type": role, "uuid": row_id, "message": message}
            if previous_message and previous_message[:2] == (role, text) and previous_message[2] != kind:
                if is_message:
                    out[previous_message[3]] = row  # Prefer the record with the original content blocks.
                previous_message = None
                continue
            previous_message = (role, text, kind, len(out))
            out.append(row)
        elif kind == "response_item" and ptype in ("function_call", "custom_tool_call", "local_shell_call"):
            name = str(payload.get("name") or ptype)
            raw = payload.get("arguments") or payload.get("input") or payload.get("action") or {}
            try:
                tool_input = json.loads(raw) if isinstance(raw, str) else raw
            except ValueError:
                tool_input = {"input": raw}
            out.append({**base, "type": "assistant", "message": {"role": "assistant", "model": model, "content": [
                {"type": "tool_use", "id": str(payload.get("call_id") or ""), "name": _tool_name(name),
                 "input": tool_input if isinstance(tool_input, dict) else {"input": tool_input}}]}})
        elif kind == "response_item" and ptype in ("function_call_output", "custom_tool_call_output"):
            output = payload.get("output")
            text = output if isinstance(output, str) else json.dumps(output)[:4000]
            out.append({**base, "type": "user", "isMeta": True, "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": str(payload.get("call_id") or ""), "content": text[:4000]}]}})
    return out


def _tool_name(name: str) -> str:
    return {"shell": "Bash", "exec_command": "Bash", "local_shell_call": "Bash", "apply_patch": "Edit",
            "spawn_agent": "Agent"}.get(name, name)


def transcript_path(chat_id: str) -> Path:
    _registry_path(chat_id)  # validates the id
    return state_dir() / "transcripts" / f"{chat_id}.jsonl"


def _mirror_is_current(target: Path, source_mtime_ns: int) -> bool:
    try:
        if target.stat().st_mtime_ns != source_mtime_ns:
            return False
        with target.open(encoding="utf-8") as handle:
            header = json.loads(handle.readline())
        return isinstance(header, dict) and header.get("openmatesMirrorVersion") == MIRROR_VERSION
    except (OSError, ValueError):
        return False


def mirror(chat_id: str) -> Path | None:
    """Rewrite the chat's Claude-format transcript when its Codex session file changed."""
    record = load(chat_id)
    if record is None:
        return None
    source = rollout_path(str(record.get("thread_id") or ""))
    target = transcript_path(chat_id)
    if source is None:
        if not target.exists():  # started, no thread yet: title and first prompt only
            target.parent.mkdir(parents=True, exist_ok=True)
            first = {"type": "user", "timestamp": record.get("started_at"), "sessionId": chat_id,
                     "cwd": record.get("cwd", ""), "message": {"role": "user", "content": record.get("prompt", "")}}
            rows = to_claude_records(iter(()), record) + ([first] if record.get("prompt") else [])
            target.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        return target
    source_mtime = source.stat().st_mtime_ns
    if _mirror_is_current(target, source_mtime):
        return target
    rows = to_claude_records(_rollout_lines(source), record)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent, delete=False) as handle:
        tmp = Path(handle.name)
        try:
            for row in rows:
                handle.write(json.dumps(row) + "\n")
            handle.close()
            os.utime(tmp, ns=(source_mtime, source_mtime))
            tmp.replace(target)
        finally:
            tmp.unlink(missing_ok=True)
    return target


def transcripts() -> dict[str, Path]:
    """chat id -> mirrored transcript for every registered Codex chat (refreshed on read)."""
    found: dict[str, Path] = {}
    for record in records():
        path = mirror(record["chat_id"])
        if path is not None:
            found[record["chat_id"]] = path
    return found


# ── Lifecycle ────────────────────────────────────────────────────────────────

def last_times(chat_id: str) -> tuple[float, float]:
    """(last activity, last owner/user prompt) of a Codex chat from its mirrored transcript."""
    path = mirror(chat_id)
    activity = prompt = 0.0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if path else []:
        try:
            item = json.loads(line)
            at = datetime.fromisoformat(str(item.get("timestamp")).replace("Z", "+00:00")).timestamp()
        except (ValueError, TypeError):
            continue
        activity = max(activity, at)
        if item.get("type") == "user" and not item.get("isMeta"):
            prompt = max(prompt, at)
    return activity, prompt


USAGE_LIMIT_ERROR = "usage_limit_exceeded"


def turn_activity(chat_id: str) -> tuple[float, str]:
    """Rollout activity time and most recent turn boundary, using a bounded read."""
    changed, state, _error = turn_end(chat_id)
    return changed, state


def turn_end(chat_id: str) -> tuple[float, str, str]:
    """(rollout activity time, working|idle|'', error code of the last finished turn or '').

    A turn Codex refused (2026-11-27: `usage_limit_exceeded` until the weekly reset) ends
    with `task_complete` carrying an error and no answer, so the chat never pushes ✅ or ❓.
    """
    record = load(chat_id) or {}
    path = rollout_path(record.get("thread_id") or "")
    if path is None:
        return 0, "", ""
    try:
        changed = path.stat().st_mtime
        with path.open("rb") as stream:
            end = stream.seek(0, os.SEEK_END)
            stream.seek(max(0, end - 512 * 1024))
            if end > 512 * 1024:
                stream.readline()
            rows = stream.read().splitlines()
    except FileNotFoundError:
        return 0, "", ""
    for line in reversed(rows):
        if b'"event_msg"' not in line:
            continue
        try:
            row = json.loads(line)
        except (ValueError, UnicodeError):
            continue
        payload = row.get("payload") or {}
        event = payload.get("type")
        if event in ("user_message", "task_started"):
            return changed, "working", ""
        if event in ("task_complete", "turn_aborted"):
            error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
            return changed, "idle", str(error.get("codex_error_info") or "")
    return changed, "", ""


def usage_reset_at(reading: dict | None = None, now: datetime | None = None) -> float | None:
    """Epoch time when every exhausted Codex window has reset; None when none is exhausted or known."""
    reading = usage() if reading is None else reading
    exhausted = {item.split(":", 1)[0] for item in exhausted_windows(reading, now)}
    resets = [datetime.fromisoformat(reading[window]["resets_at"]).timestamp() for window in exhausted
              if (reading.get(window) or {}).get("resets_at")]
    return max(resets) if resets else None


def reap(pushed, idle_minutes: float, waiting: set[str], now: float, act: bool = True,
         signal_fn=os.kill, can_suspend=None, ready: set[str] | None = None,
         idle_suspend_minutes: float | None = None, reset_at=None) -> list[dict[str, Any]]:
    """Stop live Codex chats that reported done (✅) or asked the owner (❓) and sat idle since.

    Same rule as Claude pane chats (claude_idle_chats.py): a chat is closed only when it
    pushed done or asked, waits on no waiter and its last step is `idle_minutes` old. A new
    message (dev connector send_message) or its waiter reopens it with `codex resume`.
    `pushed(chat_id, last_prompt_at)` returns the chat's push marker ({} when none).

    With `can_suspend` (the lifecycle), two more idle chats are stopped, since nothing ever
    wakes an idle Codex process (2026-11-27: 11 of them held 11 of 15 slots for hours):
      * its last turn was refused for the usage limit: stopped at once; the entry carries
        `reopen_at` (`reset_at()`, the limit's reset) so a timer reopens it to continue,
      * idle `idle_suspend_minutes` without ✅, ❓ or waiter: stopped with `unfinished`; its
        worktree stays snapshotted and listed, and a new message reopens it.
    """
    import signal

    stopped = []
    for chat_id, info in live().items():
        if chat_id in (ready or ()):
            continue
        waits = chat_id in waiting
        if waits and can_suspend is None:
            continue
        error = ""
        if can_suspend is not None:
            activity, state = turn_activity(chat_id)
            if state != "idle" or now - activity < idle_minutes * 60 or not can_suspend(chat_id, info["pid"]):
                continue
            error = turn_end(chat_id)[2]
        activity, prompt = last_times(chat_id)
        marker = pushed(chat_id, prompt) or {}
        kind = marker.get("kind")
        quiet = now - max(activity, float(marker.get("ts", 0)))
        extra: dict[str, Any] = {}
        if error == USAGE_LIMIT_ERROR and not waits:
            reason = "Codex usage limit reached; reopens when the limit resets"
            extra["reopen_at"] = reset_at() if reset_at else None
        elif kind in ("✅", "❓") or waits:
            if quiet < idle_minutes * 60:
                continue
            reason = "registered wait" if waits else "reported done" if kind == "✅" else "asked the owner"
        elif can_suspend is not None and idle_suspend_minutes is not None and quiet >= idle_suspend_minutes * 60:
            reason = f"idle {quiet / 60:.0f} min without ✅, question or waiter"
            extra["unfinished"] = True
        else:
            continue
        entry = {"chat_id": chat_id, "pid": info["pid"], "why": reason, **extra}
        if marker.get("source") == "chat_compaction_handoff":
            entry["archived"] = True
        if act:
            try:
                signal_fn(info["pid"], signal.SIGTERM)
            except ProcessLookupError:
                continue
        stopped.append(entry)
    return stopped


def type_into(chat_id: str, text: str, zellij=None, *, images: tuple[str, ...] = (),
              preserve_input: bool = False) -> str:
    """Type a message into a live Codex chat's tab and submit it ('ok' or why not).

    Codex queues a message typed while a turn runs and takes it as the next prompt.
    """
    import subprocess

    process = live().get(chat_id)
    if not process:
        return "not running"
    env = _proc_env(process["pid"])
    session, pane = env.get("ZELLIJ_SESSION_NAME", ""), env.get("ZELLIJ_PANE_ID", "")
    if env.get("OPENMATES_CHAT_ID") != chat_id or not session or not pane.isdecimal():
        return "its terminal pane could not be confirmed"
    run = zellij or (lambda *a: subprocess.run(["zellij", "--session", session, "action", *a],
                                               capture_output=True, text=True, timeout=30, check=False))
    if preserve_input:
        screen = run("dump-screen", "--pane-id", f"terminal_{pane}", "--ansi")
        lines = [re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", line) for line in screen.stdout.splitlines()]
        footer = max((i for i, line in enumerate(lines) if re.match(r"\s+(?:GPT-|gpt-|Codex\s+)", line)), default=-1)
        box = max((i for i, line in enumerate(lines[:footer]) if line.startswith("›")), default=-1)
        if screen.returncode or box < 0 or any(line.strip() for line in lines[box + 1:footer]):
            return "The chat composer is not available for a safe wake"
        if lines[box][1:].strip() not in ("", "Ask Codex to do anything"):
            return "The chat has an unsent draft"
        if any(line.strip() for line in lines[footer + 1:]):
            return "The chat may be waiting for input"
    actions = [("write-chars", [" ".join(text.split("\n"))])]
    for path in images:
        # The Codex composer attaches a single image path received as a bracketed paste.
        paste = f"\x1b[200~{path}\x1b[201~".encode()
        actions.append(("write", [str(byte) for byte in paste]))
    actions.append(("write", ["13"]))
    for index, (action, args) in enumerate(actions):
        if index == len(actions) - 1:
            time.sleep(0.5)  # Let Codex finish interpreting the paste before submitting it.
        result = run(action, "--pane-id", f"terminal_{pane}", *args)
        if result.returncode:
            return f"zellij {action} failed: {(result.stderr or '').strip()[:160]}"
    return "ok"


# ── Usage ────────────────────────────────────────────────────────────────────

def _window(raw: Any, observed: float) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or not isinstance(raw.get("used_percent"), (int, float)):
        return None
    resets = raw.get("resets_at")
    if not isinstance(resets, (int, float)) and isinstance(raw.get("resets_in_seconds"), (int, float)):
        resets = observed + raw["resets_in_seconds"]
    minutes = raw.get("window_minutes")
    return {"used_percent": float(raw["used_percent"]), "remaining_percent": round(100 - float(raw["used_percent"]), 1),
            "window_minutes": minutes if isinstance(minutes, int) else None,
            "resets_at": datetime.fromtimestamp(resets, timezone.utc).isoformat(timespec="seconds")
            if isinstance(resets, (int, float)) else None}


def usage(newest: int = 20) -> dict[str, Any]:
    """Remaining Codex plan usage from the newest rate-limit reading in the session files.

    `weekly` is the longer window (Codex calls it secondary), `five_hour` the shorter one.
    Readings come only from Codex's own events; with none yet the result says so.
    """
    files = sorted((codex_home() / "sessions").glob("**/rollout-*.jsonl"), key=lambda p: p.stat().st_mtime,
                   reverse=True)[:newest] if (codex_home() / "sessions").is_dir() else []
    best: tuple[float, dict[str, Any]] | None = None
    for path in files:
        for item in _rollout_lines(path):
            payload = item.get("payload") or {}
            limits = payload.get("rate_limits") if isinstance(payload, dict) else None
            if not isinstance(limits, dict):
                continue
            try:
                observed = datetime.fromisoformat(str(item.get("timestamp")).replace("Z", "+00:00")).timestamp()
            except ValueError:
                observed = path.stat().st_mtime
            # Codex writes one reading per limit id; the "premium" one has no windows and
            # hid an exhausted weekly limit (2026-11-27), so only readings with a window count.
            if not any(_window(limits.get(key), observed) for key in ("primary", "secondary")):
                continue
            if best is None or observed > best[0]:
                best = (observed, limits)
    if best is None:
        return {"engine": "codex", "known": False, "why": "no Codex rate-limit reading yet (no Codex turn has run)"}
    observed, limits = best
    windows = [w for w in (_window(limits.get("primary"), observed), _window(limits.get("secondary"), observed)) if w]
    windows.sort(key=lambda w: w["window_minutes"] or 0)
    result: dict[str, Any] = {"engine": "codex", "known": True,
                              "observed_at": datetime.fromtimestamp(observed, timezone.utc).isoformat(timespec="seconds")}
    if windows:
        result["five_hour" if len(windows) > 1 else "weekly"] = windows[0]
    if len(windows) > 1:
        result["weekly"] = windows[-1]
    return result


def exhausted_windows(reading: dict | None = None, now: datetime | None = None) -> list[str]:
    """Unreset Codex rate-limit windows that report no capacity."""
    reading = usage() if reading is None else reading
    now = now or datetime.now(timezone.utc)
    exhausted = []
    for window in ("five_hour", "weekly"):
        limit = reading.get(window) or {}
        if float(limit.get("used_percent", 0)) < 100:
            continue
        reset = limit.get("resets_at")
        if not reset or now < datetime.fromisoformat(reset):
            exhausted.append(f"{window}:{reset or reading.get('observed_at', 'unknown')}")
    return exhausted


def describe(record: dict[str, Any]) -> str:
    """One-line shell form of a chat's start command (for logs; never contains secrets)."""
    return shlex.join(codex_args(record, "<prompt>"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    mirror_cmd = sub.add_parser("mirror")
    mirror_cmd.add_argument("--chat", default="")
    sub.add_parser("usage")
    args = parser.parse_args(argv)
    if args.command == "list":
        running = live()
        print(json.dumps([{**r, "live": r["chat_id"] in running} for r in records()], indent=1, sort_keys=True))
    elif args.command == "mirror":
        paths = {args.chat: mirror(args.chat)} if args.chat else transcripts()
        print(json.dumps({k: str(v) if v else None for k, v in paths.items()}, indent=1, sort_keys=True))
    else:
        print(json.dumps(usage(), indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
