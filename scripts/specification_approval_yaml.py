#!/usr/bin/env python3
"""Create a complete, exact-fingerprint YAML Specification review artifact.

This is the local fallback when the private PDF publisher is unavailable. The
command prints both source documents in Markdown fences for direct presentation
to the approver and writes one self-contained YAML artifact that approval can
verify against the current bundle.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import specifications  # noqa: E402


DEFAULT_OUTPUT_ROOT = Path("/tmp/openmates/specification-approvals")
DEFAULT_BASELINE_REF = "HEAD"


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.") or "specification"


def _unused_output(output: Path, *, explicit: bool) -> Path:
    candidate = output
    revision = 1
    while candidate.exists():
        if explicit:
            raise ValueError(f"Review output already exists: {output}; choose a new output path")
        revision += 1
        candidate = output.with_name(f"{output.stem}-review-{revision}{output.suffix}")
    return candidate


def _markdown_fence(*documents: str) -> str:
    longest = max((len(match.group(0)) for text in documents for match in re.finditer(r"`+", text)), default=2)
    return "`" * max(3, longest + 1)


def _baseline_commit(repo_root: Path, ref: str) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", f"{ref}^{{commit}}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise ValueError(f"Baseline ref does not resolve to a commit: {ref}")
    return result.stdout.strip()


def _git_yaml(repo_root: Path, ref: str, path: Path) -> dict[str, Any] | None:
    relative = path.resolve().relative_to(repo_root.resolve())
    result = subprocess.run(
        ["git", "show", f"{ref}:{relative.as_posix()}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    value = yaml.safe_load(result.stdout)
    if not isinstance(value, dict):
        raise ValueError(f"Baseline file must contain a mapping: {ref}:{relative.as_posix()}")
    return value


def build_review_artifact(
    bundle: specifications.SpecificationBundle,
    *,
    baseline_ref: str,
    baseline_commit: str,
) -> dict[str, Any]:
    specification_path = bundle.path / "specification.yml"
    examples_file = bundle.specification.get("examples", {}).get("file")
    if not isinstance(examples_file, str) or not examples_file:
        raise ValueError("Specification examples.file must identify the examples document")
    examples_path = bundle.path / examples_file
    documents = []
    for path in (specification_path, examples_path):
        content = path.read_text(encoding="utf-8")
        documents.append(
            {
                "name": path.name,
                "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                "content": content,
            }
        )
    return {
        "schema_version": 1,
        "review_format": "yaml_chat",
        "specification": bundle.versioned_id,
        "fingerprint": bundle.fingerprint,
        "baseline_ref": baseline_ref,
        "baseline_commit": baseline_commit,
        "approval_eligible": True,
        "documents": documents,
    }


def render_markdown(artifact: dict[str, Any], artifact_path: Path) -> str:
    documents = artifact["documents"]
    fence = _markdown_fence(*(document["content"] for document in documents))
    parts = [
        f"Specification: {artifact['specification']}",
        f"Fingerprint: {artifact['fingerprint']}",
        f"Review artifact: {artifact_path.resolve()}",
        "",
        "Present everything below to the user before asking for explicit approval:",
    ]
    for document in documents:
        parts.extend(("", f"### {document['name']}", f"{fence}yaml", document["content"].rstrip("\n"), fence))
    return "\n".join(parts)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a complete YAML Specification approval fallback")
    parser.add_argument("bundle", help="Specification bundle directory or specification.yml path")
    parser.add_argument("--baseline-ref", default=DEFAULT_BASELINE_REF, help="Git ref used to identify the review baseline")
    parser.add_argument("--output", type=Path, help="YAML review artifact path; defaults under /tmp/openmates/specification-approvals")
    parser.add_argument("--json", action="store_true", help="Print metadata as JSON instead of the user-facing YAML presentation")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        bundle = specifications.validate_bundle(specifications._resolve_specification_path(args.bundle))
        baseline_commit = _baseline_commit(specifications.REPO_ROOT, args.baseline_ref)
        baseline_contract = _git_yaml(
            specifications.REPO_ROOT,
            args.baseline_ref,
            bundle.path / "specification.yml",
        )
        specifications.validate_yaml_review_eligibility(bundle, baseline_contract or {})
        output = args.output or DEFAULT_OUTPUT_ROOT / f"{_safe_name(bundle.specification_id)}-{bundle.fingerprint[:16]}.approval.yml"
        output = _unused_output(output, explicit=args.output is not None)
        artifact = build_review_artifact(
            bundle,
            baseline_ref=args.baseline_ref,
            baseline_commit=baseline_commit,
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(yaml.safe_dump(artifact, sort_keys=False, allow_unicode=True), encoding="utf-8")
    except Exception as exc:
        print(f"specification_approval_yaml: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps({
            "specification": bundle.versioned_id,
            "fingerprint": bundle.fingerprint,
            "review_artifact": str(output.resolve()),
            "review_format": "yaml_chat",
        }, indent=2, sort_keys=True))
    else:
        print(render_markdown(artifact, output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
