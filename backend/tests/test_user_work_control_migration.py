"""Tooling coverage for the destructive unreleased work-control migration."""

from pathlib import Path

# contract-test-file: tooling


def test_work_control_migration_removes_retired_plan_storage():
    sql = (Path(__file__).resolve().parents[1] / "core/directus/setup/migrate_user_work_control_indexes.sql").read_text()
    assert "DELETE FROM public.directus_relations" in sql
    assert "DELETE FROM public.directus_fields" in sql
    assert "DELETE FROM public.directus_collections" in sql
    assert "collection = 'user_plan_steps'" in sql
    assert "field IN (" in sql
    assert "DROP COLUMN IF EXISTS encrypted_plan_key" in sql
    assert "DROP COLUMN IF EXISTS plan_step_id" in sql
    assert "DROP TABLE IF EXISTS public.user_plan_steps" in sql


def test_dev_cms_setup_mounts_required_work_control_migration():
    compose = (Path(__file__).resolve().parents[1] / "core/docker-compose.yml").read_text()
    migration = "migrate_user_work_control_indexes.sql"

    assert f'USER_WORK_CONTROL_MIGRATION_PATH: "/usr/src/app/migrations/{migration}"' in compose
    assert f"./directus/setup/{migration}:/usr/src/app/migrations/{migration}:ro" in compose
