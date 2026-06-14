#!/usr/bin/env python3
"""Spawn the weekly OpenCode technical-debt analysis session.

The scanner creates machine-readable and Markdown reports first. This helper
then asks OpenCode, in read-only plan mode, to interpret the report and propose
the top five next improvements with explicit attention to previous-run deltas.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from _nightly_report import write_nightly_report
from _opencode_utils import run_opencode_session


def _load_text(path: Path, fallback: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return fallback


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _now_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def run_analysis() -> None:
    dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"
    project_root = Path(os.environ.get("PROJECT_ROOT", ""))
    today = os.environ.get("TODAY_DATE") or _now_date()
    json_report = Path(os.environ.get("TECH_DEBT_JSON_REPORT", ""))
    markdown_report = Path(os.environ.get("TECH_DEBT_MARKDOWN_REPORT", ""))
    prompt_template = Path(os.environ.get("PROMPT_TEMPLATE_PATH", ""))

    if not project_root:
        print("[technical-debt] ERROR: PROJECT_ROOT not set", file=sys.stderr)
        sys.exit(1)
    if not json_report.is_file():
        print(f"[technical-debt] ERROR: JSON report missing: {json_report}", file=sys.stderr)
        sys.exit(1)
    if not prompt_template.is_file():
        print(f"[technical-debt] ERROR: prompt template missing: {prompt_template}", file=sys.stderr)
        sys.exit(1)

    report = _load_json(json_report)
    markdown = _load_text(markdown_report, "(Markdown report missing; use JSON report path.)")
    template = prompt_template.read_text(encoding="utf-8")
    summary = json.dumps(
        {
            "generated_at": report.get("generated_at"),
            "head_sha": report.get("head_sha"),
            "summary": report.get("summary"),
            "delta": report.get("delta"),
            "top_hotspots_by_score": report.get("top_hotspots_by_score", [])[:15],
            "churn_hotspots_6_months": report.get("churn_hotspots_6_months", [])[:15],
            "directory_rollup": report.get("directory_rollup", [])[:12],
            "duplication_fingerprints": report.get("duplication_fingerprints", [])[:12],
        },
        indent=2,
    )
    prompt = (
        template.replace("{{DATE}}", today)
        .replace("{{JSON_REPORT_PATH}}", str(json_report.relative_to(project_root)))
        .replace("{{MARKDOWN_REPORT_PATH}}", str(markdown_report.relative_to(project_root)))
        .replace("{{REPORT_SUMMARY_JSON}}", summary)
        .replace("{{REPORT_MARKDOWN}}", markdown[:18000])
    )

    if dry_run:
        print("[technical-debt] DRY RUN — would spawn OpenCode with prompt:")
        print("-" * 60)
        print(prompt[:5000])
        print(f"... ({len(prompt)} chars total)")
        return

    title = f"technical-debt: weekly top 5 {today}"
    returncode, session_id = run_opencode_session(
        prompt=prompt,
        session_title=title,
        project_root=str(project_root),
        log_prefix="[technical-debt]",
        agent="plan",
        timeout=1800,
        job_type="technical-debt",
        context_summary="Weekly technical debt report analysis and top five improvement recommendations.",
        linear_task=False,
    )

    write_nightly_report(
        job="technical-debt-analysis",
        status="ok" if returncode == 0 else "error",
        summary=f"Weekly technical debt analysis completed. Session: {session_id or 'N/A'}.",
        details={
            "date": today,
            "head_sha": report.get("head_sha"),
            "session_id": session_id,
            "json_report": str(json_report.relative_to(project_root)),
            "markdown_report": str(markdown_report.relative_to(project_root)),
            "delta": report.get("delta"),
        },
    )
    if returncode != 0:
        sys.exit(returncode)


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] != "run-analysis":
        print(f"Usage: {sys.argv[0]} run-analysis", file=sys.stderr)
        sys.exit(1)
    run_analysis()
