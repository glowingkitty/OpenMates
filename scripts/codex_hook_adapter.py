#!/usr/bin/env python3
"""Run this repository's Claude Code hooks for Codex chats, so both engines obey one rule set.

Codex (0.169+) has lifecycle hooks with Claude-compatible payloads and decisions: the same
event names, `Bash` with `tool_input.command`, exit 2 + stderr or JSON `decision: block`
to refuse. `.codex/hooks.json` is static: it sends every event to this adapter, and the
adapter reads `.claude/settings.json` at run time and runs the Claude hooks whose matcher
fits. A hook therefore exists once, in .claude/settings.json, and nothing can drift.

Translation:
  * tool names: Codex `apply_patch` matches Claude `Edit|Write|MultiEdit|NotebookEdit`
    matchers, `spawn_agent` matches `Agent|Task`; Claude-only tools (Read, SendMessage)
    never match. `*` or no matcher matches everything.
  * edits: one `apply_patch` may touch many files. Each file becomes its own Claude-style
    payload (Write with the content of an added file, Edit with old_string/new_string for
    an update, Edit with an empty new_string for a deletion); the hook runs per file and
    the first refusal wins. Relative patch paths resolve against the payload cwd.
  * identity: `session_id` becomes the chat id the launcher exported (OPENMATES_CHAT_ID),
    so session bindings, CI waiters and push records match the chat; the Codex thread id
    is stored in the chat's registry record (OPENMATES_CODEX_CHATS_DIR/<chat id>.json).
    Every adapted payload carries codex_thread_id, even without a launcher chat id.
  * output: Codex rejects plain text on Stop; plain stdout of a Stop hook that exits 0 is
    dropped. Exit 2 and JSON decisions pass through.
Built-in guards run before the repository hooks: sub-agents keep the chat's model and at
most medium effort; a chat may not change or switch off the Codex hooks and config; and
the `permissions.deny` rules of .claude/settings.json hold for Codex too (`Bash(prefix:*)`
refuses matching commands, `Read(path)`/`Edit(path)` refuse commands and patches that
touch the path, since Codex reads and writes files through the shell).

A hook that crashes or times out is reported on stderr and does not block (as in Claude
Code, where only exit 2 blocks). Hooks of one event run in parallel, like Claude Code.

This file is self-contained (standard library only) so other repositories can carry an
identical copy. Usage (.codex/hooks.json): python3 <repo>/scripts/codex_hook_adapter.py --event PreToolUse
Tests: scripts/tests/test_codex_hook_adapter.py
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

HOOK_TIMEOUT_SECONDS = 590  # Codex's own per-hook default is 600
UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
TOOL_ALIASES = {"apply_patch": ("apply_patch", "Edit", "Write", "MultiEdit", "NotebookEdit"),
                "spawn_agent": ("spawn_agent", "Agent", "Task"), "Bash": ("Bash",)}
EFFORT_ORDER = ("minimal", "low", "medium", "high", "xhigh", "max", "ultra")
MAX_EFFORT = "medium"
PROTECTED = (".codex/hooks.json", ".codex/config.toml", ".codex/requirements.toml", "/etc/codex/")
_WRITE_HINT = ("rm ", "mv ", "cp ", "tee ", "sed -i", ">", "truncate", "chmod", "ln ", "python", "perl", "unlink",
               "install ", "git checkout", "git restore")
Result = tuple[int, str, str]  # exit code, stdout, stderr


# ── apply_patch ──────────────────────────────────────────────────────────────

def parse_patch(patch: str) -> list[dict[str, str]]:
    """Files of an apply_patch body: [{op: add|update|delete, path, old, new}] in order."""
    files: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    tags = (("add", "*** Add File: "), ("update", "*** Update File: "), ("delete", "*** Delete File: "))
    for line in patch.splitlines():
        header = next(((op, line[len(tag):].strip()) for op, tag in tags if line.startswith(tag)), None)
        if header:
            current = {"op": header[0], "path": header[1], "old": [], "new": []}
            files.append(current)
        elif current is not None and line.startswith("*** Move to: "):
            current["path"] = line[len("*** Move to: "):].strip()
        elif current is None or line.startswith("*** "):
            continue
        elif line.startswith("+"):
            current["new"].append(line[1:])
        elif line.startswith("-"):
            current["old"].append(line[1:])
        elif line.startswith(" "):
            current["old"].append(line[1:])
            current["new"].append(line[1:])
    return [{"op": f["op"], "path": f["path"], "old": "\n".join(f["old"]), "new": "\n".join(f["new"])} for f in files]


def edit_payloads(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """One Claude-style Edit/Write payload per file an apply_patch touches (else the payload itself)."""
    if payload.get("tool_name") != "apply_patch":
        return [payload]
    tool_input = payload.get("tool_input") or {}
    patch = tool_input.get("command") or tool_input.get("patch") or tool_input.get("input") or ""
    if isinstance(patch, list):
        patch = "\n".join(str(p) for p in patch)
    cwd = Path(str(tool_input.get("workdir") or payload.get("cwd") or os.getcwd()))
    out = []
    for item in parse_patch(str(patch)):
        path = Path(item["path"])
        absolute = str(path if path.is_absolute() else (cwd / path))
        if item["op"] == "add":
            tool, args = "Write", {"file_path": absolute, "content": item["new"]}
        else:
            tool, args = "Edit", {"file_path": absolute, "old_string": item["old"],
                                  "new_string": "" if item["op"] == "delete" else item["new"]}
        out.append({**payload, "tool_name": tool, "tool_input": args, "codex_tool_name": "apply_patch"})
    return out


# ── Identity ─────────────────────────────────────────────────────────────────

def record_thread(chat_id: str, thread_id: str, env: dict[str, str]) -> None:
    """Store the Codex thread id in the chat's registry record (written by the launcher)."""
    folder = env.get("OPENMATES_CODEX_CHATS_DIR", "")
    if not folder or not UUID_RE.match(chat_id) or not UUID_RE.match(thread_id):
        return
    path = Path(folder) / f"{chat_id}.json"
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(record, dict) or record.get("thread_id") == thread_id:
        return
    record["thread_id"] = thread_id
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(record, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def normalize(payload: dict[str, Any], env: dict[str, str]) -> dict[str, Any]:
    chat_id, thread = env.get("OPENMATES_CHAT_ID", ""), str(payload.get("session_id") or "")
    if UUID_RE.match(chat_id):
        if thread and thread != chat_id:
            record_thread(chat_id, thread, env)
        payload = {**payload, "session_id": chat_id}
    return {**payload, "codex_thread_id": thread}


def hook_env(env: dict[str, str], root: Path) -> dict[str, str]:
    out = {**env, "CLAUDE_PROJECT_DIR": str(root)}
    if env.get("OPENMATES_CHAT_ID"):
        out["CLAUDE_CODE_SESSION_ID"] = env["OPENMATES_CHAT_ID"]
    return out


# ── Matching ─────────────────────────────────────────────────────────────────

def matches(matcher: str | None, event: str, payload: dict[str, Any]) -> bool:
    if matcher in (None, "", "*"):
        return True
    names = matcher.split("|")
    if event in ("PreToolUse", "PostToolUse", "PermissionRequest"):
        tool = str(payload.get("tool_name") or "")
        aliases = TOOL_ALIASES.get(tool, (tool,))
        if tool.startswith("mcp__"):
            return any(re.fullmatch(n, tool) for n in names if n)
        return any(name in aliases for name in names)
    if event == "SessionStart":
        return str(payload.get("source") or "startup") in names
    return True


def hooks_for(settings: dict[str, Any], event: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    found = []
    for group in (settings.get("hooks") or {}).get(event) or []:
        if matches(group.get("matcher"), event, payload):
            found += [h for h in group.get("hooks") or [] if h.get("type", "command") == "command" and h.get("command")]
    return found


# ── Built-in guards ──────────────────────────────────────────────────────────

def agent_guard(payload: dict[str, Any], env: dict[str, str]) -> Result | None:
    """Codex sub-agents keep the chat's model and at most medium effort."""
    if payload.get("tool_name") != "spawn_agent":
        return None
    tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    model = str(tool_input.get("model") or "").lower()
    chat_model = env.get("OPENMATES_CHAT_MODEL", "").lower()
    if model and model != chat_model:
        return 2, "", (f"codex agent guard: sub-agents run on the chat's model ({chat_model or 'its default'}); "
                       f"drop the model override {model!r}\n")
    effort = str(tool_input.get("reasoning_effort") or tool_input.get("effort") or "").lower()
    if effort in EFFORT_ORDER and EFFORT_ORDER.index(effort) > EFFORT_ORDER.index(MAX_EFFORT):
        return 2, "", f"codex agent guard: effort is at most {MAX_EFFORT}, not {effort}\n"
    return None


def self_guard(payload: dict[str, Any]) -> Result | None:
    """A chat may not change or switch off the Codex hooks and config that bind it."""
    refusal = (2, "", "codex self guard: the Codex hooks and config are managed outside the chat; "
                      "a chat may not change or bypass them\n")
    if payload.get("tool_name") == "apply_patch":
        paths = [str(item["tool_input"].get("file_path", "")) for item in edit_payloads(payload)]
        return refusal if any(mark in p for p in paths for mark in PROTECTED) else None
    command = str((payload.get("tool_input") or {}).get("command") or "")
    squashed = command.replace(" ", "")
    if any(mark in command for mark in PROTECTED) and any(hint in command for hint in _WRITE_HINT):
        return refusal
    if any(flag in squashed for flag in ("features.hooks=false", "codex_hooks=false", "--disablehooks")):
        return refusal
    return None


def deny_guard(payload: dict[str, Any], settings: dict[str, Any], env: dict[str, str]) -> Result | None:
    """Claude's permissions.deny rules, applied to Codex shell commands and patches."""
    home = env.get("HOME") or str(Path.home())
    tool = payload.get("tool_name")
    command = str((payload.get("tool_input") or {}).get("command") or "").strip() if tool == "Bash" else ""
    edited = [str(p["tool_input"].get("file_path", "")) for p in edit_payloads(payload)] if tool == "apply_patch" else []
    refusal = lambda rule: (2, "", f"codex deny guard: {rule} is denied in .claude/settings.json\n")  # noqa: E731 - local helper
    for rule in (settings.get("permissions") or {}).get("deny") or []:
        match = re.fullmatch(r"(\w+)\((.+)\)", str(rule))
        if not match:
            continue
        kind, arg = match.groups()
        if kind == "Bash" and command:
            prefix = arg[:-2] if arg.endswith(":*") else arg
            if command == prefix or command.startswith(prefix + " "):
                return refusal(rule)
        elif kind in ("Read", "Edit", "Write"):
            target = home + arg[1:] if arg.startswith("~") else arg
            literal = target.split("*", 1)[0].rstrip("/")
            tilde = arg.split("*", 1)[0].rstrip("/")
            if command and literal and (literal in command or (tilde.startswith("~") and tilde in command)):
                return refusal(rule)
            if any(fnmatch.fnmatch(path, target) or (literal and path.startswith(literal)) for path in edited):
                return refusal(rule)
    return None


# ── Running ──────────────────────────────────────────────────────────────────

def _blocks(decision: dict[str, Any]) -> bool:
    specific = decision.get("hookSpecificOutput") or {}
    return (decision.get("decision") == "block" or decision.get("continue") is False
            or (isinstance(specific, dict) and specific.get("permissionDecision") == "deny"))


def run_one(command: str, payload: dict[str, Any], env: dict[str, str], root: Path, timeout: float) -> Result:
    try:
        done = subprocess.run(["/bin/bash", "-c", command], input=json.dumps(payload), capture_output=True,
                              text=True, timeout=timeout, env=env, cwd=str(root), check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        return 1, "", f"codex_hook_adapter: hook {command[:80]!r} failed to run: {error}"
    return done.returncode, done.stdout, done.stderr


def combine(event: str, results: list[Result]) -> Result:
    """First refusal wins; otherwise the joined output (plain text dropped on Stop)."""
    outputs, errors = [], []
    for code, stdout, stderr in results:
        if code == 2:
            return 2, "", stderr or stdout
        text = stdout.strip()
        if code == 0 and text.startswith("{"):
            try:
                decision = json.loads(text)
            except ValueError:
                decision = None
            if isinstance(decision, dict) and _blocks(decision):
                return 0, text + "\n", stderr
        if code == 0 and text:
            outputs.append(text)
        if stderr.strip():
            errors.append(stderr.strip()[-500:])
    text = "\n".join(outputs)
    if event == "Stop" and not text.lstrip().startswith("{"):
        text = ""
    return 0, (text + "\n") if text else "", "\n".join(errors)


def dispatch(event: str, raw: str, env: dict[str, str], root: Path) -> Result:
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except ValueError:
        return 0, "", "codex_hook_adapter: payload is not JSON; hooks skipped\n"
    payload = normalize(payload if isinstance(payload, dict) else {}, env)
    try:
        settings = json.loads((root / ".claude" / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return 0, "", f"codex_hook_adapter: no readable .claude/settings.json in {root}: {error}\n"
    if event == "PreToolUse":
        for guard in (self_guard(payload), agent_guard(payload, env), deny_guard(payload, settings, env)):
            if guard:
                return guard
    hooks = hooks_for(settings, event, payload)
    if not hooks:
        return 0, "", ""
    payloads = edit_payloads(payload) if event in ("PreToolUse", "PostToolUse") else [payload]
    run_env = hook_env(env, root)
    jobs = [(h["command"], p, min(float(h.get("timeout") or HOOK_TIMEOUT_SECONDS), HOOK_TIMEOUT_SECONDS))
            for p in payloads for h in hooks]
    with ThreadPoolExecutor(max_workers=min(16, len(jobs))) as pool:
        results = list(pool.map(lambda job: run_one(job[0], job[1], run_env, root, job[2]), jobs))
    return combine(event, results)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--event", required=True)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    code, stdout, stderr = dispatch(args.event, sys.stdin.read(), dict(os.environ), args.root)
    sys.stdout.write(stdout)
    sys.stderr.write(stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
