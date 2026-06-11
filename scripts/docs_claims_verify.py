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

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_ROOT = REPO_ROOT / "docs"
USER_GUIDE_ROOT = DOCS_ROOT / "user-guide"
VALID_CLAIM_TYPES = {"e2e", "unit", "backend", "integration", "workflow", "static", "manual"}
INVALID_NON_SPEC_STATUSES = {"planned", "idea", "todo", "in-progress", "partial", "implemented"}
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
    claim: str | None = None
    source: tuple[str, ...] = ()
    tests: tuple[dict[str, str], ...] = ()
    verified: str | None = None


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


@dataclass(frozen=True)
class ValidationResult:
    errors: list[str]
    warnings: list[str]
    checked_docs: int
    docs_with_claims: int


def _extract_frontmatter(markdown: str) -> list[str]:
    lines = markdown.splitlines()
    if not lines or lines[0].strip() != "---":
        return []
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return lines[1:index]
    return []


def _load_frontmatter(frontmatter: list[str]) -> dict[str, Any]:
    if not frontmatter:
        return {}
    data = yaml.safe_load("\n".join(frontmatter))
    return data if isinstance(data, dict) else {}


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
    data = _load_frontmatter(frontmatter)
    raw_claims = data.get("claims")
    if isinstance(raw_claims, list):
        return tuple(_claim_from_mapping(claim) for claim in raw_claims if isinstance(claim, dict))

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


def _string_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list):
        return tuple(item for item in value if isinstance(item, str))
    return ()


def _claim_tests(claim: dict[str, Any]) -> tuple[dict[str, str], ...]:
    raw_tests = claim.get("tests")
    if isinstance(raw_tests, list):
        tests = raw_tests
    elif isinstance(claim.get("test"), dict):
        tests = [claim["test"]]
    elif claim.get("file") or claim.get("assertion"):
        tests = [{"file": claim.get("file"), "assertion": claim.get("assertion")}]
    else:
        tests = []
    normalized: list[dict[str, str]] = []
    for test in tests:
        if not isinstance(test, dict):
            continue
        normalized.append({key: value for key, value in test.items() if isinstance(key, str) and isinstance(value, str)})
    return tuple(normalized)


def _claim_from_mapping(claim: dict[str, Any]) -> Claim:
    tests = _claim_tests(claim)
    first_test = tests[0] if tests else {}
    claim_type = str(claim.get("type") or "unit")
    return Claim(
        id=str(claim.get("id") or ""),
        type=claim_type,
        file=claim.get("file") if isinstance(claim.get("file"), str) else first_test.get("file"),
        assertion=claim.get("assertion") if isinstance(claim.get("assertion"), str) else first_test.get("assertion"),
        reason=claim.get("reason") if isinstance(claim.get("reason"), str) else None,
        claim=claim.get("claim") if isinstance(claim.get("claim"), str) else None,
        source=_string_tuple(claim.get("source")),
        tests=tests,
        verified=str(claim.get("verified")) if claim.get("verified") is not None else None,
    )


