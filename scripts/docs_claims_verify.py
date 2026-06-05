#!/usr/bin/env python3
"""
Validate OpenMates documentation claims.

Docs can declare machine-checkable claims in Markdown frontmatter. Each
non-manual claim points to a test/spec/assertion file and a hardcoded
docAssert/doc_assert marker. This verifier checks the wiring without running
the linked tests; CI/test runners remain responsible for executing assertions.

Architecture: docs/contributing/guides/docs-writing-guidelines.md
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_ROOT = REPO_ROOT / "docs"
USER_GUIDE_ROOT = DOCS_ROOT / "user-guide"
VALID_CLAIM_TYPES = {"e2e", "unit", "backend", "integration", "static", "manual"}
SUPPORTED_ASSERTION_MARKERS = (
    "docAssert",
    "docAssertStatic",
    "doc_assert",
)


@dataclass(frozen=True)
class Claim:
    id: str
    type: str
    file: str | None
    assertion: str | None
    reason: str | None


@dataclass(frozen=True)
class DocClaims:
    path: Path
    status: str | None
    doc_type: str | None
    audience: tuple[str, ...]
    last_verified: str | None
    claims: tuple[Claim, ...]
    has_summary: bool
    has_remotion_placeholder: bool


def _extract_frontmatter(markdown: str) -> list[str]:
    lines = markdown.splitlines()
    if not lines or lines[0].strip() != "---":
        return []
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return lines[1:index]
    return []


def _parse_scalar(frontmatter: list[str], key: str) -> str | None:
    prefix = f"{key}:"
    for line in frontmatter:
        if line.startswith(prefix):
            return line[len(prefix):].strip() or None
    return None


def _parse_string_list(frontmatter: list[str], key: str) -> tuple[str, ...]:
    values: list[str] = []
    in_list = False
    prefix = f"{key}:"
    for raw_line in frontmatter:
        if raw_line.startswith(prefix):
            in_list = True
            inline = raw_line[len(prefix):].strip()
            if inline:
                return (inline,)
            continue
        if in_list:
            if raw_line and not raw_line.startswith(" "):
                break
            line = raw_line.strip()
            if line.startswith("- "):
                values.append(line.removeprefix("- ").strip())
    return tuple(values)


def _parse_claims(frontmatter: list[str]) -> tuple[Claim, ...]:
    claims: list[Claim] = []
    current: dict[str, str] | None = None
    in_claims = False

    def flush_current() -> None:
        nonlocal current
        if current is None:
            return
        claims.append(
            Claim(
                id=current.get("id", ""),
                type=current.get("type", ""),
                file=current.get("file"),
                assertion=current.get("assertion"),
                reason=current.get("reason"),
            )
        )
        current = None

    for raw_line in frontmatter:
        if raw_line.startswith("claims:"):
            in_claims = True
            continue
        if not in_claims:
            continue
        if raw_line and not raw_line.startswith(" "):
            flush_current()
            break

        line = raw_line.strip()
        if line.startswith("- id:"):
            flush_current()
            current = {"id": line.removeprefix("- id:").strip()}
            continue
        if current is None or ":" not in line:
            continue
        key, _, value = line.partition(":")
        current[key.strip()] = value.strip()

    flush_current()
    return tuple(claims)


def parse_doc(path: Path) -> DocClaims:
    markdown = path.read_text(encoding="utf-8")
    frontmatter = _extract_frontmatter(markdown)
    return DocClaims(
        path=path,
        status=_parse_scalar(frontmatter, "status"),
        doc_type=_parse_scalar(frontmatter, "doc_type"),
        audience=_parse_string_list(frontmatter, "audience"),
        last_verified=_parse_scalar(frontmatter, "last_verified"),
        claims=_parse_claims(frontmatter),
        has_summary=bool(re.search(r"(?m)^##\s+Summary\s*$", markdown)),
        has_remotion_placeholder="remotion-video:" in markdown,
    )


def _assertion_marker_exists(text: str, assertion: str) -> bool:
    escaped = re.escape(assertion)
    for marker in SUPPORTED_ASSERTION_MARKERS:
        marker_pattern = re.escape(marker)
        if re.search(rf"\b{marker_pattern}\(\s*['\"]{escaped}['\"]", text):
            return True
    return False


def validate_doc(doc: DocClaims, *, require_claims: bool) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    rel_doc = doc.path.relative_to(REPO_ROOT)

    if doc.status == "active":
        if not doc.doc_type:
            warnings.append(f"{rel_doc}: active doc is missing doc_type")
        if not doc.audience:
            warnings.append(f"{rel_doc}: active doc is missing audience")
        if not doc.last_verified:
            warnings.append(f"{rel_doc}: active doc is missing last_verified")
        if require_claims and not doc.claims:
            errors.append(f"{rel_doc}: active doc is missing claims")
        elif not doc.claims:
            warnings.append(f"{rel_doc}: active doc has no claims")

    if doc.status == "active" and USER_GUIDE_ROOT in doc.path.parents:
        if not doc.has_summary:
            warnings.append(f"{rel_doc}: active user guide is missing ## Summary")
        if not doc.has_remotion_placeholder:
            warnings.append(f"{rel_doc}: active user guide is missing remotion-video placeholder")

    seen_claim_ids: set[str] = set()
    for claim in doc.claims:
        label = f"{rel_doc}: claim {claim.id or '<missing id>'}"
        if not claim.id:
            errors.append(f"{label} is missing id")
            continue
        if claim.id in seen_claim_ids:
            errors.append(f"{label} duplicates another claim id in the same doc")
        seen_claim_ids.add(claim.id)
        if claim.type not in VALID_CLAIM_TYPES:
            errors.append(f"{label} has invalid type: {claim.type or '<missing>'}")
            continue
        if claim.type == "manual":
            if not claim.reason:
                warnings.append(f"{label} is manual but has no reason")
            continue
        if not claim.file:
            errors.append(f"{label} is missing file")
            continue
        if not claim.assertion:
            errors.append(f"{label} is missing assertion")
            continue
        claim_file = REPO_ROOT / claim.file
        if not claim_file.exists():
            errors.append(f"{label} references missing file: {claim.file}")
            continue
        text = claim_file.read_text(encoding="utf-8", errors="replace")
        if not _assertion_marker_exists(text, claim.assertion):
            errors.append(
                f"{label} assertion marker not found in {claim.file}: {claim.assertion}"
            )

    return errors, warnings


def collect_docs(paths: list[str]) -> list[Path]:
    if paths:
        return [(REPO_ROOT / path).resolve() for path in paths]
    return sorted(DOCS_ROOT.rglob("*.md"))


def build_claim_index(docs: list[DocClaims]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for doc in docs:
        rel_doc = str(doc.path.relative_to(REPO_ROOT))
        for claim in doc.claims:
            if not claim.file:
                continue
            index.setdefault(claim.file, []).append(
                {
                    "doc": rel_doc,
                    "claim_id": claim.id,
                    "type": claim.type,
                    "assertion": claim.assertion,
                }
            )
    return index


def active_docs_without_claims(docs: list[DocClaims]) -> list[str]:
    return [
        str(doc.path.relative_to(REPO_ROOT))
        for doc in docs
        if doc.status == "active" and not doc.claims
    ]


def validate_global_claim_ids(docs: list[DocClaims]) -> list[str]:
    seen: dict[str, str] = {}
    errors: list[str] = []
    for doc in docs:
        rel_doc = str(doc.path.relative_to(REPO_ROOT))
        for claim in doc.claims:
            if not claim.id:
                continue
            previous = seen.get(claim.id)
            if previous is not None:
                errors.append(
                    f"claim id {claim.id} is duplicated in {previous} and {rel_doc}"
                )
            else:
                seen[claim.id] = rel_doc
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--guide",
        action="append",
        default=[],
        help="Specific doc path to validate. May be repeated. Defaults to all docs.",
    )
    parser.add_argument(
        "--require-claims",
        action="store_true",
        help="Fail active docs that do not declare claims.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable validation result.",
    )
    parser.add_argument(
        "--uncovered",
        action="store_true",
        help="Print only active docs that do not yet have claim coverage.",
    )
    args = parser.parse_args()

    parsed_docs = [parse_doc(path) for path in collect_docs(args.guide)]
    all_errors: list[str] = []
    all_warnings: list[str] = []
    for doc in parsed_docs:
        errors, warnings = validate_doc(doc, require_claims=args.require_claims)
        all_errors.extend(errors)
        all_warnings.extend(warnings)
    all_errors.extend(validate_global_claim_ids(parsed_docs))

    result = {
        "checked_docs": len(parsed_docs),
        "docs_with_claims": sum(1 for doc in parsed_docs if doc.claims),
        "active_docs_without_claims": active_docs_without_claims(parsed_docs),
        "errors": all_errors,
        "warnings": all_warnings,
        "claim_index": build_claim_index(parsed_docs),
    }

    if args.uncovered:
        uncovered = result["active_docs_without_claims"]
        assert isinstance(uncovered, list)
        print(f"Active docs without claim coverage: {len(uncovered)}")
        for path in uncovered:
            print(f"- {path}")
    elif args.json:
        print(json.dumps(result, indent=2))
    else:
        print(
            f"Validated {result['checked_docs']} doc(s); "
            f"{result['docs_with_claims']} contain claim metadata."
        )
        if all_warnings:
            print("Warnings:")
            for warning in all_warnings:
                print(f"- {warning}")
        if all_errors:
            print("Errors:", file=sys.stderr)
            for error in all_errors:
                print(f"- {error}", file=sys.stderr)

    return 1 if all_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
