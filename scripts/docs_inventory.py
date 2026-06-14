#!/usr/bin/env python3
"""
Build a deterministic inventory report for OpenMates documentation.

The report is the input for docs cleanup agents: it surfaces objective facts
about folder structure, links, statuses, claims, and cleanup candidates without
trying to rewrite prose. Context-heavy remediation remains an agent/skill task.

Architecture: docs/specs/docs-claims-enforcement-cleanup/spec.yml
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent


def _load_local_helpers():
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))
    from docs_claims_verify import INVALID_NON_SPEC_STATUSES, parse_doc
    from docs_markdown_links import _candidate_paths, _clean_target, _is_ignored_target, _looks_like_file_target

    return (
        INVALID_NON_SPEC_STATUSES,
        parse_doc,
        _candidate_paths,
        _clean_target,
        _is_ignored_target,
        _looks_like_file_target,
    )


(
    INVALID_NON_SPEC_STATUSES,
    parse_doc,
    _candidate_paths,
    _clean_target,
    _is_ignored_target,
    _looks_like_file_target,
) = _load_local_helpers()


REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_ROOT = REPO_ROOT / "docs"
LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
CLOUD_PAYMENT_RE = re.compile(r"\b(stripe|billing|payment|credit|gift card|top-?up|invoice|refund)\b", re.I)
SELF_HOST_ALLOWED_RE = re.compile(r"invoice", re.I)
TARGET_STRUCTURE = {
    "architecture/platforms": ("architecture", "platforms"),
    "user-guide/billing": ("user-guide", "billing"),
}


def _extract_frontmatter(markdown: str) -> dict[str, str]:
    lines = markdown.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    result: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" in line and not line.startswith(" "):
            key, _, value = line.partition(":")
            result[key.strip()] = value.strip()
    return result


def _display(path: Path, docs_root: Path) -> str:
    return "docs/" + str(path.relative_to(docs_root)).replace("\\", "/")


def _bucket(path: Path, docs_root: Path) -> str:
    parts = path.relative_to(docs_root).parts
    if len(parts) == 1:
        return "."
    if parts[0] in {"architecture", "user-guide"} and len(parts) > 2:
        return "/".join(parts[:2])
    return parts[0]


def _markdown_target(raw_target: str) -> str | None:
    target = _clean_target(raw_target)
    if _is_ignored_target(target) or not _looks_like_file_target(target):
        return None
    return target


def _is_cloud_payment_self_hosting_doc(path: Path, text: str, docs_root: Path) -> bool:
    try:
        parts = path.relative_to(docs_root).parts
    except ValueError:
        return False
    if not parts or parts[0] != "self-hosting":
        return False
    if not CLOUD_PAYMENT_RE.search(text):
        return False
    # The Proton Bridge guide uses "invoice" as example email content, not billing docs.
    without_invoice = SELF_HOST_ALLOWED_RE.sub("", text)
    return bool(CLOUD_PAYMENT_RE.search(without_invoice))


def build_inventory(docs_root: Path = DOCS_ROOT) -> dict[str, Any]:
    docs_root = docs_root.resolve()
    markdown_files = sorted(docs_root.rglob("*.md"))
    status_counts: Counter[str] = Counter()
    folder_counts: dict[str, dict[str, int]] = defaultdict(lambda: {"docs": 0, "active": 0, "with_claims": 0})
    inbound: Counter[str] = Counter()
    outbound: dict[str, list[str]] = defaultdict(list)
    broken_links: list[dict[str, str]] = []
    invalid_status_docs: list[str] = []
    missing_frontmatter_docs: list[str] = []
    docs_without_claims: list[str] = []
    self_hosting_cloud_payment_docs: list[str] = []

    existing_paths = {path.resolve(): path for path in markdown_files}

    for path in markdown_files:
        text = path.read_text(encoding="utf-8", errors="replace")
        parsed = parse_doc(path)
        display = _display(path, docs_root)
        bucket = _bucket(path, docs_root)
        status = parsed.status or "<missing>"
        status_counts[status] += 1
        folder_counts[bucket]["docs"] += 1
        if status == "active":
            folder_counts[bucket]["active"] += 1
            if not parsed.claims:
                docs_without_claims.append(display)
        if parsed.claims:
            folder_counts[bucket]["with_claims"] += 1
        if not _extract_frontmatter(text):
            missing_frontmatter_docs.append(display)
        try:
            parts = path.relative_to(docs_root).parts
        except ValueError:
            parts = ()
        if parts and parts[0] != "specs" and parsed.status in INVALID_NON_SPEC_STATUSES:
            invalid_status_docs.append(display)
        if _is_cloud_payment_self_hosting_doc(path, text, docs_root):
            self_hosting_cloud_payment_docs.append(display)

        for raw_target in LINK_RE.findall(text):
            target = _markdown_target(raw_target)
            if target is None:
                continue
            outbound[display].append(target)
            candidates = _candidate_paths(path, target, docs_root)
            linked_doc = next((existing_paths[candidate] for candidate in candidates if candidate in existing_paths), None)
            if linked_doc:
                inbound[_display(linked_doc, docs_root)] += 1
            elif not any(candidate.exists() for candidate in candidates):
                broken_links.append({"source": display, "target": target})

    orphan_docs = [
        _display(path, docs_root)
        for path in markdown_files
        if inbound[_display(path, docs_root)] == 0 and path.name != "README.md"
    ]
    zero_outbound_docs = [_display(path, docs_root) for path in markdown_files if not outbound[_display(path, docs_root)]]

    return {
        "totals": {
            "markdown_docs": len(markdown_files),
            "active_docs": status_counts["active"],
            "docs_with_claims": sum(1 for path in markdown_files if parse_doc(path).claims),
            "missing_frontmatter": len(missing_frontmatter_docs),
            "broken_links": len(broken_links),
        },
        "status_counts": dict(status_counts),
        "folders": dict(sorted(folder_counts.items())),
        "links": {
            "internal_markdown_links": sum(len(value) for value in outbound.values()),
            "broken": broken_links,
            "zero_inbound_non_readme": len(orphan_docs),
            "zero_outbound": len(zero_outbound_docs),
        },
        "cleanup_candidates": {
            "missing_frontmatter_docs": missing_frontmatter_docs,
            "invalid_status_docs": invalid_status_docs,
            "docs_without_claims": docs_without_claims,
            "orphan_docs": orphan_docs,
            "zero_outbound_docs": zero_outbound_docs,
            "self_hosting_cloud_payment_docs": self_hosting_cloud_payment_docs,
        },
        "target_structure": {
            key: (docs_root.joinpath(*parts).exists()) for key, parts in TARGET_STRUCTURE.items()
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docs-root", default=str(DOCS_ROOT), help="Docs root to inspect.")
    args = parser.parse_args()
    print(json.dumps(build_inventory(Path(args.docs_root)), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
