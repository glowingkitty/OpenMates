"""Daily meeting records and read-only inputs from Tasks, Git and CI receipts.

Calendar windows use the user's explicit timezone. Agent chat history is not
collected here; previous work is reviewed through OpenMates Tasks, commits and
recorded meeting decisions. CI batch states never masquerade as individual test
counts. Reruns retain source and suite identity. The meeting thread is the
coordinating chat's UUID (a Claude Code session ID), stored as a plain ID.
See .claude/skills/daily-meeting-and-orchestration/SKILL.md.
"""

from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import subprocess
import uuid
from zoneinfo import ZoneInfo

try:
    from scripts.agent_identity import agent_thread_id
except ModuleNotFoundError:
    from agent_identity import agent_thread_id

def commits(root, day, timezone_name):
    if not day:
        return []
    start = datetime.fromisoformat(day).replace(tzinfo=ZoneInfo(timezone_name))
    output = subprocess.check_output(
        [
            "git",
            "log",
            "dev",
            f"--since={start.isoformat()}",
            f"--until={(start + timedelta(days=1)).isoformat()}",
            "--format=%H%x09%cI%x09%s",
        ],
        cwd=root,
        text=True,
    )
    return [
        dict(zip(("commit", "time", "subject"), line.split("\t", 2)))
        for line in output.splitlines()
    ]


def read_jobs(root, since, until, owner="daily"):
    path = root / "logs/ci-coordinator/queue.sqlite3"
    if not path.exists():
        return [], "CI queue missing"
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        return [
            dict(r)
            for r in db.execute(
                "SELECT * FROM jobs WHERE owner=? AND created>=? AND created<? ORDER BY created",
                (owner, since, until),
            )
        ], None


def case_counts(directory, job):
    """Actual reporter counts only; missing reports remain unknown, never zero-green."""
    totals = Counter()
    found = False
    receipt = directory / "receipt.json"
    if not receipt.exists():
        return None
    identity = json.loads(receipt.read_text())
    if identity.get("source_commit") != job["source"] or str(
        identity.get("run_id")
    ) != str(job["run_id"]):
        return None
    if job["mode"] in ("e2e", "artifact", "selfhost"):
        for result in (identity.get("report") or {}).get("results", []):
            stats = result.get("stats")
            if stats is None:
                return None
            found = True
            totals.update(
                passed=stats.get("expected", 0),
                failed=stats.get("unexpected", 0),
                flaky=stats.get("flaky", 0),
                skipped=stats.get("skipped", 0),
            )
    else:
        for pattern in ("ci-pytest.json", "ci-unit-*.json"):
            for file in directory.rglob(pattern):
                report = json.loads(file.read_text())
                summary = report.get("summary")
                if summary is not None:
                    found = True
                    totals.update(
                        {
                            k: summary.get(k, 0)
                            for k in ("passed", "failed", "skipped", "error")
                        }
                    )
                elif "numTotalTests" in report:
                    found = True
                    totals.update(
                        passed=report.get("numPassedTests", 0),
                        failed=report.get("numFailedTests", 0),
                        skipped=report.get("numPendingTests", 0),
                    )
    if not found:
        return None
    totals["executed"] = (
        totals["passed"] + totals["failed"] + totals["flaky"] + totals["error"]
    )
    totals["discovered"] = totals["executed"] + totals["skipped"]
    return dict(totals)


