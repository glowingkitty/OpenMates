#!/usr/bin/env python3
"""
scripts/_scheduled_review_helper.py

Runs report-only OpenCode review cronjobs for UI design consistency, Apple web
parity, and SEO. The helper always includes current codebase inventory as the
primary input and recent git commits only as prioritization context.

Jobs create persisted OpenCode chats and write compact nightly report JSON so
the daily meeting can surface review status without parsing chat transcripts.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _nightly_report import write_nightly_report
from _opencode_utils import run_opencode_session


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = PROJECT_ROOT / "scripts"

JOB_CONFIG = {
    "ui-design-review": {
        "title": "ui-design-review",
        "prompt": SCRIPT_DIR / "prompts" / "ui-design-review.md",
        "report_job": "ui-design-review",
        "timeout": 1800,
        "recent_paths": [
            "frontend/packages/ui/src/components/",
            "frontend/packages/ui/src/styles/",
            "frontend/packages/ui/src/tokens/",
            "frontend/apps/web_app/src/routes/",
            "apple/OpenMates/Sources/",
            "DESIGN.md",
        ],
        "inventory_paths": [
            "DESIGN.md",
            ".claude/rules/frontend.md",
            ".claude/rules/settings-ui.md",
            ".claude/rules/apple-ui.md",
            "frontend/packages/ui/src/components",
            "frontend/packages/ui/src/styles",
            "frontend/packages/ui/src/tokens",
            "apple/OpenMates/Sources",
            "scripts/lint-design-tokens.sh",
            "scripts/lint-swift-design-tokens.sh",
        ],
        "summary": "UI design review OpenCode chat created.",
    },
    "apple-parity-review": {
        "title": "apple-parity-review",
        "prompt": SCRIPT_DIR / "prompts" / "apple-parity-review.md",
        "report_job": "apple-parity-review",
        "timeout": 1800,
        "recent_paths": [
            "frontend/packages/ui/src/components/",
            "frontend/packages/ui/src/styles/",
            "frontend/packages/ui/src/tokens/",
            "frontend/apps/web_app/src/routes/",
            "apple/OpenMates/Sources/",
            "apple/SVELTE_SWIFT_COUNTERPARTS.md",
        ],
        "inventory_paths": [
            "apple/SVELTE_SWIFT_COUNTERPARTS.md",
            "apple/AGENTS.md",
            ".claude/rules/apple-ui.md",
            "scripts/apple_parity_audit.py",
            "frontend/packages/ui/src/components",
            "frontend/packages/ui/src/styles",
            "frontend/packages/ui/src/tokens/generated/swift",
            "apple/OpenMates/Sources",
        ],
        "summary": "Apple parity review OpenCode chat created.",
    },
    "seo-audit": {
        "title": "seo-audit",
        "prompt": SCRIPT_DIR / "prompts" / "seo-audit.md",
        "report_job": "seo-audit",
        "timeout": 1800,
        "recent_paths": [
            "frontend/apps/web_app/src/routes/",
            "frontend/apps/web_app/src/app.html",
            "frontend/packages/ui/src/i18n/sources/metadata/",
            "frontend/packages/ui/src/demo_chats/",
            "backend/scripts/publish_newsletter.py",
        ],
        "inventory_paths": [
            ".opencode/agents/seo-auditor.md",
            "frontend/apps/web_app/src/app.html",
            "frontend/apps/web_app/src/routes",
            "frontend/packages/ui/src/i18n/sources/metadata",
            "frontend/packages/ui/src/demo_chats",
            "scripts/_daily_meeting_helper.py",
        ],
        "summary": "SEO audit OpenCode chat created.",
    },
}


def _run_git(args: list[str], timeout: int = 30) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except Exception as error:
        return f"(git command failed: {error})"
    output = result.stdout.strip()
    return output or "(none)"


def _repo_path(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT).as_posix()


def _count_paths(root: Path, pattern: str) -> int:
    if not root.exists():
        return 0
    return sum(1 for _ in root.rglob(pattern))


def _path_inventory(paths: list[str]) -> str:
    lines: list[str] = []
    for raw_path in paths:
        path = PROJECT_ROOT / raw_path
        if not path.exists():
            lines.append(f"- `{raw_path}`: missing")
            continue
        if path.is_file():
            try:
                line_count = len(path.read_text(encoding="utf-8", errors="replace").splitlines())
            except Exception:
                line_count = 0
            lines.append(f"- `{raw_path}`: file, {line_count} lines")
            continue
        swift_count = _count_paths(path, "*.swift")
        svelte_count = _count_paths(path, "*.svelte")
        ts_count = _count_paths(path, "*.ts")
        css_count = _count_paths(path, "*.css")
        md_count = _count_paths(path, "*.md")
        lines.append(
            f"- `{raw_path}`: directory, swift={swift_count}, svelte={svelte_count}, "
            f"ts={ts_count}, css={css_count}, md={md_count}"
        )
    return "\n".join(lines)


def _recent_changes(paths: list[str], since: str) -> str:
    args = ["log", "--name-only", "--pretty=format:%h %ad %s", "--date=short", f"--since={since}", "--", *paths]
    return _run_git(args, timeout=60)


def _current_head() -> str:
    return _run_git(["rev-parse", "--short", "HEAD"])


def _build_prompt(job_name: str, since: str) -> str:
    config = JOB_CONFIG[job_name]
    prompt_path: Path = config["prompt"]
    if not prompt_path.is_file():
        raise FileNotFoundError(f"Prompt template not found: {prompt_path}")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    replacements = {
        "{{DATE}}": today,
        "{{GIT_SHA}}": _current_head(),
        "{{RECENT_SINCE}}": since,
        "{{RECENT_CHANGES}}": _recent_changes(config["recent_paths"], since),
        "{{CODEBASE_INVENTORY}}": _path_inventory(config["inventory_paths"]),
    }
    prompt = prompt_path.read_text(encoding="utf-8")
    for key, value in replacements.items():
        prompt = prompt.replace(key, value)
    return prompt


def run_review(job_name: str, dry_run: bool, since: str) -> int:
    if job_name not in JOB_CONFIG:
        print(f"Unknown review job: {job_name}", file=sys.stderr)
        return 2

    config = JOB_CONFIG[job_name]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prompt = _build_prompt(job_name, since)
    session_title = f"{config['title']} {today}"
    log_prefix = f"[{job_name}]"

    if dry_run:
        print(f"{log_prefix} DRY RUN — would start OpenCode chat `{session_title}`")
        print("-" * 80)
        print(prompt[:4000])
        if len(prompt) > 4000:
            print(f"... ({len(prompt)} chars total)")
        print("-" * 80)
        write_nightly_report(
            job=config["report_job"],
            status="skipped",
            summary=f"Dry run for {session_title}; no OpenCode chat started.",
            details={"date": today, "head_sha": _current_head(), "dry_run": True},
        )
        return 0

    returncode, session_id = run_opencode_session(
        prompt=prompt,
        session_title=session_title,
        project_root=str(PROJECT_ROOT),
        log_prefix=log_prefix,
        agent="plan",
        timeout=int(config["timeout"]),
        job_type=config["report_job"],
        context_summary=config["summary"],
        linear_task=False,
    )
    status = "ok" if returncode == 0 else "error"
    write_nightly_report(
        job=config["report_job"],
        status=status,
        summary=config["summary"] if returncode == 0 else f"{config['title']} failed with exit code {returncode}.",
        details={
            "date": today,
            "head_sha": _current_head(),
            "session_id": session_id,
            "recent_since": since,
            "prompt_template": _repo_path(config["prompt"]),
            "report_only": True,
        },
    )
    return returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Run scheduled OpenCode review cronjobs.")
    parser.add_argument("job", choices=sorted(JOB_CONFIG))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--since", default="14 days ago", help="Recent git context window.")
    args = parser.parse_args()
    return run_review(args.job, args.dry_run, args.since)


if __name__ == "__main__":
    raise SystemExit(main())
