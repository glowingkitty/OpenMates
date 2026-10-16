#!/usr/bin/env python3
"""Read-only Directus storage/accountability inventory (no item payload output).

Example: DATABASE_URL=... python backend/scripts/inventory_directus_storage.py
Requires a database role with SELECT on Directus tables and pg_catalog access.
The query scans historical audit rows; run off peak on large databases.
"""

from __future__ import annotations

import argparse
import json
import os


def inventory(connection) -> dict:
    with connection.cursor() as cursor:
        cursor.execute("SET TRANSACTION READ ONLY")
        cursor.execute(
            """
            SELECT c.relname, c.reltuples::bigint,
                   pg_total_relation_size(c.oid)
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = current_schema()
              AND c.relkind = 'r'
            ORDER BY pg_total_relation_size(c.oid) DESC, c.relname
            """
        )
        tables = [
            {"table": name, "estimated_rows": rows, "total_bytes": size}
            for name, rows, size in cursor.fetchall()
        ]
        cursor.execute(
            """
            SELECT a.collection, a.action, c.accountability,
                   count(DISTINCT a.id), count(r.id),
                   coalesce(sum(coalesce(pg_column_size(r.data), 0) +
                                coalesce(pg_column_size(r.delta), 0)), 0),
                   min(a.timestamp), max(a.timestamp)
            FROM directus_activity a
            LEFT JOIN directus_revisions r ON r.activity = a.id
            LEFT JOIN directus_collections c ON c.collection = a.collection
            GROUP BY a.collection, a.action, c.accountability
            ORDER BY count(r.id) DESC, a.collection, a.action
            """
        )
        by_collection = [
            {
                "collection": name,
                "action": action,
                "accountability": accountability,
                "activity_rows": activity_rows,
                "revision_rows": revision_rows,
                "revision_payload_bytes": payload_bytes,
                "first_activity": first.isoformat() if first else None,
                "last_activity": last.isoformat() if last else None,
            }
            for name, action, accountability, activity_rows, revision_rows,
            payload_bytes, first, last in cursor.fetchall()
        ]
    return {"tables": tables, "by_collection": by_collection}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", default=os.getenv("DATABASE_URL"), help="PostgreSQL DSN or DATABASE_URL")
    parser.add_argument("--statement-timeout-ms", type=int, default=120_000)
    args = parser.parse_args()
    if not args.dsn:
        parser.error("--dsn or DATABASE_URL is required")
    if args.statement_timeout_ms <= 0:
        parser.error("--statement-timeout-ms must be positive")

    import psycopg

    with psycopg.connect(args.dsn, options=f"-c statement_timeout={args.statement_timeout_ms}") as connection:
        print(json.dumps(inventory(connection), indent=2))


if __name__ == "__main__":
    main()
