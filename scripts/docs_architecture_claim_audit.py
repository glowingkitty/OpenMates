#!/usr/bin/env python3
"""
Audit architecture documentation claim coverage and source links.

The audit is deterministic and intentionally conservative: it reports weak or
missing claim profiles so implementation agents can update, delete, or fold docs
after checking code as the source of truth.

Architecture: docs/specs/architecture-docs-claim-coverage/spec.yml
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent


def _load_local_helpers():
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))
    from docs_claims_verify import parse_doc

    return parse_doc


parse_doc = _load_local_helpers()

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_ROOT = REPO_ROOT / "docs"
ARCH_ROOT = DOCS_ROOT / "architecture"
CODE_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
CODE_EXTENSIONS = {
    ".py",
    ".ts",
    ".tsx",
    ".svelte",
    ".swift",
    ".yml",
    ".yaml",
    ".json",
    ".css",
    ".sh",
}
BEHAVIORAL_TYPES = {"backend", "integration", "unit", "e2e", "workflow"}


def _display(path: Path, docs_root: Path) -> str:
    return "docs/" + str(path.relative_to(docs_root)).replace("\\", "/")


def _is_arch_index(path: Path, parsed: Any) -> bool:
    return path.name == "README.md" or parsed.doc_type == "index"


def _frontmatter_key_files(text: str) -> list[str]:
    values: list[str] = []
    lines = text.splitlines()
    in_key_files = False
    for line in lines:
        if line.startswith("key_files:"):
            in_key_files = True
            continue
        if in_key_files:
            if line and not line.startswith(" "):
                break
            stripped = line.strip()
            if stripped.startswith("- "):
                values.append(stripped.removeprefix("- ").strip())
    return values


def _code_links(path: Path, text: str, parsed: Any) -> list[str]:
    links: list[str] = []
    for raw_target in CODE_LINK_RE.findall(text):
        target = raw_target.split("#", 1)[0]
        if "://" in target or target.startswith("mailto:"):
            continue
        suffix = Path(target).suffix
        if suffix in CODE_EXTENSIONS and not target.endswith(".md"):
            links.append(target)
    links.extend(_frontmatter_key_files(text))
    for claim in parsed.claims:
        links.extend(claim.source)
    return sorted(set(links))


def _claim_counts(parsed: Any) -> Counter[str]:
    return Counter(claim.type for claim in parsed.claims)


def _is_strong_profile(path: Path, parsed: Any) -> bool:
    counts = _claim_counts(parsed)
    if not parsed.claims:
        return False
    behavioral_claims = sum(counts[kind] for kind in BEHAVIORAL_TYPES)
    if _is_arch_index(path, parsed):
        return bool(behavioral_claims or counts["static"] or counts["manual"])
    if counts["manual"] and len(parsed.claims) == counts["manual"]:
        return False
    return behavioral_claims >= 1


def build_architecture_claim_report(
    *,
    docs_root: Path = DOCS_ROOT,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    docs_root = docs_root.resolve()
    arch_root = docs_root / "architecture"
    markdown_files = sorted(arch_root.rglob("*.md"))
    failures: dict[str, list[str]] = {
        "missing_claims": [],
        "weak_claim_profiles": [],
        "missing_source_links": [],
    }
    docs_report: list[dict[str, Any]] = []
    active_count = 0
    active_with_claims = 0
    total_claims = 0
    static_claims = 0
    behavioral_claims = 0
    manual_exceptions = 0

    for path in markdown_files:
        parsed = parse_doc(path)
        text = path.read_text(encoding="utf-8", errors="replace")
        rel = _display(path, docs_root)
        claims = list(parsed.claims)
        counts = _claim_counts(parsed)
        code_links = _code_links(path, text, parsed)
        is_active = parsed.status == "active"
        is_index = _is_arch_index(path, parsed)
        if is_active:
            active_count += 1
            if claims:
                active_with_claims += 1
            if not claims:
                failures["missing_claims"].append(rel)
            if not _is_strong_profile(path, parsed):
                failures["weak_claim_profiles"].append(rel)
            if not is_index and not code_links:
                failures["missing_source_links"].append(rel)
        total_claims += len(claims)
        static_claims += counts["static"]
        manual_exceptions += counts["manual"]
        behavioral_claims += sum(counts[kind] for kind in BEHAVIORAL_TYPES)
        docs_report.append(
            {
                "path": rel,
                "status": parsed.status,
                "doc_type": parsed.doc_type,
                "is_index": is_index,
                "claim_count": len(claims),
                "claim_types": dict(counts),
                "source_links": code_links,
            }
        )

    return {
        "totals": {
            "architecture_docs_total": len(markdown_files),
            "active_architecture_docs": active_count,
            "active_architecture_docs_with_claims": active_with_claims,
            "total_architecture_claims": total_claims,
            "static_claims": static_claims,
            "behavioral_claims": behavioral_claims,
            "manual_exceptions": manual_exceptions,
        },
        "failures": failures,
        "docs": docs_report,
        "next_docs_area_recommendation": "After architecture, prioritize self-hosting and CLI docs because they are technical, drift-prone, and already close to assertion-backed architecture coverage.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print machine-readable report.")
    parser.add_argument("--report-json", help="Write the report to this JSON path.")
    args = parser.parse_args()

    report = build_architecture_claim_report()
    if args.report_json:
        output_path = REPO_ROOT / args.report_json
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        totals = report["totals"]
        print(
            "Architecture docs: "
            f"{totals['architecture_docs_total']} total, "
            f"{totals['active_architecture_docs']} active, "
            f"{totals['active_architecture_docs_with_claims']} active with claims."
        )
        for name, paths in report["failures"].items():
            print(f"{name}: {len(paths)}")
            for path in paths:
                print(f"- {path}")
    return 1 if any(report["failures"].values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
