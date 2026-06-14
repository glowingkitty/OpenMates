#!/usr/bin/env python3
"""Detect sensitive data exposure in newly added logging statements.

The audit is optimized for staged diffs and hook usage. It blocks obvious cases
where code logs full payloads, tokens, keys, encrypted content, emails, or chat
messages in security-sensitive areas.
Architecture context: docs/architecture/privacy/privacy-promises.md
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_EXTENSIONS = {".py", ".ts", ".tsx", ".svelte", ".js", ".mjs", ".swift"}
SENSITIVE_PATH_RE = re.compile(
    r"(^|/)(auth|billing|payments?|stripe|revolut|privacy|legal|sync|websockets?|encryption|crypto|upload|settings)(/|_|-|\.)",
    re.IGNORECASE,
)
LOGGING_RE = re.compile(r"\b(?:logger\.(?:debug|info|warning|warn|error|exception)|console\.(?:log|warn|error|debug)|print)\s*\(")
SENSITIVE_TERM_RE = re.compile(
    r"\b(payload|request|response|token|secret|password|passkey|api[_-]?key|email|encrypted(?:_[a-z0-9]+)?|chat[_-]?content|message[_-]?content|private[_-]?key|recovery[_-]?key)\b",
    re.IGNORECASE,
)
SAFE_CONTEXT_RE = re.compile(r"\b(len|length|count|type|keys|list)\s*\(|redacted|saniti[sz]ed|masked", re.IGNORECASE)
ALLOW_MARKERS = ("sensitive-logging: allow", "privacy-log: allow")


@dataclass(frozen=True)
class AuditIssue:
    path: str
    line: int
    message: str


def _git(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False)


def staged_added_lines() -> list[tuple[str, int, str]]:
    """Return staged added lines as (path, new_line_number, line)."""
    result = _git(["diff", "--cached", "--unified=0"])
    current_file = ""
    current_line = 0
    added: list[tuple[str, int, str]] = []
    hunk_re = re.compile(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
    for raw_line in result.stdout.splitlines():
        if raw_line.startswith("+++ b/"):
            current_file = raw_line[6:]
            current_line = 0
            continue
        if raw_line.startswith("@@"):
            match = hunk_re.search(raw_line)
            current_line = int(match.group(1)) if match else 0
            continue
        if raw_line.startswith("+") and not raw_line.startswith("+++") and current_file:
            added.append((current_file, current_line, raw_line[1:]))
            current_line += 1
        elif raw_line.startswith("-") and not raw_line.startswith("---"):
            continue
        elif current_line:
            current_line += 1
    return added


def _is_source(path: str) -> bool:
    return Path(path).suffix in SOURCE_EXTENSIONS


def _has_allow_marker(line: str) -> bool:
    return any(marker in line for marker in ALLOW_MARKERS)


def audit_added_lines(lines: list[tuple[str, int, str]]) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    for path, line_no, line in lines:
        if not _is_source(path):
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "//")):
            continue
        if not LOGGING_RE.search(line) or _has_allow_marker(line):
            continue
        sensitive_path = bool(SENSITIVE_PATH_RE.search(path))
        sensitive_line = bool(SENSITIVE_TERM_RE.search(line))
        safe_context = bool(SAFE_CONTEXT_RE.search(line))
        if sensitive_line and not safe_context:
            issues.append(AuditIssue(path, line_no, "logging statement appears to include sensitive data; log IDs, counts, or sanitized fields only"))
        elif sensitive_path and "payload" in line.lower() and not safe_context:
            issues.append(AuditIssue(path, line_no, "security-sensitive path logs payload data; log sanitized summaries only"))
    return issues


def audit_files(paths: list[Path]) -> list[AuditIssue]:
    lines: list[tuple[str, int, str]] = []
    for path in paths:
        resolved = path.resolve()
        if not resolved.is_file() or resolved.suffix not in SOURCE_EXTENSIONS:
            continue
        rel = str(resolved.relative_to(REPO_ROOT))
        for index, line in enumerate(resolved.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
            lines.append((rel, index, line))
    return audit_added_lines(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit logging statements for sensitive data exposure.")
    parser.add_argument("paths", nargs="*", help="Specific files to audit. Defaults to staged added lines.")
    args = parser.parse_args(argv)

    issues = audit_files([REPO_ROOT / path for path in args.paths]) if args.paths else audit_added_lines(staged_added_lines())
    if issues:
        print("[sensitive-logging] Issues found:", file=sys.stderr)
        for issue in issues[:80]:
            print(f"  - {issue.path}:{issue.line}: {issue.message}", file=sys.stderr)
        if len(issues) > 80:
            print(f"  - ... {len(issues) - 80} more issue(s)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