def nightly_snapshot(root, since, until):
    jobs, error = read_jobs(root, since, until)
    groups = {}
    for job in jobs:
        group = groups.setdefault(
            job["source"],
            {
                "source_commit": job["source"],
                "batches": Counter(),
                "latest": {},
                "attempts": 0,
                "runs": [],
            },
        )
        group["batches"][job["state"]] += 1
        group["attempts"] += 1
        specs = json.loads(job["specs"])
        # Batch identity includes exact spec set/profile; partially overlapping batches
        # are reported per-spec below and never silently summed as unique test coverage.
        key = json.dumps([job["mode"], sorted(specs), job.get("proof_profile", "")])
        group["latest"][key] = job
        group["runs"].append(
            {
                "id": job["id"],
                "run_id": job["run_id"],
                "url": job.get("url"),
                "state": job["state"],
            }
        )
    output = []
    for group in groups.values():
        latest = list(group.pop("latest").values())
        selected = set()
        overlaps = False
        for job in latest:
            keys = {
                (job["mode"], s, job.get("proof_profile", ""))
                for s in json.loads(job["specs"])
            }
            overlaps |= bool(keys & selected)
            selected |= keys
        files = subprocess.check_output(
            [
                "git",
                "ls-tree",
                "-r",
                "--name-only",
                group["source_commit"],
                "--",
                "frontend/apps/web_app/tests",
            ],
            cwd=root,
            text=True,
        ).splitlines()
        expected = sum(f.endswith(".spec.ts") for f in files)
        counts = [
            case_counts(root / "test-results/ci-runs" / j["id"], j) for j in latest
        ]
        total = Counter()
        for count in counts:
            if count:
                total.update(count)
        output.append(
            {
                **group,
                "expected_browser_and_cli_specs": expected,
                "selected_unique_specs": len({s for _, s, _ in selected}),
                "case_counts": dict(total)
                if all(c is not None for c in counts) and not overlaps
                else None,
                "available_partial_case_counts": dict(total) if not overlaps else None,
                "suites": [
                    {
                        "mode": j["mode"],
                        "specs": json.loads(j["specs"]),
                        "profile": j.get("proof_profile", ""),
                        "run_id": j["run_id"],
                        "state": j["state"],
                        "case_counts": c,
                    }
                    for j, c in zip(latest, counts)
                ],
                "case_inventory": "reporter-discovered only; full parameterized inventory unknown",
                "coverage": "incomplete"
                if overlaps or any(c is None for c in counts)
                else "reported_selected_cases",
                "overlapping_reruns": overlaps,
                "rerun_batches": group["attempts"] - len(latest),
                "unfinished_batches": sum(
                    j["state"] not in {"success", "failure", "cancelled"}
                    for j in latest
                ),
            }
        )
    manifests = []
    for path in (root / "test-results/daily-runs").glob("*.json"):
        item = json.loads(path.read_text())
        if since <= item.get("created", 0) < until:
            manifests.append(item)
    return {
        "window_start": since,
        "window_end": until,
        "sources": output,
        "daily_manifests": manifests,
        "error": error,
        "status": "not_started_or_unrecorded" if not jobs else "recorded",
        "notifications": "No delivery receipt recorded; do not assume email or Discord was sent",
        "priority_rule": "Investigate suspected signup, billing or basic-chat failures today; rank other causes against approved goals.",
    }


def meeting_path(root, day):
    if datetime.fromisoformat(day).date().isoformat() != day:
        raise ValueError("Meeting date must be YYYY-MM-DD")
    return root / "logs/daily-meetings" / (day + ".json")


def load_meeting(root, day, thread):
    path = meeting_path(root, day)
    return (
        json.loads(path.read_text()).get("meetings", {}).get(thread, {})
        if path.exists()
        else {}
    )


def save_meeting_step(root, day, thread, step, text, message_id, timezone_name):
    """Private dated text records: intent and approval remain distinct."""
    uuid.UUID(thread)
    ZoneInfo(timezone_name)
    if not text.strip() or len(text) > 12000:
        raise ValueError("Meeting text must contain 1–12000 characters")
    if step in {"priorities", "answer", "approve"} and not message_id:
        raise ValueError("Record the actual human reply message ID")
    try:
        from scripts.agent_state import transaction
    except ModuleNotFoundError:
        from agent_state import transaction
    with transaction(meeting_path(root, day)) as archive:
        record = archive.setdefault("meetings", {}).setdefault(thread, {})
        if step == "priorities":
            if record.get("priorities_message_id") == message_id:
                return record
            if record:
                archive.setdefault("revisions", []).append({"thread": thread, **record})
            record.clear()
            record.update(
                priorities=text,
                priorities_message_id=message_id,
                answers=[],
                phase="research",
                timezone=timezone_name,
                date=day,
                meeting_thread=thread,
            )
        elif not record.get("priorities"):
            raise ValueError(
                "Ask for today's priorities before research or clarification"
            )
        elif step == "answer":
            if any(a["message_id"] == message_id for a in record["answers"]):
                return record
            record["answers"].append({"message_id": message_id, "text": text})
            record["phase"] = "clarifying"
        elif step == "proposal":
            record.update(proposal=text, phase="proposed")
            record.pop("approval", None)
        elif step == "approve":
            if record.get("phase") != "proposed":
                raise ValueError("Present the proposal before recording approval")
            record.update(
                approval={"message_id": message_id, "text": text}, phase="approved"
            )
        else:
            raise ValueError("Unknown meeting step")
        record["updated_at"] = datetime.now(timezone.utc).isoformat()
    return record


