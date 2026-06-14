"""
Tests for the chat/message index migration script.

The migration itself is executed manually against Postgres with CONCURRENTLY,
so these tests keep verification local and deterministic. They validate the
index contract and the error path used when the Postgres CLI is unavailable.
"""

from pathlib import Path
import importlib.util


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "migrate_chat_message_indexes.py"


def load_migration_module():
    spec = importlib.util.spec_from_file_location("migrate_chat_message_indexes", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_index_definitions_cover_chat_and_message_hot_paths():
    migration = load_migration_module()

    indexes = {name: (table, create_sql, drop_sql) for name, table, create_sql, drop_sql in migration.INDEXES}

    assert set(indexes) == {
        "messages_chat_created_client_id_idx",
        "messages_client_message_id_idx",
        "messages_hashed_user_created_idx",
        "chats_hashed_user_last_message_idx",
        "chats_hashed_user_last_edited_idx",
        "chats_parent_id_idx",
    }
    assert indexes["messages_chat_created_client_id_idx"][0] == "messages"
    assert "ON public.messages (chat_id, created_at, client_message_id, id)" in indexes[
        "messages_chat_created_client_id_idx"
    ][1]
    assert indexes["chats_hashed_user_last_message_idx"][0] == "chats"
    assert "ON public.chats (hashed_user_id, last_message_timestamp)" in indexes[
        "chats_hashed_user_last_message_idx"
    ][1]


def test_all_indexes_are_concurrent_and_rollbackable():
    migration = load_migration_module()

    names = [name for name, _, _, _ in migration.INDEXES]

    assert len(names) == len(set(names))
    for name, _, create_sql, drop_sql in migration.INDEXES:
        assert "CREATE INDEX CONCURRENTLY IF NOT EXISTS" in create_sql
        assert name in create_sql
        assert drop_sql == f"DROP INDEX CONCURRENTLY IF EXISTS {name};"


def test_run_psql_reports_missing_psql(monkeypatch):
    migration = load_migration_module()
    monkeypatch.setattr(migration.shutil, "which", lambda _: None)

    success, output = migration.run_psql("SELECT 1;")

    assert success is False
    assert "psql executable not found" in output
