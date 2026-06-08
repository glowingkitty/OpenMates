#!/usr/bin/env python3
"""Run deterministic contract audits and email a compact admin summary.

This weekly cron wrapper runs repository-specific static audits, stores latest
and dated JSON artifacts, writes a daily-meeting report, and optionally sends an
admin email via Brevo or the internal test-summary email endpoint.

Suggested crontab:
  15 5 * * 1 cd /home/superdev/projects/OpenMates && python3 scripts/run_contract_audits.py
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

import contract_audits
from _nightly_report import write_nightly_report


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "test-results" / "contract-audits"
BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"
DEFAULT_SENDER_EMAIL = "noreply@openmates.org"
DEFAULT_SENDER_NAME = "OpenMates"
MAX_FINDINGS_IN_EMAIL = 15

SEVERITIES_PRIORITY = ("critical", "high", "medium")
SEVERITIES_OBSERVATION = ("low", "info")

RULE_FIX_GUIDANCE = {
    "ARCH-CROSS-APP-SHARED-HELPER": (
        "Cross-app helper imports",
        "Move reusable helpers out of backend/apps/ai into backend/shared/python_utils or BaseSkill.",
    ),
    "ARCH-CROSS-APP-IMPORT": (
        "Cross-app imports",
        "Keep skills isolated by moving shared behavior to backend/shared or a shared provider wrapper.",
    ),
    "ENC-GET-KEY-SYNC": (
        "Synchronous chat-key access",
        "Replace unsafe sync access with async ChatKeyManager calls, or add a KEYS-04 justification where sync access is intentional.",
    ),
    "ENC-DIRECT-CHAT-KEY-DECRYPT": (
        "Direct chat-key unwraps",
        "Route chat-key loading through ChatKeyManager or document/allowlist true key-management modules.",
    ),
    "SETTINGS-HARDCODED-COLOR": (
        "Hardcoded settings colors",
        "Replace raw color literals with design-token CSS variables or canonical settings/elements components.",
    ),
    "SETTINGS-MISSING-TESTID": (
        "Missing settings test IDs",
        "Add stable kebab-case data-testid attributes to interactive settings controls.",
    ),
    "SETTINGS-INLINE-STYLE": (
        "Inline settings styles",
        "Move styles to token-backed CSS classes or canonical settings/elements components.",
    ),
    "SETTINGS-ADHOC-CONTROL": (
        "Ad-hoc settings controls",
        "Replace custom controls with the canonical settings/elements primitives where practical.",
    ),
    "APP-SKILLS-DIR-MISSING": (
        "Declared skill directories missing",
        "Confirm planned metadata-only apps or add the missing backend skills directory.",
    ),
}


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


def _dated_path(output_dir: Path) -> Path:
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return output_dir / f"weekly-{date}.json"


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp_path, path)


def _status_for_report(report: dict[str, Any]) -> str:
    counts = report["summary"]["counts_by_severity"]
    if counts.get("critical", 0) or counts.get("high", 0):
        return "warning"
    return "ok" if report["summary"]["total_findings"] == 0 else "warning"


def _email_subject(report: dict[str, Any], environment: str) -> str:
    counts = report["summary"]["counts_by_severity"]
    if counts.get("critical", 0):
        status = f"{counts['critical']} critical"
    elif counts.get("high", 0):
        status = f"{counts['high']} high"
    elif counts.get("medium", 0):
        status = f"{counts['medium']} medium"
    else:
        status = "no medium+ findings"
    return f"[OpenMates] Weekly contract audits: {status} ({environment})"


def _severity_sum(counts: dict[str, Any], severities: tuple[str, ...]) -> int:
    return sum(int(counts.get(severity, 0)) for severity in severities)


def _priority_total(summary: dict[str, Any]) -> int:
    return _severity_sum(summary.get("counts_by_severity", {}), SEVERITIES_PRIORITY)


def _observation_total(summary: dict[str, Any]) -> int:
    return _severity_sum(summary.get("counts_by_severity", {}), SEVERITIES_OBSERVATION)


def _rule_fix_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    counts_by_rule = report["summary"].get("counts_by_rule", {})
    rows = []
    for rule_id, count in sorted(counts_by_rule.items(), key=lambda item: int(item[1]), reverse=True):
        title, next_step = RULE_FIX_GUIDANCE.get(rule_id, (rule_id, "Review sampled findings in the JSON report."))
        rows.append({"rule_id": rule_id, "count": int(count), "title": title, "next_step": next_step})
    return rows


def _top_findings(report: dict[str, Any]) -> list[dict[str, Any]]:
    findings = report.get("findings", [])
    return [finding for finding in findings[:MAX_FINDINGS_IN_EMAIL] if isinstance(finding, dict)]


def _top_priority_findings(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        finding for finding in _top_findings(report)
        if contract_audits.severity_at_or_above(str(finding.get("severity", "info")), "medium")
    ]


def _build_text_email(report: dict[str, Any], report_path: Path, git_sha: str, git_branch: str, environment: str) -> str:
    summary = report["summary"]
    counts = summary["counts_by_severity"]
    priority = _priority_total(summary)
    observations = _observation_total(summary)
    lines = [
        f"Weekly Contract Audits ({environment})",
        "=" * 42,
        "This is a deterministic static audit, not a test run.",
        "Priority findings are critical/high/medium items. Low/info findings are tracked as observations.",
        "",
        f"Generated: {report['generated_at']}",
        f"Git: {git_sha}@{git_branch}",
        f"JSON report: {report_path.relative_to(REPO_ROOT)}",
        "",
        f"Total findings: {summary['total_findings']}",
        f"Priority findings: {priority}",
        f"Observations: {observations}",
        f"Emitted for review: {summary.get('emitted_findings', len(report.get('findings', [])))} (max {summary.get('max_findings_per_rule', 'n/a')} per rule)",
        "Critical: {critical}  High: {high}  Medium: {medium}  Low: {low}  Info: {info}".format(**counts),
        "",
        "Findings by audit area:",
    ]
    for audit, count in summary.get("counts_by_audit", {}).items():
        audit_counts = summary.get("counts_by_audit_severity", {}).get(audit, {})
        audit_priority = _severity_sum(audit_counts, SEVERITIES_PRIORITY)
        audit_observations = _severity_sum(audit_counts, SEVERITIES_OBSERVATION)
        lines.append(f"- {audit}: {count} total, {audit_priority} priority, {audit_observations} observations")

    lines.append("")
    lines.append("Recommended fix order:")
    for row in _rule_fix_rows(report)[:6]:
        lines.append(f"- {row['count']}x {row['title']}: {row['next_step']}")

    omitted = summary.get("omitted_by_rule", {})
    if omitted:
        lines.append("")
        lines.append("Omitted repeated findings from email/agent sample:")
        for rule_id, count in omitted.items():
            lines.append(f"- {rule_id}: {count}")

    lines.append("")
    lines.append("Top sampled priority findings:")
    priority_findings = _top_priority_findings(report)
    if not priority_findings:
        lines.append("- None in the emitted sample.")
    for finding in priority_findings:
        lines.append(
            f"- [{finding['severity']}] {finding['rule_id']} {finding['file']}:{finding['line']} — {finding['title']}"
        )
    lines.extend(
        [
            "",
            "Review the JSON artifact before treating individual findings as release blockers.",
        ]
    )
    return "\n".join(lines)


def _build_html_email(report: dict[str, Any], report_path: Path, git_sha: str, git_branch: str, environment: str) -> str:
    summary = report["summary"]
    counts = summary["counts_by_severity"]
    priority = _priority_total(summary)
    observations = _observation_total(summary)
    status_color = "#ef4444" if counts.get("critical", 0) or counts.get("high", 0) else "#22c55e"
    audit_rows = "".join(
        "<tr>"
        f"<td style='padding:6px'><code>{html.escape(str(audit))}</code></td>"
        f"<td style='padding:6px;text-align:right'>{int(count)}</td>"
        f"<td style='padding:6px;text-align:right;color:#b91c1c'><b>{_severity_sum(summary.get('counts_by_audit_severity', {}).get(audit, {}), SEVERITIES_PRIORITY)}</b></td>"
        f"<td style='padding:6px;text-align:right;color:#6b7280'>{_severity_sum(summary.get('counts_by_audit_severity', {}).get(audit, {}), SEVERITIES_OBSERVATION)}</td>"
        "</tr>"
        for audit, count in summary.get("counts_by_audit", {}).items()
    )
    rule_rows = "".join(
        "<tr>"
        f"<td style='padding:6px;text-align:right'><b>{row['count']}</b></td>"
        f"<td style='padding:6px'><code>{html.escape(str(row['rule_id']))}</code><br>{html.escape(str(row['title']))}</td>"
        f"<td style='padding:6px'>{html.escape(str(row['next_step']))}</td>"
        "</tr>"
        for row in _rule_fix_rows(report)[:6]
    )
    finding_rows = "".join(
        "<tr>"
        f"<td style='padding:6px'>{html.escape(str(finding['severity']))}</td>"
        f"<td style='padding:6px'><code>{html.escape(str(finding['rule_id']))}</code><br>{html.escape(str(finding['title']))}</td>"
        f"<td style='padding:6px'><code>{html.escape(str(finding['file']))}:{int(finding['line'])}</code></td>"
        f"<td style='padding:6px'>{html.escape(str(finding['recommendation']))}</td>"
        "</tr>"
        for finding in _top_priority_findings(report)
    ) or "<tr><td colspan='4' style='padding:6px;color:#6b7280'>None in the emitted sample.</td></tr>"
    return f"""<html><body style="font-family:Arial,sans-serif;background:#f9fafb;color:#111827;padding:24px">
