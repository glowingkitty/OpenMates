#!/usr/bin/env python3
"""Block Figma-referenced UI work that lacks visual evidence.

The audit is intentionally low-noise: it only triggers when staged content adds a
Figma/design-reference claim and also changes UI source files. It requires agents
to record reference PNGs, rendered screenshots, and accepted differences instead
of shipping subjective visual matches without evidence.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
UI_SOURCE_PATH_RE = re.compile(
    r"^(frontend/packages/ui/src/.+\.(svelte|ts|css)|frontend/apps/web_app/src/routes/.+\.(svelte|ts|css)|apple/OpenMates/Sources/.+\.swift)$"
)
EVIDENCE_PATH_RE = re.compile(
    r"^(docs/specs/.+/spec\.yml|frontend/apps/web_app/tests/.+\.(spec|test)\.ts|test-results/figma/.+|docs/design-guide/.+\.md)$"
)
FIGMA_CLAIM_RE = re.compile(r"\b(figma|mockup|artboard|design reference|design board|visual match|visual fidelity)\b", re.IGNORECASE)
REFERENCE_TEXT_RE = re.compile(r"\b(reference PNG|figma reference|figma export|test-results/figma|V-FIGMA)\b", re.IGNORECASE)
RENDERED_TEXT_RE = re.compile(r"\b(rendered screenshot|rendered web|playwright artifact|visual-smoke|browser screenshot)\b", re.IGNORECASE)
ACCEPTED_DIFF_TEXT_RE = re.compile(r"\baccepted differences\b", re.IGNORECASE)
ALLOW_MARKERS = (
    "figma-visual-proof: not-required",
    "figma-visual-proof: covered",
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


def _path_text(path: Path) -> str:
    if not path.exists() or path.is_dir():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _has_allow_marker(value: str) -> bool:
    return any(marker in value for marker in ALLOW_MARKERS)


def _has_figma_claim(added_lines: list[tuple[str, int, str]]) -> bool:
    return any(FIGMA_CLAIM_RE.search(line) and not _has_allow_marker(line) for _, _, line in added_lines)


def _has_evidence(paths: list[Path]) -> bool:
    for path in paths:
        rel_path = _rel(path)
        if not EVIDENCE_PATH_RE.search(rel_path):
            continue
        text = _path_text(path)
        if rel_path.startswith("test-results/figma/"):
            return True
        if REFERENCE_TEXT_RE.search(text) and RENDERED_TEXT_RE.search(text) and ACCEPTED_DIFF_TEXT_RE.search(text):
            return True
    return False


def audit_paths(
    paths: list[Path],
    *,
    added_lines: list[tuple[str, int, str]] | None = None,
    evidence_paths: list[Path] | None = None,
) -> list[AuditIssue]:
    added_lines = added_lines if added_lines is not None else _added_lines_with_numbers()
    evidence_paths = evidence_paths if evidence_paths is not None else paths
    ui_paths = [path for path in paths if UI_SOURCE_PATH_RE.search(_rel(path))]
    if not ui_paths or not _has_figma_claim(added_lines) or _has_evidence(evidence_paths):
        return []

    issues: list[AuditIssue] = []
    for path in ui_paths[:5]:
        rel_path = _rel(path)
        text = _path_text(path)
        if _has_allow_marker(text):
            continue
        issues.append(
            AuditIssue(
                rel_path,
                1,
                "Figma-referenced UI change lacks visual evidence; record reference PNGs, rendered screenshots, and accepted differences in docs/specs or test-results/figma, or add figma-visual-proof: not-required",
                blocking=True,
            )
        )
    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit staged Figma-referenced UI work for visual evidence.")
    parser.add_argument("paths", nargs="*", help="Specific paths to audit. Defaults to staged files.")
    args = parser.parse_args(argv)

    paths = [REPO_ROOT / path for path in args.paths] if args.paths else _staged_paths()
    issues = audit_paths(paths)
    if not issues:
        return 0
    print("[figma-visual-evidence] Issues found:", file=sys.stderr)
    for issue in issues[:40]:
        level = "BLOCK" if issue.blocking else "WARN"
        print(f"  - {level} {issue.path}:{issue.line}: {issue.message}", file=sys.stderr)
    if len(issues) > 40:
        print(f"  - ... {len(issues) - 40} more issue(s)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
