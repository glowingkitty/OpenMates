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
import json
import statistics
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
OPENCODE_CONFIG = REPO_ROOT / "opencode.json"
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
}


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


def audit(root: Path = REPO_ROOT) -> list[AuditIssue]:
    return audit_instruction_surface(root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit OpenCode output-quality and context-efficiency guardrails.")
    parser.add_argument("--json", action="store_true", help="Print issues as JSON.")
    args = parser.parse_args(argv)

    issues = audit(REPO_ROOT)
    if args.json:
        print(json.dumps([issue.__dict__ for issue in issues], indent=2, sort_keys=True))
    elif issues:
        print("FAIL OpenCode output-quality audit", file=sys.stderr)
        for issue in issues:
            print(f"- {issue.path}: {issue.message}", file=sys.stderr)
    else:
        print("PASS OpenCode output-quality audit")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