<h2 style="color:{status_color};margin:0 0 12px">Weekly Contract Audits</h2>
<p style="margin:0 0 12px;color:#4b5563"><b>This is a deterministic static audit, not a test run.</b> Priority findings are critical/high/medium items. Low/info findings are tracked as observations.</p>
<p style="margin:0 0 16px;color:#4b5563">Generated: <code>{html.escape(str(report['generated_at']))}</code><br>Git: <code>{html.escape(git_sha)}@{html.escape(git_branch)}</code><br>Environment: {html.escape(environment)}<br>JSON report: <code>{html.escape(str(report_path.relative_to(REPO_ROOT)))}</code></p>
<table style="border-collapse:collapse;margin:16px 0;background:white">
<tr><td style="padding:6px 16px;color:#4b5563">Total</td><td style="padding:6px 16px"><b>{int(summary['total_findings'])}</b></td></tr>
<tr><td style="padding:6px 16px;color:#b91c1c">Priority findings</td><td style="padding:6px 16px"><b>{priority}</b></td></tr>
<tr><td style="padding:6px 16px;color:#6b7280">Observations</td><td style="padding:6px 16px"><b>{observations}</b></td></tr>
<tr><td style="padding:6px 16px;color:#4b5563">Emitted sample</td><td style="padding:6px 16px"><b>{int(summary.get('emitted_findings', len(report.get('findings', []))))}</b></td></tr>
<tr><td style="padding:6px 16px;color:#991b1b">Critical</td><td style="padding:6px 16px"><b>{int(counts.get('critical', 0))}</b></td></tr>
<tr><td style="padding:6px 16px;color:#b91c1c">High</td><td style="padding:6px 16px"><b>{int(counts.get('high', 0))}</b></td></tr>
<tr><td style="padding:6px 16px;color:#92400e">Medium</td><td style="padding:6px 16px"><b>{int(counts.get('medium', 0))}</b></td></tr>
<tr><td style="padding:6px 16px;color:#374151">Low</td><td style="padding:6px 16px"><b>{int(counts.get('low', 0))}</b></td></tr>
<tr><td style="padding:6px 16px;color:#6b7280">Info</td><td style="padding:6px 16px"><b>{int(counts.get('info', 0))}</b></td></tr>
</table>
<h3>Findings by audit area</h3>
<table style="border-collapse:collapse;background:white;font-size:13px"><tr style="background:#eef2ff"><th style="text-align:left;padding:6px">Audit</th><th style="text-align:right;padding:6px">Total</th><th style="text-align:right;padding:6px">Priority</th><th style="text-align:right;padding:6px">Observations</th></tr>{audit_rows}</table>
<h3>Recommended fix order</h3>
<table style="border-collapse:collapse;width:100%;background:white;font-size:13px"><tr style="background:#eef2ff"><th style="text-align:right;padding:6px">Count</th><th style="text-align:left;padding:6px">Rule</th><th style="text-align:left;padding:6px">Next step</th></tr>{rule_rows}</table>
<h3>Top sampled priority findings</h3>
<table style="border-collapse:collapse;width:100%;background:white;font-size:13px">
<tr style="background:#eef2ff"><th style="text-align:left;padding:6px">Severity</th><th style="text-align:left;padding:6px">Rule</th><th style="text-align:left;padding:6px">Location</th><th style="text-align:left;padding:6px">Recommendation</th></tr>
{finding_rows}
</table>
<p style="color:#6b7280;font-size:12px;margin-top:16px">The sampled findings are capped per rule. Use the JSON artifact for the full count and exact locations.</p>
</body></html>"""


def _send_brevo_email(
    *,
    api_key: str,
    recipient: str,
    subject: str,
    text: str,
    html_body: str,
    report_path: Path,
    sender_email: str,
    sender_name: str,
) -> None:
    attachment_content = base64.b64encode(report_path.read_bytes()).decode("ascii")
    payload = {
        "sender": {"name": sender_name, "email": sender_email},
        "to": [{"email": recipient}],
        "subject": subject,
        "textContent": text,
        "htmlContent": html_body,
        "attachment": [{"name": report_path.name, "content": attachment_content}],
        "headers": {"Precedence": "bulk", "Auto-Submitted": "auto-generated"},
    }
    req = urllib.request.Request(
        BREVO_API_URL,
        data=json.dumps(payload).encode("utf-8"),
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
    report_path: Path,
) -> dict[str, Any]:
    summary = report["summary"]
    findings = report.get("findings", [])
    failed_findings = [
        finding for finding in findings
        if contract_audits.severity_at_or_above(str(finding.get("severity", "info")), "medium")
    ]
    all_tests = [
        {
            "suite": f"contract-audit:{finding['audit']}",
            "name": f"{finding['rule_id']} · {finding['file']}:{finding['line']}",
            "status": "failed" if finding in failed_findings else "passed",
            "duration_seconds": 0,
        }
        for finding in findings[:200]
    ]
    failed_tests = [
        {
            "suite": f"contract-audit:{finding['audit']}",
            "name": f"{finding['severity']} · {finding['rule_id']}",
            "error": (
                f"{finding['file']}:{finding['line']} — {finding['title']}. "
                f"Recommended fix: {finding['recommendation']} Report: {report_path.relative_to(REPO_ROOT)}"
            ),
        }
        for finding in failed_findings[:50]
    ]
    counts_by_audit = summary.get("counts_by_audit", {})
    counts_by_audit_severity = summary.get("counts_by_audit_severity", {})
    suites = [
        {
            "name": f"contract-audit:{audit}",
            "total": int(count),
            "passed": _severity_sum(counts_by_audit_severity.get(audit, {}), SEVERITIES_OBSERVATION),
            "failed": _severity_sum(counts_by_audit_severity.get(audit, {}), SEVERITIES_PRIORITY),
            "status": "failed" if _severity_sum(counts_by_audit_severity.get(audit, {}), SEVERITIES_PRIORITY) else "passed",
        }
        for audit, count in counts_by_audit.items()
    ]
    total = int(summary["total_findings"])
    failed = _priority_total(summary)
    passed = _observation_total(summary)
    return {
        "recipient_email": recipient,
        "environment": environment,
        "run_id": f"contract-audits-weekly-{datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
        "git_sha": git_sha,
        "git_branch": git_branch,
        "duration_seconds": duration_seconds,
        "total": total,
        "passed": passed,
        "failed": failed,
        "dispatch_error": 0,
        "timeout": 0,
        "result_unknown": 0,
        "skipped": 0,
        "not_started": 0,
        "suites": suites or [{"name": "contract-audits", "total": 1, "passed": 1, "failed": 0, "status": "passed"}],
        "failed_tests": failed_tests,
        "all_tests": all_tests or [{"suite": "contract-audits", "name": "no findings", "status": "passed", "duration_seconds": 0}],
        "subject_override": subject,
        "summary_copy": {
            "header_success": "No priority contract findings",
            "header_failure": "{failed} priority findings of {total} total findings",
            "intro_note": "This is a deterministic static contract audit, not a test run. Priority findings are critical/high/medium static findings; low/info items are tracked as observations.",
            "status_success": "NO PRIORITY FINDINGS",
            "status_failure": "{failed} PRIORITY FINDINGS",
            "item_label_plural": "findings",
            "passed_label": "observations",
            "failed_label": "priority",
            "suites_label": "Audit Areas",
            "suite_name_header": "Audit Area",
            "passed_header": "Observations",
            "failed_header": "Priority",
            "status_passed": "CLEAR",
            "status_failed": "NEEDS REVIEW",
            "failed_tests_label": "Top Priority Findings (sample)",
            "all_tests_label": "Sampled Findings",
            "footer_note": "Findings are capped per rule in this email. Review the JSON artifact for full counts, exact locations, and omitted repeated findings.",
        },
    }


def _send_internal_summary_email(*, api_url: str, internal_token: str, payload: dict[str, Any]) -> None:
    req = urllib.request.Request(
        api_url.rstrip("/") + "/internal/dispatch-test-summary-email",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Internal-Service-Token": internal_token},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        resp.read()


def _write_nightly_summary(report: dict[str, Any], latest_json: Path, dated_json: Path, git_sha: str, git_branch: str, duration_seconds: int) -> None:
    summary = report["summary"]
    counts = summary["counts_by_severity"]
    status = _status_for_report(report)
    readable = (
        f"Contract audits found {summary['total_findings']} finding(s): "
        f"{counts.get('critical', 0)} critical, {counts.get('high', 0)} high, "
        f"{counts.get('medium', 0)} medium."
    )
    write_nightly_report(
        job="contract-audits",
        status=status,
        summary=readable,
        details={
            "head_sha": git_sha,
            "git_branch": git_branch,
            "duration_seconds": duration_seconds,
            "latest_json": str(latest_json.relative_to(REPO_ROOT)),
            "dated_json": str(dated_json.relative_to(REPO_ROOT)),
            "counts_by_severity": counts,
            "counts_by_audit": summary.get("counts_by_audit", {}),
            "emitted_findings": summary.get("emitted_findings", len(report.get("findings", []))),
            "omitted_by_rule": summary.get("omitted_by_rule", {}),
            "top_findings": _top_findings(report)[:10],
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic contract audits and email the admin summary.")
    parser.add_argument("--dry-run", action="store_true", help="Write reports and print email preview without sending.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Directory for generated reports.")
    parser.add_argument("--recipient", default="", help="Override recipient email. Defaults to CONTRACT_AUDIT_EMAIL or ADMIN_NOTIFY_EMAIL.")
    parser.add_argument("--environment", default="development", help="Environment label for the email subject/body.")
    parser.add_argument("--audit", action="append", choices=sorted(contract_audits.AUDITS), help="Audit to run. Repeatable. Defaults to all audits.")
    parser.add_argument("--fail-on", choices=sorted(contract_audits.SEVERITY_ORDER, key=contract_audits.SEVERITY_ORDER.get), default=None, help="Exit non-zero if findings at this severity or higher exist.")
    args = parser.parse_args()

    dot_env = _read_env_file(REPO_ROOT / ".env")
    output_dir = args.output_dir if args.output_dir.is_absolute() else REPO_ROOT / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    started_at = time.monotonic()
    report = contract_audits.build_report(args.audit)
    duration_seconds = int(time.monotonic() - started_at)

    latest_json = output_dir / "latest.json"
    dated_json = _dated_path(output_dir)
    _write_json(latest_json, report)
    _write_json(dated_json, report)

    git_sha = _git_value(["rev-parse", "--short", "HEAD"], "unknown")
    git_branch = _git_value(["branch", "--show-current"], "unknown")
    _write_nightly_summary(report, latest_json, dated_json, git_sha, git_branch, duration_seconds)

    recipient = args.recipient or _env("CONTRACT_AUDIT_EMAIL", dot_env) or _env("ADMIN_NOTIFY_EMAIL", dot_env)
    brevo_api_key = _env("BREVO_API_KEY", dot_env)
    internal_token = _env("INTERNAL_API_SHARED_TOKEN", dot_env)
    internal_api_url = _env("INTERNAL_API_URL", dot_env, "http://localhost:8000")
    sender_email = _env("CONTRACT_AUDIT_SENDER_EMAIL", dot_env, DEFAULT_SENDER_EMAIL)
    sender_name = _env("CONTRACT_AUDIT_SENDER_NAME", dot_env, DEFAULT_SENDER_NAME)
    subject = _email_subject(report, args.environment)
    text = _build_text_email(report, dated_json, git_sha, git_branch, args.environment)
    html_body = _build_html_email(report, dated_json, git_sha, git_branch, args.environment)

    print(f"Wrote {latest_json.relative_to(REPO_ROOT)}")
    print(f"Wrote {dated_json.relative_to(REPO_ROOT)}")
    print(f"Subject: {subject}")

    if args.dry_run:
        print("Dry run: email not sent.")
        print(text)
    else:
        if not recipient:
            print("ERROR: CONTRACT_AUDIT_EMAIL or ADMIN_NOTIFY_EMAIL is required to send email.", file=sys.stderr)
            return 1
        try:
            if brevo_api_key:
                _send_brevo_email(
                    api_key=brevo_api_key,
                    recipient=recipient,
                    subject=subject,
                    text=text,
                    html_body=html_body,
                    report_path=dated_json,
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
                    report_path=dated_json,
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

    if contract_audits.should_fail(report, args.fail_on):
        print(f"Failing because findings at severity {args.fail_on!r} or higher are present.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
