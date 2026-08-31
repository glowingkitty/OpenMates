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
import re
import sqlite3
import statistics
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
OPENCODE_CONFIG = REPO_ROOT / "opencode.json"
OPENCODE_DB_PATH = Path.home() / ".local" / "share" / "opencode" / "opencode.db"
CORE_INSTRUCTION = "docs/contributing/guides/agent-workflow-core.md"
RUNTIME_INSTRUCTIONS = ("AGENTS.md", "CLAUDE.md")
EAGER_LONG_INSTRUCTIONS = {
    ".claude/rules/planning.md",
    ".claude/rules/testing.md",
    "docs/contributing/guides/spec-driven-development.md",
}
MAX_ALWAYS_LOADED_INSTRUCTIONS = 2
MAX_TOP_LEVEL_EMPTY_UNKNOWN_COMPLETIONS = 0
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
    "clarifying-question guidance": (
        "Whenever asking a clarifying question",
        "`Recommendation:`",
        "`Examples:`",
        "safest reversible default",
    ),
}
CLARIFYING_GUIDANCE_PATHS = {
    "AGENTS.md",
    "CLAUDE.md",
    ".claude/rules/planning.md",
    ".claude/skills/clarify/SKILL.md",
    ".claude/skills/specify/SKILL.md",
    ".claude/skills/create-pr/SKILL.md",
    ".claude/skills/next-tasks/SKILL.md",
    ".claude/skills/add-focus-mode/SKILL.md",
    ".claude/skills/add-memory-type/SKILL.md",
    ".claude/skills/reproduce-first/SKILL.md",
    ".claude/skills/new-task/SKILL.md",
}
REQUIRED_CLARIFYING_GUIDANCE = (
    "Recommendation:",
    "Examples:",
    "evidence-based",
    "task-specific",
    "safest reversible default",
)
REQUIRED_SCAN_FIRST_GUIDANCE = (
    "scan-first layout",
    "## ✅ Done",
    "## 🚧 Blocked",
    "## ❓ Decision Needed",
    "## 🧠 Investigation",
    "compact tables",
    "Use icons semantically and sparingly",
    "Do not paste large YAML, JSON, contracts, or logs",
)
REQUIRED_RETROSPECTIVE_PHRASES = (
    "task-closing",
    "agentic process",
    "observed preventable process problems",
    "inefficiencies",
    "not about the request's product results",
    "research",
    "delegated agents",
    "sub-chats",
    "unnecessary retries",
    "avoidable context growth",
    "wasted subagent runs",
    "agent cycles",
    "inference tokens",
    "focused audits/tests",
    "Do not repeat implementation results",
    "test outcomes",
    "Ordinary task difficulty is not a workflow issue",
    "existing hooks",
    "skills",
    "agents",
    "agent instructions",
    "deterministic audits/tests",
    "smallest concrete workflow improvement",
    "Do not recommend new prompt prose",
    "Ground efficiency claims in observable actions only",
    "do not estimate token counts or durations",
    "no change is warranted",
    "None observed",
    "Do not invent problems",
    "hidden reasoning",
    "guess durations",
    "raw private logs",
    "private chat content",
    "Simple requests",
    "clarification-only turns",
    "progress updates",
)
PROOF_MEDIA_GUIDANCE_PATHS = (
    "AGENTS.md",
    "docs/contributing/guides/agent-workflow-core.md",
    "docs/contributing/guides/spec-driven-development.md",
    ".claude/skills/create-demo-video/SKILL.md",
    ".agents/skills/create-demo-video/SKILL.md",
    ".claude/skills/plan-from-spec/SKILL.md",
    ".agents/skills/plan-from-spec/SKILL.md",
    ".claude/skills/tasks-from-spec/SKILL.md",
    ".agents/skills/tasks-from-spec/SKILL.md",
    ".claude/skills/verify-spec/SKILL.md",
    ".agents/skills/verify-spec/SKILL.md",
    ".claude/skills/deploy/SKILL.md",
    ".agents/skills/deploy/SKILL.md",
)
FORBIDDEN_PROOF_DISCORD_PHRASES = (
    "confirmed Discord delivery is a hard completion gate",
    "require confirmed Discord delivery",
    "configured Discord delivery",
    "configured Discord publication",
    "Discord publication attempt",
    "proof-video publish` path when Discord is configured",
    "Publish a passed proof to dev-smoke Discord",
)
REQUIRED_PROOF_MEDIA_TERMS = (
    "opencode_response_media.py",
    "final OpenCode response",
    "Do not send proof media to Discord unless the user explicitly asks",
    "actual `openmates` CLI",
    "generic smoke scripts",
)
CONTRACT_APPROVAL_GUIDANCE_PATHS = (
    "AGENTS.md",
    "CLAUDE.md",
    "docs/contributing/guides/agent-workflow-core.md",
    ".claude/skills/define-contract/SKILL.md",
    ".agents/skills/define-contract/SKILL.md",
)
REQUIRED_CONTRACT_APPROVAL_TERMS = (
    "scripts/contract_approval_pdf.py",
    "fingerprint",
    "yellow",
    "before asking",
    "review artifact",
)
FORBIDDEN_RETROSPECTIVE_CLAUSE = re.compile(
    r"^(?:(?:this (?:section|retrospective)|agents?)\s+(?:must|should)\s+)?"
    r"(?:include|summarize|report|repeat)\b.*\b(?:implementation results|changed files|"
    r"(?:discovered )?product bugs|test outcomes|remaining (?:product )?work)\b",
    re.IGNORECASE,
)
RETROSPECTIVE_EXCEPTION_TERMS = (
    "unless an agent-workflow deficiency",
    "when an agent-workflow deficiency",
)
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
MAX_CONSERVATIVE_BATCHABLE_TURNS_PER_DAY = 80
MAX_STANDALONE_TODO_TURNS_PER_DAY = 80
MAX_ROUTING_ERROR_TURNS_PER_DAY = 20
MAX_GREP_OUTPUT_TOO_LARGE_ERRORS_PER_DAY = 5
MAX_MISSING_RUNTIME_ARTIFACT_ERRORS_PER_DAY = 20
MAX_CHILD_MUTATION_BLOCK_ERRORS_PER_DAY = 10


