#!/usr/bin/env python3
"""Render deterministic, privacy-bounded security operator email reports.

This module accepts already-normalized report dictionaries. Collection and
finding lifecycle decisions belong to ``security_reporting.py``.
"""

from __future__ import annotations

from html import escape
import re
from typing import Any


DETAIL_LIMIT = 20
TEXT_LIMIT = 160
SEVERITIES = ("critical", "high", "medium", "low", "unknown")
_GHSA = re.compile(r"^GHSA-[A-Za-z0-9-]+$")
_CVE = re.compile(r"^CVE-\d{4}-\d{4,}$")


def safe_advisory_link(advisory: object) -> str | None:
    """Build links only from known advisory identifiers, never source URLs."""
    value = str(advisory or "").strip()
    if _GHSA.fullmatch(value):
        return f"https://github.com/advisories/{value}"
    if _CVE.fullmatch(value):
        return f"https://nvd.nist.gov/vuln/detail/{value}"
    return None


def _text(value: object, limit: int = TEXT_LIMIT) -> str:
    return " ".join(str(value or "").split())[:limit] or "unknown"


def _findings(report: dict[str, Any], state: str) -> list[dict[str, Any]]:
    values = report.get(state, [])
    return [value for value in values if isinstance(value, dict)] if isinstance(values, list) else []


def _counts(findings: list[dict[str, Any]]) -> dict[str, int]:
    counts = {severity: 0 for severity in SEVERITIES}
    for finding in findings:
        severity = str(finding.get("severity", "unknown")).lower()
        counts[severity if severity in counts else "unknown"] += 1
    return counts


def _count_text(label: str, findings: list[dict[str, Any]]) -> str:
    counts = _counts(findings)
    detail = ", ".join(f"{severity} {counts[severity]}" for severity in SEVERITIES)
    return f"{label}: {detail} ({len(findings)} total)"


def _finding_text(finding: dict[str, Any]) -> str:
    package = _text(finding.get("package"))
    advisory = _text(finding.get("advisory"))
    severity = _text(finding.get("severity", "unknown")).lower()
    return f"- {severity}: {package} ({advisory})"


def _render_finding_html(finding: dict[str, Any]) -> str:
    advisory = _text(finding.get("advisory"))
    link = safe_advisory_link(advisory)
    advisory_html = f'<a href="{escape(link, quote=True)}">{escape(advisory)}</a>' if link else escape(advisory)
    return f"<li><strong>{escape(_text(finding.get('severity')).lower())}</strong>: {escape(_text(finding.get('package')))} ({advisory_html})</li>"


def _coverage_lines(coverage: object) -> list[str]:
    if not isinstance(coverage, dict):
        return ["Coverage: unavailable"]
    lines: list[str] = []
    for source in sorted(coverage):
        item = coverage[source] if isinstance(coverage[source], dict) else {}
        completed = item.get("completed", 0)
        expected = item.get("expected", 0)
        missing = item.get("missing", max(0, int(expected or 0) - int(completed or 0)))
        suffix = " coverage incomplete" if missing or completed != expected else ""
        lines.append(f"{_text(source)}: {completed}/{expected}{suffix}")
    return lines or ["Coverage: unavailable"]


def _source_lines(sources: object) -> list[str]:
    if not isinstance(sources, dict):
        return ["Sources: unavailable"]
    lines = []
    for source in sorted(sources):
        item = sources[source] if isinstance(sources[source], dict) else {}
        status = _text(item.get("status", "unavailable"))
        observed = item.get("observed_at")
        lines.append(f"{_text(source)}: {status}" + (f" ({_text(observed)})" if observed else ""))
    return lines or ["Sources: unavailable"]


def render_security_report(report: dict[str, Any], *, detail_limit: int = DETAIL_LIMIT) -> dict[str, str]:
    """Return subject, escaped HTML, and plain text for an explicit report dict."""
    if not isinstance(report, dict):
        raise ValueError("report must be a dictionary")
    if detail_limit < 0:
        raise ValueError("detail_limit must be non-negative")
    environment = _text(report.get("environment"))
    window_start = _text(report.get("window_start"))
    window_end = _text(report.get("window_end"))
    subject_commit = _text(report.get("subject_commit"))
    groups = [("new", "New"), ("open", "Open"), ("resolved", "Resolved")]
    findings = {key: _findings(report, key) for key, _ in groups}
    subject = f"[Security] {environment} digest: {len(findings['new'])} new, {len(findings['open'])} open"

    text_lines = [
        f"Security report for {environment}",
        f"Window: {window_start} to {window_end} (UTC)",
        f"Subject revision: {subject_commit}",
        "",
        *[_count_text(label, findings[key]) for key, label in groups],
        "",
        "Coverage:",
        *[f"- {line}" for line in _coverage_lines(report.get("coverage"))],
        "Latest structured sources:",
        *[f"- {line}" for line in _source_lines(report.get("sources"))],
    ]
    detail_remaining = detail_limit
    detail_html: list[str] = []
    for key, label in groups:
        shown = findings[key][:detail_remaining]
        detail_remaining -= len(shown)
        if shown:
            text_lines.extend(["", f"{label} findings:", *[_finding_text(finding) for finding in shown]])
            detail_html.append(f"<h3>{escape(label)} findings</h3><ul>{''.join(_render_finding_html(finding) for finding in shown)}</ul>")
        omitted = len(findings[key]) - len(shown)
        if omitted:
            text_lines.append(f"{omitted} additional {key} findings omitted; totals above remain complete.")
            detail_html.append(f"<p>{omitted} additional {escape(key)} findings omitted; totals above remain complete.</p>")
    if not findings["new"]:
        text_lines.extend(["", "No new findings were recorded in this window."])

    summary_html = "".join(f"<li>{escape(_count_text(label, findings[key]))}</li>" for key, label in groups)
    coverage_html = "".join(f"<li>{escape(line)}</li>" for line in _coverage_lines(report.get("coverage")))
    sources_html = "".join(f"<li>{escape(line)}</li>" for line in _source_lines(report.get("sources")))
    html = (
        "<!doctype html><html><body>"
        f"<h1>Security report: {escape(environment)}</h1>"
        f"<p>UTC window: {escape(window_start)} to {escape(window_end)}<br>Subject revision: {escape(subject_commit)}</p>"
        f"<h2>Finding totals</h2><ul>{summary_html}</ul>"
        f"<h2>Coverage</h2><ul>{coverage_html}</ul>"
        f"<h2>Latest structured sources</h2><ul>{sources_html}</ul>"
        f"{''.join(detail_html)}"
        "</body></html>"
    )
    return {"subject": subject, "text": "\n".join(text_lines), "html": html}
