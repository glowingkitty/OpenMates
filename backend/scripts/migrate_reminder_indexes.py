#!/usr/bin/env python3
"""
One-time migration: add PostgreSQL indexes to the reminders table.

The Directus schema YAML documents several fields as "[Indexed]", but Directus
does not auto-create PostgreSQL indexes for custom collections. This script adds
all required indexes using CONCURRENTLY (no table lock, safe on a live database).

Indexes added:
  reminders:
    - reminders_trigger_at_status_idx      (trigger_at, status)        — hot-window promotion query
    - reminders_status_trigger_at_idx      (status, trigger_at)        — overdue/pending scans
    - reminders_hashed_user_id_status_idx  (hashed_user_id, status)    — per-user listing
    - reminders_trigger_at_idx             (trigger_at)                — DB fallback ZRANGEBYSCORE equivalent
    - reminders_status_idx                 (status)                    — status-only filter queries

Architecture: docs/apps/reminder.md
Tests: N/A — migration, run once

Usage:
    docker exec api python /app/backend/scripts/migrate_reminder_indexes.py
    docker exec api python /app/backend/scripts/migrate_reminder_indexes.py --dry-run
    docker exec api python /app/backend/scripts/migrate_reminder_indexes.py --check
"""

import argparse
import os
import subprocess
import sys


# ─── Index definitions ────────────────────────────────────────────────────────
# Each tuple: (index_name, table_name, create_sql, drop_sql)
# Use IF NOT EXISTS so the script is idempotent.

INDEXES = [
    # ── reminders ────────────────────────────────────────────────────────────

    # Primary promotion query: WHERE status='pending' AND trigger_at <= window_end ORDER BY trigger_at
    # This covers get_pending_reminders_in_window() used by the promotion task and startup warm-up.
    (
        "reminders_trigger_at_status_idx",
        "reminders",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS reminders_trigger_at_status_idx "
        "ON public.reminders (trigger_at, status) WHERE status = 'pending';",
        "DROP INDEX CONCURRENTLY IF EXISTS reminders_trigger_at_status_idx;",
    ),

    # Per-user reminder listing: WHERE hashed_user_id='...' AND status='pending' ORDER BY trigger_at
    # Used by list-reminders skill, cancel-reminder skill, and the settings API endpoint.
    (
        "reminders_hashed_user_id_status_idx",
        "reminders",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS reminders_hashed_user_id_status_idx "
        "ON public.reminders (hashed_user_id, status);",
        "DROP INDEX CONCURRENTLY IF EXISTS reminders_hashed_user_id_status_idx;",
    ),

    # Overdue scan: WHERE status='pending' AND trigger_at <= now() ORDER BY trigger_at
    # Used by get_overdue_pending_reminders() in the DB fallback path.
    (
        "reminders_status_trigger_at_idx",
        "reminders",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS reminders_status_trigger_at_idx "
        "ON public.reminders (status, trigger_at);",
        "DROP INDEX CONCURRENTLY IF EXISTS reminders_status_trigger_at_idx;",
    ),

    # Simple trigger_at range scan — fallback for any ad-hoc range queries.
    (
        "reminders_trigger_at_idx",
        "reminders",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS reminders_trigger_at_idx "
        "ON public.reminders (trigger_at);",
        "DROP INDEX CONCURRENTLY IF EXISTS reminders_trigger_at_idx;",
    ),

    # Status-only filter — used by count_pending_reminders() for monitoring.
    (
        "reminders_status_idx",
        "reminders",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS reminders_status_idx "
        "ON public.reminders (status);",
        "DROP INDEX CONCURRENTLY IF EXISTS reminders_status_idx;",
    ),
]

# ─── PostgreSQL connection (reads from environment) ───────────────────────────

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = os.environ.get("DB_PORT", "5432")
DB_NAME = os.environ.get("POSTGRES_DB", os.environ.get("DATABASE_NAME", "directus"))
DB_USER = os.environ.get("DATABASE_USERNAME", "directus")
DB_PASS = os.environ.get("DATABASE_PASSWORD", "")


def run_psql(sql: str, dry_run: bool = False) -> tuple[bool, str]:
    """Execute a single SQL statement via psql. Returns (success, output)."""
    if dry_run:
        print(f"  [DRY RUN] Would execute:\n    {sql}")
        return True, ""

    env = os.environ.copy()
    env["PGPASSWORD"] = DB_PASS

    result = subprocess.run(
        [
            "psql",
            "-h", DB_HOST,
            "-p", DB_PORT,
            "-U", DB_USER,
            "-d", DB_NAME,
            "-c", sql,
            "--no-password",
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    output = (result.stdout + result.stderr).strip()
    return result.returncode == 0, output


def check_indexes() -> None:
    """Print which indexes exist on the reminders table."""
    print("\nChecking existing indexes on reminders...\n")
    check_sql = (
        "SELECT indexname, indexdef "
        "FROM pg_indexes "
        "WHERE tablename = 'reminders' "
        "ORDER BY indexname;"
    )
    _, output = run_psql(check_sql, dry_run=False)
    print(output)

    print("\nExpected indexes:")
    for name, table, _, _ in INDEXES:
        print(f"  [{table}] {name}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Add PostgreSQL indexes to the reminders table."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print SQL statements without executing them.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Show existing indexes and exit.",
    )
    parser.add_argument(
        "--rollback",
        action="store_true",
        help="Drop all indexes added by this migration (idempotent, IF EXISTS).",
    )
    args = parser.parse_args()

    if args.check:
        check_indexes()
        sys.exit(0)

    if args.rollback:
        print("\nRolling back reminder indexes migration...\n")
        for name, table, _, drop_sql in INDEXES:
            print(f"  Dropping [{table}] {name} ...")
            success, output = run_psql(drop_sql, dry_run=args.dry_run)
            status = "OK" if success else "FAILED"
            print(f"    {status}: {output}")
        print("\nRollback complete.")
        sys.exit(0)

    # ── Forward migration ────────────────────────────────────────────────────
    print("\nRunning reminder indexes migration...")
    print(f"  Target: {DB_USER}@{DB_HOST}:{DB_PORT}/{DB_NAME}")
    print(f"  Indexes to create: {len(INDEXES)}")
    if args.dry_run:
        print("  Mode: DRY RUN (no changes will be made)\n")
    else:
        print("  Mode: LIVE (using CONCURRENTLY — no table locks)\n")

    success_count = 0
    skip_count = 0
    fail_count = 0

    for name, table, create_sql, _ in INDEXES:
        print(f"  Creating [{table}] {name} ...")
        success, output = run_psql(create_sql, dry_run=args.dry_run)
        if args.dry_run:
            success_count += 1
            continue

        if success:
            if "already exists" in output:
                print(f"    SKIP (already exists): {output}")
                skip_count += 1
            else:
                print(f"    OK: {output}")
                success_count += 1
        else:
            print(f"    FAILED: {output}")
            fail_count += 1

    print(
        f"\nMigration complete. "
        f"Created: {success_count}, Skipped: {skip_count}, Failed: {fail_count}"
    )

    if fail_count > 0:
        print("\nWARNING: Some indexes failed to create. Check output above.")
        sys.exit(1)

    if not args.dry_run:
        print("\nVerifying final index state...")
        check_indexes()


if __name__ == "__main__":
    main()
