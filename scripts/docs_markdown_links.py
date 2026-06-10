#!/usr/bin/env python3
"""
Validate Markdown links in repository documentation.

This static checker is intentionally browser-free: it validates relative links
between kept docs and repo files so broken documentation links are caught by
cheap pytest, hook, and CI checks. Context-heavy remediation remains an agent
task, because only source context can decide whether to replace, update, remove,
fold, or delete a link.

Architecture: docs/specs/docs-claims-enforcement-cleanup/spec.yml
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_ROOT = REPO_ROOT / "docs"
LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "tel:")
REMEDIATION = "Decide from context whether to replace, update, remove, fold, or delete the link."


@dataclass(frozen=True)
class LinkFinding:
    source: Path
    target: str
    message: str


def _iter_markdown_files(docs_root: Path) -> Iterable[Path]:
    for path in sorted(docs_root.rglob("*.md")):
        if any(part in {"images", "assets", "figma-newchat"} for part in path.relative_to(docs_root).parts):
            continue
        yield path


def _clean_target(raw_target: str) -> str:
    return raw_target.strip().split("#", 1)[0]


def _is_ignored_target(target: str) -> bool:
    return (
        not target
        or target.startswith("#")
        or target.startswith("/")
        or target.startswith(EXTERNAL_PREFIXES)
        or ":" in target
    )


def _looks_like_file_target(target: str) -> bool:
    return bool(Path(target).suffix) or target.endswith("/")


def _candidate_paths(source: Path, target: str, docs_root: Path) -> list[Path]:
    repo_root = docs_root.parent
    candidates = [(source.parent / target).resolve()]
    stripped_target = target
    while stripped_target.startswith("../"):
        stripped_target = stripped_target[3:]
    if stripped_target != target:
        candidates.append((repo_root / stripped_target).resolve())
    return candidates


def validate_markdown_links(docs_root: Path = DOCS_ROOT) -> list[LinkFinding]:
    """Return broken relative Markdown links under docs_root."""

    docs_root = docs_root.resolve()
    findings: list[LinkFinding] = []

    for source in _iter_markdown_files(docs_root):
        text = source.read_text(encoding="utf-8", errors="replace")
        for raw_target in LINK_RE.findall(text):
            target = _clean_target(raw_target)
            if _is_ignored_target(target):
                continue
            if not _looks_like_file_target(target):
                continue

            if any(candidate.exists() for candidate in _candidate_paths(source, target, docs_root)):
                continue

            findings.append(
                LinkFinding(
                    source=source,
                    target=target,
                    message=f"Broken Markdown link: {target}. {REMEDIATION}",
                )
            )

    return findings


def _display_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docs-root", default=str(DOCS_ROOT), help="Docs root to validate.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable findings.")
    args = parser.parse_args()

    docs_root = Path(args.docs_root)
    findings = validate_markdown_links(docs_root)
    repo_root = docs_root.parent

    if args.json:
        print(
            json.dumps(
                [
                    {**asdict(finding), "source": _display_path(finding.source, repo_root)}
                    for finding in findings
                ],
                indent=2,
                default=str,
            )
        )
    elif findings:
        print("Documentation Markdown link validation failed:", file=sys.stderr)
        for finding in findings:
            print(
                f"- {_display_path(finding.source, repo_root)} -> {finding.target}: {finding.message}",
                file=sys.stderr,
            )
    else:
        print("Documentation Markdown links are valid.")

    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
