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
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

DEFAULT_MODEL = "gpt-6.2-sol"
# Owner, 2026-11-23: Astra only when Marco names it, like Fable for Claude.
EXPLICIT_ONLY_MODELS = ("gpt-6.2-astra",)
MAX_EFFORT = "medium"
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


# ── Launch command ───────────────────────────────────────────────────────────

def chat_env(record: dict[str, Any]) -> dict[str, str]:
    """Variables every process of the chat sees (hooks, sessions.py, agent_question.py)."""
    return {"OPENMATES_CHAT_ID": record["chat_id"], "CLAUDE_CODE_SESSION_ID": record["chat_id"],
            "OPENMATES_CHAT_ENGINE": "codex", "OPENMATES_CHAT_MODEL": record["model"],
            "OPENMATES_CODEX_CHATS_DIR": str(state_dir()), "CLAUDE_CHAT_TITLE": record["title"]}


def codex_args(record: dict[str, Any], prompt: str = "", resume_thread: str = "") -> list[str]:
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
    if prompt:
        args.append(prompt)
    return args


def tab_command(record: dict[str, Any], prompt: str = "", resume_thread: str = "") -> list[str]:
    """Command for the chat's zellij tab: user bins first on PATH plus the chat identity."""
    user_bins = [str(Path.home() / ".npm-global/bin"), str(Path.home() / ".local/bin")]
    inherited = [p for p in os.environ.get("PATH", os.defpath).split(os.pathsep) if p and p not in user_bins]
    env = [f"{k}={v}" for k, v in sorted(chat_env(record).items())]
    return ["/usr/bin/env", f"PATH={os.pathsep.join([*user_bins, *inherited])}", *env,
            *codex_args(record, prompt, resume_thread)]


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
    return any(part.endswith((b"/codex", b"codex.js")) or part == b"codex" for part in cmd[:3])


def live(proc: Path = Path("/proc")) -> dict[str, dict[str, Any]]:
    """chat id -> {pid} for every running Codex chat process started by the host (top process only)."""
    found: dict[str, dict[str, Any]] = {}
    for entry in proc.iterdir() if proc.is_dir() else []:
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        env = _proc_env(pid)
        chat_id = env.get("OPENMATES_CHAT_ID", "")
        if env.get("OPENMATES_CHAT_ENGINE") != "codex" or not UUID_RE.match(chat_id) or not _is_codex_process(pid):
            continue
        if chat_id not in found or pid < found[chat_id]["pid"]:
            found[chat_id] = {"pid": pid}
    return found


# ── Session files and transcripts ────────────────────────────────────────────

def rollout_path(thread_id: str) -> Path | None:
    if not UUID_RE.match(thread_id):
        return None
    matches = sorted((codex_home() / "sessions").glob(f"**/rollout-*-{thread_id}.jsonl"))
    return matches[-1] if matches else None


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


def to_claude_records(items: Iterator[dict[str, Any]], record: dict[str, Any]) -> list[dict[str, Any]]:
    """Codex session items as Claude Code transcript records (what the connector reads)."""
    chat_id, cwd, model = record["chat_id"], record.get("cwd", ""), f"codex:{record.get('model', DEFAULT_MODEL)}"
    out: list[dict[str, Any]] = [{"type": "custom-title", "customTitle": record.get("title", ""), "sessionId": chat_id}]
    for item in items:
        stamp, payload = item.get("timestamp"), item.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        base = {"timestamp": stamp, "sessionId": chat_id, "cwd": cwd, "engine": "codex"}
        kind, ptype = item.get("type"), payload.get("type")
        if kind == "event_msg" and ptype == "user_message" and payload.get("message"):
            out.append({**base, "type": "user", "message": {"role": "user", "content": str(payload["message"])}})
        elif kind == "event_msg" and ptype == "agent_message" and payload.get("message"):
            out.append({**base, "type": "assistant", "message": {
                "role": "assistant", "model": model, "content": [{"type": "text", "text": str(payload["message"])}]}})
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
    if target.exists() and target.stat().st_mtime >= source.stat().st_mtime:
        return target
    rows = to_claude_records(_rollout_lines(source), record)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    tmp.replace(target)
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


def reap(pushed, idle_minutes: float, waiting: set[str], now: float, act: bool = True,
         signal_fn=os.kill) -> list[dict[str, Any]]:
    """Stop live Codex chats that reported done (✅) or asked the owner (❓) and sat idle since.

    Same rule as Claude pane chats (claude_idle_chats.py): a chat is closed only when it
    pushed done or asked, waits on no waiter and its last step is `idle_minutes` old. A new
    message (dev connector send_message) or its waiter reopens it with `codex resume`.
    `pushed(chat_id, last_prompt_at)` returns the chat's push marker ({} when none).
    """
    import signal

    stopped = []
    for chat_id, info in live().items():
        if chat_id in waiting:
            continue
        activity, prompt = last_times(chat_id)
        marker = pushed(chat_id, prompt) or {}
        kind = marker.get("kind")
        if kind not in ("✅", "❓") or now - max(activity, float(marker.get("ts", 0))) < idle_minutes * 60:
            continue
        entry = {"chat_id": chat_id, "pid": info["pid"], "why": "reported done" if kind == "✅" else "asked the owner"}
        if marker.get("source") == "chat_compaction_handoff":
            entry["archived"] = True
        if act:
            try:
                signal_fn(info["pid"], signal.SIGTERM)
            except ProcessLookupError:
                continue
        stopped.append(entry)
    return stopped


def type_into(chat_id: str, text: str, zellij=None) -> str:
    """Type a message into a live Codex chat's tab and submit it ('ok' or why not).

    Codex queues a message typed while a turn runs and takes it as the next prompt.
    """
    import subprocess

    record = load(chat_id) or {}
    title = str(record.get("title") or "")
    if chat_id not in live() or not title:
        return "not running"
    session = os.environ.get("CLAUDE_DISPATCH_ZELLIJ_SESSION", "claude")
    run = zellij or (lambda *a: subprocess.run(["zellij", "--session", session, "action", *a],
                                               capture_output=True, text=True, timeout=30, check=False))
    for args in (("go-to-tab-name", title), ("write-chars", " ".join(text.split("\n"))), ("write", "13")):
        result = run(*args)
        if result.returncode:
            return f"zellij {args[0]} failed: {(result.stderr or '').strip()[:160]}"
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
