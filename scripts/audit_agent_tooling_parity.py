#!/usr/bin/env python3
"""Audit Claude Code, Codex, and OpenCode tooling parity.

Claude Code remains the canonical authoring format for OpenMates skills,
agents, and hook scripts. This audit makes the shared hook/config baseline
explicit, checks generated/bridged tool coverage, and allows only documented
tool-specific exceptions.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = Path("docs/architecture/agent-tooling-parity.yml")
CLAUDE_SETTINGS = Path(".claude/settings.json")
CODEX_BRIDGE = Path(".codex/hooks/claude-hook-bridge.sh")
CODEX_HOOKS_JSON = Path(".codex/hooks.json")
OPENCODE_PLUGIN = Path(".opencode/plugins/openmates-hooks.js")
OPENCODE_PLUGIN_IMPLEMENTATION = Path(".opencode/runtime/openmates-hooks-runtime.js")


@dataclass(frozen=True)
class AuditIssue:
    path: str
    message: str


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _load_manifest(root: Path) -> dict[str, Any]:
    path = root / MANIFEST
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _exception_reason(hook: dict[str, Any], tool: str) -> str:
    exceptions = hook.get("exceptions") or {}
    if not isinstance(exceptions, dict):
        return ""
    reason = exceptions.get(tool) or ""
    return str(reason).strip()


def _matcher_covers(actual: str, expected: str) -> bool:
    actual_parts = {part.strip() for part in actual.split("|") if part.strip()}
    expected_parts = {part.strip() for part in expected.split("|") if part.strip()}
    return bool(expected_parts) and expected_parts <= actual_parts


def _claude_settings_has_hook(text: str, *, event: str, matcher: str, hook_name: str) -> bool:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return False
    hooks = data.get("hooks", {})
    event_entries = hooks.get(event, [])
    if not isinstance(event_entries, list):
        return False
    for entry in event_entries:
        if not isinstance(entry, dict):
            continue
        actual_matcher = str(entry.get("matcher") or "")
        if not _matcher_covers(actual_matcher, matcher):
            continue
        commands = entry.get("hooks", [])
        if not isinstance(commands, list):
            continue
        for command in commands:
            if isinstance(command, dict) and hook_name in str(command.get("command") or ""):
                return True
    return False


def _event_block(text: str, event: str) -> str:
    markers = (f"  {event})", f"{event})")
    starts = [index for marker in markers if (index := text.find(marker)) != -1]
    if not starts:
        return ""
    start = min(starts)
    search_from = start + len(event) + 1
    next_starts = [index for candidate in ("  PreToolUse)", "PreToolUse)", "  PostToolUse)", "PostToolUse)", "  Stop)", "Stop)", "  UserPromptSubmit)", "UserPromptSubmit)") if (index := text.find(candidate, search_from)) != -1]
    end = min(next_starts) if next_starts else len(text)
    return text[start:end]


def _codex_bridge_has_hook(text: str, *, event: str, matcher: str, hook_name: str) -> bool:
    block = _event_block(text, event)
    if hook_name not in block:
        return False
    if matcher == "Bash":
        return "Bash" in block and hook_name in block
    if not _matcher_covers("apply_patch|Edit|Write", matcher):
        return hook_name in block
    if "apply_patch|Edit|Write)" not in block:
        return False
    hook_index = block.find(hook_name)
    conditional_window = block[max(0, hook_index - 160) : hook_index]
    if '"$TOOL" = "apply_patch"' in conditional_window and matcher != "apply_patch":
        return False
    return True


def _claude_hook_commands(text: str) -> set[str]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return set()
    commands: set[str] = set()
    for entries in (data.get("hooks") or {}).values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            for hook in entry.get("hooks") or []:
                if not isinstance(hook, dict):
                    continue
                command = str(hook.get("command") or "")
                commands.update(re.findall(r"([A-Za-z0-9_.-]+\.sh)", command))
    return commands


def _tracked_claude_hook_files(root: Path) -> set[str]:
    hooks_dir = root / ".claude" / "hooks"
    if not hooks_dir.exists():
        return set()
    return {str(path.relative_to(hooks_dir)) for path in hooks_dir.rglob("*.sh")}


def _bridge_hook_references(text: str) -> set[str]:
    return set(re.findall(r'"([A-Za-z0-9_.-]+\.sh)"', text))


def _manifest_exception_names(manifest: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for item in manifest.get("tracked_hook_exceptions") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        reason = str(item.get("reason") or "").strip()
        if name and reason:
            names.add(name)
    return names


def _required_tools(hook: dict[str, Any]) -> set[str]:
    tools = hook.get("tools") or []
    return {str(tool).strip() for tool in tools if str(tool).strip()}


def _audit_shared_hook(root: Path, hook: dict[str, Any], texts: dict[str, str]) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    name = str(hook.get("name") or "").strip()
    if not name:
        return [AuditIssue(str(MANIFEST), "shared hook entry missing name")]
    tools = _required_tools(hook)
    event = str(hook.get("event") or "").strip()
    matcher = str(hook.get("matcher") or "").strip()

    if "claude" in tools and not _claude_settings_has_hook(texts["claude"], event=event, matcher=matcher, hook_name=name):
        issues.append(AuditIssue(str(CLAUDE_SETTINGS), f"Claude settings missing shared hook: {name}"))
    codex_terms = [str(term) for term in hook.get("codex_terms") or []]
    if "codex" in tools:
        if codex_terms:
            for term in codex_terms:
                if term not in texts["codex_hooks_json"] and term not in texts["codex"]:
                    issues.append(AuditIssue(str(CODEX_HOOKS_JSON), f"Codex hooks missing shared hook term for {name}: {term}"))
        elif not _codex_bridge_has_hook(texts["codex"], event=event, matcher=matcher, hook_name=name):
            issues.append(AuditIssue(str(CODEX_BRIDGE), f"Codex bridge missing shared hook: {name}"))
    if "opencode" in tools:
        terms = [str(term) for term in hook.get("opencode_terms") or [name]]
        for term in terms:
            if term not in texts["opencode"]:
                issues.append(AuditIssue(str(OPENCODE_PLUGIN), f"OpenCode plugin missing shared hook term for {name}: {term}"))
        if hook.get("opencode_delegates_to_codex_bridge") is True and not _codex_bridge_has_hook(texts["codex"], event=event, matcher=matcher, hook_name=name):
            issues.append(AuditIssue(str(CODEX_BRIDGE), f"OpenCode delegated hook missing from Codex bridge: {name}"))
    elif _exception_reason(hook, "opencode") == "" and {"claude", "codex"} <= tools:
        issues.append(AuditIssue(str(MANIFEST), f"OpenCode exception for shared hook {name} needs a reason"))

    for tool in {"claude", "codex", "opencode"} - tools:
        reason = _exception_reason(hook, tool)
        if reason == "" and tool in {"claude", "codex"}:
            issues.append(AuditIssue(str(MANIFEST), f"{tool} exception for shared hook {name} needs a reason"))
    return issues


def _audit_quickstart(root: Path, manifest: dict[str, Any]) -> list[AuditIssue]:
    quickstart = manifest.get("quickstart") or {}
    if not isinstance(quickstart, dict):
        return [AuditIssue(str(MANIFEST), "quickstart contract must be a mapping")]
    path = Path(str(quickstart.get("path") or ""))
    if not path:
        return [AuditIssue(str(MANIFEST), "quickstart.path is required")]
    text = _read(root / path)
    if not text:
        return [AuditIssue(str(path), "quickstart file is missing")]
    issues: list[AuditIssue] = []
    for term in quickstart.get("required_terms") or []:
        term_text = str(term)
        if term_text not in text:
            issues.append(AuditIssue(str(path), f"quickstart missing required term: {term_text}"))
    return issues


def audit(root: Path = REPO_ROOT) -> list[AuditIssue]:
    manifest = _load_manifest(root)
    if not manifest:
        return [AuditIssue(str(MANIFEST), "agent tooling parity manifest is missing or invalid")]

    texts = {
        "claude": _read(root / CLAUDE_SETTINGS),
        "codex": _read(root / CODEX_BRIDGE),
        "codex_hooks_json": _read(root / CODEX_HOOKS_JSON),
        "opencode": _read(
            root / (OPENCODE_PLUGIN_IMPLEMENTATION if (root / OPENCODE_PLUGIN_IMPLEMENTATION).is_file() else OPENCODE_PLUGIN)
        ),
    }
    issues: list[AuditIssue] = []
    shared_hooks = manifest.get("shared_hooks") or []
    manifest_hook_names: set[str] = set()
    for hook in shared_hooks:
        if not isinstance(hook, dict):
            issues.append(AuditIssue(str(MANIFEST), "shared hook entry must be a mapping"))
            continue
        if hook.get("name"):
            manifest_hook_names.add(str(hook["name"]))
        issues.extend(_audit_shared_hook(root, hook, texts))
    exception_names = _manifest_exception_names(manifest)
    represented_names = manifest_hook_names | exception_names
    for hook_name in sorted(_tracked_claude_hook_files(root) - represented_names):
        issues.append(AuditIssue(str(MANIFEST), f"tracked Claude hook file is missing from parity manifest: {hook_name}"))
    for hook_name in sorted(_bridge_hook_references(texts["codex"]) - represented_names - {"claude-hook-bridge.sh"}):
        issues.append(AuditIssue(str(MANIFEST), f"Codex bridge hook reference is missing from parity manifest: {hook_name}"))
    for hook_name in sorted(_claude_hook_commands(texts["claude"]) - represented_names):
        issues.append(AuditIssue(str(MANIFEST), f"tracked Claude hook is missing from parity manifest: {hook_name}"))
    issues.extend(_audit_quickstart(root, manifest))
    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit Claude Code, Codex, and OpenCode tooling parity.")
    parser.add_argument("--json", action="store_true", help="Print issues as JSON.")
    args = parser.parse_args(argv)

    issues = audit(REPO_ROOT)
    if args.json:
        print(json.dumps([issue.__dict__ for issue in issues], indent=2, sort_keys=True))
    elif issues:
        print("FAIL agent tooling parity audit", file=sys.stderr)
        for issue in issues:
            print(f"- {issue.path}: {issue.message}", file=sys.stderr)
    else:
        print("PASS agent tooling parity audit")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
