#!/usr/bin/env python3
"""Run manual GPT-5.6 Luna research over recent local OpenCode chats.

The runner reads bounded local transcript evidence, dispatches one read-only
OpenCode research session, atomically publishes gitignored reports, and can send
an optional Discord attachment. It is intentionally manual/on-demand; historical
cron installation is retired so unattended analysis does not create report noise.
Architecture: docs/specs/opencode-chat-improvement-review/spec.yml.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any, Callable


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
REPORT_DIR = PROJECT_ROOT / "logs" / "nightly-reports" / "opencode-improvements"
PROMPT_TEMPLATE = SCRIPT_DIR / "prompts" / "opencode-improvement-research.md"
MODEL = "openai/gpt-5.6-luna"
DISCORD_ENV = "DISCORD_WEBHOOK_DEV_NIGHTLY"
CRON_BEGIN = "# BEGIN OpenMates OpenCode improvement research"
CRON_END = "# END OpenMates OpenCode improvement research"
ALLOWED_PRIORITIES = {"high", "medium", "low"}
MAX_SUMMARY_CHARS = 4_000
MAX_RECOMMENDATION_TEXT_CHARS = 4_000
MAX_RECOMMENDATION_LIST_ITEMS = 20

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _opencode_utils import run_opencode_session  # noqa: E402
from _workflow_review_helper import collect_transcript_evidence  # noqa: E402
from discord_webhook import post_attachment  # noqa: E402
from _nightly_report import write_nightly_report  # noqa: E402
from spec_demo import redact_text_with_canonical_scanner  # noqa: E402


@dataclass(frozen=True)
class ReportPaths:
    json_latest: Path
    markdown_latest: Path
    json_dated: Path
    markdown_dated: Path


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    os.replace(temporary, path)


@contextmanager
def run_lock(output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / ".review.lock").open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("OpenCode improvement research is already running") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _report_stamp(report: dict[str, Any]) -> str:
    period_end = str((report.get("period") or {}).get("end") or "")
    try:
        parsed = datetime.fromisoformat(period_end.replace("Z", "+00:00"))
    except ValueError:
        parsed = datetime.now(timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def write_reports(report: dict[str, Any], markdown: str, output_dir: Path) -> ReportPaths:
    stamp = _report_stamp(report)
    paths = ReportPaths(
        json_latest=output_dir / "latest.json",
        markdown_latest=output_dir / "latest.md",
        json_dated=output_dir / f"{stamp}.json",
        markdown_dated=output_dir / f"{stamp}.md",
    )
    report = dict(report)
    report["artifact_generation"] = stamp
    report["markdown_sha256"] = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
    encoded = json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    _atomic_write(paths.markdown_dated, markdown)
    _atomic_write(paths.json_dated, encoded)
    _atomic_write(paths.markdown_latest, markdown)
    _atomic_write(paths.json_latest, encoded)
    return paths


def _priority_counts(report: dict[str, Any]) -> str:
    counts: dict[str, int] = {}
    for recommendation in report.get("recommendations") or []:
        priority = str(recommendation.get("priority") or "unspecified")
        counts[priority] = counts.get(priority, 0) + 1
    return ", ".join(f"{count} {priority}" for priority, count in sorted(counts.items())) or "none"


def build_discord_payload(report: dict[str, Any]) -> dict[str, str]:
    counts = report.get("source_counts") or {}
    content = (
        "**OpenCode improvement research**\n"
        f"Status: `{report.get('status', 'unknown')}`\n"
        f"Model: `{report.get('model', MODEL)}`\n"
        f"Evidence: {counts.get('sessions', 0)} sessions, {counts.get('parts', 0)} parts\n"
        f"Recommendations: {_priority_counts(report)}\n"
        "The attached gitignored report contains the researched evidence and proposed changes. "
        "Implementation remains user-triggered."
    )
    return {"content": content[:1900]}


def notify_discord(
    report: dict[str, Any],
    markdown_path: Path,
    webhook_url: str,
    *,
    attachment_sender: Callable[..., dict[str, str] | None] = post_attachment,
    text_sanitizer: Callable[[str], str] | None = None,
) -> str:
    if not webhook_url:
        return "skipped_missing_webhook"
    try:
        markdown = markdown_path.read_text(encoding="utf-8")
        sanitizer = text_sanitizer or (lambda text: redact_text_with_canonical_scanner(text)["text"])
        sanitized = sanitizer(markdown)
        payload = build_discord_payload(report)
        payload["content"] = sanitizer(payload["content"])
        result = attachment_sender(
            webhook_url=webhook_url,
            payload=payload,
            content=sanitized.encode("utf-8"),
            filename=markdown_path.name,
        )
    except Exception as exc:
        return f"failed:{type(exc).__name__}"
    return "sent" if result else "failed"


def _dotenv_value(root: Path, key: str) -> str:
    if os.environ.get(key):
        return os.environ[key]
    env_path = root / ".env"
    if not env_path.is_file():
        return ""
    prefix = f"{key}="
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :].strip().strip("\"'")
    return ""


def _git_commit(root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def root_from_common_git_dir(common_dir: Path, fallback: Path) -> Path:
    resolved = common_dir.resolve()
    return resolved.parent if resolved.name == ".git" else fallback.resolve()


def canonical_checkout_root(fallback: Path) -> Path:
    result = subprocess.run(
        ["git", "-C", str(fallback), "rev-parse", "--path-format=absolute", "--git-common-dir"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return fallback.resolve()
    return root_from_common_git_dir(Path(result.stdout.strip()), fallback)


def _validate_recommendations(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    recommendations = []
    allowed_categories = {"skill", "hook", "agent", "instruction", "deterministic_guard", "no_change"}
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            continue
        category = str(item.get("category") or "no_change")
        if category not in allowed_categories:
            category = "no_change"
        priority = str(item.get("priority") or "low").casefold()
        normalized = {
            "id": _bounded_string(item.get("id") or f"REC-{index}", 50),
            "category": category,
            "priority": priority if priority in ALLOWED_PRIORITIES else "low",
            "title": _bounded_string(item.get("title") or "Untitled recommendation", 200),
        }
        normalized.update(
            {
                field: _bounded_string(item.get(field) or "", MAX_RECOMMENDATION_TEXT_CHARS)
                for field in ("evidence", "current_behavior", "proposed_change", "expected_benefit", "risk")
            }
        )
        normalized.update(
            {
                field: _bounded_string_list(item.get(field), max_chars=500)
                for field in ("target_files", "research_sources", "verification")
            }
        )
        recommendations.append(normalized)
    return recommendations[:10]


def _bounded_string(value: Any, max_chars: int) -> str:
    text = str(value)
    return text if len(text) <= max_chars else text[:max_chars] + "...[truncated]"


def _bounded_string_list(value: Any, *, max_chars: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_bounded_string(item, max_chars) for item in value[:MAX_RECOMMENDATION_LIST_ITEMS]]


def _render_markdown(report: dict[str, Any]) -> str:
    period = report.get("period") or {}
    lines = [
        "# OpenCode Improvement Research",
        "",
        f"- Status: `{report.get('status', 'unknown')}`",
        f"- Period: `{period.get('start', '')}` to `{period.get('end', '')}`",
        f"- Model: `{report.get('model', MODEL)}`",
        f"- Subject commit: `{report.get('subject_commit', 'unknown')}`",
        f"- Analysis session: `{report.get('analysis_session_id') or 'none'}`",
        "",
    ]
    summary = str(report.get("summary") or "No analysis summary was produced.")
    lines.extend(["## Summary", "", summary, "", "## Recommendations", ""])
    recommendations = report.get("recommendations") or []
    if not recommendations:
        lines.append("No actionable recommendations were produced.")
    for recommendation in recommendations:
        lines.extend(
            [
                f"### {recommendation.get('id')}: {recommendation.get('title')}",
                "",
                f"- Priority: `{recommendation.get('priority', 'low')}`",
                f"- Category: `{recommendation.get('category', 'no_change')}`",
                f"- Target files: {', '.join(map(str, recommendation.get('target_files') or [])) or 'none'}",
                "",
                str(recommendation.get("evidence") or "No evidence supplied."),
                "",
                f"**Proposed change:** {recommendation.get('proposed_change') or 'No change proposed.'}",
                "",
                f"**Expected benefit:** {recommendation.get('expected_benefit') or 'Not specified.'}",
                "",
                f"**Risk:** {recommendation.get('risk') or 'Not specified.'}",
                "",
                f"**Verification:** {', '.join(map(str, recommendation.get('verification') or [])) or 'Not specified.'}",
                "",
            ]
        )
    if report.get("error"):
        lines.extend(["## Error", "", f"`{report['error']}`", ""])
    return "\n".join(lines).rstrip() + "\n"


def _parse_analysis_output(path: Path) -> dict[str, Any]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    candidates: list[str] = []
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        part = event.get("part") if isinstance(event, dict) else None
        if event.get("type") != "text" or not isinstance(part, dict):
            continue
        text = part.get("text")
        if isinstance(text, str):
            candidates.append(text.strip())
    for candidate in reversed(candidates):
        if candidate.startswith("```"):
            candidate = candidate.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}


def run_review(
    root: Path,
    output_dir: Path,
    *,
    hours: int,
    dry_run_notify: bool,
    excluded_session_ids: set[str] | None = None,
) -> tuple[int, ReportPaths]:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    period_start = now - timedelta(hours=hours)
    start_iso = period_start.strftime("%Y-%m-%dT%H:%M:%SZ")
    end_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    commit = _git_commit(root)
    with run_lock(output_dir):
        evidence = collect_transcript_evidence(
            start_iso,
            end_iso,
            project_directory=canonical_checkout_root(root),
            exclude_session_ids=excluded_session_ids,
        )
        raw_output_path = root / "scripts" / ".tmp" / f"opencode-improvement-output-{os.getpid()}.jsonl"
        template = PROMPT_TEMPLATE.read_text(encoding="utf-8")
        prompt = (
            template.replace("{{PERIOD_START}}", start_iso)
            .replace("{{PERIOD_END}}", end_iso)
            .replace("{{SUBJECT_COMMIT}}", commit)
            .replace("{{TRANSCRIPT_EVIDENCE}}", json.dumps(evidence, ensure_ascii=False, indent=2))
        )
        returncode = 0
        session_id = None
        try:
            if evidence.get("session_count", 0):
                returncode, session_id = run_opencode_session(
                    prompt=prompt,
                    session_title=f"opencode improvement research {end_iso[:10]}",
                    project_root=str(root),
                    log_prefix="[opencode-improvements]",
                    agent="cron-research",
                    timeout=1800,
                    model=MODEL,
                    context_summary=f"Analyze {evidence['session_count']} OpenCode sessions from the previous {hours} hours.",
                    capture_output_path=raw_output_path,
                )
            draft = _parse_analysis_output(raw_output_path)
        finally:
            raw_output_path.unlink(missing_ok=True)

        status = "ok"
        error = ""
        if evidence.get("status") != "ok":
            status = "collection_failed"
            error = str(evidence.get("error") or "OpenCode transcript collection failed")
        elif not evidence.get("session_count"):
            status = "no_sessions"
        elif returncode == 124:
            status = "analysis_timeout"
            error = "GPT-5.6 Luna analysis timed out"
        elif returncode != 0:
            status = "analysis_failed"
            error = f"GPT-5.6 Luna analysis exited with code {returncode}"
        elif not draft:
            status = "analysis_failed"
            error = "GPT-5.6 Luna did not return a valid JSON analysis"

        report = {
            "schema_version": 1,
            "status": status,
            "period": {"start": start_iso, "end": end_iso, "hours": hours},
            "subject_commit": commit,
            "model": MODEL,
            "analysis_session_id": session_id,
            "source_counts": {
                "sessions": int(evidence.get("session_count", 0)),
                "messages": int(evidence.get("message_count", 0)),
                "parts": int(evidence.get("part_count", 0)),
            },
            "collection_limits": evidence.get("limits") or {},
            "collection_truncated": evidence.get("truncated") or {},
            "summary": _bounded_string(draft.get("summary") or "", MAX_SUMMARY_CHARS),
            "recommendations": _validate_recommendations(draft.get("recommendations")),
            "error": error or None,
            "notification_status": "pending",
        }
        markdown = _render_markdown(report)
        paths = write_reports(report, markdown, output_dir)
        if dry_run_notify:
            print(json.dumps(build_discord_payload(report), indent=2))
            notification_status = "dry_run"
        else:
            notification_status = notify_discord(
                report,
                paths.markdown_latest,
                _dotenv_value(root, DISCORD_ENV),
            )
        report["notification_status"] = notification_status
        paths = write_reports(report, _render_markdown(report), output_dir)
        write_nightly_report(
            job="opencode-improvements",
            status="ok" if status in {"ok", "no_sessions"} else "error",
            summary=(
                f"OpenCode improvement research {status}: "
                f"{len(report['recommendations'])} recommendation(s) from "
                f"{report['source_counts']['sessions']} session(s)."
            ),
            details={
                "period": report["period"],
                "model": MODEL,
                "analysis_session_id": session_id,
                "recommendation_count": len(report["recommendations"]),
                "notification_status": notification_status,
                "report_path": "logs/nightly-reports/opencode-improvements/latest.json",
            },
        )
        return (0 if status in {"ok", "no_sessions"} else 1), paths


def _remove_managed_block(lines: list[str]) -> list[str]:
    kept: list[str] = []
    inside = False
    for line in lines:
        if line.strip() == CRON_BEGIN:
            if inside:
                raise ValueError("Malformed managed cron block: nested begin marker")
            inside = True
            continue
        if line.strip() == CRON_END:
            if not inside:
                raise ValueError("Malformed managed cron block: end marker without begin marker")
            inside = False
            continue
        if not inside:
            kept.append(line)
    if inside:
        raise ValueError("Malformed managed cron block: missing end marker")
    return kept


def render_crontab(existing: str, project_root: Path) -> str:
    del project_root
    lines = _remove_managed_block(existing.splitlines())
    while lines and not lines[-1].strip():
        lines.pop()
    return "" if not lines else "\n".join(lines) + "\n"


def install_cron(project_root: Path) -> None:
    del project_root
    raise RuntimeError(
        "Automated OpenCode improvement research is retired; use the "
        "opencode-workflow-review skill or run this script manually."
    )


def uninstall_cron(project_root: Path) -> None:
    (project_root / "logs").mkdir(parents=True, exist_ok=True)
    current = subprocess.run(["crontab", "-l"], capture_output=True, text=True, check=False)
    if current.returncode not in (0, 1):
        raise RuntimeError(f"crontab -l failed: {current.stderr.strip()}")
    rendered = render_crontab(current.stdout, project_root)
    result = subprocess.run(["crontab", "-"], input=rendered, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"crontab installation failed: {result.stderr.strip()}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Manually research improvements from recent local OpenCode chats")
    parser.add_argument("--hours", type=int, default=168)
    parser.add_argument("--output-dir", type=Path, default=REPORT_DIR)
    parser.add_argument("--exclude-session", action="append", default=[])
    parser.add_argument("--dry-run-notify", action="store_true")
    parser.add_argument("--install-cron", action="store_true", help="Deprecated; automated analysis is retired.")
    parser.add_argument("--uninstall-cron", action="store_true", help="Remove the retired managed cron block.")
    args = parser.parse_args()
    if args.hours <= 0 or args.hours > 168:
        parser.error("--hours must be between 1 and 168")
    if args.install_cron:
        print(
            "[opencode-improvements] automated cron installation is retired; "
            "use --uninstall-cron to remove the old managed block or run the "
            "opencode-workflow-review skill manually.",
            file=sys.stderr,
        )
        return 1
    if args.uninstall_cron:
        install_root = canonical_checkout_root(PROJECT_ROOT)
        uninstall_cron(install_root)
        print(f"[opencode-improvements] removed managed cron block for {install_root}")
        return 0
    returncode, paths = run_review(
        PROJECT_ROOT,
        args.output_dir.resolve(),
        hours=args.hours,
        dry_run_notify=args.dry_run_notify,
        excluded_session_ids=set(args.exclude_session),
    )
    print(f"[opencode-improvements] report={paths.json_latest}")
    return returncode


if __name__ == "__main__":
    raise SystemExit(main())
