#!/usr/bin/env python3
"""Audit incremental proof-video metadata coverage for Playwright specs.

This is intentionally path-scoped for hooks: when an agent edits one web spec,
the hook can ask for proof-video metadata or a deliberate not-required note
without forcing a noisy repository-wide backfill.

Usage: python3 scripts/audit_playwright_proof_metadata.py <spec.ts> [...]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PLAYWRIGHT_SPEC_ROOT = Path("frontend/apps/web_app/tests")
PROOF_DEFINITION_FIELDS = ("devices:", "transcript:", "assertions:", "tutorial:")
CLASSIFICATION_RE = re.compile(r"proof-video:\s*not_required\s+reason=([A-Za-z0-9_.-]+)")
VALID_CLASSIFICATION_REASONS = {
    "api_setup",
    "account_health",
    "cleanup_only",
    "cli_helper",
    "non_visual_setup",
    "performance_probe",
    "storage_audit",
    "visual_smoke_not_needed",
}


def repo_relative(path: Path) -> Path:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve())
    except ValueError:
        return path


def is_web_playwright_spec(path: Path) -> bool:
    rel = repo_relative(path)
    return rel.suffix == ".ts" and rel.name.endswith(".spec.ts") and rel.is_relative_to(PLAYWRIGHT_SPEC_ROOT)


def classification_reason(text: str) -> str | None:
    match = CLASSIFICATION_RE.search(text)
    if not match:
        return None
    return match.group(1)


def proof_definition_problems(text: str) -> list[str]:
    problems: list[str] = []
    if "defineVideoProof" not in text:
        problems.append("missing defineVideoProof(...) contract")
        return problems
    if "createVideoProofRuntime" not in text:
        problems.append("missing createVideoProofRuntime(...) timeline runtime")
    for field in PROOF_DEFINITION_FIELDS:
        if field not in text:
            problems.append(f"missing proof field {field}")
    if "surface: 'web'" in text or 'surface: "web"' in text:
        if "domain:" not in text:
            problems.append("web proof contract is missing domain")
    return problems


def audit_path(path: Path) -> list[str]:
    if not is_web_playwright_spec(path):
        return []
    if not path.is_file():
        return [f"{repo_relative(path)}: file does not exist"]
    text = path.read_text(encoding="utf-8")
    reason = classification_reason(text)
    if reason:
        if reason not in VALID_CLASSIFICATION_REASONS:
            return [
                f"{repo_relative(path)}: invalid proof-video not_required reason={reason}; "
                f"use one of {', '.join(sorted(VALID_CLASSIFICATION_REASONS))}"
            ]
        return []
    problems = proof_definition_problems(text)
    if not problems:
        return []
    return [
        f"{repo_relative(path)}: {', '.join(problems)}. Add defineVideoProof(...) "
        "with transcript/assertions/checkpoints/devices, or add a top-of-file "
        "classification comment like `// proof-video: not_required reason=non_visual_setup`."
    ]


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path, help="Spec files to audit")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    problems: list[str] = []
    for path in args.paths:
        problems.extend(audit_path(path if path.is_absolute() else REPO_ROOT / path))
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
