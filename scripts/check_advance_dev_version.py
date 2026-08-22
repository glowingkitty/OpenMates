#!/usr/bin/env python3
"""Report the dev-version advancement pipeline state.

Purpose: make post-main-merge version diagnostics deterministic for agents.
Architecture: GitHub data comes from the authenticated local `gh` CLI, not MCP.
Safety: commands are read-only except optional remote-ref fetches, and all errors
are reported in the JSON/text output instead of being hidden.
Tests: scripts/tests/test_check_advance_dev_version.py.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_NAME = "Advance dev version after main merge"
PRODUCT_CONFIG = ROOT / "shared" / "config" / "product_version.json"


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


def run_command(command: Sequence[str]) -> CommandResult:
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    return CommandResult(result.returncode, result.stdout.strip(), result.stderr.strip())


def command_json(command: Sequence[str]) -> tuple[Any | None, str]:
    result = run_command(command)
    if result.returncode != 0:
        return None, result.stderr or result.stdout or f"command failed: {' '.join(command)}"
    try:
        return json.loads(result.stdout or "null"), ""
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON from {' '.join(command)}: {exc}"


def local_product_version() -> dict[str, Any]:
    if not PRODUCT_CONFIG.exists():
        return {"error": f"missing {PRODUCT_CONFIG.relative_to(ROOT)}"}
    try:
        return json.loads(PRODUCT_CONFIG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"error": str(exc)}


def local_git_state(fetch: bool) -> dict[str, Any]:
    if fetch:
        fetch_result = run_command(["git", "fetch", "origin", "dev", "main"])
        if fetch_result.returncode != 0:
            return {"error": fetch_result.stderr or fetch_result.stdout}
    branch = run_command(["git", "branch", "--show-current"])
    head = run_command(["git", "rev-parse", "HEAD"])
    origin_dev = run_command(["git", "rev-parse", "origin/dev"])
    return {
        "branch": branch.stdout,
        "head": head.stdout,
        "origin_dev": origin_dev.stdout,
        "head_matches_origin_dev": bool(head.stdout and head.stdout == origin_dev.stdout),
    }


def latest_merged_dev_pr() -> tuple[dict[str, Any] | None, str]:
    payload, error = command_json(
        [
            "gh",
            "pr",
            "list",
            "--base",
            "main",
            "--head",
            "dev",
            "--state",
            "merged",
            "--limit",
            "1",
            "--json",
            "number,title,mergedAt,mergeCommit,headRefOid,url",
        ]
    )
    if error:
        return None, error
    if not isinstance(payload, list) or not payload:
        return None, "no merged dev-to-main PR found"
    return payload[0], ""


def latest_workflow_runs(limit: int) -> tuple[list[dict[str, Any]], str]:
    payload, error = command_json(
        [
            "gh",
            "run",
            "list",
            "--workflow",
            WORKFLOW_NAME,
            "--limit",
            str(limit),
            "--json",
            "databaseId,status,conclusion,displayTitle,createdAt,url,headBranch,headSha,event",
        ]
    )
    if error:
        return [], error
    return payload if isinstance(payload, list) else [], ""


def run_failure_log(run_id: int) -> str:
    result = run_command(["gh", "run", "view", str(run_id), "--log-failed"])
    if result.returncode != 0:
        return result.stderr or result.stdout
    lines = result.stdout.splitlines()
    return "\n".join(lines[-80:])


def classify_recommendation(report: dict[str, Any]) -> list[str]:
    recommendations: list[str] = []
    product = report.get("product_version") if isinstance(report.get("product_version"), dict) else {}
    user_facing = product.get("userFacing")
    latest_run = report.get("latest_run") if isinstance(report.get("latest_run"), dict) else {}
    failure_log = str(report.get("latest_failure_log") or "")

    if user_facing != "v0.17":
        recommendations.append("Open a normal PR to dev that runs `python3 scripts/bump_alpha_version_line.py --minor 17`.")
    if latest_run.get("conclusion") == "failure" and "Changes must be made through a pull request" in failure_log:
        recommendations.append("Keep the automation PR-based; direct pushes to dev violate repository rules.")
    if "without `workflows` permission" in failure_log or "without workflows permission" in failure_log:
        recommendations.append("Keep routine version bumps from editing `.github/workflows/**` files.")
    if not recommendations:
        recommendations.append("No remediation needed from this report.")
    return recommendations


def build_report(fetch: bool, run_limit: int) -> dict[str, Any]:
    pr, pr_error = latest_merged_dev_pr()
    runs, runs_error = latest_workflow_runs(run_limit)
    latest_run = runs[0] if runs else None
    failure_log = ""
    if isinstance(latest_run, dict) and latest_run.get("conclusion") == "failure" and latest_run.get("databaseId"):
        failure_log = run_failure_log(int(latest_run["databaseId"]))
    report: dict[str, Any] = {
        "git": local_git_state(fetch),
        "product_version": local_product_version(),
        "latest_merged_dev_pr": pr,
        "latest_merged_dev_pr_error": pr_error,
        "workflow_name": WORKFLOW_NAME,
        "latest_runs": runs,
        "latest_runs_error": runs_error,
        "latest_run": latest_run,
        "latest_failure_log": failure_log,
    }
    report["recommendations"] = classify_recommendation(report)
    return report


def render_text(report: dict[str, Any]) -> str:
    product = report.get("product_version") or {}
    latest_pr = report.get("latest_merged_dev_pr") or {}
    latest_run = report.get("latest_run") or {}
    lines = [
        "Advance dev version status",
        f"Product line: {product.get('userFacing', 'unknown')}",
        f"Stable base: {(product.get('cli') or {}).get('stableBase', 'unknown')}",
        f"Latest merged dev->main PR: #{latest_pr.get('number', 'unknown')} {latest_pr.get('title', '')}".rstrip(),
        f"Latest workflow run: {latest_run.get('databaseId', 'unknown')} {latest_run.get('conclusion', 'unknown')}",
        "Recommendations:",
    ]
    lines.extend(f"- {item}" for item in report.get("recommendations", []))
    if report.get("latest_runs_error"):
        lines.append(f"Workflow query error: {report['latest_runs_error']}")
    if report.get("latest_merged_dev_pr_error"):
        lines.append(f"PR query error: {report['latest_merged_dev_pr_error']}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    parser.add_argument("--no-fetch", action="store_true", help="Do not fetch origin/dev and origin/main first")
    parser.add_argument("--run-limit", type=int, default=5, help="Number of workflow runs to inspect")
    args = parser.parse_args()
    report = build_report(fetch=not args.no_fetch, run_limit=args.run_limit)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(render_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
