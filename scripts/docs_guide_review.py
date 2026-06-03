#!/usr/bin/env python3
"""
Prepare or launch a user-guide freshness review for changed linked specs.

This is the second layer of test-backed user-guide freshness. It finds user
guides whose `tested_by` specs changed, gathers structured evidence, and either
prints a dry-run review package or spawns an OpenCode session to decide whether
the natural-language guide needs an update.

Validator: scripts/docs_guide_verify.py
Architecture: docs/contributing/guides/docs-writing-guidelines.md
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from docs_guide_verify import REPO_ROOT, USER_GUIDE_ROOT, GuideMetadata, parse_guide


TMP_DIR = REPO_ROOT / "scripts" / ".tmp" / "docs-guide-review"


@dataclass(frozen=True)
class AffectedGuide:
    guide: GuideMetadata
    changed_specs: tuple[str, ...]


def run_git(args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        text=True,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


def changed_files_since(since: str) -> set[str]:
    output = run_git(["diff", "--name-only", since, "--"])
    return {line.strip() for line in output.splitlines() if line.strip()}


def collect_linked_guides() -> list[GuideMetadata]:
    guides: list[GuideMetadata] = []
    for path in sorted(USER_GUIDE_ROOT.rglob("*.md")):
        metadata = parse_guide(path)
        if metadata.tested_by:
            guides.append(metadata)
    return guides


def find_affected_guides(changed_paths: set[str], specs: set[str]) -> list[AffectedGuide]:
    targets = changed_paths | specs
    affected: list[AffectedGuide] = []
    for guide in collect_linked_guides():
        changed_specs = tuple(
            entry.spec for entry in guide.tested_by if entry.spec in targets
        )
        if changed_specs:
            affected.append(AffectedGuide(guide=guide, changed_specs=changed_specs))
    return affected


def file_diff(path: str, since: str) -> str:
    try:
        return run_git(["diff", since, "--", path])
    except subprocess.CalledProcessError as exc:
        return f"[diff unavailable for {path}: {exc}]"


def read_file(path: str) -> str:
    full_path = REPO_ROOT / path
    if not full_path.exists():
        return f"[missing file: {path}]"
    return full_path.read_text(encoding="utf-8", errors="replace")


def build_prompt(affected: list[AffectedGuide], since: str, changed_paths: set[str]) -> str:
    today = dt.date.today().isoformat()
    payload = {
        "review_date": today,
        "since": since,
        "changed_paths": sorted(changed_paths),
        "affected_guides": [
            {
                "guide": str(item.guide.path.relative_to(REPO_ROOT)),
                "changed_specs": list(item.changed_specs),
                "tested_by": [entry.__dict__ for entry in item.guide.tested_by],
            }
            for item in affected
        ],
    }

    sections: list[str] = [
        "You are reviewing whether OpenMates user-guide docs need updates after linked Playwright specs changed.",
        "",
        "Rules:",
        "- Read the guide text and linked spec diffs before editing.",
        "- Update natural-language user-guide docs only if user-visible behavior, steps, labels, screenshots, or expected outcomes changed.",
        "- Do not update docs for test-only refactors, helper cleanup, mock fixture changes that do not alter the user flow, or selector-only changes.",
        "- If docs do not need changes, report that clearly and do not edit files.",
        "- If docs need changes, edit only the affected docs under docs/user-guide/ unless a linked index needs a cross-link update.",
        "- After any doc edit, run: python3 scripts/docs_guide_verify.py --guide <changed-guide> for every changed guide.",
        "- If docs changed, admin notification is mandatory: include the changed guide path, linked spec, commit SHA once deployed, and a short explanation for Discord and email review.",
        "- Preserve the existing user-guide tone: plain language, no engineering jargon.",
        "",
        "Structured review payload:",
        "```json",
        json.dumps(payload, indent=2),
        "```",
        "",
    ]

    for item in affected:
        guide_path = str(item.guide.path.relative_to(REPO_ROOT))
        sections.extend([
            f"## Guide: {guide_path}",
            "",
            "Current guide content:",
            "```markdown",
            read_file(guide_path),
            "```",
            "",
        ])
        for spec in item.changed_specs:
            sections.extend([
                f"### Changed spec: {spec}",
                "",
                "Spec diff:",
                "```diff",
                file_diff(spec, since),
                "```",
                "",
                "Current spec content:",
                "```ts",
                read_file(spec),
                "```",
                "",
            ])

    sections.extend([
        "Final response required:",
        "- State whether docs needed updates.",
        "- If updated, list files changed and the exact user-visible behavior that changed.",
        "- If not updated, explain why the spec change did not affect the guide.",
    ])
    return "\n".join(sections)


def write_prompt(prompt: str) -> Path:
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    path = TMP_DIR / f"review-{timestamp}.md"
    path.write_text(prompt, encoding="utf-8")
    return path


def spawn_review(prompt_path: Path) -> None:
    name = "docs-guide-review"
    subprocess.run(
        [
            "python3",
            "scripts/sessions.py",
            "spawn-chat",
            "--prompt-file",
            str(prompt_path.relative_to(REPO_ROOT)),
            "--name",
            name,
            "--mode",
            "execute",
        ],
        cwd=REPO_ROOT,
        check=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", default="HEAD~1", help="Git ref to diff against.")
    parser.add_argument(
        "--spec",
        action="append",
        default=[],
        help="Explicit linked spec path to review. May be repeated.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Spawn an OpenCode execute-mode review session. Dry-run is the default.",
    )
    args = parser.parse_args()

    changed_paths = changed_files_since(args.since)
    affected = find_affected_guides(changed_paths, set(args.spec))
    if not affected:
        print("No linked user guides affected by changed specs.")
        return 0

    prompt = build_prompt(affected, args.since, changed_paths)
    prompt_path = write_prompt(prompt)

    print(f"Affected guides: {len(affected)}")
    for item in affected:
        guide_path = item.guide.path.relative_to(REPO_ROOT)
        print(f"- {guide_path}: {', '.join(item.changed_specs)}")
    print(f"Review prompt written to: {prompt_path.relative_to(REPO_ROOT)}")

    notification_payload = {
        "event": "docs_guide_review_prepared",
        "affected_guides": [str(item.guide.path.relative_to(REPO_ROOT)) for item in affected],
        "linked_specs": sorted({spec for item in affected for spec in item.changed_specs}),
        "prompt_file": str(prompt_path.relative_to(REPO_ROOT)),
    }
    print("Admin notification payload for any resulting docs change:")
    print(json.dumps(notification_payload, indent=2))

    if args.execute:
        spawn_review(prompt_path)
        print("Spawned OpenCode docs guide review session.")
    else:
        print("Dry-run only. Re-run with --execute to spawn the review session.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
