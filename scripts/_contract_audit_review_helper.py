#!/usr/bin/env python3
"""Start a read-only OpenCode review session for contract-audit results.

The weekly cron wrapper runs deterministic audits first, then calls this helper
to create a persisted OpenCode chat that reads the JSON and recommends the top
next steps. The helper writes a compact nightly report with the session ID for
daily meeting discovery.

Architecture context: docs/architecture/infrastructure/cronjobs.md
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _nightly_report import write_nightly_report  # noqa: E402
from _opencode_utils import run_opencode_session  # noqa: E402


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = PROJECT_ROOT / "scripts"
DEFAULT_REPORT_PATH = PROJECT_ROOT / "test-results" / "contract-audits" / "latest.json"
PROMPT_TEMPLATE_PATH = SCRIPT_DIR / "prompts" / "contract-audit-review.md"


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
    return result.stdout.strip() or "(none)"


def _repo_path(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT).as_posix()


def _current_head() -> str:
    return _run_git(["rev-parse", "--short", "HEAD"])


def _recent_commits() -> str:
    return _run_git(["log", "--oneline", "--decorate", "-20"], timeout=20)


def _load_report(report_path: Path) -> dict[str, Any]:
    if not report_path.is_file():
        raise FileNotFoundError(f"Contract audit report not found: {report_path}")
    return json.loads(report_path.read_text(encoding="utf-8"))


def _summary_for_prompt(report: dict[str, Any]) -> str:
    compact = {
        "generated_at": report.get("generated_at"),
        "summary": report.get("summary", {}),
        "top_findings": report.get("findings", [])[:20],
    }
    return json.dumps(compact, indent=2)[:12000]


def _build_prompt(report_path: Path, report: dict[str, Any]) -> str:
    if not PROMPT_TEMPLATE_PATH.is_file():
        raise FileNotFoundError(f"Prompt template not found: {PROMPT_TEMPLATE_PATH}")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    replacements = {
        "{{DATE}}": today,
        "{{GIT_SHA}}": _current_head(),
        "{{REPORT_PATH}}": _repo_path(report_path),
        "{{REPORT_SUMMARY}}": _summary_for_prompt(report),
        "{{RECENT_COMMITS}}": _recent_commits(),
    }
    prompt = PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")
    for key, value in replacements.items():
        prompt = prompt.replace(key, value)
    return prompt


def run_review(report_path: Path, dry_run: bool) -> int:
    report_path = report_path if report_path.is_absolute() else PROJECT_ROOT / report_path
    report = _load_report(report_path)
    prompt = _build_prompt(report_path, report)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    session_title = f"contract-audit-review {today}"
    log_prefix = "[contract-audit-review]"
    summary = report.get("summary", {})
    counts = summary.get("counts_by_severity", {})
    context_summary = (
        f"Contract audit review for {summary.get('total_findings', 0)} finding(s): "
        f"{counts.get('critical', 0)} critical, {counts.get('high', 0)} high, "
        f"{counts.get('medium', 0)} medium."
    )

    if dry_run:
        print(f"{log_prefix} DRY RUN — would start OpenCode chat `{session_title}`")
        print("-" * 80)
        print(prompt[:5000])
        if len(prompt) > 5000:
            print(f"... ({len(prompt)} chars total)")
        print("-" * 80)
        write_nightly_report(
            job="contract-audit-review",
            status="skipped",
            summary=f"Dry run for {session_title}; no OpenCode chat started.",
            details={
                "date": today,
                "head_sha": _current_head(),
                "dry_run": True,
                "report_path": _repo_path(report_path),
            },
        )
        return 0

    returncode, session_id = run_opencode_session(
        prompt=prompt,
        session_title=session_title,
        project_root=str(PROJECT_ROOT),
        log_prefix=log_prefix,
        agent="plan",
        timeout=1800,
        job_type="contract-audit-review",
        context_summary=context_summary,
        linear_task=False,
    )
    status = "ok" if returncode == 0 else "error"
    write_nightly_report(
        job="contract-audit-review",
        status=status,
        summary=(
            "Contract audit OpenCode recommendation chat created."
            if returncode == 0
            else f"Contract audit review failed with exit code {returncode}."
        ),
        details={
            "date": today,
            "head_sha": _current_head(),
            "session_id": session_id,
            "report_path": _repo_path(report_path),
            "report_only": True,
            "counts_by_severity": counts,
            "counts_by_audit": summary.get("counts_by_audit", {}),
        },
    )
    return returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Start an OpenCode recommendation chat for contract-audit results.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH, help="Contract audit JSON report to review.")
    args = parser.parse_args()
    return run_review(args.report, args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
