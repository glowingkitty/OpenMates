#!/usr/bin/env python3
"""
One-time migration: add missing PostgreSQL indexes for chat and message hot paths.

Directus schema metadata does not reliably create PostgreSQL indexes for custom
collections, so this script creates the database indexes used by chat sync,
message pagination, message idempotency checks, and auto-delete lookup paths.
All indexes are created CONCURRENTLY to avoid blocking production writes.

Architecture: docs/architecture/sync.md
Tests: N/A - migration, run once

Usage:
    python3 backend/scripts/migrate_chat_message_indexes.py --dry-run
    docker exec cms-database psql -U directus -d directus -c '<CREATE INDEX SQL>'

Run the script live from an environment that has `psql` installed and network
access to the Directus Postgres database. Use `--dry-run` to print the exact SQL
when only the database container has `psql`.
"""

import argparse
import os
import shutil
import subprocess
import sys


# Each tuple: (index_name, table_name, create_sql, drop_sql)
INDEXES = [
    # -- messages -------------------------------------------------------------
    (
        "messages_chat_created_client_id_idx",
        "messages",
        # Main sync and pagination path:
        #   WHERE chat_id = ? ORDER BY created_at
        #   WHERE chat_id = ? AND created_at/client_message_id before cursor
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS messages_chat_created_client_id_idx "
        "ON public.messages (chat_id, created_at, client_message_id, id);",
        "DROP INDEX CONCURRENTLY IF EXISTS messages_chat_created_client_id_idx;",
    ),
    (
        "messages_client_message_id_idx",
        "messages",
        # Idempotency and single-message delete lookups.
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS messages_client_message_id_idx "
        "ON public.messages (client_message_id) WHERE client_message_id IS NOT NULL;",
        "DROP INDEX CONCURRENTLY IF EXISTS messages_client_message_id_idx;",
    ),
    (
        "messages_hashed_user_created_idx",
        "messages",
        # User-scoped retention/archive scans and future per-user reporting.
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS messages_hashed_user_created_idx "
        "ON public.messages (hashed_user_id, created_at) WHERE hashed_user_id IS NOT NULL;",
        "DROP INDEX CONCURRENTLY IF EXISTS messages_hashed_user_created_idx;",
    ),
    # -- chats ----------------------------------------------------------------
    (
        "chats_hashed_user_last_message_idx",
        "chats",
        # Chat list, stale-chat auto-delete, and future per-user retention scans.
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS chats_hashed_user_last_message_idx "
        "ON public.chats (hashed_user_id, last_message_timestamp) "
        "WHERE last_message_timestamp IS NOT NULL;",
        "DROP INDEX CONCURRENTLY IF EXISTS chats_hashed_user_last_message_idx;",
    ),
    (
        "chats_hashed_user_last_edited_idx",
        "chats",
        # Fallback ordering/staleness signal for chats without message timestamps.
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS chats_hashed_user_last_edited_idx "
        "ON public.chats (hashed_user_id, last_edited_overall_timestamp) "
        "WHERE last_edited_overall_timestamp IS NOT NULL;",
        "DROP INDEX CONCURRENTLY IF EXISTS chats_hashed_user_last_edited_idx;",
    ),
    (
        "chats_parent_id_idx",
        "chats",
        # Sub-chat and agent tree lookup path.
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS chats_parent_id_idx "
        "ON public.chats (parent_id) WHERE parent_id IS NOT NULL;",
        "DROP INDEX CONCURRENTLY IF EXISTS chats_parent_id_idx;",
    ),
]


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

    if not shutil.which("psql"):
        return False, (
            "psql executable not found. Run --dry-run and execute the printed "
            "SQL in the database container."
        )

    env = os.environ.copy()
    env["PGPASSWORD"] = DB_PASS

    result = subprocess.run(
        [
            "psql",
            "-h",
            DB_HOST,
            "-p",
            DB_PORT,
            "-U",
            DB_USER,
            "-d",
            DB_NAME,
            "-c",
            sql,
            "--no-password",
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    output = (result.stdout + result.stderr).strip()
    return result.returncode == 0, output


def check_indexes() -> None:
    """Print existing chat/message indexes and the expected index list."""
    print("\nChecking existing indexes on chats and messages...\n")
    check_sql = """
        SELECT indexname, tablename
        FROM pg_indexes
        WHERE tablename IN ('chats', 'messages')
        ORDER BY tablename, indexname;
    """
    success, output = run_psql(check_sql, dry_run=False)
    print(output)
    if not success:
        sys.exit(1)

    print("\nExpected indexes:")
    for name, table, _, _ in INDEXES:
        print(f"  [{table}] {name}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Add missing PostgreSQL indexes to chats and messages tables."
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
        print("\nRolling back chat/message indexes migration...\n")
        for name, table, _, drop_sql in INDEXES:
            print(f"  Dropping [{table}] {name} ...")
            success, output = run_psql(drop_sql, dry_run=args.dry_run)
            status = "OK" if success else "FAILED"
            print(f"    {status}: {output}")
        print("\nRollback complete.")
        sys.exit(0)

    print("\nRunning chat/message indexes migration...")
    print(f"  Target: {DB_USER}@{DB_HOST}:{DB_PORT}/{DB_NAME}")
    print(f"  Indexes to create: {len(INDEXES)}")
    if args.dry_run:
        print("  Mode: DRY RUN (no changes will be made)\n")
    else:
        print("  Mode: LIVE (using CONCURRENTLY - no table locks)\n")

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

    print("\nMigration complete:")
    print(f"  Created: {success_count}")
    print(f"  Skipped: {skip_count}")
    print(f"  Failed:  {fail_count}")

    if fail_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
