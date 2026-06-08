#!/usr/bin/env python3
"""Deterministic Playwright spec hygiene audit.

This script catches high-confidence E2E flakiness patterns before an agent spends
tokens debugging them. It is intentionally path-scoped for hook use because this
repository still contains legacy specs that are being migrated gradually.
Architecture context: docs/contributing/guides/testing.md
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC_ROOT = REPO_ROOT / "frontend" / "apps" / "web_app" / "tests"
SPEC_SUFFIXES = (".spec.ts", ".test.ts")
CSS_LOCATOR_RE = re.compile(r"\b(?:page|\w+)\.locator\(\s*(['\"`])\.[^'\"`]*\1")
WAIT_RE = re.compile(r"\bwaitForTimeout\s*\(")
SERIAL_CONFIG_RE = re.compile(r"test\.describe\.configure\s*\(\s*\{[^}]*mode\s*:\s*['\"]serial['\"]", re.DOTALL)
ALLOW_MARKERS = (
    "playwright-determinism: allow",
    "deterministic-audit: allow",
)
RESERVED_ACCOUNT_SPEC_NAMES = {
    "account-recovery-flow.spec.ts",
    "backup-code-login-flow.spec.ts",
    "backup-codes-settings.spec.ts",
    "recovery-key-login-flow.spec.ts",
    "recovery-key-settings.spec.ts",
    "settings-change-email.spec.ts",
    "api-keys-flow.spec.ts",
}


@dataclass(frozen=True)
class AuditIssue:
    path: str
    line: int
    message: str


def _git(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False)


def _staged_paths() -> list[Path]:
    result = _git(["diff", "--cached", "--name-only", "--diff-filter=ACMR"])
    return [REPO_ROOT / line.strip() for line in result.stdout.splitlines() if line.strip()]


def _is_spec(path: Path) -> bool:
    return path.name.endswith(SPEC_SUFFIXES) and SPEC_ROOT in path.resolve().parents


def _has_allow_marker(lines: list[str], index: int) -> bool:
    current = lines[index]
    previous = lines[index - 1] if index > 0 else ""
    return any(marker in current or marker in previous for marker in ALLOW_MARKERS)


def audit_spec(path: Path) -> list[AuditIssue]:
    """Audit a single Playwright spec for deterministic selector/wait patterns."""
    if not path.is_file() or not _is_spec(path):
        return []

    rel_path = str(path.relative_to(REPO_ROOT))
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    issues: list[AuditIssue] = []

    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        line_no = index + 1
        if CSS_LOCATOR_RE.search(line) and not _has_allow_marker(lines, index):
            issues.append(
                AuditIssue(
                    rel_path,
                    line_no,
                    "CSS class selectors are flaky in Playwright specs; use data-testid, role, text, or an explicit allow marker",
                )
            )
        if WAIT_RE.search(line) and not _has_allow_marker(lines, index):
            issues.append(
                AuditIssue(
                    rel_path,
                    line_no,
                    "waitForTimeout is timing-based; wait for UI state, network response, or add an explicit allow marker",
                )
            )

    if path.name in RESERVED_ACCOUNT_SPEC_NAMES:
        text = "\n".join(lines)
        if not SERIAL_CONFIG_RE.search(text):
            issues.append(
                AuditIssue(
                    rel_path,
                    1,
                    "credential-mutating reserved-account specs must configure serial execution",
                )
            )

    return issues


def audit_reserved_account_specs(paths: list[Path]) -> list[AuditIssue]:
    """Audit file-level reserved account requirements for changed specs."""
    issues: list[AuditIssue] = []
    for path in paths:
        resolved = path.resolve()
        if not resolved.is_file() or not _is_spec(resolved) or resolved.name not in RESERVED_ACCOUNT_SPEC_NAMES:
            continue
        text = resolved.read_text(encoding="utf-8", errors="replace")
        if "test.describe.configure" not in text or "serial" not in text:
            issues.append(
                AuditIssue(
                    str(resolved.relative_to(REPO_ROOT)),
                    1,
                    "credential-mutating reserved-account specs must configure serial execution",
                )
            )
    return issues


def audit_added_lines(lines: list[tuple[str, int, str]]) -> list[AuditIssue]:
    """Audit newly added spec lines for flaky selectors and blind waits."""
    issues: list[AuditIssue] = []
    added_by_location = {(path, line_no): line for path, line_no, line in lines}
    for path, line_no, line in lines:
        spec_path = REPO_ROOT / path
        if not _is_spec(spec_path):
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        previous_added_line = added_by_location.get((path, line_no - 1), "")
        has_allow_marker = any(marker in line or marker in previous_added_line for marker in ALLOW_MARKERS)
        if CSS_LOCATOR_RE.search(line) and not has_allow_marker:
            issues.append(
                AuditIssue(
                    path,
                    line_no,
                    "CSS class selectors are flaky in Playwright specs; use data-testid, role, text, or an explicit allow marker",
                )
            )
        if WAIT_RE.search(line) and not has_allow_marker:
            issues.append(
                AuditIssue(
                    path,
                    line_no,
                    "waitForTimeout is timing-based; wait for UI state, network response, or add an explicit allow marker",
                )
            )
    return issues


def audit_paths(paths: list[Path]) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    for path in paths:
        issues.extend(audit_spec(path.resolve()))
    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit changed Playwright specs for deterministic test patterns.")
    parser.add_argument("paths", nargs="*", help="Specific paths to audit. Defaults to staged spec files.")
    parser.add_argument("--all", action="store_true", help="Audit all Playwright specs under frontend/apps/web_app/tests.")
    args = parser.parse_args(argv)

    if args.all:
        paths = sorted(SPEC_ROOT.rglob("*.spec.ts")) + sorted(SPEC_ROOT.rglob("*.test.ts"))
    elif args.paths:
        paths = [REPO_ROOT / path for path in args.paths]
    else:
        paths = _staged_paths()

    issues = audit_paths(paths)
    if issues:
        print("[playwright-determinism] Issues found:", file=sys.stderr)
        for issue in issues[:80]:
            print(f"  - {issue.path}:{issue.line}: {issue.message}", file=sys.stderr)
        if len(issues) > 80:
            print(f"  - ... {len(issues) - 80} more issue(s)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
