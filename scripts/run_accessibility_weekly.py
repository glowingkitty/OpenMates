#!/usr/bin/env python3
"""Run the weekly accessibility audit and email a compact admin summary.

This host-safe cron wrapper reuses scripts/accessibility_audit.py, writes both
latest and dated report artifacts, and sends a Brevo email when credentials are
configured. Use --dry-run for local verification without sending email.

Suggested crontab:
  0 6 * * 1 cd /home/superdev/projects/OpenMates && python3 scripts/run_accessibility_weekly.py
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import accessibility_audit


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "test-results" / "accessibility"
BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"
DEFAULT_SENDER_EMAIL = "noreply@openmates.org"
DEFAULT_SENDER_NAME = "OpenMates"
MAX_RULES_IN_EMAIL = 12


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _env(name: str, dot_env: dict[str, str], default: str = "") -> str:
    return os.environ.get(name) or dot_env.get(name, default)


def _git_value(args: list[str], default: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip() or default
    except Exception:
        return default


def _dated_path(output_dir: Path, suffix: str) -> Path:
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return output_dir / f"weekly-{date}.{suffix}"


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _severity_counts(report: dict[str, Any]) -> dict[str, int]:
    summary = report.get("summary", {})
    counts = summary.get("counts_by_severity", {}) if isinstance(summary, dict) else {}
    return {severity: int(counts.get(severity, 0)) for severity in accessibility_audit.FAIL_SEVERITIES}


def _email_subject(report: dict[str, Any], environment: str) -> str:
    counts = _severity_counts(report)
    if counts["critical"]:
        status = f"{counts['critical']} critical"
    elif counts["high"]:
        status = f"{counts['high']} high"
    else:
        status = "no high findings"
    return f"[OpenMates] Weekly accessibility audit: {status} ({environment})"


def _top_rule_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    summary = report.get("summary", {})
    rules = summary.get("counts_by_rule", []) if isinstance(summary, dict) else []
    return [rule for rule in rules[:MAX_RULES_IN_EMAIL] if isinstance(rule, dict)]


def _build_text_email(report: dict[str, Any], markdown_path: Path, git_sha: str, git_branch: str, environment: str) -> str:
    summary = report["summary"]
    counts = _severity_counts(report)
    lines = [
        f"Weekly Accessibility Audit ({environment})",
        "=" * 44,
        f"Generated: {report['generated_at']}",
        f"Git: {git_sha}@{git_branch}",
        f"Report: {_display_path(markdown_path)}",
        "",
        f"Total: {summary['total_findings']}",
        f"Critical: {counts['critical']}  High: {counts['high']}  Medium: {counts['medium']}  Low: {counts['low']}",
        "",
        "Top rule groups:",
    ]
    for rule in _top_rule_rows(report):
        lines.append(
            f"- [{rule['severity']}] {rule['id']} ({rule['count']}): {rule['title']} — example {rule['example']}"
        )
    lines.extend(
        [
            "",
            "This is a deterministic static audit. Review the Markdown/JSON artifacts before treating findings as release blockers.",
        ]
    )
    return "\n".join(lines)


def _build_html_email(report: dict[str, Any], markdown_path: Path, git_sha: str, git_branch: str, environment: str) -> str:
    summary = report["summary"]
    counts = _severity_counts(report)
    rows = "".join(
        "<tr>"
        f"<td>{html.escape(str(rule['severity']))}</td>"
        f"<td><code>{html.escape(str(rule['id']))}</code><br>{html.escape(str(rule['title']))}</td>"
        f"<td style='text-align:right'>{int(rule['count'])}</td>"
        f"<td><code>{html.escape(str(rule['example']))}</code></td>"
        "</tr>"
        for rule in _top_rule_rows(report)
    )
    status_color = "#ef4444" if counts["critical"] or counts["high"] else "#22c55e"
    return f"""<html><body style="font-family:Arial,sans-serif;background:#f9fafb;color:#111827;padding:24px">
