"""PostgreSQL health and migration helpers for the control plane.

The psycopg import remains local so deterministic unit tests can run without
the production database driver installed. Every connection targets only the
dedicated engineering database URL supplied by the service configuration.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.engineering_control_plane.config import Settings


def connect(database_url: str) -> Any:
    import psycopg

    return psycopg.connect(database_url)


def apply_migrations(settings: Settings) -> list[str]:
    migration_paths = sorted(Path(settings.migration_directory).glob("*.sql"))
    applied: list[str] = []
    with connect(settings.database_url) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS engineering_control_plane_migrations (
                migration_name text PRIMARY KEY,
                applied_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
        existing = {
            row[0]
            for row in connection.execute(
                "SELECT migration_name FROM engineering_control_plane_migrations"
            ).fetchall()
        }
        for path in migration_paths:
            if path.name in existing:
                continue
            connection.execute(path.read_text(encoding="utf-8"))
            connection.execute(
                "INSERT INTO engineering_control_plane_migrations (migration_name) VALUES (%s)",
                (path.name,),
            )
            applied.append(path.name)
    return applied


def readiness(settings: Settings) -> dict[str, str | int]:
    with connect(settings.database_url) as connection:
        runtime_epoch = connection.execute(
            "SELECT runtime_epoch FROM control_plane_runtime_state WHERE singleton = true"
        ).fetchone()[0]
        migration = connection.execute(
            "SELECT migration_name FROM engineering_control_plane_migrations ORDER BY migration_name DESC LIMIT 1"
        ).fetchone()
    return {
        "database": "ready",
        "migration": migration[0] if migration else "none",
        "runtime_epoch": runtime_epoch,
    }