@dataclass(frozen=True)
class AuditIssue:
    path: str
    message: str


class DuplicateConfigKeyError(ValueError):
    """Raised when JSON parsing would silently overwrite a duplicate key."""


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateConfigKeyError(key)
        result[key] = value
    return result


def _load_config(path: Path = OPENCODE_CONFIG) -> dict[str, Any]:
    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_json_keys,
    )


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    lower = text.lower()
    return any(term.lower() in lower for term in terms)


def _retrospective_body(text: str) -> str | None:
    heading = re.search(r"(?im)^#{2,3}\s+Agent Workflow Retrospective\s*$", text)
    if heading is None:
        return None
    next_heading = re.search(r"(?m)^#{1,3}\s+", text[heading.end() :])
    end = heading.end() + next_heading.start() if next_heading else len(text)
    body_lines = (line for line in text[heading.end() : end].splitlines() if line.strip() != "---")
    return " ".join("\n".join(body_lines).split())


def _audit_retrospective_guidance(path: str, text: str) -> list[AuditIssue]:
    body = _retrospective_body(text)
    if body is None:
        return [AuditIssue(path, "workflow retrospective guidance missing: Agent Workflow Retrospective")]
    normalized = body.lower()
    missing = [phrase for phrase in REQUIRED_RETROSPECTIVE_PHRASES if phrase.lower() not in normalized]
    if missing:
        return [AuditIssue(path, f"workflow retrospective guidance missing: {missing[0]}")]
    for clause in re.split(r"(?<=[.!?])\s+", body):
        lower_clause = clause.lower()
        if FORBIDDEN_RETROSPECTIVE_CLAUSE.search(clause) and not any(
            term in lower_clause for term in RETROSPECTIVE_EXCEPTION_TERMS
        ):
            return [AuditIssue(path, "workflow retrospective guidance contradicts the agent-process-only contract")]
    return []


def _audit_clarifying_question_guidance(path: str, text: str) -> list[AuditIssue]:
    normalized = " ".join(text.split())
    missing = [phrase for phrase in REQUIRED_CLARIFYING_GUIDANCE if phrase not in normalized]
    if not missing:
        return []
    return [AuditIssue(path, f"clarifying-question guidance missing: {missing[0]}")]


