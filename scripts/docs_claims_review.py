#!/usr/bin/env python3
"""
Prepare or launch OpenCode reviews for docs affected by claim failures.

This script is the low-noise automation layer for assertion-backed docs. It
reads test failure JSON, maps failing test files to documentation claims, and
builds focused OpenCode review prompts. It only spawns sessions when called
with --execute; otherwise it prints the review plan and writes prompts.

Architecture: docs/contributing/guides/docs-writing-guidelines.md
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from docs_claims_verify import REPO_ROOT, Claim, DocClaims, parse_doc


DOCS_ROOT = REPO_ROOT / "docs"
TMP_DIR = REPO_ROOT / "scripts" / ".tmp" / "docs-claims-review"


@dataclass(frozen=True)
class AffectedClaim:
    doc: DocClaims
    claim: Claim
    failure: dict[str, object]


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def collect_claim_docs() -> list[DocClaims]:
    docs: list[DocClaims] = []
    for path in sorted(DOCS_ROOT.rglob("*.md")):
        doc = parse_doc(path)
        if doc.claims:
            docs.append(doc)
    return docs


def _failure_file_candidates(failure: dict[str, object]) -> set[str]:
    candidates: set[str] = set()
    for key in ("file", "path", "name"):
        value = failure.get(key)
        if isinstance(value, str) and value:
            candidates.add(value)
            candidates.add(Path(value).name)
    return candidates


def _failure_assertion_ids(failure: dict[str, object]) -> set[str]:
    error = failure.get("error")
    if not isinstance(error, str):
        return set()
    return set(re.findall(r"\[doc-assert:([^\]]+)\]", error))


def find_affected_claims(failures: list[dict[str, object]]) -> list[AffectedClaim]:
    docs = collect_claim_docs()
    affected: list[AffectedClaim] = []
    for failure in failures:
        candidates = _failure_file_candidates(failure)
        assertion_ids = _failure_assertion_ids(failure)
        for doc in docs:
            for claim in doc.claims:
                if not claim.file:
                    continue
                claim_path = Path(claim.file)
                file_matches = claim.file in candidates or claim_path.name in candidates
                assertion_matches = bool(assertion_ids) and claim.assertion in assertion_ids
                if assertion_matches or (file_matches and not assertion_ids):
                    affected.append(AffectedClaim(doc=doc, claim=claim, failure=failure))
    return affected


def _read_file(path: Path) -> str:
    if not path.exists():
        return f"[missing file: {path.relative_to(REPO_ROOT)}]"
    return path.read_text(encoding="utf-8", errors="replace")


def build_prompt(affected: list[AffectedClaim], result_path: Path) -> str:
    grouped: dict[str, list[AffectedClaim]] = {}
    for item in affected:
        grouped.setdefault(str(item.doc.path.relative_to(REPO_ROOT)), []).append(item)

    sections: list[str] = [
        "You are reviewing OpenMates documentation after linked doc-claim tests failed.",
        "",
        "Rules:",
        "- Decide whether docs need updates only after reading the guide and linked assertion context.",
        "- If the product is broken and docs still describe intended behavior, do not edit docs; report that product code/tests need fixing.",
        "- If behavior intentionally changed, update the affected docs and claim metadata as needed.",
        "- Keep user-guide language plain and concise.",
        "- Keep architecture docs contributor-focused and technically precise.",
        f"- Write result JSON to `{result_path.relative_to(REPO_ROOT)}` before finishing.",
        "",
        "Result JSON shape:",
        "```json",
        json.dumps(
            {
                "docs_updated": False,
                "changed_files": [],
                "claims_reviewed": [],
                "reason": "",
                "notification_required": False,
            },
            indent=2,
        ),
        "```",
        "",
    ]

    for doc_path, items in grouped.items():
        sections.extend([
            f"## Doc: {doc_path}",
            "",
            "Doc content:",
            "```markdown",
            _read_file(REPO_ROOT / doc_path),
            "```",
            "",
        ])
        seen_files: set[str] = set()
        for item in items:
            sections.extend([
                f"### Failed linked claim: {item.claim.id}",
                "",
                "Claim metadata:",
                "```json",
                json.dumps(item.claim.__dict__, indent=2),
                "```",
                "",
                "Failure:",
                "```json",
                json.dumps(item.failure, indent=2),
                "```",
                "",
            ])
            if item.claim.file and item.claim.file not in seen_files:
                seen_files.add(item.claim.file)
                sections.extend([
                    f"Linked assertion file: {item.claim.file}",
                    "```",
                    _read_file(REPO_ROOT / item.claim.file),
                    "```",
                    "",
                ])
    return "\n".join(sections)


def write_prompt(prompt: str) -> tuple[Path, Path]:
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    prompt_path = TMP_DIR / f"review-{timestamp}.md"
    result_path = TMP_DIR / f"result-{timestamp}.json"
    prompt = prompt.replace("RESULT_PATH_PLACEHOLDER", str(result_path.relative_to(REPO_ROOT)))
    prompt_path.write_text(prompt, encoding="utf-8")
    return prompt_path, result_path


def spawn_review(prompt_path: Path) -> None:
    subprocess.run(
        [
            "python3",
            "scripts/sessions.py",
            "spawn-chat",
            "--prompt-file",
            str(prompt_path.relative_to(REPO_ROOT)),
            "--name",
            "docs-claims-review",
            "--mode",
            "execute",
        ],
        cwd=REPO_ROOT,
        check=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--failures",
        default="test-results/last-failed-tests.json",
        help="Failure JSON path. Defaults to test-results/last-failed-tests.json.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Spawn an OpenCode docs review session for affected claims.",
    )
    args = parser.parse_args()

    failures_path = REPO_ROOT / args.failures
    payload = _read_json(failures_path)
    tests = payload.get("tests", [])
    if not isinstance(tests, list):
        raise SystemExit(f"Invalid failures JSON: {failures_path}")

    failures = [item for item in tests if isinstance(item, dict)]
    affected = find_affected_claims(failures)
    if not affected:
        print("No documentation claims linked to current failed test files.")
        return 0

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    result_path = TMP_DIR / f"result-{dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    prompt = build_prompt(affected, result_path)
    prompt_path = TMP_DIR / f"review-{dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%SZ')}.md"
    prompt_path.write_text(prompt, encoding="utf-8")

    print(f"Affected claim(s): {len(affected)}")
    for item in affected:
        print(
            "- "
            f"{item.doc.path.relative_to(REPO_ROOT)} :: {item.claim.id} "
            f"({item.claim.file})"
        )
    print(f"Review prompt written to: {prompt_path.relative_to(REPO_ROOT)}")
    print(f"Expected result file: {result_path.relative_to(REPO_ROOT)}")

    if args.execute:
        spawn_review(prompt_path)
        print("Spawned OpenCode docs claims review session.")
    else:
        print("Dry-run only. Re-run with --execute to spawn the review session.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
