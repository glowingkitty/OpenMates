#!/usr/bin/env python3
"""
Audit embed preview components for forbidden child hydration.

Parent search previews must be self-contained and metadata-only. They may render
counts or summary fields from the parent embed, but they must not load child
embed content until the user explicitly opens fullscreen, copies, downloads, or
otherwise requests full content.

Architecture: docs/specs/scalable-chat-embed-loading/spec.yml
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EMBEDS_ROOT = REPO_ROOT / "frontend/packages/ui/src/components/embeds"


@dataclass(frozen=True)
class ForbiddenPattern:
    name: str
    regex: re.Pattern[str]
    reason: str


@dataclass(frozen=True)
class AuditIssue:
    path: Path
    line: int
    pattern: str
    reason: str

    def format(self, root: Path) -> str:
        try:
            display_path = self.path.relative_to(root)
        except ValueError:
            display_path = self.path
        return f"{display_path}:{self.line}: {self.pattern} - {self.reason}"


FORBIDDEN_PATTERNS = (
    ForbiddenPattern(
        name="loadEmbedsWithRetry",
        regex=re.compile(r"\bloadEmbedsWithRetry\s*\("),
        reason="preview components must not batch-load child embeds",
    ),
    ForbiddenPattern(
        name="loadChildEmbedsForPreview",
        regex=re.compile(r"\bloadChildEmbedsForPreview\b"),
        reason="preview-specific child loaders bypass parent-only preview metadata",
    ),
    ForbiddenPattern(
        name="isLoadingChildren",
        regex=re.compile(r"\bisLoadingChildren\b"),
        reason="child loading state means the preview can hydrate children before explicit open",
    ),
)


def iter_preview_files(embeds_root: Path = DEFAULT_EMBEDS_ROOT) -> list[Path]:
    """Return Svelte preview files, excluding tests and fullscreen components."""
    return sorted(
        path
        for path in embeds_root.rglob("*Preview.svelte")
        if "__tests__" not in path.parts
    )


def audit_file(path: Path) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        for pattern in FORBIDDEN_PATTERNS:
            if pattern.regex.search(line):
                issues.append(
                    AuditIssue(
                        path=path,
                        line=line_number,
                        pattern=pattern.name,
                        reason=pattern.reason,
                    )
                )
    return issues


def audit_embed_preview_hydration(embeds_root: Path = DEFAULT_EMBEDS_ROOT) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    for path in iter_preview_files(embeds_root):
        issues.extend(audit_file(path))
    return issues


def main() -> int:
    issues = audit_embed_preview_hydration()
    if issues:
        print("EMBED PREVIEW HYDRATION ISSUES")
        for issue in issues:
            print(f"- {issue.format(REPO_ROOT)}")
        print(f"Summary: {len(issues)} issue(s).")
        return 1

    print("Embed preview hydration audit passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
