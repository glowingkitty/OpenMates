#!/usr/bin/env python3
"""Build a synthetic Directus schema dump for fresh isolated CI databases.

The producer runs the canonical initializer against an empty database, removes
all application data and transient Directus rows, and writes a plain SQL gzip
consumed by the standard Postgres entrypoint. The published image is only an
artifact carrier: every test still creates its own database volume and rotates
the retained synthetic administrator password before API/worker startup.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
from pathlib import Path
import subprocess

try:
    from scripts.ci_environment import (
        PREPARED_SCHEMA_ADMIN_PASSWORD,
        compose_profile,
    )
except ModuleNotFoundError:  # Direct script execution puts scripts/ on sys.path.
    from ci_environment import PREPARED_SCHEMA_ADMIN_PASSWORD, compose_profile


ROOT = Path(__file__).resolve().parent.parent
PRIVATE = ROOT / "test-results/ci-private"
COMPOSE_PATH = PRIVATE / "schema-compose.json"
OUTPUT = PRIVATE / "openmates-ci-schema.sql.gz"
SCHEMA_SERVICES = ("cms-database", "cms", "cms-setup")


SANITIZE_SQL = r"""
DO $$
DECLARE item record;
BEGIN
  FOR item IN
    SELECT schemaname, tablename
    FROM pg_tables
    WHERE schemaname = 'public' AND tablename NOT LIKE 'directus\_%' ESCAPE '\'
  LOOP
    EXECUTE format('TRUNCATE TABLE %I.%I CASCADE', item.schemaname, item.tablename);
  END LOOP;
END $$;
TRUNCATE TABLE directus_sessions, directus_activity, directus_revisions,
  directus_notifications, directus_shares CASCADE;
DELETE FROM directus_users WHERE email <> 'runtime@example.com';
UPDATE directus_users
SET token = NULL, external_identifier = NULL, last_access = NULL, last_page = NULL
WHERE email = 'runtime@example.com';
"""


def require_runner() -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("Schema bundles may only be produced on GitHub Actions")


def producer_profile(source: str) -> dict:
    profile = compose_profile(
        source,
        credential_overrides={"admin": PREPARED_SCHEMA_ADMIN_PASSWORD},
    )
    profile["services"] = {name: profile["services"][name] for name in SCHEMA_SERVICES}
    for service in profile["services"].values():
        service.pop("ports", None)
    return profile


def run(*args: str, input_bytes: bytes | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(args),
        cwd=ROOT,
        input=input_bytes,
        capture_output=True,
        check=True,
        timeout=900,
    )


def compose(
    *args: str, input_bytes: bytes | None = None
) -> subprocess.CompletedProcess:
    return run(
        "docker",
        "compose",
        "-f",
        str(COMPOSE_PATH),
        *args,
        input_bytes=input_bytes,
    )


def generate(output: Path = OUTPUT) -> Path:
    require_runner()
    source = run("git", "rev-parse", "HEAD").stdout.decode().strip()
    PRIVATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    COMPOSE_PATH.write_text(json.dumps(producer_profile(source)))
    COMPOSE_PATH.chmod(0o600)
    try:
        compose(
            "up",
            "-d",
            "--no-build",
            "--wait",
            "--wait-timeout",
            "600",
            "cms-setup",
        )
        compose(
            "exec",
            "-T",
            "cms-database",
            "psql",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            "openmates",
            "-d",
            "openmates",
            input_bytes=SANITIZE_SQL.encode(),
        )
        users = (
            compose(
                "exec",
                "-T",
                "cms-database",
                "psql",
                "-At",
                "-U",
                "openmates",
                "-d",
                "openmates",
                "-c",
                "SELECT email FROM directus_users ORDER BY email",
            )
            .stdout.decode()
            .splitlines()
        )
        if users != ["runtime@example.com"]:
            raise RuntimeError("Prepared schema contains unexpected Directus users")
        dump = compose(
            "exec",
            "-T",
            "cms-database",
            "pg_dump",
            "--no-owner",
            "--no-privileges",
            "--no-comments",
            "-U",
            "openmates",
            "-d",
            "openmates",
        ).stdout
        if b"ci-" in dump or b"@example.com" in dump.replace(
            b"runtime@example.com", b""
        ):
            raise RuntimeError("Prepared schema contains non-bootstrap account data")
        output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        output.write_bytes(gzip.compress(dump, compresslevel=9, mtime=0))
        output.chmod(0o600)
        return output
    finally:
        compose("down", "--volumes", "--remove-orphans")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    print(generate(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