<h2 style="color:{status_color};margin:0 0 12px">Weekly Accessibility Audit</h2>
<p style="margin:0 0 16px;color:#4b5563">Generated: <code>{html.escape(str(report['generated_at']))}</code><br>Git: <code>{html.escape(git_sha)}@{html.escape(git_branch)}</code><br>Environment: {html.escape(environment)}<br>Report: <code>{html.escape(_display_path(markdown_path))}</code></p>
<table style="border-collapse:collapse;margin:16px 0;background:white">
<tr><td style="padding:6px 16px;color:#4b5563">Total</td><td style="padding:6px 16px"><b>{int(summary['total_findings'])}</b></td></tr>
<tr><td style="padding:6px 16px;color:#991b1b">Critical</td><td style="padding:6px 16px"><b>{counts['critical']}</b></td></tr>
<tr><td style="padding:6px 16px;color:#b91c1c">High</td><td style="padding:6px 16px"><b>{counts['high']}</b></td></tr>
<tr><td style="padding:6px 16px;color:#92400e">Medium</td><td style="padding:6px 16px"><b>{counts['medium']}</b></td></tr>
<tr><td style="padding:6px 16px;color:#374151">Low</td><td style="padding:6px 16px"><b>{counts['low']}</b></td></tr>
</table>
<h3>Top rule groups</h3>
<table style="border-collapse:collapse;width:100%;background:white;font-size:13px">
<tr style="background:#eef2ff"><th style="text-align:left;padding:6px">Severity</th><th style="text-align:left;padding:6px">Rule</th><th style="text-align:right;padding:6px">Count</th><th style="text-align:left;padding:6px">Example</th></tr>
{rows}
</table>
<p style="color:#6b7280;font-size:12px;margin-top:16px">This deterministic static audit complements axe, keyboard, simulator, and manual assistive-technology testing.</p>
</body></html>"""


def _send_brevo_email(
    *,
    api_key: str,
    recipient: str,
    subject: str,
    text: str,
    html_body: str,
    markdown_path: Path,
    sender_email: str,
    sender_name: str,
) -> None:
    attachment_content = base64.b64encode(markdown_path.read_bytes()).decode("ascii")
    payload = {
        "sender": {"name": sender_name, "email": sender_email},
        "to": [{"email": recipient}],
        "subject": subject,
        "textContent": text,
        "htmlContent": html_body,
        "attachment": [
            {
                "name": markdown_path.name,
                "content": attachment_content,
            }
        ],
        "headers": {
            "Precedence": "bulk",
            "Auto-Submitted": "auto-generated",
        },
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        BREVO_API_URL,
        data=body,
        headers={"accept": "application/json", "api-key": api_key, "content-type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        resp.read()


def _build_internal_summary_payload(
    *,
    report: dict[str, Any],
    recipient: str,
    subject: str,
    git_sha: str,
    git_branch: str,
    environment: str,
    duration_seconds: int,
    markdown_path: Path,
) -> dict[str, Any]:
    counts = _severity_counts(report)
    rule_rows = _top_rule_rows(report)
    failed_tests = [
        {
            "suite": "accessibility-static-audit",
            "name": f"{rule['severity']} · {rule['id']}",
            "error": f"{rule['count']} finding(s): {rule['title']} — example {rule['example']}. Report: {_display_path(markdown_path)}",
        }
        for rule in rule_rows
    ]
    all_tests = [
        {
            "suite": "accessibility-static-audit",
            "name": f"{rule['id']} · {rule['title']}",
            "status": "failed" if rule["severity"] in {"critical", "high", "medium"} else "passed",
            "duration_seconds": 0,
        }
        for rule in rule_rows
    ]
    total = int(report["summary"]["total_findings"])
    failed = counts["critical"] + counts["high"] + counts["medium"]
    passed = max(0, total - failed)
    return {
        "recipient_email": recipient,
        "environment": environment,
        "run_id": f"accessibility-weekly-{datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
        "git_sha": git_sha,
        "git_branch": git_branch,
        "duration_seconds": duration_seconds,
        "total": total,
        "passed": passed,
        "failed": failed,
        "dispatch_error": 0,
        "timeout": 0,
        "result_unknown": 0,
        "skipped": counts["low"],
        "not_started": 0,
        "suites": [
            {
                "name": "accessibility-static-audit",
                "total": total,
                "passed": passed,
                "failed": failed,
                "status": "failed" if failed else "passed",
            }
        ],
        "failed_tests": failed_tests,
        "all_tests": all_tests,
        "subject_override": subject,
    }


def _send_internal_summary_email(*, api_url: str, internal_token: str, payload: dict[str, Any]) -> None:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        api_url.rstrip("/") + "/internal/dispatch-test-summary-email",
        data=body,
        headers={"Content-Type": "application/json", "X-Internal-Service-Token": internal_token},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        resp.read()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run weekly accessibility audit and email the admin summary.")
    parser.add_argument("--dry-run", action="store_true", help="Write reports and print email preview without sending.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Directory for generated reports.")
    parser.add_argument("--recipient", default="", help="Override recipient email. Defaults to ACCESSIBILITY_AUDIT_EMAIL or ADMIN_NOTIFY_EMAIL.")
    parser.add_argument("--environment", default="development", help="Environment label for the email subject/body.")
    parser.add_argument("--fail-on", choices=accessibility_audit.FAIL_SEVERITIES, default=None, help="Exit non-zero if findings at this severity or higher exist.")
    args = parser.parse_args()

    dot_env = _read_env_file(REPO_ROOT / ".env")
    output_dir = args.output_dir if args.output_dir.is_absolute() else REPO_ROOT / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    started_at = time.monotonic()
    report = accessibility_audit.build_report()
    duration_seconds = int(time.monotonic() - started_at)
    latest_json = output_dir / "latest.json"
    latest_md = output_dir / "latest.md"
    dated_json = _dated_path(output_dir, "json")
    dated_md = _dated_path(output_dir, "md")
    accessibility_audit.write_report(report, latest_json, latest_md)
    accessibility_audit.write_report(report, dated_json, dated_md)

    git_sha = _git_value(["rev-parse", "--short", "HEAD"], "unknown")
    git_branch = _git_value(["branch", "--show-current"], "unknown")
    recipient = args.recipient or _env("ACCESSIBILITY_AUDIT_EMAIL", dot_env) or _env("ADMIN_NOTIFY_EMAIL", dot_env)
    brevo_api_key = _env("BREVO_API_KEY", dot_env)
    internal_token = _env("INTERNAL_API_SHARED_TOKEN", dot_env)
    internal_api_url = _env("INTERNAL_API_URL", dot_env, "http://localhost:8000")
    sender_email = _env("ACCESSIBILITY_AUDIT_SENDER_EMAIL", dot_env, DEFAULT_SENDER_EMAIL)
    sender_name = _env("ACCESSIBILITY_AUDIT_SENDER_NAME", dot_env, DEFAULT_SENDER_NAME)
    subject = _email_subject(report, args.environment)
    text = _build_text_email(report, dated_md, git_sha, git_branch, args.environment)
    html_body = _build_html_email(report, dated_md, git_sha, git_branch, args.environment)

    print(f"Wrote {_display_path(latest_json)}")
    print(f"Wrote {_display_path(latest_md)}")
    print(f"Wrote {_display_path(dated_json)}")
    print(f"Wrote {_display_path(dated_md)}")
    print(f"Subject: {subject}")

    if args.dry_run:
        print("Dry run: email not sent.")
        print(text)
    else:
        if not recipient:
            print("ERROR: ACCESSIBILITY_AUDIT_EMAIL or ADMIN_NOTIFY_EMAIL is required to send email.", file=sys.stderr)
            return 1
        try:
            if brevo_api_key:
                _send_brevo_email(
                    api_key=brevo_api_key,
                    recipient=recipient,
                    subject=subject,
                    text=text,
                    html_body=html_body,
                    markdown_path=dated_md,
                    sender_email=sender_email,
                    sender_name=sender_name,
                )
                print(f"Email sent to {recipient} via Brevo")
            elif internal_token:
                payload = _build_internal_summary_payload(
                    report=report,
                    recipient=recipient,
                    subject=subject,
                    git_sha=git_sha,
                    git_branch=git_branch,
                    environment=args.environment,
                    duration_seconds=duration_seconds,
                    markdown_path=dated_md,
                )
                _send_internal_summary_email(api_url=internal_api_url, internal_token=internal_token, payload=payload)
                print(f"Email dispatched to {recipient} via internal API")
            else:
                print("ERROR: BREVO_API_KEY or INTERNAL_API_SHARED_TOKEN is required to send email.", file=sys.stderr)
                return 1
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            print(f"ERROR: email dispatch failed HTTP {exc.code}: {body[:500]}", file=sys.stderr)
            return 1
        except Exception as exc:
            print(f"ERROR: email dispatch failed: {exc}", file=sys.stderr)
            return 1

    if accessibility_audit.should_fail(report, args.fail_on):
        print(f"Failing because findings at severity {args.fail_on!r} or higher are present.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