def previous_priorities(root, day):
    yesterday = (datetime.fromisoformat(day) - timedelta(days=1)).date().isoformat()

    def read(date):
        path = meeting_path(root, date)
        return json.loads(path.read_text()) if path.exists() else None

    previous = read(yesterday)
    latest = None
    for age in range(1, 31):
        date = (datetime.fromisoformat(day) - timedelta(days=age)).date().isoformat()
        value = read(date)
        if value:
            latest = {"date": date, "record": value}
            break
    # Preserve pre-migration meeting decisions as explicitly dated legacy evidence.
    legacy_path = root / "scripts/.daily-meeting-state.json"
    legacy = json.loads(legacy_path.read_text()) if legacy_path.exists() else None
    return {
        "calendar_yesterday": previous,
        "last_recorded_day": latest,
        "legacy_state": legacy,
        "status": "recorded" if previous else "no_record_for_yesterday",
    }


def openmates_tasks(root, reader=None):
    if reader is None:
        try:
            from scripts.openmates_task_reader import cli as reader
        except ModuleNotFoundError:
            from openmates_task_reader import cli as reader
    tasks, errors = {}, []
    for status in (None,):
        try:
            result = reader(root, ["list"])
            if result.get("complete") is not True:
                raise ValueError("Global CLI lacks complete task discovery; update it before collecting tasks")
            rows = result["tasks"]
            if not isinstance(rows, list):
                raise ValueError("Invalid CLI task response")
            for task in rows:
                tasks[task["task_id"]] = {
                    k: task.get(k)
                    for k in (
                        "task_id",
                        "short_id",
                        "title",
                        "description",
                        "status",
                        "priority",
                        "due_at",
                        "blocked_reason_code",
                        "latest_instruction",
                        "external_chat",
                    )
                }
        except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as exc:
            # RuntimeError covers CLI failures and shared-cooldown deferrals.
            errors.append({"status": status, "error": type(exc).__name__})
    return {
        "tasks": list(tasks.values()),
        "errors": errors,
        "coverage": "incomplete"
        if errors
        else "complete CLI snapshot",
        "activity_instruction": "Read relevant tasks' activities with the CLI before prioritization; list data is not their full history.",
    }


def collect(root, now, timezone_name, meeting=None):
    if not meeting or not meeting.get("priorities"):
        raise ValueError(
            "Ask and record today's priorities before collecting research inputs"
        )
    midnight = now.astimezone(ZoneInfo(timezone_name)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    yesterday = (midnight - timedelta(days=1)).date().isoformat()
    return {
        "collected_at": now.isoformat(),
        "meeting": meeting,
        "previous_priorities": previous_priorities(root, midnight.date().isoformat()),
        "openmates_tasks": openmates_tasks(root),
        "review_day": yesterday,
        "commits": commits(root, yesterday, timezone_name),
        "today_commits": commits(root, midnight.date().isoformat(), timezone_name),
        "nightly": nightly_snapshot(
            root, (midnight - timedelta(days=1)).timestamp(), now.timestamp()
        ),
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--timezone", required=True)
    p.add_argument(
        "--meeting-thread",
        default=agent_thread_id(),
        help="UUID of the coordinating chat; defaults to CLAUDE_CODE_SESSION_ID",
    )
    p.add_argument("--output", type=Path)
    p.add_argument("--record", choices=["priorities", "answer", "proposal", "approve"])
    p.add_argument("--text-file", type=Path)
    p.add_argument("--message-id", default="")
    args = p.parse_args()
    if not args.meeting_thread:
        p.error("--meeting-thread is required outside a Claude Code session")
    from agent_state import canonical_root

    root = canonical_root(Path(__file__).resolve().parent.parent)
    now = datetime.now(timezone.utc)
    day = now.astimezone(ZoneInfo(args.timezone)).date().isoformat()
    if args.record:
        if not args.text_file:
            p.error("--record requires --text-file")
        result = save_meeting_step(
            root,
            day,
            args.meeting_thread,
            args.record,
            args.text_file.read_text(),
            args.message_id,
            args.timezone,
        )
    else:
        record = load_meeting(root, day, args.meeting_thread)
        if not record.get("priorities"):
            p.error("Ask and record today's priorities first; no research was started")
        result = collect(root, now, args.timezone, record)
    text = json.dumps(result, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text)
        args.output.chmod(0o600)
    else:
        print(text)


if __name__ == "__main__":
    main()
