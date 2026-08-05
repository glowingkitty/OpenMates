#!/usr/bin/env python3
"""
Daily report-only stale-code runner for OpenMates.

Runs the deterministic detector, atomically writes local JSON and Markdown
evidence, and sends a redacted Discord summary. It never edits source or starts
an agent. Architecture: docs/specs/deterministic-stale-code-reporting/spec.yml.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
from typing import Callable
from urllib import request


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
REPORT_DIR = PROJECT_ROOT / "logs" / "nightly-reports"
CRON_BEGIN = "# BEGIN OpenMates deterministic stale-code report"
CRON_END = "# END OpenMates deterministic stale-code report"
CRON_SCHEDULE = "0 2 * * *"
DISCORD_ENV = "DISCORD_WEBHOOK_DEV_NIGHTLY"

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from find_dead_code import format_markdown_report, scan_repository  # noqa: E402


class AlreadyRunningError(RuntimeError):
    """Raised when another stale-code report process owns the output lock."""


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
    lock_path = output_dir / ".stale-code.lock"
    with lock_path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise AlreadyRunningError("A stale-code report is already running.") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def write_reports(
    report: dict,
    markdown: str,
    output_dir: Path,
    *,
    commit: str,
    notification_status: str = "pending",
) -> tuple[Path, Path]:
    envelope = deepcopy(report)
    envelope["job"] = "stale-code"
    envelope["ran_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    envelope["subject_commit"] = commit
    envelope["notification_status"] = notification_status
    json_path = output_dir / "stale-code.json"
    markdown_path = output_dir / "stale-code.md"
    _atomic_write(json_path, json.dumps(envelope, indent=2) + "\n")
    _atomic_write(markdown_path, markdown)
    return json_path, markdown_path


def _classification_totals(report: dict) -> tuple[int, int, int]:
    summary = report.get("summary", {})
    ready = sum(int(stats.get("deletion_ready", 0)) for stats in summary.values())
    review = sum(int(stats.get("review_only", 0)) for stats in summary.values())
    suppressed = sum(int(stats.get("suppressed", 0)) for stats in summary.values())
    return ready, review, suppressed


def build_discord_payload(report: dict, commit: str, report_path: Path) -> dict:
    ready, review, suppressed = _classification_totals(report)
    status = report.get("status", "error")
    color = 0x2E7D32 if status == "ok" and ready == 0 else 0xF9A825
    if status == "error":
        color = 0xC62828
    if "logs" in report_path.parts:
        report_display = Path(*report_path.parts[report_path.parts.index("logs") :]).as_posix()
    else:
        report_display = report_path.name
    description = (
        f"Status: **{status}**\n"
        f"Commit: `{commit[:12]}`\n"
        f"**{ready} deletion-ready**, {review} review-only, {suppressed} suppressed\n"
        f"Local report: `{report_display}`"
    )
    return {
        "username": "OpenMates stale-code audit",
        "embeds": [
            {
                "title": "Daily deterministic stale-code report",
                "description": description[:4000],
                "color": color,
            }
        ],
    }


def notify_discord(
    report: dict,
    commit: str,
    report_path: Path,
    webhook_url: str,
    *,
    opener: Callable = request.urlopen,
) -> str:
    if not webhook_url:
        return "skipped_missing_webhook"
    payload = build_discord_payload(report, commit, report_path)
    body = json.dumps(payload).encode("utf-8")
    discord_request = request.Request(
        webhook_url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "OpenMates-Stale-Code-Audit/1.0",
        },
        method="POST",
    )
    try:
        with opener(discord_request, timeout=15) as response:
            status = getattr(response, "status", 204)
            if 200 <= status < 300:
                return "sent"
            return f"failed:http_{status}"
    except Exception as exc:
        return f"failed:{type(exc).__name__}"


def _remove_managed_block(lines: list[str]) -> list[str]:
    kept: list[str] = []
    in_block = False
    for line in lines:
        if line.strip() == CRON_BEGIN:
            if in_block:
                raise ValueError("Malformed managed cron block: nested begin marker.")
            in_block = True
            continue
        if line.strip() == CRON_END:
            if not in_block:
                raise ValueError("Malformed managed cron block: end marker without begin marker.")
            in_block = False
            continue
        legacy_disabled = line.lstrip().startswith("#DISABLED") and "nightly-dead-code-removal.sh" in line
        if in_block or legacy_disabled:
            continue
        kept.append(line)
    if in_block:
        raise ValueError("Malformed managed cron block: missing end marker.")
    return kept


def render_crontab(existing: str, project_root: Path) -> str:
    lines = _remove_managed_block(existing.splitlines())
    while lines and not lines[-1].strip():
        lines.pop()
    root = shlex.quote(str(project_root))
    runner = shlex.quote(str(project_root / "scripts" / "stale_code_daily.py"))
    log_path = shlex.quote(str(project_root / "logs" / "stale-code-daily.log"))
    command = f"{CRON_SCHEDULE} cd {root} && python3 {runner} >> {log_path} 2>&1"
    lines.extend(
        [
            "",
            CRON_BEGIN,
            "# Daily at 02:00 UTC. Report and Discord notification only; never edits source.",
            command,
            CRON_END,
        ]
    )
    return "\n".join(lines) + "\n"


def install_cron(project_root: Path) -> None:
    (project_root / "logs").mkdir(parents=True, exist_ok=True)
    current = subprocess.run(["crontab", "-l"], capture_output=True, text=True, check=False)
    if current.returncode not in (0, 1):
        raise RuntimeError(f"crontab -l failed: {current.stderr.strip()}")
    rendered = render_crontab(current.stdout, project_root)
    result = subprocess.run(["crontab", "-"], input=rendered, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"crontab installation failed: {result.stderr.strip()}")


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


def _git_commit(root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def _dotenv_value(root: Path, key: str) -> str:
    if os.environ.get(key):
        return os.environ[key]
    env_path = root / ".env"
    if not env_path.exists():
        return ""
    prefix = f"{key}="
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :].strip().strip("\"'")
    return ""


def run_daily(root: Path, output_dir: Path, limit: int, *, dry_run_notify: bool) -> int:
    with run_lock(output_dir):
        commit = _git_commit(root)
        try:
            report_object = scan_repository(root, limit=limit)
            report = report_object.to_dict()
            markdown = format_markdown_report(report_object)
        except Exception as exc:
            error_name = type(exc).__name__
            report = {
                "status": "error",
                "total_found": 0,
                "summary": {},
                "errors": [f"Detector failed: {error_name}"],
                "analyzers": {},
                "items": [],
            }
            markdown = (
                "# Deterministic Stale Code Report\n\n"
                "Status: **error**\n\n"
                f"Detector failed: `{error_name}`. See the gitignored cron log for diagnostics.\n"
            )
            print(f"[stale-code] detector failed: {error_name}: {exc}", file=sys.stderr)
        json_path, _markdown_path = write_reports(report, markdown, output_dir, commit=commit)
        if dry_run_notify:
            print(json.dumps(build_discord_payload(report, commit, json_path), indent=2))
            notification_status = "dry_run"
        else:
            notification_status = notify_discord(
                report,
                commit,
                json_path,
                _dotenv_value(root, DISCORD_ENV),
            )
        write_reports(
            report,
            markdown,
            output_dir,
            commit=commit,
            notification_status=notification_status,
        )
        print(
            f"[stale-code] report={json_path} status={report['status']} notification={notification_status}",
            file=sys.stderr,
        )
        return 1 if report.get("status") == "error" else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the report-only OpenMates stale-code audit")
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--output-dir", type=Path, default=REPORT_DIR)
    parser.add_argument("--limit", type=int, default=100, help="Maximum findings per detector class")
    parser.add_argument("--dry-run-notify", action="store_true", help="Print the Discord payload without sending")
    parser.add_argument("--install-cron", action="store_true", help="Idempotently install the daily user cron entry")
    args = parser.parse_args()
    if args.install_cron:
        install_root = canonical_checkout_root(args.root)
        install_cron(install_root)
        print(f"[stale-code] installed daily cron for {install_root}")
        return 0
    try:
        return run_daily(args.root.resolve(), args.output_dir.resolve(), args.limit, dry_run_notify=args.dry_run_notify)
    except AlreadyRunningError as exc:
        print(f"[stale-code] skipped: {exc}", file=sys.stderr)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
