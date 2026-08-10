# backend/tests/test_chat_recovery_unique_indexes.py
# Verifies the database-enforced idempotency identities required by the
# cross-device chat completion recovery protocol. This focused test remains
# database-independent so schema drift is caught before deployment.

from pathlib import Path
import re


MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "core/directus/setup/migrate_chat_recovery_unique_indexes.sql"
)


def _normalized_statements() -> set[str]:
    sql = re.sub(r"--[^\n]*", "", MIGRATION.read_text(encoding="utf-8"))
    return {" ".join(statement.split()).lower() for statement in sql.split(";")}


def test_recovery_migration_has_required_unique_identities() -> None:
    statements = _normalized_statements()
    required_fragments = {
        "chat_turn_preflights (hashed_user_id, chat_id, turn_id)",
        "chat_turn_preflights (user_message_id)",
        "chat_turn_preflights (inference_task_id)",
        "chat_turn_preflights (billing_identity)",
        "chat_inference_outbox (preflight_id)",
        "chat_inference_outbox (inference_task_id)",
        "chat_inference_outbox (billing_identity)",
        "chat_completion_recovery_jobs (hashed_user_id, chat_id, turn_id)",
        "chat_completion_recovery_jobs (preflight_id)",
        "chat_completion_recovery_jobs (inference_task_id)",
        "chat_completion_recovery_jobs (assistant_message_id)",
    }

    for fragment in required_fragments:
        assert any(
            statement.startswith("create unique index if not exists")
            and fragment.lower() in statement
            for statement in statements
        ), f"missing unique identity: {fragment}"


def test_recovery_migration_is_atomic_and_partial_indexes_ignore_nulls() -> None:
    statements = _normalized_statements()
    assert "begin" in statements
    assert "commit" in statements
    task_statement = next(
        statement
        for statement in statements
        if "chat_turn_preflights (inference_task_id)" in statement
    )
    billing_statement = next(
        statement
        for statement in statements
        if "chat_turn_preflights (billing_identity)" in statement
    )
    assert "where inference_task_id is not null" in task_statement
    assert "where billing_identity is not null" in billing_statement
