#!/usr/bin/env python3
"""
linear-cleanup-e2e-artifacts.py — Cancel Linear issues created by E2E test specs.

Runs as a daily cronjob (via linear-cron-setup.sh) or manually. Finds all
non-canceled/non-completed Linear issues whose title starts with "[E2E Test]"
and cancels them. These are artifacts from the report-issue-flow.spec.ts nightly
run — each run creates a real issue report that auto-creates a Linear issue.

Also archives Done issues older than 30 days to keep the workspace clean.

Usage:
    python3 scripts/linear-cleanup-e2e-artifacts.py          # run both jobs
    python3 scripts/linear-cleanup-e2e-artifacts.py --dry-run # show what would be done
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).parent))

from _linear_client import _graphql, TEAM_ID

# Canceled state ID (from OPE workspace)
STATE_CANCELED_ID = "cb96deb5-9146-46ee-b4f7-a0aa914d2cf2"


def cancel_e2e_artifacts(dry_run: bool = False) -> int:
    """Find and cancel all [E2E Test] issues that are not already canceled/done."""
    # Linear doesn't support title.startsWith — filter client-side after fetching
    # all non-closed issues. The "[E2E Test]" prefix is set by report-issue-flow.spec.ts.
    query = """
    query($teamId: ID!) {
      issues(
        filter: {
          team: { id: { eq: $teamId } }
          state: { type: { nin: ["canceled", "completed"] } }
        }
        first: 200
        orderBy: createdAt
      ) {
        nodes { id identifier title state { name } }
      }
    }
    """
    result = _graphql(query, {"teamId": TEAM_ID})
    if not result or "issues" not in result:
        print("Failed to query Linear for E2E artifacts.", file=sys.stderr)
        return 0

    # Client-side filter: only issues whose title starts with "[E2E Test]"
    issues = [i for i in result["issues"]["nodes"] if i["title"].startswith("[E2E Test]")]
    if not issues:
        print("[E2E cleanup] No E2E test artifacts to cancel.")
        return 0

    print(f"[E2E cleanup] Found {len(issues)} E2E test artifact(s) to cancel:")
    canceled = 0
    for issue in issues:
        identifier = issue["identifier"]
        title = issue["title"][:80]
        state = issue["state"]["name"]
        print(f"  {identifier} ({state}): {title}")

        if dry_run:
            continue

        mutation = """
        mutation($id: String!, $stateId: String!) {
          issueUpdate(id: $id, input: { stateId: $stateId }) {
            success
            issue { identifier state { name } }
          }
        }
        """
        resp = _graphql(mutation, {"id": issue["id"], "stateId": STATE_CANCELED_ID})
        if resp and resp.get("issueUpdate", {}).get("success"):
            canceled += 1
        else:
            print(f"    Failed to cancel {identifier}", file=sys.stderr)

    action = "Would cancel" if dry_run else "Canceled"
    print(f"[E2E cleanup] {action} {canceled if not dry_run else len(issues)} issue(s).")
    return canceled if not dry_run else len(issues)


def archive_old_done_issues(days: int = 30, dry_run: bool = False) -> int:
    """Archive Done issues older than `days` days."""
    from datetime import datetime, timedelta, timezone

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    # Fetch all completed issues, filter by completedAt client-side
    # (Linear's DateTime filter type is unreliable across API versions)
    query = """
    query($teamId: ID!) {
      issues(
        filter: {
          team: { id: { eq: $teamId } }
          state: { type: { eq: "completed" } }
        }
        first: 200
        orderBy: updatedAt
      ) {
        nodes { id identifier title completedAt }
      }
    }
    """
    result = _graphql(query, {"teamId": TEAM_ID})
    if not result or "issues" not in result:
        print("Failed to query Linear for old Done issues.", file=sys.stderr)
        return 0

    all_done = result["issues"]["nodes"]
    # Client-side date filter
    issues = [
        i for i in all_done
        if i.get("completedAt") and i["completedAt"] < cutoff
    ]
    if not issues:
        print(f"[Archive] No Done issues older than {days} days (checked {len(all_done)} completed).")
        return 0

    print(f"[Archive] Found {len(issues)} Done issue(s) older than {days} days:")
    archived = 0
    for issue in issues:
        identifier = issue["identifier"]
        title = issue["title"][:60]
        completed = issue.get("completedAt", "?")[:10]
        print(f"  {identifier} (done {completed}): {title}")

        if dry_run:
            continue

        mutation = """
        mutation($id: String!) {
          issueArchive(id: $id) { success }
        }
        """
        resp = _graphql(mutation, {"id": issue["id"]})
        if resp and resp.get("issueArchive", {}).get("success"):
            archived += 1
        else:
            print(f"    Failed to archive {identifier}", file=sys.stderr)

    action = "Would archive" if dry_run else "Archived"
    print(f"[Archive] {action} {archived if not dry_run else len(issues)} issue(s).")
    return archived if not dry_run else len(issues)


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean up E2E test artifacts and archive old Done issues")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without making changes")
    parser.add_argument("--skip-archive", action="store_true", help="Only cancel E2E artifacts, skip archiving")
    parser.add_argument("--archive-days", type=int, default=30, help="Archive Done issues older than N days (default: 30)")
    args = parser.parse_args()

    e2e_count = cancel_e2e_artifacts(dry_run=args.dry_run)
    archive_count = 0
    if not args.skip_archive:
        archive_count = archive_old_done_issues(days=args.archive_days, dry_run=args.dry_run)

    print(f"\nSummary: {e2e_count} E2E artifacts canceled, {archive_count} old issues archived.")


if __name__ == "__main__":
    main()
