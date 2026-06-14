#!/usr/bin/env python3
"""
Validate static source anchors declared by documentation claims.

Static claims are for architecture facts that can be proven without starting the
app: source files exist, stable functions/classes/routes/schema fields/config
keys are still present, and docs do not depend on brittle line-number links.

Architecture: docs/specs/architecture-docs-claim-coverage/spec.yml
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_ROOT = REPO_ROOT / "docs"
LINE_LINK_RE = re.compile(r"\[[^\]]+\]\([^)]*#L\d+[^)]*\)")
SUPPORTED_ANCHOR_TYPES = {
    "file_exists",
    "function",
    "class",
    "route",
    "schema_field",
    "enum_value",
    "config_key",
    "workflow_step",
    "css_class",
    "svelte_component",
    "swift_type",
}


@dataclass(frozen=True)
class StaticValidationResult:
    errors: list[str]
    checked_claims: int
    checked_anchors: int


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


def _display(path: Path, repo_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo_root.resolve()))
    except ValueError:
        return str(path)


def _source_text(anchor: dict[str, Any], repo_root: Path) -> tuple[Path | None, str | None]:
    raw_path = anchor.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None, None
    clean_path = raw_path.split("#", 1)[0].strip()
    path = repo_root / clean_path
    if any(char in clean_path for char in "*?["):
        matches = list(repo_root.glob(clean_path))
        if matches and anchor.get("type") == "file_exists":
            return matches[0], "<glob-match>"
        return path, None
    if path.is_dir() and anchor.get("type") == "file_exists":
        return path, "<directory>"
    if not path.exists():
        return path, None
    if path.is_dir():
        return path, None
    return path, path.read_text(encoding="utf-8", errors="replace")


def _contains_anchor(text: str, anchor: dict[str, Any]) -> bool:
    anchor_type = anchor.get("type")
    name = anchor.get("name")
    value = anchor.get("value")
    if anchor_type == "file_exists":
        return True
    if anchor_type == "function" and isinstance(name, str):
        return bool(re.search(rf"(?m)^\s*(async\s+)?def\s+{re.escape(name)}\s*\(", text)) or bool(
            re.search(rf"(?m)^\s*(export\s+)?(async\s+)?function\s+{re.escape(name)}\s*\(", text)
        )
    if anchor_type in {"class", "swift_type"} and isinstance(name, str):
        return bool(re.search(rf"(?m)^\s*(export\s+)?(final\s+)?class\s+{re.escape(name)}\b", text)) or bool(
            re.search(rf"(?m)^\s*(struct|enum|actor)\s+{re.escape(name)}\b", text)
        )
    if anchor_type == "svelte_component" and isinstance(name, str):
        return name in text or f"{name}.svelte" in text
    if anchor_type in {"route", "enum_value", "config_key", "workflow_step", "css_class", "schema_field"}:
        token = value if isinstance(value, str) else name
        return isinstance(token, str) and token in text
    return False


def _validate_anchor(anchor: dict[str, Any], claim_id: str, doc: Path, repo_root: Path) -> list[str]:
    errors: list[str] = []
    anchor_type = anchor.get("type")
    rel_doc = _display(doc, repo_root)
    if anchor_type not in SUPPORTED_ANCHOR_TYPES:
        return [f"{rel_doc}: claim {claim_id} has unsupported static anchor type: {anchor_type}"]
    source_path, text = _source_text(anchor, repo_root)
    if source_path is None:
        return [f"{rel_doc}: claim {claim_id} anchor is missing path"]
    if text is None:
        return [f"{rel_doc}: claim {claim_id} references missing source file: {_display(source_path, repo_root)}"]
    if not _contains_anchor(text, anchor):
        token = anchor.get("name") or anchor.get("value") or anchor_type
        errors.append(f"{rel_doc}: claim {claim_id} missing {anchor_type} anchor {token!r} in {_display(source_path, repo_root)}")
    return errors


def _line_number_errors(doc: Path, repo_root: Path) -> list[str]:
    text = doc.read_text(encoding="utf-8", errors="replace")
    return [f"{_display(doc, repo_root)}: line-number link is not allowed: {match.group(0)}" for match in LINE_LINK_RE.finditer(text)]


def validate_static_claims(docs: list[Path], *, repo_root: Path = REPO_ROOT) -> StaticValidationResult:
    errors: list[str] = []
    checked_claims = 0
    checked_anchors = 0
    repo_root = repo_root.resolve()

    for doc in docs:
        errors.extend(_line_number_errors(doc, repo_root))
        frontmatter = _frontmatter(doc)
        claims = frontmatter.get("claims")
        if not isinstance(claims, list):
            continue
        for claim in claims:
            if not isinstance(claim, dict) or claim.get("type") != "static":
                continue
            claim_id = str(claim.get("id") or "<missing>")
            anchors = claim.get("anchors")
            if not isinstance(anchors, list) or not anchors:
                errors.append(f"{_display(doc, repo_root)}: claim {claim_id} has no static anchors")
                checked_claims += 1
                continue
            checked_claims += 1
            for anchor in anchors:
                if not isinstance(anchor, dict):
                    errors.append(f"{_display(doc, repo_root)}: claim {claim_id} has malformed anchor")
                    continue
                checked_anchors += 1
                errors.extend(_validate_anchor(anchor, claim_id, doc, repo_root))

    return StaticValidationResult(errors=errors, checked_claims=checked_claims, checked_anchors=checked_anchors)


def _collect_docs(paths: list[str]) -> list[Path]:
    if paths:
        return [(REPO_ROOT / path).resolve() for path in paths]
    return sorted((DOCS_ROOT / "architecture").rglob("*.md"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", help="Optional doc paths to validate. Defaults to architecture docs.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable result.")
    args = parser.parse_args()

    result = validate_static_claims(_collect_docs(args.paths), repo_root=REPO_ROOT)
    payload = {
        "checked_claims": result.checked_claims,
        "checked_anchors": result.checked_anchors,
        "errors": result.errors,
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Checked {result.checked_claims} static claim(s), {result.checked_anchors} anchor(s).")
        for error in result.errors:
            print(f"- {error}")
    return 1 if result.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
