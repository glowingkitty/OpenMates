#!/usr/bin/env python3
"""Audit OpenCode output-quality and context-efficiency guardrails.

OpenMates relies on OpenCode for most agentic coding work. This audit keeps the
always-loaded instruction surface small, checks that concise guidance still
requires evidence-backed final answers, and exposes privacy-safe aggregate
telemetry helpers without reading or persisting raw chat content.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import sqlite3
import statistics
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
OPENCODE_CONFIG = REPO_ROOT / "opencode.json"
OPENCODE_DB_PATH = Path.home() / ".local" / "share" / "opencode" / "opencode.db"
CORE_INSTRUCTION = "docs/contributing/guides/agent-workflow-core.md"
EAGER_LONG_INSTRUCTIONS = {
    ".claude/rules/planning.md",
    ".claude/rules/testing.md",
    "docs/contributing/guides/spec-driven-development.md",
}
MAX_ALWAYS_LOADED_INSTRUCTIONS = 2
MIN_DUPLICATE_LINE_LENGTH = 40
REQUIRED_CORE_TERMS = {
    "lazy-load guidance": ("lazy-load", "lazy load"),
    "verification guidance": ("verification",),
    "uncertainty guidance": ("uncertainty",),
    "command guidance": ("command",),
    "Firecrawl fallback guidance": ("firecrawl", "fallback", "quota-backed"),
    "parallel tool guidance": ("independent calls", "one turn", "batch"),
    "todo coalescing guidance": ("todo update", "standalone", "model round-trip"),
}
REQUIRED_CORE_PHRASES = {
    "deployed Playwright guidance": (
        "Playwright `*.spec.ts` verification is deployed-code verification",
        "python3 scripts/sessions.py deploy",
        "--gate-deploy --expected-commit",
        "https://app.dev.openmates.org",
    ),
}
FIRECRAWL_TOOL_PERMISSIONS = {
    "firecrawl_firecrawl_agent",
    "firecrawl_firecrawl_agent_status",
    "firecrawl_firecrawl_check_crawl_status",
    "firecrawl_firecrawl_crawl",
    "firecrawl_firecrawl_extract",
    "firecrawl_firecrawl_feedback",
    "firecrawl_firecrawl_interact",
    "firecrawl_firecrawl_interact_stop",
    "firecrawl_firecrawl_map",
    "firecrawl_firecrawl_monitor_check",
    "firecrawl_firecrawl_monitor_checks",
    "firecrawl_firecrawl_monitor_create",
    "firecrawl_firecrawl_monitor_delete",
    "firecrawl_firecrawl_monitor_get",
    "firecrawl_firecrawl_monitor_list",
    "firecrawl_firecrawl_monitor_run",
    "firecrawl_firecrawl_monitor_update",
    "firecrawl_firecrawl_parse",
    "firecrawl_firecrawl_research_inspect_paper",
    "firecrawl_firecrawl_research_read_paper",
    "firecrawl_firecrawl_research_related_papers",
    "firecrawl_firecrawl_research_search_github",
    "firecrawl_firecrawl_research_search_papers",
    "firecrawl_firecrawl_scrape",
    "firecrawl_firecrawl_search",
    "firecrawl_firecrawl_search_feedback",
}
FIRECRAWL_SAFE_PERMISSION_ACTIONS = {"ask", "deny"}


@dataclass(frozen=True)
class AuditIssue:
    path: str
    message: str


def _load_config(path: Path = OPENCODE_CONFIG) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    lower = text.lower()
    return any(term.lower() in lower for term in terms)


def audit_config(config: dict[str, Any], *, root: Path = REPO_ROOT) -> list[AuditIssue]:
    del root
    issues: list[AuditIssue] = []
    instructions = list(config.get("instructions", []))
    instruction_set = set(instructions)

    eager = sorted(instruction_set & EAGER_LONG_INSTRUCTIONS)
    if eager:
        issues.append(
            AuditIssue(
                "opencode.json",
                "always-loaded OpenCode instructions include long rule docs; use the concise core and lazy-load detailed rules: "
                + ", ".join(eager),
            )
        )
    if CORE_INSTRUCTION not in instruction_set:
        issues.append(AuditIssue("opencode.json", f"missing concise core instruction: {CORE_INSTRUCTION}"))
    if len(instructions) > MAX_ALWAYS_LOADED_INSTRUCTIONS:
        issues.append(
            AuditIssue(
                "opencode.json",
                f"always-loaded instruction budget exceeded: {len(instructions)} > {MAX_ALWAYS_LOADED_INSTRUCTIONS}",
            )
        )
    permission = config.get("permission")
    if not isinstance(permission, dict):
        issues.append(AuditIssue("opencode.json", "permission config must explicitly ask-gate Firecrawl MCP tools"))
    else:
        for tool in sorted(FIRECRAWL_TOOL_PERMISSIONS):
            action = permission.get(tool)
            if action not in FIRECRAWL_SAFE_PERMISSION_ACTIONS:
                issues.append(
                    AuditIssue(
                        "opencode.json",
                        f"{tool} must be set to ask or deny so Firecrawl credits are not spent silently",
                    )
                )
    return issues


def _duplicate_guidance_lines(text: str) -> list[str]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for line in text.splitlines():
        normalized = " ".join(line.strip().lower().split())
        if len(normalized) < MIN_DUPLICATE_LINE_LENGTH or normalized.startswith("#"):
            continue
        if normalized in seen:
            duplicates.append(normalized)
        seen.add(normalized)
    return duplicates


def audit_instruction_surface(root: Path = REPO_ROOT, config: dict[str, Any] | None = None) -> list[AuditIssue]:
    if config is None:
        config = _load_config(root / "opencode.json")
    issues = audit_config(config, root=root)

    for instruction in config.get("instructions", []):
        path = root / instruction
        if not path.exists():
            issues.append(AuditIssue(instruction, "instruction file is missing"))
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if duplicates := _duplicate_guidance_lines(text):
            issues.append(AuditIssue(instruction, f"duplicated guidance line: {duplicates[0][:120]}"))

    core_path = root / CORE_INSTRUCTION
    if core_path.exists():
        core = core_path.read_text(encoding="utf-8", errors="replace")
        for label, terms in REQUIRED_CORE_TERMS.items():
            if not _contains_any(core, terms):
                issues.append(AuditIssue(CORE_INSTRUCTION, f"core instruction missing {label}"))
        lower_core = core.lower()
        for label, phrases in REQUIRED_CORE_PHRASES.items():
            missing = [phrase for phrase in phrases if phrase.lower() not in lower_core]
            if missing:
                issues.append(AuditIssue(CORE_INSTRUCTION, f"core instruction missing {label}: {missing[0]}"))
        if not (_contains_any(core, ("final response", "final responses")) and "evidence" in core.lower()):
            issues.append(AuditIssue(CORE_INSTRUCTION, "core instruction missing final-answer evidence guidance"))
    return issues


def _percentiles(values: list[int]) -> dict[str, int]:
    if not values:
        return {"p50": 0, "p90": 0, "max": 0}
    ordered = sorted(values)
    p90_index = round((len(ordered) - 1) * 0.9)
    return {
        "p50": int(statistics.median(ordered)),
        "p90": int(ordered[p90_index]),
        "max": int(ordered[-1]),
    }


def _token_values(sessions: list[dict[str, Any]], key: str) -> list[int]:
    values: list[int] = []
    for session in sessions:
        value = session.get(key) or 0
        if isinstance(value, bool):
            continue
        if isinstance(value, int | float):
            values.append(int(value))
    return values


def summarize_opencode_telemetry(sessions: list[dict[str, Any]], log_lines: list[str] | None = None) -> dict[str, Any]:
    """Return aggregate-only OpenCode telemetry safe for reports and specs."""

    agent_counts = Counter(str(session.get("agent") or "<none>") for session in sessions)
    model_counts = Counter(str(session.get("model") or "<none>") for session in sessions)
    log_counts = Counter()
    for line in log_lines or []:
        lower = line.lower()
        if "error" in lower:
            log_counts["error"] += 1
        if "warn" in lower:
            log_counts["warning"] += 1
        if "stream error" in lower:
            log_counts["stream_error"] += 1
        if "snapshot" in lower:
            log_counts["snapshot"] += 1

    return {
        "session_count": len(sessions),
        "tokens_input": _percentiles(_token_values(sessions, "tokens_input")),
        "tokens_output": _percentiles(_token_values(sessions, "tokens_output")),
        "tokens_cache_read": _percentiles(_token_values(sessions, "tokens_cache_read")),
        "agent_counts": dict(sorted(agent_counts.items())),
        "model_counts": dict(sorted(model_counts.items())),
        "log_counts": dict(sorted(log_counts.items())),
    }


def _canonical_tool_path(value: str) -> str:
    if not value:
        return ""
    path = Path(value)
    project_root = _opencode_project_directory().resolve()
    resolved = path.resolve() if path.is_absolute() else (project_root / path).resolve()
    parts = resolved.parts
    if ".openmates-agent-worktrees" in parts:
        marker = parts.index(".openmates-agent-worktrees")
        if len(parts) > marker + 2:
            return Path(*parts[marker + 2 :]).as_posix()
    try:
        return resolved.relative_to(project_root).as_posix()
    except ValueError:
        return resolved.as_posix()


def _tool_path(args: dict[str, Any]) -> str:
    raw_path = str(args.get("filePath") or args.get("file_path") or args.get("path") or "")
    return _canonical_tool_path(raw_path)


def _patch_paths(args: dict[str, Any]) -> set[str]:
    paths: set[str] = set()
    patch = str(args.get("patchText") or args.get("patch") or "")
    for line in patch.splitlines():
        for prefix in ("*** Add File: ", "*** Update File: ", "*** Delete File: ", "*** Move to: "):
            if line.startswith(prefix):
                paths.add(_canonical_tool_path(line[len(prefix) :].strip()))
    return paths


def _batchable_pair(first: dict[str, Any], second: dict[str, Any]) -> bool:
    if first.get("session_id") != second.get("session_id"):
        return False
    if int(second.get("time_created") or 0) - int(first.get("time_created") or 0) > 120_000:
        return False
    first_tools = first.get("tools") or []
    second_tools = second.get("tools") or []
    if len(first_tools) != 1 or len(second_tools) != 1:
        return False
    first_tool, second_tool = first_tools[0], second_tools[0]
    if first_tool["name"] == second_tool["name"] == "read":
        first_path = _tool_path(first_tool["args"])
        second_path = _tool_path(second_tool["args"])
        return bool(first_path and second_path and first_path != second_path)
    if first_tool["name"] == second_tool["name"] == "apply_patch":
        first_paths = _patch_paths(first_tool["args"])
        second_paths = _patch_paths(second_tool["args"])
        return bool(first_paths and second_paths and first_paths.isdisjoint(second_paths))
    return False


def summarize_tool_turns(turns: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize privacy-safe round-trip metrics from assistant tool turns."""

    ordered = sorted(turns, key=lambda turn: (str(turn.get("session_id") or ""), int(turn.get("time_created") or 0)))
    tool_turns = [turn for turn in ordered if turn.get("tools")]
    tool_calls = sum(len(turn["tools"]) for turn in tool_turns)
    singleton_turns = sum(len(turn["tools"]) == 1 for turn in tool_turns)

    batchable_turns = 0
    index = 0
    while index + 1 < len(ordered):
        if _batchable_pair(ordered[index], ordered[index + 1]):
            batchable_turns += 1
            index += 2
        else:
            index += 1

    standalone_todos = 0
    todo_next_input = 0
    todo_next_cache_read = 0
    turns_by_session: dict[str, list[dict[str, Any]]] = {}
    for turn in ordered:
        turns_by_session.setdefault(str(turn.get("session_id") or ""), []).append(turn)
    for session_turns in turns_by_session.values():
        for position, turn in enumerate(session_turns[:-1]):
            tools = turn.get("tools") or []
            if len(tools) != 1 or tools[0]["name"] != "todowrite":
                continue
            standalone_todos += 1
            next_turn = session_turns[position + 1]
            todo_next_input += int(next_turn.get("tokens_input") or 0)
            todo_next_cache_read += int(next_turn.get("tokens_cache_read") or 0)

    return {
        "assistant_tool_turns": len(tool_turns),
        "tool_calls": tool_calls,
        "singleton_tool_turns": singleton_turns,
        "singleton_tool_turn_rate": round(singleton_turns / len(tool_turns), 4) if tool_turns else 0.0,
        "conservative_batchable_turns": batchable_turns,
        "standalone_todo_turns": standalone_todos,
        "todo_next_turn_context": {
            "tokens_input": todo_next_input,
            "tokens_cache_read": todo_next_cache_read,
        },
    }


