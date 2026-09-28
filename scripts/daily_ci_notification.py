#!/usr/bin/env python3
"""Report a scheduled isolated-CI run from its manifest and source-bound receipts.

Cron calls this repeatedly. A blocked selection is reported immediately; queued
work is reported when terminal or at noon UTC. Each channel has a durable send
receipt so retrying one failed channel does not duplicate the other.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time
from types import SimpleNamespace
import urllib.parse
import urllib.error
import urllib.request


TERMINAL = {"success", "failure", "cancelled"}
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def canonical_root() -> Path:
    checkout = Path(__file__).resolve().parents[1]
    common = subprocess.check_output(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=checkout, text=True,
    ).strip()
    return Path(common).parent


def configured_value(root: Path, key: str) -> str:
    if os.environ.get(key):
        return os.environ[key]
    path = root / ".env"
    if path.is_file():
        for line in path.read_text().splitlines():
            name, separator, value = line.strip().partition("=")
            if separator and name.strip() == key:
                return value.strip().strip("'\"")
    return ""


def daily_manifest(root: Path, day: date) -> dict | None:
    found = []
    for path in (root / "test-results/daily-runs").glob("*.json"):
        try:
            data = json.loads(path.read_text())
            created = datetime.fromtimestamp(data["created"], timezone.utc).date()
            if data.get("run_date", created.isoformat()) == day.isoformat():
                found.append((data["created"], data))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return max(found, key=lambda item: item[0])[1] if found else None


def daily_jobs(root: Path, day: date, manifest: dict | None) -> list[dict]:
    database = root / "logs/ci-coordinator/queue.sqlite3"
    if not database.is_file():
        return []
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp()
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        if manifest is None:
            rows = connection.execute(
                "SELECT * FROM jobs WHERE owner='daily' AND created>=? AND created<? ORDER BY created",
                (start, start + 86400),
            )
        else:
            ids = manifest.get("jobs", [])
            if not ids:
                return []
            rows = connection.execute(
                f"SELECT * FROM jobs WHERE id IN ({','.join('?' for _ in ids)})",
                ids,
            )
        return [dict(row) for row in rows]


def validated_receipt(root: Path, job: dict) -> dict | None:
    path = root / "test-results/ci-runs" / job["id"] / "receipt.json"
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    if (data.get("id") != job["id"] or data.get("source_commit") != job["source"]
            or str(data.get("run_id")) != str(job["run_id"])):
        return None
    return data


def reconcile_receipts(root: Path, day: date, limit: int = 30) -> int:
    """Fetch a bounded number of terminal GitHub artifacts per cron tick."""
    jobs = daily_jobs(root, day, daily_manifest(root, day))
    pending = [job for job in jobs if job["mode"] != "prepare" and job["state"] in TERMINAL
               and job.get("run_id") and validated_receipt(root, job) is None]
    if not pending:
        return 0
    from scripts.ci_coordinator import GitHub, Queue
    from scripts.ci_results import fetch

    queue = Queue(root / "logs/ci-coordinator/queue.sqlite3")
    github = GitHub(root)
    fetched = 0
    for job in sorted(pending, key=lambda item: item["state"] != "failure")[:limit]:
        try:
            queue.result(github, job["id"], root, fetch)
            fetched += 1
        except Exception:
            # A missing or invalid artifact stays visible in the report. The
            # coordinator owns rate limiting; the next tick can try again.
            continue
    return fetched


def case_summaries(root: Path, job: dict, receipt: dict) -> list[dict]:
    """Read only fixed, validated-artifact report paths and recorded case counts."""
    directory = root / "test-results/ci-runs" / job["id"] / "test-results"
    summaries = []
    names = {
        "pytest": ("ci-pytest.json", "ci-unit-sdk.json"),
        "vitest": ("ci-unit-ui.json", "ci-unit-web_app.json"),
    }.get(job["mode"], ())
    for name in names:
        try:
            data = json.loads((directory / name).read_text())
        except (OSError, ValueError):
            continue
        if name.startswith("ci-unit-") and name != "ci-unit-sdk.json":
            summary = {
                "area": "frontend/packages/ui" if name == "ci-unit-ui.json" else "frontend/apps/web_app",
                "total": data.get("numTotalTests"), "passed": data.get("numPassedTests"),
                "failed": data.get("numFailedTests"), "skipped": data.get("numPendingTests"),
                "failed_suites": data.get("numFailedTestSuites"),
            }
        else:
            counts = data.get("summary", {})
            summary = {
                "area": "pytest" if name == "ci-pytest.json" else "python-sdk-accounts",
                "total": counts.get("total"), "passed": counts.get("passed"),
                "failed": counts.get("failed", 0), "skipped": counts.get("skipped", 0),
            }
        if all(type(summary[key]) is int for key in ("total", "passed", "failed", "skipped")):
            summaries.append(summary)
    if job["mode"] == "vitest":
        for name, area in (("ci-unit-cli.log", "cli-accounts"), ("ci-unit-cli-plans.log", "cli-plans")):
            try:
                content = (directory / name).read_text()
            except OSError:
                continue
            values = dict((key, int(value)) for key, value in re.findall(r"^ℹ (tests|pass|fail|skipped) (\d+)$", content, re.MULTILINE))
            if all(key in values for key in ("tests", "pass", "fail", "skipped")):
                summaries.append({
                    "area": area, "total": values["tests"], "passed": values["pass"],
                    "failed": values["fail"], "skipped": values["skipped"],
                })
    if job["mode"] in ("component", "e2e", "artifact", "selfhost"):
        for result in (receipt.get("report") or {}).get("results", []):
            stats = result.get("stats") or {}
            counts = [stats.get(key) for key in ("expected", "unexpected", "skipped", "flaky")]
            if all(type(value) is int for value in counts):
                summaries.append({
                    "area": result.get("spec", "browser"),
                    "total": sum(counts), "passed": counts[0],
                    "failed": counts[1], "skipped": counts[2], "flaky": counts[3],
                })
    return summaries


def selection_diagnostic(root: Path, source: str) -> str:
    if not source:
        return "No source-bound daily manifest was written."
    try:
        try:
            from scripts.ci_dispatch import select_specs
        except ModuleNotFoundError:
            from ci_dispatch import select_specs
        select_specs(root, SimpleNamespace(spec=[], daily=True), source)
    except RuntimeError as exc:
        if str(exc).startswith("Unclassified AI spec cannot enter scheduled discovery:"):
            return str(exc)
    except Exception:
        pass
    return "No source-bound daily manifest was written; inspect the 03:00 launcher log."


def build_report(root: Path, day: date, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    manifest = daily_manifest(root, day)
    jobs = daily_jobs(root, day, manifest)
    sources = {job["source"] for job in jobs}
    source = (manifest or {}).get("source_commit", "")
    if not source and len(sources) == 1:
        source = sources.pop()
    job_states = Counter(job["state"] for job in jobs)
    modes = Counter(job["mode"] for job in jobs)
    admitted_specs = set()
    for job in jobs:
        if job["mode"] in ("component", "e2e", "artifact", "selfhost"):
            try:
                admitted_specs.update(json.loads(job["specs"]))
            except (KeyError, ValueError, TypeError):
                pass
    failed_cases: list[str] = []
    failing_workspaces: list[str] = []
    failed_specs: list[str] = []
    case_counts: list[dict] = []
    missing_receipts = []
    run_links = []
    for job in jobs:
        if job.get("url"):
            run_links.append(job["url"])
        if job["state"] not in TERMINAL or job["mode"] == "prepare":
            continue
        receipt = validated_receipt(root, job)
        if receipt is None:
            missing_receipts.append(job["id"][:12])
            continue
        case_counts.extend(case_summaries(root, job, receipt))
        for result in (receipt.get("report") or {}).get("results", []):
            failed_cases.extend(result.get("failed_tests") or [])
            if result.get("exit_code", 0) != 0 and job["mode"] == "vitest":
                failing_workspaces.append(result.get("suite", "unknown"))
            if result.get("exit_code", 0) != 0 and result.get("spec"):
                failed_specs.append(result["spec"])
    error = (manifest or {}).get("selection_error", "") or (manifest or {}).get("coordinator_error", "")
    if not manifest and jobs:
        error = selection_diagnostic(root, source)
    if error or not manifest:
        status = "blocked"
    elif not jobs:
        status = "blocked"
    elif any(job["state"] not in TERMINAL for job in jobs):
        status = "incomplete"
    elif (job_states["failure"] or job_states["cancelled"] or missing_receipts
          or manifest.get("held_specs") or any(item["failed"] for item in case_counts)):
        status = "failed_or_held"
    else:
        status = "passed"
    files = Counter(name.split("::")[0].split("/")[-1] for name in failed_cases)
    ready = bool(error) or (
        manifest is not None and jobs and not missing_receipts
        and all(job["state"] in TERMINAL for job in jobs)
    )
    ready = ready or (day < now.date() or (day == now.date() and now.hour >= 12))
    return {
        "date": day.isoformat(), "status": status, "source_commit": source,
        "selection_error": error, "manifest_present": manifest is not None,
        "selected_specs": len(manifest.get("selected_specs", [])) if manifest and "selected_specs" in manifest else None,
        "admitted_specs": len(admitted_specs),
        "held_specs": len(manifest.get("held_specs", [])) if manifest else None,
        "job_count": len(jobs), "job_states": dict(job_states), "job_modes": dict(modes),
        "failed_case_count": len(failed_cases), "failed_case_files": files.most_common(12),
        "case_counts": case_counts,
        "known_total_tests": sum(item["total"] for item in case_counts),
        "known_failed_tests": sum(item["failed"] for item in case_counts),
        "known_passed_tests": sum(item["passed"] for item in case_counts),
        "known_skipped_tests": sum(item["skipped"] for item in case_counts),
        "failing_vitest_workspaces": sorted(set(failing_workspaces)),
        "failed_specs": sorted(set(failed_specs)),
        "missing_receipts": missing_receipts, "run_links": run_links[:4],
        "ready": ready,
    }


def format_report(report: dict) -> tuple[str, str]:
    title = f"OpenMates daily CI {report['date']}: {report['status'].upper()}"
    lines = [title, f"Source: {report['source_commit'] or 'unknown'}"]
    if report["selection_error"]:
        lines.append(f"Selection: {report['selection_error']}")
    if report["selected_specs"] is None:
        if report["manifest_present"]:
            lines.append(
                f"Browser selection count not retained; {report['admitted_specs']} specs admitted, "
                f"{report['held_specs']} held."
            )
        else:
            lines.append("Browser inventory: unknown; selection did not finish. No browser jobs were admitted.")
    else:
        lines.append(
            f"Browser specs selected: {report['selected_specs']}; "
            f"admitted: {report['admitted_specs']}; held: {report['held_specs']}."
        )
    lines.append(
        f"CI jobs: {report['job_count']} total; "
        + ", ".join(f"{key}={value}" for key, value in sorted(report["job_states"].items()))
    )
    lines.append(
        "Job areas: " + (", ".join(f"{key}={value}" for key, value in sorted(report["job_modes"].items())) or "none")
    )
    if report.get("case_counts"):
        lines.append(
            f"Counted cases: {report['known_total_tests']} total, "
            f"{report['known_passed_tests']} passed, {report['known_failed_tests']} failed, "
            f"{report['known_skipped_tests']} skipped."
        )
        lines.append("Failures by counted area: " + ", ".join(
            f"{item['area']} {item['failed']}/{item['total']}"
            for item in report["case_counts"] if item["failed"]
        ))
    else:
        lines.append("Individual case totals are unavailable until source-bound artifacts are retrieved.")
    pytest_failed = next(
        (item["failed"] for item in report.get("case_counts", []) if item["area"] == "pytest"),
        None,
    )
    if pytest_failed is not None and report["failed_case_count"] > pytest_failed:
        lines.append(
            f"Pytest also recorded {report['failed_case_count'] - pytest_failed} "
            "failure entry outside its counted cases (for example, a collection error)."
        )
    if report["failed_case_files"]:
        lines.append("Top failing pytest files: " + ", ".join(
            f"{name} ({count})" for name, count in report["failed_case_files"][:8]
        ))
    if report["failing_vitest_workspaces"]:
        lines.append("Failing Vitest workspaces: " + ", ".join(report["failing_vitest_workspaces"]))
    if report["failed_specs"]:
        lines.append("Failing browser specs: " + ", ".join(report["failed_specs"][:10]))
    if report["missing_receipts"]:
        lines.append(f"Terminal jobs without validated receipts: {len(report['missing_receipts'])}.")
    if report["run_links"]:
        lines.append("GitHub runs: " + " ".join(report["run_links"][:2]))
    if report["status"] != "passed":
        lines.append("Coverage is incomplete or failing; this run must not be read as green.")
    return title, "\n".join(lines)


def email_task_status(root: Path, task_id: str) -> dict:
    token = configured_value(root, "INTERNAL_API_SHARED_TOKEN")
    if not token:
        return {"status": "unconfigured"}
    url = f"http://localhost:8000/internal/test-summary-email-status/{task_id}"
    request = urllib.request.Request(url, headers={"X-Internal-Service-Token": token})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            result = json.load(response)
        if result.get("state") == "SUCCESS":
            return {"status": "provider_accepted" if result.get("provider_accepted") else "failed", "task_id": task_id}
        if result.get("state") in ("FAILURE", "REVOKED"):
            return {"status": "failed", "task_id": task_id, "task_state": result["state"]}
        return {"status": "queued_unconfirmed", "task_id": task_id, "task_state": result.get("state", "unknown")}
    except urllib.error.HTTPError as exc:
        return {"status": "queued_unconfirmed", "task_id": task_id, "http_status": exc.code}
    except Exception as exc:
        return {"status": "queued_unconfirmed", "task_id": task_id, "error_type": type(exc).__name__}


def deliver_email(root: Path, subject: str, body: str, report: dict) -> dict:
    recipient = configured_value(root, "ADMIN_NOTIFY_EMAIL")
    token = configured_value(root, "INTERNAL_API_SHARED_TOKEN")
    if not recipient or not token:
        return {"status": "unconfigured"}
    report_day = report["date"]
    # The existing internal task retrieves the current Brevo key from Vault.
    # The host's legacy BREVO_API_KEY can be stale (401) and is not authoritative.
    failed_jobs = report["job_states"].get("failure", 0)
    total_jobs = report["job_count"]
    payload = {
        "recipient_email": recipient, "environment": "development",
        "run_id": report_day, "git_sha": report["source_commit"] or "unknown",
        "git_branch": "dev", "duration_seconds": 0,
        "total": total_jobs, "passed": report["job_states"].get("success", 0),
        "failed": failed_jobs, "skipped": 0, "not_started": 0,
        "suites": [], "failed_tests": [], "all_tests": [],
        "subject_override": f"[OpenMates] {subject}",
        "summary_copy": {
            "header_failure": subject, "status_failure": report["status"].upper(),
            "intro_note": body, "item_label_plural": "CI jobs",
        },
        "failure_groups": ([{"title": "Nightly coverage and failures", "description": body}]
                           if report["status"] != "passed" else []),
    }
    request = urllib.request.Request(
        "http://localhost:8000/internal/dispatch-test-summary-email",
        data=json.dumps(payload).encode(), method="POST",
        headers={"X-Internal-Service-Token": token, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.load(response)
        task_id = result.get("task_id", "")
        if not task_id:
            return {"status": "failed", "reason": "missing_task_id"}
        for _ in range(15):
            checked = email_task_status(root, task_id)
            if checked["status"] != "queued_unconfirmed":
                return checked
            time.sleep(2)
        return checked
    except urllib.error.HTTPError as exc:
        return {"status": "failed", "http_status": exc.code}
    except Exception as exc:
        return {"status": "failed", "error_type": type(exc).__name__}


def deliver_discord(root: Path, subject: str, body: str) -> dict:
    webhook = configured_value(root, "DISCORD_WEBHOOK_DEV_NIGHTLY")
    if not webhook:
        return {"status": "unconfigured"}
    separator = "&" if "?" in webhook else "?"
    url = webhook + separator + urllib.parse.urlencode({"wait": "true"})
    payload = {
        "username": "OpenMates Server",
        "embeds": [{"title": subject, "description": body[:3900],
                    "color": 0x22C55E if "PASSED" in subject else 0xEF4444}],
    }
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "OpenMates-TestRunner/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.load(response)
        return {"status": "provider_accepted", "message_id": result.get("id", "")}
    except urllib.error.HTTPError as exc:
        return {"status": "failed", "http_status": exc.code}
    except Exception as exc:
        return {"status": "failed", "error_type": type(exc).__name__}


def send_report(root: Path, report: dict) -> dict:
    output = root / "test-results/daily-runs/notifications"
    output.mkdir(parents=True, exist_ok=True)
    state_path = output / f"{report['date']}.json"
    title, body = format_report(report)
    digest = hashlib.sha256(body.encode()).hexdigest()
    with (output / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            state = json.loads(state_path.read_text())
        except (OSError, ValueError):
            state = {"date": report["date"], "revisions": {}}
        current = state["revisions"].setdefault(digest, {})
        for channel, sender in (("email", deliver_email), ("discord", deliver_discord)):
            if current.get(channel, {}).get("status") == "provider_accepted":
                continue
            if channel == "email" and current.get(channel, {}).get("status") == "queued_unconfirmed":
                current[channel] = email_task_status(root, current[channel]["task_id"])
            else:
                current[channel] = (
                    sender(root, title, body, report) if channel == "email"
                    else sender(root, title, body)
                )
            temporary = state_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(state, indent=2) + "\n")
            temporary.replace(state_path)
        return {"report": report, "revision": digest[:12], "channels": current}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=canonical_root())
    parser.add_argument("--date", type=date.fromisoformat, default=datetime.now(timezone.utc).date())
    parser.add_argument("--send", action="store_true")
    parser.add_argument("--force", action="store_true", help="Send an incomplete historical run now")
    args = parser.parse_args()
    if args.send:
        reconcile_receipts(args.root, args.date)
    report = build_report(args.root, args.date)
    if not args.send or (not args.force and not report["ready"]):
        print(json.dumps(report))
        return 0
    result = send_report(args.root, report)
    print(json.dumps(result))
    return 0 if all(
        channel.get("status") == "provider_accepted"
        for channel in result["channels"].values()
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
