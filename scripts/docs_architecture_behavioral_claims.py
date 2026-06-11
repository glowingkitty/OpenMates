#!/usr/bin/env python3
"""
Audit behavioral documentation claims for architecture docs.

Architecture docs use concise claims where code is the source of truth: each
substantive claim names the source files, the test assertion, and the date the
linked command last passed. Static claims are allowed only as supplemental checks.

Architecture: docs/specs/architecture-docs-claim-coverage/spec.yml
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
ARCH_ROOT = REPO_ROOT / "docs" / "architecture"
BEHAVIORAL_TYPES = {"backend", "integration", "unit", "e2e", "workflow"}


def _frontmatter(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            data = yaml.safe_load("\n".join(lines[1:index]))
            return data if isinstance(data, dict) else {}
    return {}


def _display(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT)).replace("\\", "/")


def _source_exists(source: str) -> bool:
    if (REPO_ROOT / source).exists():
        return True
    if any(char in source for char in "*?["):
        return bool(list(REPO_ROOT.glob(source)))
    return (REPO_ROOT / source).exists()


def _claim_tests(claim: dict[str, Any]) -> list[dict[str, str]]:
    if isinstance(claim.get("tests"), list):
        return [test for test in claim["tests"] if isinstance(test, dict)]
    if isinstance(claim.get("test"), dict):
        return [claim["test"]]
    if claim.get("file") or claim.get("assertion"):
        return [{"file": claim.get("file"), "assertion": claim.get("assertion"), "command": ""}]
    return []


def build_report() -> dict[str, Any]:
    docs = sorted(ARCH_ROOT.rglob("*.md"))
    failures: dict[str, list[str]] = {
        "missing_behavioral_claims": [],
        "static_only_profiles": [],
        "invalid_behavioral_claims": [],
        "missing_sources": [],
        "missing_test_commands": [],
    }
    behavioral_claims = 0
    verified_behavioral_claims = 0
    commands: set[str] = set()
    doc_reports: list[dict[str, Any]] = []

    for doc in docs:
        frontmatter = _frontmatter(doc)
        rel = _display(doc)
        is_active = frontmatter.get("status") == "active"
        claims = frontmatter.get("claims") if isinstance(frontmatter.get("claims"), list) else []
        behavioral = [claim for claim in claims if isinstance(claim, dict) and claim.get("type") in BEHAVIORAL_TYPES]
        static = [claim for claim in claims if isinstance(claim, dict) and claim.get("type") == "static"]

        if is_active and not behavioral:
            failures["missing_behavioral_claims"].append(rel)
        if is_active and static and not behavioral:
            failures["static_only_profiles"].append(rel)

        for claim in behavioral:
            behavioral_claims += 1
            claim_id = str(claim.get("id") or "<missing>")
            label = f"{rel}: claim {claim_id}"
            if not claim.get("claim"):
                failures["invalid_behavioral_claims"].append(f"{label} is missing claim text")
            source = claim.get("source")
            sources = [source] if isinstance(source, str) else source if isinstance(source, list) else []
            if not sources:
                failures["invalid_behavioral_claims"].append(f"{label} is missing source")
            for source_item in sources:
                if not isinstance(source_item, str) or not _source_exists(source_item):
                    failures["missing_sources"].append(f"{label} references missing source: {source_item}")
            tests = _claim_tests(claim)
            if not tests:
                failures["invalid_behavioral_claims"].append(f"{label} is missing test/tests")
            for test in tests:
                command = test.get("command")
                if not isinstance(command, str) or not command.strip():
                    failures["missing_test_commands"].append(f"{label} test is missing command")
                else:
                    commands.add(command)
            if claim.get("verified"):
                verified_behavioral_claims += 1

        doc_reports.append(
            {
                "path": rel,
                "status": frontmatter.get("status"),
                "behavioral_claims": len(behavioral),
                "static_claims": len(static),
            }
        )

    return {
        "totals": {
            "architecture_docs_total": len(docs),
            "active_architecture_docs": sum(1 for doc in docs if _frontmatter(doc).get("status") == "active"),
            "behavioral_claims": behavioral_claims,
            "verified_behavioral_claims": verified_behavioral_claims,
            "linked_test_commands": len(commands),
        },
        "commands": sorted(commands),
        "failures": failures,
        "docs": doc_reports,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print machine-readable report.")
    parser.add_argument("--report-json", help="Write machine-readable report to a path.")
    args = parser.parse_args()

    report = build_report()
    if args.report_json:
        output_path = REPO_ROOT / args.report_json
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        totals = report["totals"]
        print(
            "Architecture behavioral claims: "
            f"{totals['behavioral_claims']} claim(s), "
            f"{totals['verified_behavioral_claims']} verified, "
            f"{totals['linked_test_commands']} command(s)."
        )
        for name, items in report["failures"].items():
            print(f"{name}: {len(items)}")
            for item in items:
                print(f"- {item}")
    return 1 if any(report["failures"].values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
