"""Static migration checks for coordination persistence guarantees.

These checks catch accidental weakening of the database-level invariants
without requiring access to the live engineering PostgreSQL instance.
Runtime integration tests will exercise the same migration against PostgreSQL.
"""

# contract-test-file: infrastructure

from pathlib import Path


MIGRATION = Path(__file__).parents[1] / "migrations" / "0001_coordination.sql"
SHARED_LEASE_MIGRATION = Path(__file__).parents[1] / "migrations" / "0004_shared_resource_leases.sql"


def test_migration_enforces_lease_exclusion_and_dispatch_reuse() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "EXCLUDE USING gist" in sql
    assert "resource_key WITH =" in sql
    assert "active_window WITH &&" in sql
    assert "control_plane_dispatch_requests_reuse_idx" in sql
    assert "fingerprint_sha256" in sql
    assert "'succeeded'" in sql


def test_migration_persists_runtime_epoch_and_event_cursor() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "control_plane_runtime_state" in sql
    assert "runtime_epoch bigint" in sql
    assert "cursor bigint GENERATED ALWAYS AS IDENTITY" in sql
    assert "control_plane_session_event_acknowledgements" in sql
    assert "interval '7 days'" in sql


def test_shared_lease_migration_uses_the_postgres_generated_constraint_name() -> None:
    sql = SHARED_LEASE_MIGRATION.read_text(encoding="utf-8")

    assert "control_plane_resource_lease_it_resource_key_active_window_excl" in sql