def _audit_scan_first_guidance(path: str, text: str) -> list[AuditIssue]:
    normalized = " ".join(text.split())
    missing = [phrase for phrase in REQUIRED_SCAN_FIRST_GUIDANCE if phrase not in normalized]
    if not missing:
        return []
    return [AuditIssue(path, f"scan-first final-answer guidance missing: {missing[0]}")]


def _audit_proof_media_guidance(root: Path) -> list[AuditIssue]:
    if not (root / ".claude/skills/create-demo-video/SKILL.md").exists():
        return []
    issues: list[AuditIssue] = []
    combined: list[str] = []
    for rel_path in PROOF_MEDIA_GUIDANCE_PATHS:
        path = root / rel_path
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        combined.append(text)
        for phrase in FORBIDDEN_PROOF_DISCORD_PHRASES:
            if phrase in text:
                issues.append(AuditIssue(rel_path, f"proof media guidance still requires Discord delivery: {phrase}"))
    all_text = "\n".join(combined)
    for term in REQUIRED_PROOF_MEDIA_TERMS:
        if term not in all_text:
            issues.append(AuditIssue("proof-media-guidance", f"proof media guidance missing: {term}"))
    return issues


def _audit_contract_approval_pdf_guidance(root: Path) -> list[AuditIssue]:
    if not (root / ".claude/skills/define-contract/SKILL.md").is_file():
        return []
    issues: list[AuditIssue] = []
    if not (root / "scripts/contract_approval_pdf.py").is_file():
        issues.append(AuditIssue("scripts/contract_approval_pdf.py", "Contract approval PDF renderer is missing"))
    for rel_path in CONTRACT_APPROVAL_GUIDANCE_PATHS:
        path = root / rel_path
        if not path.is_file():
            issues.append(AuditIssue(rel_path, "Contract approval PDF guidance file is missing"))
            continue
        normalized = " ".join(path.read_text(encoding="utf-8", errors="replace").lower().split())
        for term in REQUIRED_CONTRACT_APPROVAL_TERMS:
            if term.lower() not in normalized:
                issues.append(AuditIssue(rel_path, f"Contract approval PDF guidance missing: {term}"))
                break
    return issues


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
    plan = config.get("agent", {}).get("plan")
    if isinstance(plan, dict):
        issues.extend(
            _audit_clarifying_question_guidance(
                "opencode.json agent.plan.prompt",
                str(plan.get("prompt", "")),
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
        try:
            config = _load_config(root / "opencode.json")
        except DuplicateConfigKeyError as error:
            return [AuditIssue("opencode.json", f"duplicate JSON key: {error}")]
    issues = audit_config(config, root=root)

    for instruction in config.get("instructions", []):
        path = root / instruction
        if not path.exists():
            issues.append(AuditIssue(instruction, "instruction file is missing"))
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if duplicates := _duplicate_guidance_lines(text):
            issues.append(AuditIssue(instruction, f"duplicated guidance line: {duplicates[0][:120]}"))

    retrospective_bodies: dict[str, str] = {}
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
        issues.extend(_audit_scan_first_guidance(CORE_INSTRUCTION, core))
        issues.extend(_audit_retrospective_guidance(CORE_INSTRUCTION, core))
        if body := _retrospective_body(core):
            retrospective_bodies[CORE_INSTRUCTION] = body
    for rel_path in RUNTIME_INSTRUCTIONS:
        path = root / rel_path
        if not path.exists():
            issues.append(AuditIssue(rel_path, "cross-runtime instruction file is missing"))
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        issues.extend(_audit_retrospective_guidance(rel_path, text))
        issues.extend(_audit_clarifying_question_guidance(rel_path, text))
        issues.extend(_audit_scan_first_guidance(rel_path, text))
        if body := _retrospective_body(text):
            retrospective_bodies[rel_path] = body
    for rel_path in sorted(CLARIFYING_GUIDANCE_PATHS - set(RUNTIME_INSTRUCTIONS)):
        path = root / rel_path
        if not path.exists():
            issues.append(AuditIssue(rel_path, "clarifying-question guidance file is missing"))
            continue
        issues.extend(
            _audit_clarifying_question_guidance(
                rel_path,
                path.read_text(encoding="utf-8", errors="replace"),
            )
        )
    if len(set(retrospective_bodies.values())) > 1:
        issues.append(AuditIssue("cross-runtime", "agent workflow retrospective guidance differs across instruction surfaces"))
    issues.extend(_audit_proof_media_guidance(root))
    issues.extend(_audit_contract_approval_pdf_guidance(root))
    return issues


def _percentiles(values: list[int]) -> dict[str, int]:
    if not values:
        return {"count": 0, "p50": 0, "p90": 0, "max": 0}
    ordered = sorted(values)
    p90_index = round((len(ordered) - 1) * 0.9)
    return {
        "count": len(ordered),
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


def summarize_tool_turns(turns: list[dict[str, Any]], *, include_breakdowns: bool = True) -> dict[str, Any]:
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

    error_counts = Counter()
    for turn in tool_turns:
        for tool in turn.get("tools") or []:
            if tool.get("status") != "error":
                continue
            error = str(tool.get("error") or "")
            if "child ownership guard" in error and "child role unknown" in error:
                category = "child_role_unknown"
            elif "child ownership guard" in error:
                category = "child_mutation_block"
            elif "explicitly references the root checkout" in error:
                category = "root_path_routing"
            elif "no active sessions.py worktree" in error:
                category = "missing_session"
            elif "Ripgrep JSON record exceeded" in error:
                category = "grep_output_too_large"
            elif tool.get("name") == "read" and "File not found" in error:
                category = "missing_runtime_artifact"
            elif "stale-read guard" in error:
                category = "stale_read"
            else:
                category = "other"
            error_counts[category] += 1

    report = {
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
        "tool_error_counts": dict(sorted(error_counts.items())),
    }
    if not include_breakdowns:
        return report

    by_agent: dict[str, dict[str, Any]] = {}
    for agent in sorted({str(turn.get("agent") or "<none>") for turn in ordered}):
        agent_turns = [turn for turn in ordered if str(turn.get("agent") or "<none>") == agent]
        by_agent[agent] = summarize_tool_turns(agent_turns, include_breakdowns=False)
    session_reports = [
        summarize_tool_turns(session_turns, include_breakdowns=False)
        for session_turns in turns_by_session.values()
    ]
    report["by_agent"] = by_agent
    report["per_session"] = {
        key: _percentiles([int(session_report[key]) for session_report in session_reports])
        for key in ("assistant_tool_turns", "conservative_batchable_turns", "standalone_todo_turns")
    }
    return report


def summarize_child_completions(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Return aggregate-only delegated-session completion quality metrics."""

    completed = [record for record in records if record.get("terminal")]
    empty = [record for record in completed if not record.get("usable_output")]
    agents = sorted({str(record.get("agent") or "<none>") for record in completed})
    return {
        "completed": len(completed),
        "empty": len(empty),
        "empty_rate": round(len(empty) / len(completed), 4) if completed else 0.0,
        "by_agent": {
            agent: {
                "completed": sum(str(record.get("agent") or "<none>") == agent for record in completed),
                "empty": sum(str(record.get("agent") or "<none>") == agent for record in empty),
            }
            for agent in agents
        },
    }


def summarize_top_level_completions(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Return aggregate-only completion health for top-level chats."""

    completed = [record for record in records if record.get("terminal")]
    empty_unknown = [
        record
        for record in completed
        if record.get("finish") == "unknown" and not record.get("usable_output")
    ]
    agents = sorted({str(record.get("agent") or "<none>") for record in completed})
    return {
        "completed": len(completed),
        "empty_unknown": len(empty_unknown),
        "by_agent": {
            agent: {
                "completed": sum(str(record.get("agent") or "<none>") == agent for record in completed),
                "empty_unknown": sum(str(record.get("agent") or "<none>") == agent for record in empty_unknown),
            }
            for agent in agents
        },
    }


def audit_tool_turn_telemetry(telemetry: dict[str, Any], *, days: int) -> list[AuditIssue]:
    """Flag conservative workflow-efficiency regressions from aggregate telemetry."""

    if days <= 0:
        return []
    issues: list[AuditIssue] = []
    batchable = int(telemetry.get("conservative_batchable_turns") or 0)
    standalone_todos = int(telemetry.get("standalone_todo_turns") or 0)
    error_counts = telemetry.get("tool_error_counts") if isinstance(telemetry.get("tool_error_counts"), dict) else {}
    routing_errors = sum(int(error_counts.get(key) or 0) for key in ("child_role_unknown", "missing_session", "root_path_routing"))
    top_level_completion = telemetry.get("top_level_completion")
    if not isinstance(top_level_completion, dict):
        top_level_completion = {}
    empty_unknown = int(top_level_completion.get("empty_unknown") or 0)

    batchable_budget = MAX_CONSERVATIVE_BATCHABLE_TURNS_PER_DAY * days
    if batchable > batchable_budget:
        issues.append(AuditIssue(
            "opencode-telemetry",
            f"conservative batchable tool turns {batchable} exceed {days}d budget {batchable_budget}; batch independent reads/searches/status calls in one turn",
        ))
    todo_budget = MAX_STANDALONE_TODO_TURNS_PER_DAY * days
    if standalone_todos > todo_budget:
        issues.append(AuditIssue(
            "opencode-telemetry",
            f"standalone todo turns {standalone_todos} exceed {days}d budget {todo_budget}; coalesce todowrite with the next independent tool call",
        ))
    routing_budget = MAX_ROUTING_ERROR_TURNS_PER_DAY * days
    if routing_errors > routing_budget:
        issues.append(AuditIssue(
            "opencode-telemetry",
            f"session/worktree routing errors {routing_errors} exceed {days}d budget {routing_budget}; inspect child_role_unknown/missing_session/root_path_routing categories",
        ))
    grep_errors = int(error_counts.get("grep_output_too_large") or 0)
    grep_budget = MAX_GREP_OUTPUT_TOO_LARGE_ERRORS_PER_DAY * days
    if grep_errors > grep_budget:
        issues.append(AuditIssue(
            "opencode-telemetry",
            f"oversized grep errors {grep_errors} exceed {days}d budget {grep_budget}; narrow the pattern and file scope or read long matching records directly",
        ))
    missing_artifacts = int(error_counts.get("missing_runtime_artifact") or 0)
    missing_artifact_budget = MAX_MISSING_RUNTIME_ARTIFACT_ERRORS_PER_DAY * days
    if missing_artifacts > missing_artifact_budget:
        issues.append(AuditIssue(
            "opencode-telemetry",
            f"missing runtime artifact errors {missing_artifacts} exceed {days}d budget {missing_artifact_budget}; discover generated paths before reading them",
        ))
    child_mutation_blocks = int(error_counts.get("child_mutation_block") or 0)
    child_mutation_budget = MAX_CHILD_MUTATION_BLOCK_ERRORS_PER_DAY * days
    if child_mutation_blocks > child_mutation_budget:
        issues.append(AuditIssue(
            "opencode-telemetry",
            f"child mutation blocks {child_mutation_blocks} exceed {days}d budget {child_mutation_budget}; keep session, lease, dispatch, and deploy mutations parent-owned",
        ))
    if empty_unknown > MAX_TOP_LEVEL_EMPTY_UNKNOWN_COMPLETIONS:
        issues.append(AuditIssue(
            "opencode-telemetry",
            f"empty top-level finish=unknown completions detected: {empty_unknown}; inspect provider timeout and transport logs",
        ))
    return issues


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
                "agent": str(message.get("agent") or "<none>"),
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
            turn["tools"].append({
                "name": str(part.get("tool") or "unknown"),
                "args": args,
                "status": str(state.get("status") or ""),
                "error": str(state.get("error") or ""),
            })
    return list(turns.values())


def collect_child_completion_records(*, days: int, db_path: Path = OPENCODE_DB_PATH) -> list[dict[str, Any]]:
    """Collect only terminal/output booleans for delegated assistant sessions."""

    since_ms = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)
    project = _opencode_project_directory()
    connection = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only = ON")
    try:
        rows = connection.execute(
            """
            SELECT session.id, message.id, message.time_created, message.data, part.data
            FROM session
            JOIN message ON message.session_id = session.id
            LEFT JOIN part ON part.message_id = message.id
            WHERE COALESCE(session.parent_id, '') != ''
              AND (session.directory = ? OR session.directory LIKE ?)
              AND session.time_updated >= ?
            ORDER BY session.id, message.time_created, part.time_created
            """,
            (str(project), f"{project}/.openmates-agent-worktrees/%", since_ms),
        ).fetchall()
    finally:
        connection.close()

    messages: dict[tuple[str, str], dict[str, Any]] = {}
    for session_id, message_id, time_created, raw_message, raw_part in rows:
        try:
            message = json.loads(raw_message)
        except (TypeError, json.JSONDecodeError):
            continue
        if message.get("role") != "assistant":
            continue
        record = messages.setdefault(
            (str(session_id), str(message_id)),
            {
                "session_id": str(session_id),
                "time_created": int(time_created),
                "agent": str(message.get("agent") or "<none>"),
                "terminal": str(message.get("finish") or "") == "stop",
                "usable_output": False,
            },
        )
        if not raw_part:
            continue
        try:
            part = json.loads(raw_part)
        except (TypeError, json.JSONDecodeError):
            continue
        if part.get("type") == "text" and str(part.get("text") or "").strip():
            record["usable_output"] = True
        if part.get("type") == "tool":
            state = part.get("state") if isinstance(part.get("state"), dict) else {}
            if state.get("status") == "completed" and str(state.get("output") or "").strip():
                record["usable_output"] = True

    latest: dict[str, dict[str, Any]] = {}
    for record in messages.values():
        current = latest.get(record["session_id"])
        if current is None or record["time_created"] >= current["time_created"]:
            latest[record["session_id"]] = record
    return [
        {key: value for key, value in record.items() if key != "session_id"}
        for record in latest.values()
    ]


def collect_top_level_completion_records(*, days: int, db_path: Path = OPENCODE_DB_PATH) -> list[dict[str, Any]]:
    """Collect privacy-safe completion state for top-level assistant messages."""

    since_ms = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)
    project = _opencode_project_directory()
    connection = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only = ON")
    try:
        rows = connection.execute(
            """
            SELECT message.id, message.data, part.data
            FROM session
            JOIN message ON message.session_id = session.id
            LEFT JOIN part ON part.message_id = message.id
            WHERE COALESCE(session.parent_id, '') = ''
              AND (session.directory = ? OR session.directory LIKE ?)
              AND message.time_created >= ?
            ORDER BY message.id, part.time_created
            """,
            (str(project), f"{project}/.openmates-agent-worktrees/%", since_ms),
        ).fetchall()
    finally:
        connection.close()

    messages: dict[str, dict[str, Any]] = {}
    for message_id, raw_message, raw_part in rows:
        try:
            message = json.loads(raw_message)
        except (TypeError, json.JSONDecodeError):
            continue
        if message.get("role") != "assistant":
            continue
        time_data = message.get("time") if isinstance(message.get("time"), dict) else {}
        record = messages.setdefault(
            str(message_id),
            {
                "agent": str(message.get("agent") or "<none>"),
                "terminal": bool(time_data.get("completed")),
                "finish": str(message.get("finish") or ""),
                "usable_output": False,
            },
        )
        if not raw_part:
            continue
        try:
            part = json.loads(raw_part)
        except (TypeError, json.JSONDecodeError):
            continue
        if part.get("type") == "text" and str(part.get("text") or "").strip():
            record["usable_output"] = True
        if part.get("type") == "tool":
            state = part.get("state") if isinstance(part.get("state"), dict) else {}
            if state.get("status") == "completed" and str(state.get("output") or "").strip():
                record["usable_output"] = True
    return list(messages.values())


def audit(root: Path = REPO_ROOT) -> list[AuditIssue]:
    return audit_instruction_surface(root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit OpenCode output-quality and context-efficiency guardrails.")
    parser.add_argument("--json", action="store_true", help="Print issues as JSON.")
    parser.add_argument("--telemetry-days", type=int, default=0, help="Include aggregate-only tool-turn telemetry for the last N days.")
    args = parser.parse_args(argv)

    issues = audit(REPO_ROOT)
    telemetry = summarize_tool_turns(collect_tool_turns(days=args.telemetry_days)) if args.telemetry_days > 0 else None
    if telemetry is not None:
        telemetry["child_completion"] = summarize_child_completions(
            collect_child_completion_records(days=args.telemetry_days)
        )
        telemetry["top_level_completion"] = summarize_top_level_completions(
            collect_top_level_completion_records(days=args.telemetry_days)
        )
        issues.extend(audit_tool_turn_telemetry(telemetry, days=args.telemetry_days))
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