def _opencode_project_directory() -> Path:
    if REPO_ROOT.parent.name == ".openmates-agent-worktrees":
        return REPO_ROOT.parent.parent
    return REPO_ROOT


def collect_tool_turns(*, days: int, db_path: Path = OPENCODE_DB_PATH) -> list[dict[str, Any]]:
    """Collect only metadata needed for aggregate round-trip telemetry."""

    since_ms = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)
    connection = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only = ON")
    try:
        rows = connection.execute(
            """
            SELECT message.id, message.session_id, message.time_created, message.data, part.data
            FROM message
            JOIN session ON session.id = message.session_id
            LEFT JOIN part ON part.message_id = message.id
            WHERE session.directory = ? AND message.time_created >= ?
            ORDER BY message.session_id, message.time_created, part.time_created
            """,
            (str(_opencode_project_directory()), since_ms),
        ).fetchall()
    finally:
        connection.close()

    turns: dict[str, dict[str, Any]] = {}
    for message_id, session_id, time_created, raw_message, raw_part in rows:
        message = json.loads(raw_message)
        if message.get("role") != "assistant":
            continue
        tokens = message.get("tokens") or {}
        turn = turns.setdefault(
            message_id,
            {
                "session_id": session_id,
                "time_created": time_created,
                "tokens_input": int(tokens.get("input") or 0),
                "tokens_cache_read": int((tokens.get("cache") or {}).get("read") or 0),
                "tools": [],
            },
        )
        if not raw_part:
            continue
        part = json.loads(raw_part)
        if part.get("type") == "tool":
            state = part.get("state") or {}
            args = state.get("input") if isinstance(state.get("input"), dict) else {}
            turn["tools"].append({"name": str(part.get("tool") or "unknown"), "args": args})
    return list(turns.values())


def audit(root: Path = REPO_ROOT) -> list[AuditIssue]:
    return audit_instruction_surface(root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit OpenCode output-quality and context-efficiency guardrails.")
    parser.add_argument("--json", action="store_true", help="Print issues as JSON.")
    parser.add_argument("--telemetry-days", type=int, default=0, help="Include aggregate-only tool-turn telemetry for the last N days.")
    args = parser.parse_args(argv)

    issues = audit(REPO_ROOT)
    telemetry = summarize_tool_turns(collect_tool_turns(days=args.telemetry_days)) if args.telemetry_days > 0 else None
    if args.json:
        payload: Any = [issue.__dict__ for issue in issues]
        if telemetry is not None:
            payload = {"issues": payload, "telemetry": telemetry}
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif issues:
        print("FAIL OpenCode output-quality audit", file=sys.stderr)
        for issue in issues:
            print(f"- {issue.path}: {issue.message}", file=sys.stderr)
    else:
        print("PASS OpenCode output-quality audit")
    if telemetry is not None and not args.json:
        print(json.dumps(telemetry, indent=2, sort_keys=True))
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
