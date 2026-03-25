#!/usr/bin/env python3
"""
One-time migration: add missing PostgreSQL indexes to the embeds and embed_keys tables.

The Directus schema YAMLs document many fields as "[Indexed]", but Directus only
creates an index when its schema processor explicitly handles that flag for the
underlying database driver. In practice, none of those documented indexes were
created — only the primary key (id) index exists on both tables.

This script adds all missing indexes concurrently (CONCURRENTLY = no table lock,
safe to run against a live production database).

Indexes added:
  embeds:
    - embeds_embed_id_unique_idx   UNIQUE (embed_id)          — replaces Directus app-layer uniqueness check
    - embeds_hashed_chat_id_idx    (hashed_chat_id)           — primary lookup for chat sync and deletion
    - embeds_hashed_user_id_idx    (hashed_user_id)           — user-scoped queries and deletion
    - embeds_hashed_message_id_idx (hashed_message_id)        — per-message embed lookup and deletion
    - embeds_hashed_task_id_idx    (hashed_task_id)           — task-completion embed updates (partial: NOT NULL)
    - embeds_content_hash_idx      (content_hash)             — duplicate detection (partial: NOT NULL)
    - embeds_status_processing_idx (status)                   — processing embed queries (partial: status='processing')
    - embeds_updated_at_idx        (updated_at)               — future cold-storage eviction (Phase 3)

  embed_keys:
    - embed_keys_hashed_embed_id_idx   (hashed_embed_id)                          — per-embed key lookup
    - embed_keys_hashed_chat_id_idx    (hashed_chat_id)                            — per-chat key fetch
    - embed_keys_hashed_user_id_idx    (hashed_user_id)                            — user-scoped key queries

Architecture: docs/architecture/embeds.md
Tests: N/A — migration, run once

Usage:
    docker exec cms-database psql -U directus -d directus -f /path/to/migrate_embed_indexes.sql
    OR
    docker exec api python /app/backend/scripts/migrate_embed_indexes.py
    docker exec api python /app/backend/scripts/migrate_embed_indexes.py --dry-run
    docker exec api python /app/backend/scripts/migrate_embed_indexes.py --check
"""

import argparse
import os
import subprocess
import sys


# ─── Index definitions ────────────────────────────────────────────────────────
# Each tuple: (index_name, table_name, create_sql, drop_sql)
# Use IF NOT EXISTS so the script is idempotent.

