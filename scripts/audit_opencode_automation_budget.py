#!/usr/bin/env python3
"""Audit unattended OpenCode automation budget controls.

This script catches deterministic missing safeguards before scheduled or
admin-triggered automation can burn inference on broad, unbounded tasks.
It is intentionally conservative and path-scoped for hook integration.
Architecture context: docs/architecture/infrastructure/cronjobs.md
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_ROOT = REPO_ROOT / "scripts" / "prompts"
DIRECT_OPENCODE_RE = re.compile(r"opencode(?:['\"\s,]+)run|opencode\s+run", re.IGNORECASE)
RUN_SESSION_RE = re.compile(r"\brun_opencode_session\s*\(")
RISKY_TERMS = ("auth", "payment", "billing", "encryption", "sync", "privacy", "legal", "migration", "websocket")
REQUIRED_PROMPT_RULES = (
    "Do not start subagents",
    "verification",
)


@dataclass(frozen=True)
class AuditIssue:
    path: str
    message: str


def _git(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False)


def _staged_paths() -> list[Path]:
    result = _git(["diff", "--cached", "--name-only", "--diff-filter=ACMR"])
    return [REPO_ROOT / line.strip() for line in result.stdout.splitlines() if line.strip()]


def _rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def _is_opencode_script(path: Path, text: str) -> bool:
    if path.suffix not in {".py", ".sh", ".js", ".mjs"}:
        return False
    return "opencode" in text.lower() or "run_opencode_session" in text


def audit_script(path: Path) -> list[AuditIssue]:
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    if not _is_opencode_script(path, text):
        return []

    rel = _rel(path)
    issues: list[AuditIssue] = []
    lower = text.lower()
    direct_invocation = bool(DIRECT_OPENCODE_RE.search(text))
    helper_invocation = bool(RUN_SESSION_RE.search(text))
    if not direct_invocation and not helper_invocation:
        return []

    if direct_invocation and "timeout" not in lower:
        issues.append(AuditIssue(rel, "OpenCode automation must define or pass a timeout"))
    if "max_attempt" not in lower and "attempt" in lower and "auto_fix" in lower:
        issues.append(AuditIssue(rel, "retrying OpenCode automation must define a max attempts cap"))
    if direct_invocation and "dangerously-skip-permissions" in text and "risky" not in lower and "requires_human_approval" not in lower:
        issues.append(AuditIssue(rel, "permission-skipping OpenCode automation must include a risky-path/human-approval guard"))
    if direct_invocation and "XDG_DATA_HOME" not in text and "delete_opencode_session" not in text and "hidden" in lower:
        issues.append(AuditIssue(rel, "hidden OpenCode automation should isolate or delete session storage"))
    if direct_invocation and any(term in lower for term in RISKY_TERMS) and "requires_human_approval" not in lower and "human approval" not in lower:
        issues.append(AuditIssue(rel, "automation mentioning risky domains must include a human-approval block path"))

    return issues


def audit_prompt(path: Path) -> list[AuditIssue]:
    if not path.is_file() or path.suffix != ".md" or PROMPTS_ROOT not in path.resolve().parents:
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    if "auto-fix" not in path.name:
        return []
    rel = _rel(path)
    issues: list[AuditIssue] = []
    for rule in REQUIRED_PROMPT_RULES:
        if rule.lower() not in text.lower():
            issues.append(AuditIssue(rel, f"OpenCode automation prompt is missing required rule/context: {rule}"))
    if any(term in text.lower() for term in RISKY_TERMS) and "requires_human_approval" not in text:
        issues.append(AuditIssue(rel, "prompt mentions risky domains but lacks requires_human_approval block classification"))
    return issues


def audit_paths(paths: list[Path]) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    for path in paths:
        resolved = path.resolve()
        issues.extend(audit_script(resolved))
        issues.extend(audit_prompt(resolved))
    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit OpenCode automation budget and safety controls.")
    parser.add_argument("paths", nargs="*", help="Specific files to audit. Defaults to staged relevant files.")
    parser.add_argument("--all", action="store_true", help="Audit all scripts and OpenCode prompt files.")
    args = parser.parse_args(argv)

    if args.all:
        paths = [*REPO_ROOT.glob("scripts/**/*"), *REPO_ROOT.glob(".agents/skills/**/SKILL.md"), REPO_ROOT / "opencode.json"]
    elif args.paths:
        paths = [REPO_ROOT / path for path in args.paths]
    else:
        paths = _staged_paths()

    issues = audit_paths(paths)
    if issues:
        print("[opencode-automation-budget] Issues found:", file=sys.stderr)
        for issue in issues[:80]:
            print(f"  - {issue.path}: {issue.message}", file=sys.stderr)
        if len(issues) > 80:
            print(f"  - ... {len(issues) - 80} more issue(s)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
