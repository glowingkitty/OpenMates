#!/usr/bin/env python3
"""Audit changed UI controls for deterministic visibility proof.

OpenMates UI regressions frequently come from controls that exist in source but
are invisible, covered, or not clickable at runtime. This audit stays scoped to
changed UI files and reports high-signal reminders: new controls need stable
identifiers, and risky control surfaces need a test or screenshot evidence path.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
HIGH_RISK_UI_PATH_RE = re.compile(
    r"^(apple/OpenMates/Sources/.+\.swift|frontend/packages/ui/src/(components|routes)/.+\.(svelte|ts)|frontend/apps/web_app/src/routes/.+\.svelte)$"
)
TEST_OR_EVIDENCE_PATH_RE = re.compile(
    r"^(apple/OpenMatesTests/|apple/OpenMatesUITests/|frontend/apps/web_app/tests/|frontend/packages/ui/src/.+__tests__/|docs/specs/.+/spec\.yml)"
)
CONTROL_PATH_RE = re.compile(
    r"(ChatView|MessageInput|Composer|Header|Settings|Login|Signup|Auth|ReportIssue|Share|Upload|Audio|Button|Navigation|\.svelte$)"
)
SWIFT_CONTROL_RE = re.compile(r"\b(?:Button|OMButton|OMIconButton|TextField|SecureField|PhotosPicker|ShareLink)\s*\(")
SWIFT_TAP_RE = re.compile(r"\.(?:onTapGesture|fileImporter|photosPicker|confirmationDialog|sheet)\b")
SVELTE_CONTROL_RE = re.compile(r"<\s*(?:button|input|select|textarea|OMButton|IconButton|Button)\b|\bon(?:click|submit|change)=")
IDENTIFIER_RE = re.compile(r"(?:accessibilityIdentifier\s*\(|data-testid\s*=|getByTestId\s*\(|accessibilityLabel\s*\()")
ALLOW_MARKERS = (
    "ui-control-visibility: allow",
    "visual-proof: not-required",
)


@dataclass(frozen=True)
class AuditIssue:
    path: str
    line: int
    message: str
    blocking: bool = False


def _git(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False)


def _staged_paths() -> list[Path]:
    result = _git(["diff", "--cached", "--name-only", "--diff-filter=ACMR"])
    return [REPO_ROOT / line.strip() for line in result.stdout.splitlines() if line.strip()]


def _added_lines_with_numbers() -> list[tuple[str, int, str]]:
    result = _git(["diff", "--cached", "--unified=0"])
    current_file = ""
    current_line = 0
    added: list[tuple[str, int, str]] = []
    hunk_re = re.compile(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
    for line in result.stdout.splitlines():
        if line.startswith("+++ b/"):
            current_file = line[6:]
            current_line = 0
            continue
        if line.startswith("@@"):
            match = hunk_re.search(line)
            current_line = int(match.group(1)) if match else 0
            continue
        if line.startswith("+") and not line.startswith("+++") and current_file:
            added.append((current_file, current_line, line[1:]))
            current_line += 1
        elif line.startswith("-") and not line.startswith("---"):
            continue
        elif current_line:
            current_line += 1
    return added


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _is_high_risk_ui(path: str) -> bool:
    return bool(HIGH_RISK_UI_PATH_RE.search(path) and CONTROL_PATH_RE.search(path))


def _has_allow_marker(text: str) -> bool:
    return any(marker in text for marker in ALLOW_MARKERS)


def _line_has_control(path: str, line: str) -> bool:
    if path.endswith(".swift"):
        return bool(SWIFT_CONTROL_RE.search(line) or SWIFT_TAP_RE.search(line))
    if path.endswith((".svelte", ".ts")):
        return bool(SVELTE_CONTROL_RE.search(line))
    return False


def audit_added_lines(lines: list[tuple[str, int, str]]) -> list[AuditIssue]:
    """Audit newly added UI control lines for stable runtime identifiers."""
    issues: list[AuditIssue] = []
    added_by_path: dict[str, list[tuple[int, str]]] = {}
    for path, line_no, line in lines:
        added_by_path.setdefault(path, []).append((line_no, line))

    for path, file_lines in added_by_path.items():
        if not _is_high_risk_ui(path):
            continue
        indexed = {line_no: line for line_no, line in file_lines}
        source_path = REPO_ROOT / path
        existing_lines = source_path.read_text(encoding="utf-8", errors="replace").splitlines() if source_path.exists() else []
        for line_no, line in file_lines:
            if _has_allow_marker(line) or not _line_has_control(path, line):
                continue
            if existing_lines and line_no > 0:
                nearby = "\n".join(existing_lines[line_no - 1 : line_no + 7])
            else:
                nearby = "\n".join(indexed.get(candidate, "") for candidate in range(line_no, line_no + 8))
            nearby_added = "\n".join(indexed.get(candidate, "") for candidate in range(line_no, line_no + 8))
            nearby = f"{nearby}\n{nearby_added}"
            if IDENTIFIER_RE.search(nearby) or _has_allow_marker(nearby):
                continue
            issues.append(
                AuditIssue(
                    path,
                    line_no,
                    "new UI control lacks a nearby stable data-testid/accessibilityIdentifier; add one or an explicit ui-control-visibility allow marker",
                    blocking=True,
                )
            )
    return issues


def audit_file_controls(paths: list[Path], *, blocking: bool = False) -> list[AuditIssue]:
    """Audit full changed files for controls without nearby identifiers.

    This is used by post-edit hooks where staged added-line context is not
    available yet. It should warn, not block, because legacy files can contain
    controls that predate the identifier contract.
    """
    issues: list[AuditIssue] = []
    for path in paths:
        rel_path = _rel(path)
        if not _is_high_risk_ui(rel_path) or not path.exists():
            continue
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        for index, line in enumerate(lines):
            if _has_allow_marker(line) or not _line_has_control(rel_path, line):
                continue
            nearby = "\n".join(lines[index : index + 8])
            if IDENTIFIER_RE.search(nearby) or _has_allow_marker(nearby):
                continue
            issues.append(
                AuditIssue(
                    rel_path,
                    index + 1,
                    "UI control has no nearby stable data-testid/accessibilityIdentifier; add rendered visibility/clickability proof before deploy",
                    blocking=blocking,
                )
            )
            break
    return issues


def audit_paths(paths: list[Path], *, evidence_paths: list[Path] | None = None) -> list[AuditIssue]:
    """Audit changed UI files for visibility/clickability evidence."""
    evidence_paths = evidence_paths if evidence_paths is not None else paths
    rel_paths = [_rel(path) for path in paths]
    has_evidence = any(TEST_OR_EVIDENCE_PATH_RE.search(_rel(path)) for path in evidence_paths)
    issues: list[AuditIssue] = []

    for rel_path in rel_paths:
        if not _is_high_risk_ui(rel_path):
            continue
        path = REPO_ROOT / rel_path
        text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
        if _has_allow_marker(text) or has_evidence:
            continue
        if any(pattern.search(text) for pattern in (SWIFT_CONTROL_RE, SWIFT_TAP_RE, SVELTE_CONTROL_RE)):
            issues.append(
                AuditIssue(
                    rel_path,
                    1,
                    "changed high-risk UI control surface without a changed test/spec evidence file; add visibility/clickability proof or ui-control-visibility allow marker",
                    blocking=False,
                )
            )
    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit changed UI controls for identifiers and visibility proof.")
    parser.add_argument("paths", nargs="*", help="Specific paths to audit. Defaults to staged UI files.")
    parser.add_argument("--hook", action="store_true", help="Return exit 2 for hook warnings instead of exit 1.")
    args = parser.parse_args(argv)

    paths = [REPO_ROOT / path for path in args.paths] if args.paths else _staged_paths()
    issues = [*audit_paths(paths)]
    if args.paths:
        issues.extend(audit_file_controls(paths, blocking=False))
    else:
        issues.extend(audit_added_lines(_added_lines_with_numbers()))
    if not issues:
        return 0

    print("[ui-control-visibility] Issues found:", file=sys.stderr)
    for issue in issues[:80]:
        level = "BLOCK" if issue.blocking else "WARN"
        print(f"  - {level} {issue.path}:{issue.line}: {issue.message}", file=sys.stderr)
    if len(issues) > 80:
        print(f"  - ... {len(issues) - 80} more issue(s)", file=sys.stderr)
    return 2 if args.hook else 1


if __name__ == "__main__":
    raise SystemExit(main())