INDEXES = [
    # ── embeds ──────────────────────────────────────────────────────────────
    (
        "embeds_embed_id_unique_idx",
        "embeds",
        # UNIQUE index — replaces the Directus app-layer uniqueness check which
        # currently does a full seq scan per INSERT to enforce uniqueness.
        "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS embeds_embed_id_unique_idx "
        "ON public.embeds (embed_id);",
        "DROP INDEX CONCURRENTLY IF EXISTS embeds_embed_id_unique_idx;",
    ),
    (
        "embeds_hashed_chat_id_idx",
        "embeds",
        # Most-queried lookup: get_embeds_by_hashed_chat_id, delete_all_embeds_for_chat
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS embeds_hashed_chat_id_idx "
        "ON public.embeds (hashed_chat_id);",
        "DROP INDEX CONCURRENTLY IF EXISTS embeds_hashed_chat_id_idx;",
    ),
    (
        "embeds_hashed_user_id_idx",
        "embeds",
        # User-scoped queries: get_embed_by_content_hash, shared embed retention check
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS embeds_hashed_user_id_idx "
        "ON public.embeds (hashed_user_id);",
        "DROP INDEX CONCURRENTLY IF EXISTS embeds_hashed_user_id_idx;",
    ),
    (
        "embeds_hashed_message_id_idx",
        "embeds",
        # Per-message deletion: delete_embeds_for_message
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS embeds_hashed_message_id_idx "
        "ON public.embeds (hashed_message_id) WHERE hashed_message_id IS NOT NULL;",
        "DROP INDEX CONCURRENTLY IF EXISTS embeds_hashed_message_id_idx;",
    ),
    (
        "embeds_hashed_task_id_idx",
        "embeds",
        # Task-completion updates: get_embeds_by_hashed_task_id (rare, partial index)
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS embeds_hashed_task_id_idx "
        "ON public.embeds (hashed_task_id) WHERE hashed_task_id IS NOT NULL;",
        "DROP INDEX CONCURRENTLY IF EXISTS embeds_hashed_task_id_idx;",
    ),
    (
        "embeds_content_hash_idx",
        "embeds",
        # Duplicate detection: get_embed_by_content_hash (partial: only when set)
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS embeds_content_hash_idx "
        "ON public.embeds (content_hash) WHERE content_hash IS NOT NULL;",
        "DROP INDEX CONCURRENTLY IF EXISTS embeds_content_hash_idx;",
    ),
    (
        "embeds_status_processing_idx",
        "embeds",
        # Partial index on active embeds only — processing embeds are a small fraction
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS embeds_status_processing_idx "
        "ON public.embeds (status) WHERE status = 'processing';",
        "DROP INDEX CONCURRENTLY IF EXISTS embeds_status_processing_idx;",
    ),
    (
        "embeds_updated_at_idx",
        "embeds",
        # For Phase 3 cold-storage eviction: find embeds not updated in 90+ days
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS embeds_updated_at_idx "
        "ON public.embeds (updated_at);",
        "DROP INDEX CONCURRENTLY IF EXISTS embeds_updated_at_idx;",
    ),

    # ── embed_keys ───────────────────────────────────────────────────────────
    (
        "embed_keys_hashed_embed_id_idx",
        "embed_keys",
        # Per-embed key lookup: get_embed_keys_by_embed_id, _delete_embed_keys_for_embed
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS embed_keys_hashed_embed_id_idx "
        "ON public.embed_keys (hashed_embed_id);",
        "DROP INDEX CONCURRENTLY IF EXISTS embed_keys_hashed_embed_id_idx;",
    ),
    (
        "embed_keys_hashed_chat_id_idx",
        "embed_keys",
        # Per-chat key fetch: get_embed_keys_by_hashed_chat_id (most common read path)
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS embed_keys_hashed_chat_id_idx "
        "ON public.embed_keys (hashed_chat_id) WHERE hashed_chat_id IS NOT NULL;",
        "DROP INDEX CONCURRENTLY IF EXISTS embed_keys_hashed_chat_id_idx;",
    ),
    (
        "embed_keys_hashed_user_id_idx",
        "embed_keys",
        # User-scoped cleanup queries
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS embed_keys_hashed_user_id_idx "
        "ON public.embed_keys (hashed_user_id);",
        "DROP INDEX CONCURRENTLY IF EXISTS embed_keys_hashed_user_id_idx;",
    ),
]

# ─── PostgreSQL connection (reads from environment) ───────────────────────────
# Must be run in the cms-database container (or with access to the database).

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
    """Print which indexes already exist and which are missing."""
    print("\nChecking existing indexes on embeds and embed_keys...\n")

    check_sql = """
        SELECT indexname, tablename
        FROM pg_indexes
        WHERE tablename IN ('embeds', 'embed_keys')
        ORDER BY tablename, indexname;
    """
    _, output = run_psql(check_sql, dry_run=False)
    print(output)

    print("\nExpected indexes:")
    for name, table, _, _ in INDEXES:
        print(f"  [{table}] {name}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Add missing PostgreSQL indexes to embeds and embed_keys tables."
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
        print("\nRolling back embed indexes migration...\n")
        for name, table, _, drop_sql in INDEXES:
            print(f"  Dropping [{table}] {name} ...")
            success, output = run_psql(drop_sql, dry_run=args.dry_run)
            status = "OK" if success else "FAILED"
            print(f"    {status}: {output}")
        print("\nRollback complete.")
        sys.exit(0)

    # ── Forward migration ────────────────────────────────────────────────────
    print("\nRunning embed indexes migration...")
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
            if "already exists" in output or "CREATE INDEX" in output:
                if "already exists" in output:
                    print(f"    SKIP (already exists): {output}")
                    skip_count += 1
                else:
                    print(f"    OK: {output}")
                    success_count += 1
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
