"""Read-only daily meeting inputs from Codex, Git and isolated CI receipts.

Calendar windows use the user's explicit timezone, not thread updatedAt alone.
Copied fork messages are deduplicated; inaccessible history remains explicit.
CI batch states never masquerade as individual test counts. Reruns retain source
and suite identity. See docs/architecture/codex-orchestration.md.
"""

from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
from zoneinfo import ZoneInfo

MAX_PAGES = 100
MAX_TRANSCRIPT = 64 * 1024 * 1024


def stamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def messages(path, since, until):
    """Read actual message timestamps; tool output and system context are not work."""
    path = Path(path)
    if path.stat().st_size > MAX_TRANSCRIPT:
        raise ValueError(
            "Transcript exceeds bounded reader; inspect date-scoped slices separately"
        )
    found = []
    with path.open() as source:
        for line in source:
            row = json.loads(line)
            if row.get("type") != "response_item" or not row.get("timestamp"):
                continue
            moment = stamp(row["timestamp"])
            if not since <= moment < until:
                continue
            item = row.get("payload", {})
            if item.get("type") != "message" or item.get("role") not in (
                "user",
                "assistant",
            ):
                continue
            content = "\n".join(p.get("text", "") for p in item.get("content", []))
            if not content.strip() or any(
                marker in content
                for marker in (
                    "AUTOMATED ORCHESTRATION CHECKPOINT",
                    "<environment_context>",
                    "<INSTRUCTIONS>",
                    "<app-context>",
                    "No changes since the last check",
                )
            ):
                continue
            # These are review evidence, never commands or approval authority.
            found.append(
                {
                    "timestamp": moment.isoformat(),
                    "role": item["role"],
                    "fingerprint": hashlib.sha256(
                        (moment.isoformat() + content).encode()
                    ).hexdigest(),
                    "excerpt": content[:600],
                }
            )
    return found


def inventory(rpc, root):
    """Include archived tasks and routed worktrees; disclose pagination failures."""
    entries, errors = {}, []
    for archived in (False, True):
        cursor = None
        for _ in range(MAX_PAGES):
            try:
                page = rpc.call(
                    "thread/list",
                    {
                        "limit": 100,
                        "cursor": cursor,
                        "archived": archived,
                        "sortKey": "updated_at",
                    },
                )
            except (RuntimeError, OSError, TimeoutError) as exc:
                errors.append(f"Codex inventory unavailable: {type(exc).__name__}")
                break
            for thread in page["data"]:
                cwd = Path(thread.get("cwd") or "/")
                if cwd.is_relative_to(root):
                    entries[thread["id"]] = {**thread, "archived": archived}
            cursor = page.get("nextCursor")
            if not cursor:
                break
        if cursor:
            errors.append(
                "Codex inventory truncated; expand pagination before claiming complete coverage"
            )
    return list(entries.values()), errors


def review_history(threads, now, timezone_name, max_days=30):
    tz = ZoneInfo(timezone_name)
    today = now.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    earliest = today - timedelta(days=max_days)
    by_day, errors, seen = {}, [], set()
    # Prefer parent history so fork copies do not count as a second achievement.
    ordered = sorted(threads, key=lambda t: bool(t.get("forkedFromId")))
    for thread in ordered:
        try:
            rows = messages(thread["path"], earliest, today)
        except (OSError, ValueError, KeyError) as exc:
            errors.append({"thread": thread["id"], "error": type(exc).__name__})
            continue
        for row in rows:
            if row["fingerprint"] in seen:
                continue
            seen.add(row["fingerprint"])
            day = stamp(row["timestamp"]).astimezone(tz).date().isoformat()
            task = by_day.setdefault(day, {}).setdefault(
                thread["id"],
                {
                    "thread": thread["id"],
                    "link": f"codex://threads/{thread['id']}",
                    "title": thread.get("name")
                    or thread.get("preview", "Untitled")[:100],
                    "parent": thread.get("forkedFromId"),
                    "archived": thread.get("archived", False),
                    "messages": 0,
                    "last_message": None,
                },
            )
            task["messages"] += 1
            task["last_message"] = row
    selected = max(by_day) if by_day else None
    return {
        "calendar_yesterday": (today - timedelta(days=1)).date().isoformat(),
        "review_day": selected,
        "timezone": timezone_name,
        "searched_days": max_days,
        "tasks": list(by_day.get(selected, {}).values()),
        "history_errors": errors,
        "coverage": "incomplete" if errors else "complete",
    }


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


def collect(root, now, timezone_name, rpc):
    threads, errors = inventory(rpc, root)
    history = review_history(threads, now, timezone_name)
    history["inventory_errors"] = errors
    if errors:
        history["coverage"] = "incomplete"
    midnight = now.astimezone(ZoneInfo(timezone_name)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return {
        "collected_at": now.isoformat(),
        "history": history,
        "commits": commits(
            root, history["review_day"] or history["calendar_yesterday"], timezone_name
        ),
        "nightly": nightly_snapshot(
            root, (midnight - timedelta(days=1)).timestamp(), now.timestamp()
        ),
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--timezone", required=True)
    p.add_argument("--output", type=Path)
    args = p.parse_args()
    from codex_orchestration import canonical_root
    from codex_rpc import CodexRPC

    root = canonical_root(Path(__file__).resolve().parent.parent)
    with CodexRPC() as rpc:
        result = collect(root, datetime.now(timezone.utc), args.timezone, rpc)
    text = json.dumps(result, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text)
        args.output.chmod(0o600)
    else:
        print(text)


if __name__ == "__main__":
    main()
