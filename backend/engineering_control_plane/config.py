"""Environment configuration for the engineering control plane.

Only engineering-prefixed settings are accepted so the service cannot
accidentally inherit product Directus, database, S3, or application secrets.
Configuration is intentionally small until authenticated API routes land.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str
    migration_directory: str = "/app/backend/engineering_control_plane/migrations"
    identities_json: str = "{}"

    @classmethod
    def from_environment(cls) -> Settings:
        database_url = os.getenv("ENGINEERING_CONTROL_PLANE_DATABASE_URL", "").strip()
        if not database_url:
            raise RuntimeError("ENGINEERING_CONTROL_PLANE_DATABASE_URL is required")
        return cls(
            database_url=database_url,
            migration_directory=os.getenv(
                "ENGINEERING_CONTROL_PLANE_MIGRATION_DIRECTORY",
                "/app/backend/engineering_control_plane/migrations",
            ),
            identities_json=os.getenv("ENGINEERING_CONTROL_PLANE_IDENTITIES_JSON", "{}"),
        )
