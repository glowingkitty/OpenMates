# backend/tests/test_workflow_runtime_indexes.py
#
# Static migration contract for Workflow runtime scheduler and event idempotency.
# This runs without a database so missing indexes are caught before deployment.
#
# Spec: docs/specs/workflows-v1/spec.yml (TASK-2)

from pathlib import Path
import re


MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "core/directus/setup/migrate_workflow_runtime_indexes.sql"
)


def test_workflow_runtime_migration_has_required_scheduler_and_idempotency_indexes() -> None:
    sql = re.sub(r"--[^\n]*", "", MIGRATION.read_text(encoding="utf-8"))
    statements = {" ".join(statement.split()).lower() for statement in sql.split(";")}
    required_fragments = {
        "workflow_triggers (next_run_at, trigger_id)",
        "workflow_triggers (hashed_user_id, hashed_project_id, source, event_type, trigger_id)",
        "workflow_versions (version_id)",
        "workflow_runs (acceptance_idempotency_key)",
        "workflow_event_receipts (trigger_id, event_id)",
        "workflow_template_projections (workflow_id)",
        "workflow_input_events (session_id, event_id)",
        "workflow_input_sessions (hashed_user_id, updated_at desc)",
        "workflow_input_mutations (session_id, created_at)",
    }

    for fragment in required_fragments:
        assert any(fragment in statement for statement in statements), fragment

    assert "begin" in statements
    assert "commit" in statements


def test_workflow_runtime_migration_backfills_current_versions_before_manual_acceptance() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()

    assert "insert into workflow_versions" in sql
    assert "gen_random_uuid()" in sql
    assert "jsonb_array_elements" in sql
    assert "current_version_id" in sql
