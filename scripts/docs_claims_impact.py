#!/usr/bin/env python3
"""
Analyze documentation claim impact for changed docs and tests.

This script powers non-blocking hooks and cleanup prompts. It reports objective
connections between changed files, docs, claims, and assertion files; it does
not decide whether prose should change.

Architecture: docs/specs/docs-claims-enforcement-cleanup/spec.yml
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent


def _load_local_helpers():
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))
    from docs_claims_verify import parse_doc
    from docs_markdown_links import validate_markdown_links

    return parse_doc, validate_markdown_links


parse_doc, validate_markdown_links = _load_local_helpers()


REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_ROOT = REPO_ROOT / "docs"
TEST_SUFFIXES = (".spec.ts", ".test.ts", ".py")


def _display(path: Path, repo_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo_root.resolve()))
    except ValueError:
        return str(path)


def _normalize_path(path: str, repo_root: Path) -> str:
    p = Path(path)
    if p.is_absolute():
        return _display(p, repo_root)
    return path.replace("\\", "/")


def _collect_claim_docs(docs_root: Path, repo_root: Path) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    for path in sorted(docs_root.rglob("*.md")):
        parsed = parse_doc(path)
        if not parsed.claims:
            continue
        docs.append(
            {
                "path": _display(path, repo_root),
                "claims": [claim for claim in parsed.claims],
            }
        )
    return docs


def analyze_paths(
    paths: list[str],
    *,
    docs_root: Path = DOCS_ROOT,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    docs_root = docs_root.resolve()
    repo_root = repo_root.resolve()
    changed = sorted({_normalize_path(path, repo_root) for path in paths if path})
    changed_docs = [path for path in changed if path.startswith("docs/")]
    changed_tests = [path for path in changed if path.endswith(TEST_SUFFIXES) and not path.startswith("docs/")]

    affected_docs: set[str] = set()
    affected_tests: set[str] = set()
    claim_ids: set[str] = set()

    claim_docs = _collect_claim_docs(docs_root, repo_root)
    for doc in claim_docs:
        doc_path = doc["path"]
        claims = doc["claims"]
        if doc_path in changed_docs:
            affected_docs.add(doc_path)
            for claim in claims:
                claim_ids.add(claim.id)
                if claim.file:
                    affected_tests.add(claim.file)
        for claim in claims:
            if claim.file in changed_tests:
                affected_docs.add(doc_path)
                claim_ids.add(claim.id)
                affected_tests.add(claim.file)

    broken_links = []
    for doc_path in changed_docs:
        full_path = repo_root / doc_path
        if full_path.is_file() and full_path.suffix == ".md":
            findings = [finding for finding in validate_markdown_links(full_path.parent) if finding.source == full_path]
            broken_links.extend(
                {"source": _display(finding.source, repo_root), "target": finding.target}
                for finding in findings
            )

    return {
        "changed_files": changed,
        "changed_docs": changed_docs,
        "changed_tests": changed_tests,
        "affected_docs": sorted(affected_docs),
        "affected_tests": sorted(affected_tests),
        "claim_ids": sorted(claim_ids),
        "broken_links": broken_links,
        "blocking": False,
        "commands": _suggest_commands(changed_docs, changed_tests),
    }


def _suggest_commands(changed_docs: list[str], changed_tests: list[str]) -> list[str]:
    commands = ["python3 scripts/docs_claims_verify.py"]
    if changed_docs:
        commands.append("python3 scripts/docs_markdown_links.py")
    if changed_tests:
        commands.append("python3 scripts/docs_claims_review.py --failures test-results/last-failed-tests.json")
    return commands


def format_impact(impact: dict[str, Any]) -> str:
    if not impact["changed_docs"] and not impact["changed_tests"]:
        return ""
    lines = ["docs impact: related documentation/test context detected"]
    if impact["affected_docs"]:
        lines.append("  affected docs: " + ", ".join(impact["affected_docs"]))
    if impact["affected_tests"]:
        lines.append("  affected tests: " + ", ".join(impact["affected_tests"]))
    if impact["claim_ids"]:
        lines.append("  claim ids: " + ", ".join(impact["claim_ids"]))
    if impact["broken_links"]:
        links = ", ".join(f"{item['source']} -> {item['target']}" for item in impact["broken_links"])
        lines.append("  broken links: " + links)
    if impact["commands"]:
        lines.append("  suggested checks: " + " && ".join(impact["commands"]))
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", help="Changed file paths to analyze.")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text.")
    args = parser.parse_args()
    impact = analyze_paths(args.paths)
    if args.json:
        print(json.dumps(impact, indent=2))
    else:
        message = format_impact(impact)
        if message:
            print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