def parse_doc(path: Path) -> DocClaims:
    markdown = path.read_text(encoding="utf-8")
    frontmatter = _extract_frontmatter(markdown)
    data = _load_frontmatter(frontmatter)
    return DocClaims(
        path=path,
        status=data.get("status") if isinstance(data.get("status"), str) else _parse_scalar(frontmatter, "status"),
        doc_type=data.get("doc_type") if isinstance(data.get("doc_type"), str) else _parse_scalar(frontmatter, "doc_type"),
        audience=tuple(data.get("audience") or ()) if isinstance(data.get("audience"), list) else _parse_string_list(frontmatter, "audience"),
        last_verified=str(data.get("last_verified")) if data.get("last_verified") is not None else _parse_scalar(frontmatter, "last_verified"),
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
        errors.extend(_validate_claim_tests(label, claim, repo_root=REPO_ROOT))

    return errors, warnings


def _validate_claim_tests(label: str, claim: Claim, *, repo_root: Path) -> list[str]:
    errors: list[str] = []
    tests = claim.tests or ({"file": claim.file or "", "assertion": claim.assertion or ""},)
    for test in tests:
        file_path = test.get("file")
        assertion = test.get("assertion")
        if not file_path:
            errors.append(f"{label} is missing file")
            continue
        if not assertion:
            errors.append(f"{label} is missing assertion")
            continue
        claim_file = repo_root / file_path
        if not claim_file.exists():
            errors.append(f"{label} references missing file: {file_path}")
            continue
        text = claim_file.read_text(encoding="utf-8", errors="replace")
        if not _assertion_marker_exists(text, assertion):
            errors.append(f"{label} assertion marker not found in {file_path}: {assertion}")
    return errors


def collect_docs(paths: list[str]) -> list[Path]:
    if paths:
        return [(REPO_ROOT / path).resolve() for path in paths]
    return sorted(DOCS_ROOT.rglob("*.md"))


def build_claim_index(docs: list[DocClaims]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for doc in docs:
        rel_doc = str(doc.path.relative_to(REPO_ROOT))
        for claim in doc.claims:
            for test in claim.tests or ({"file": claim.file, "assertion": claim.assertion},):
                file_path = test.get("file")
                if not file_path:
                    continue
                index.setdefault(file_path, []).append(
                    {
                        "doc": rel_doc,
                        "claim_id": claim.id,
                        "type": claim.type,
                        "assertion": test.get("assertion"),
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


def _rel_to_root(path: Path, repo_root: Path) -> str:
    try:
        return str(path.relative_to(repo_root))
    except ValueError:
        return str(path)


def _is_under_specs(doc: DocClaims, docs_root: Path) -> bool:
    try:
        parts = doc.path.relative_to(docs_root).parts
    except ValueError:
        return False
    return bool(parts) and parts[0] == "specs"


def _validate_doc_with_root(
    doc: DocClaims,
    *,
    docs_root: Path,
    repo_root: Path,
    enforce_active: bool,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    rel_doc = _rel_to_root(doc.path, repo_root)
    in_specs = _is_under_specs(doc, docs_root)

    if not in_specs and doc.status in INVALID_NON_SPEC_STATUSES:
        errors.append(f"{rel_doc}: invalid status outside docs/specs: {doc.status}")

    if doc.status == "active":
        missing_level = errors if enforce_active else warnings
        if not doc.doc_type:
            missing_level.append(f"{rel_doc}: active doc is missing doc_type")
        if not doc.audience:
            missing_level.append(f"{rel_doc}: active doc is missing audience")
        if not doc.last_verified:
            missing_level.append(f"{rel_doc}: active doc is missing last_verified")
        if not doc.claims:
            missing_level.append(f"{rel_doc}: active doc is missing claims")

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
                (errors if enforce_active else warnings).append(f"{label} is manual but has no reason")
            continue
        errors.extend(_validate_claim_tests(label, claim, repo_root=repo_root))

    return errors, warnings


def validate_docs_tree(
    docs_root: Path = DOCS_ROOT,
    *,
    repo_root: Path | None = None,
    enforce_active: bool = False,
) -> ValidationResult:
    """Validate docs under docs_root with configurable repository root."""

    docs_root = docs_root.resolve()
    repo_root = (repo_root or docs_root.parent).resolve()
    docs = [parse_doc(path) for path in sorted(docs_root.rglob("*.md"))]
    errors: list[str] = []
    warnings: list[str] = []
    for doc in docs:
        doc_errors, doc_warnings = _validate_doc_with_root(
            doc,
            docs_root=docs_root,
            repo_root=repo_root,
            enforce_active=enforce_active,
        )
        errors.extend(doc_errors)
        warnings.extend(doc_warnings)

    seen_global: dict[str, str] = {}
    for doc in docs:
        rel_doc = _rel_to_root(doc.path, repo_root)
        for claim in doc.claims:
            if not claim.id:
                continue
            previous = seen_global.get(claim.id)
            if previous is not None:
                errors.append(f"claim id {claim.id} is duplicated in {previous} and {rel_doc}")
            else:
                seen_global[claim.id] = rel_doc

    return ValidationResult(
        errors=errors,
        warnings=warnings,
        checked_docs=len(docs),
        docs_with_claims=sum(1 for doc in docs if doc.claims),
    )


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
