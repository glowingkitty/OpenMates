"""Tooling coverage for the destructive unreleased work-control migration."""

from pathlib import Path

# contract-test-file: tooling


def test_work_control_migration_removes_retired_plan_storage():
    sql = (Path(__file__).resolve().parents[1] / "core/directus/setup/migrate_user_work_control_indexes.sql").read_text()
    assert "DROP COLUMN IF EXISTS encrypted_plan_key" in sql
    assert "DROP COLUMN IF EXISTS plan_step_id" in sql
    assert "DROP TABLE IF EXISTS public.user_plan_steps" in sql
