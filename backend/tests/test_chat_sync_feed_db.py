"""Engineering DB checks for the chat sync change log (architecture.sync@2).

Runs migrate_chat_sync_feed.sql against a disposable PostgreSQL 13 container
(same major version as the dev database) and exercises the triggers directly
and through the chat-sync Directus extension inside a disposable Directus
image. Opt-in because it starts containers: OPENMATES_DOCKER_DB_TESTS=1.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "backend/core/directus/setup/migrate_chat_sync_feed.sql"
SCHEMA = ROOT / "backend/tests/fixtures/chat_sync_feed_schema.sql"
EXTENSION = ROOT / "backend/core/directus/extensions/chat-sync"
PG_IMAGE = os.getenv("CHAT_SYNC_PG_IMAGE", "postgres:13-alpine")
DIRECTUS_IMAGE = os.getenv("CHAT_SYNC_DIRECTUS_IMAGE", "openmates-directus:dev")
KNEX_PATH = os.getenv(
    "CHAT_SYNC_KNEX_PATH",
    "/directus/node_modules/.pnpm/knex@3.1.0_pg@8.13.1/node_modules/knex/knex.js",
)

pytestmark = pytest.mark.skipif(
    os.getenv("OPENMATES_DOCKER_DB_TESTS") != "1" or shutil.which("docker") is None,
    reason="engineering DB test: set OPENMATES_DOCKER_DB_TESTS=1 with Docker available",
)


def _h(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@pytest.fixture(scope="module")
def database():
    suffix = uuid.uuid4().hex[:10]
    network, container = f"chat-sync-test-{suffix}", f"chat-sync-pg-{suffix}"
    subprocess.run(["docker", "network", "create", network], check=True, capture_output=True)
    try:
        subprocess.run(
            ["docker", "run", "-d", "--rm", "--name", container, "--network", network,
             "-e", "POSTGRES_PASSWORD=test", "-e", "POSTGRES_DB=feed", PG_IMAGE],
            check=True, capture_output=True,
        )
        for _ in range(60):
            ready = subprocess.run(["docker", "exec", container, "pg_isready", "-U", "postgres", "-d", "feed"],
                                   capture_output=True)
            if ready.returncode == 0:
                break
            time.sleep(1)
        time.sleep(1)

        def psql(sql: str) -> str:
            result = subprocess.run(
                ["docker", "exec", "-i", container, "psql", "-U", "postgres", "-d", "feed",
                 "-v", "ON_ERROR_STOP=1", "-At", "-q"],
                input=sql, text=True, capture_output=True,
            )
            if result.returncode != 0:
                raise AssertionError(result.stderr)
            return result.stdout.strip()

        psql(SCHEMA.read_text())
        psql(MIGRATION.read_text())
        psql(MIGRATION.read_text())  # idempotent re-run, as setup does on every deploy
        yield {"psql": psql, "network": network, "container": container}
    finally:
        subprocess.run(["docker", "rm", "-f", container], capture_output=True)
        subprocess.run(["docker", "network", "rm", network], capture_output=True)


def _changes(psql, scope: str) -> list[tuple[int, str, int]]:
    rows = psql(f"SELECT revision, coalesce(chat_id,''), kinds FROM chat_sync_changes WHERE scope = '{scope}' ORDER BY revision")
    return [(int(r), c, int(k)) for r, c, k in (line.split("|") for line in rows.splitlines() if line)]


# contract-test: supporting surface=rest_api assertions=sync.delta.cursor-gap-free
def test_triggers_record_gap_free_revisions_per_scope(database):
    psql = database["psql"]
    user, chat = str(uuid.uuid4()), str(uuid.uuid4())
    personal = f"personal:{_h(user)}"
    psql(f"""
        INSERT INTO chats (id, hashed_user_id, messages_v, title_v, pinned) VALUES ('{chat}', '{_h(user)}', 0, 1, false);
        INSERT INTO messages (id, chat_id, hashed_user_id, encrypted_content) VALUES ('{uuid.uuid4()}', '{chat}', '{_h(user)}', 'c');
        UPDATE chats SET budget_spent = 5 WHERE id = '{chat}';
        UPDATE chats SET pinned = true WHERE id = '{chat}';
        UPDATE chats SET messages_v = 2, last_edited_overall_timestamp = 9 WHERE id = '{chat}';
        UPDATE messages SET encrypted_content = 'c' WHERE chat_id = '{chat}';
        UPDATE messages SET encrypted_content = 'edited' WHERE chat_id = '{chat}';
        BEGIN; UPDATE chats SET title_v = 7 WHERE id = '{chat}'; ROLLBACK;
    """)
    changes = _changes(psql, personal)
    assert [revision for revision, _, _ in changes] == list(range(1, len(changes) + 1))
    assert [kinds for _, _, kinds in changes] == [1, 2, 1, 3, 2]
    assert psql(f"SELECT revision FROM chat_sync_clocks WHERE scope = '{personal}'") == str(len(changes))


# contract-test: supporting surface=rest_api assertions=sync.delta.scope-revocation
def test_move_records_old_and_new_scope_and_delete_records_tombstone(database):
    psql = database["psql"]
    user, team, chat = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    psql(f"""
        INSERT INTO chats (id, hashed_user_id) VALUES ('{chat}', '{_h(user)}');
        UPDATE chats SET hashed_team_id = '{_h(team)}' WHERE id = '{chat}';
        DELETE FROM chats WHERE id = '{chat}';
        INSERT INTO chat_recovery_chat_deletion_fences (id, hashed_user_id, chat_id) VALUES ('{uuid.uuid4()}', '{_h(user)}', '{chat}');
    """)
    assert [k for _, _, k in _changes(psql, f"personal:{_h(user)}")] == [1, 128, 32]
    assert [k for _, _, k in _changes(psql, f"team:{_h(team)}")] == [1 | 2 | 8 | 128, 32]


# contract-test: supporting surface=rest_api assertions=sync.overview.cross-device
def test_user_lane_records_drafts_last_opened_and_due_soon_inputs(database):
    psql = database["psql"]
    user, chat = str(uuid.uuid4()), str(uuid.uuid4())
    psql(f"""
        INSERT INTO directus_users (id, last_opened) VALUES ('{user}', '/signup/one_time_codes');
        INSERT INTO chats (id, hashed_user_id) VALUES ('{chat}', '{_h(user)}');
        INSERT INTO drafts (id, chat_id, hashed_user_id, encrypted_content, version) VALUES ('{uuid.uuid4()}', '{chat}', '{_h(user)}', 'd', 1);
        UPDATE directus_users SET credits = 3 WHERE id = '{user}';
        UPDATE directus_users SET last_opened = '/chat/{chat.upper()}' WHERE id = '{user}';
        UPDATE directus_users SET last_opened = '/chat/new' WHERE id = '{user}';
        INSERT INTO reminders (id, hashed_user_id, trigger_at, status) VALUES ('{uuid.uuid4()}', '{_h(user)}', 1, 'pending');
        INSERT INTO user_app_settings_and_memories (id, hashed_user_id, app_id, item_type) VALUES ('{uuid.uuid4()}', '{_h(user)}', 'health', 'appointments');
        INSERT INTO user_app_settings_and_memories (id, hashed_user_id, app_id, item_type) VALUES ('{uuid.uuid4()}', '{_h(user)}', 'code', 'preferences');
    """)
    assert _changes(psql, f"user:{_h(user)}") == [(1, chat, 16), (2, chat, 256), (3, "", 256), (4, "", 512), (5, "", 512)]


# contract-test: supporting surface=rest_api assertions=sync.delta.metadata-only
def test_hashed_sources_resolve_chat_and_bulk_delete_coalesces(database):
    psql = database["psql"]
    user, chat = str(uuid.uuid4()), str(uuid.uuid4())
    personal = f"personal:{_h(user)}"
    psql(f"""
        INSERT INTO chats (id, hashed_user_id) VALUES ('{chat}', '{_h(user)}');
        INSERT INTO chat_key_wrappers (id, hashed_chat_id, hashed_user_id) VALUES ('{uuid.uuid4()}', '{_h(chat)}', '{_h(user)}');
        INSERT INTO embeds (id, embed_id, hashed_chat_id, status) VALUES ('{uuid.uuid4()}', 'e1', '{_h(chat)}', 'processing');
        UPDATE embeds SET status = 'finished' WHERE embed_id = 'e1';
        INSERT INTO embed_keys (id, hashed_chat_id) VALUES ('{uuid.uuid4()}', '{_h(chat)}');
        INSERT INTO embeds (id, embed_id, hashed_chat_id) VALUES ('{uuid.uuid4()}', 'orphan', '{_h('missing')}');
        INSERT INTO messages (id, chat_id, encrypted_content) SELECT gen_random_uuid(), '{chat}', 'm' FROM generate_series(1, 50);
        DELETE FROM messages WHERE chat_id = '{chat}';
    """)
    kinds = [k for _, _, k in _changes(psql, personal)]
    # One row per statement: embed insert, status update and key insert each
    # commit separately; the 50-row insert and the bulk delete coalesce.
    assert kinds == [1, 8, 4, 4, 4, 2, 2]
    stored = psql("SELECT string_agg(column_name, ',' ORDER BY column_name) FROM information_schema.columns WHERE table_name = 'chat_sync_changes'")
    assert stored == "chat_id,created_at,hashed_chat_id,kinds,revision,scope"


# contract-test: supporting surface=rest_api assertions=sync.delta.cursor-gap-free,sync.delta.reset,sync.delta.metadata-only,sync.overview.cross-device
def test_extension_pages_replay_reset_and_hydrate(database):
    result = subprocess.run(
        ["docker", "run", "--rm", "--network", database["network"], "--entrypoint", "node",
         "-v", f"{EXTENSION}:/ext:ro", "-e", f"KNEX_PATH={KNEX_PATH}",
         "-e", f"DATABASE_URL=postgres://postgres:test@{database['container']}:5432/feed",
         DIRECTUS_IMAGE, "/ext/test/db_scenarios.mjs"],
        capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    out = json.loads(result.stdout.strip().splitlines()[-1])
    assert out["cold_cursor_parts"] == 2
    assert out["first"]["has_more"] is True
    # A page costs a fixed number of batched queries, independent of chat count.
    assert out["first"]["queries"] <= 16
    assert out["chat_ids_seen"] == out["expected_chat_ids"]
    assert out["last_opened"] == {"chat_id": out["expected_last_opened"]}
    assert out["due_soon_changed"] is True and out["saved_items"] == ["cipher-item"]
    assert [True, "cipher-draft", 3] in out["drafts"]
    # Wrappers accompany every page that mentions the chat (at-least-once).
    assert out["wrappers"] and all(out["wrappers"])
    assert out["message_fields_absent"] is True
    assert out["caught_up"] == {"changes": 0, "has_more": False}
    by_chat = {chat_id: kinds for chat_id, _, kinds in out["after_move_delete"]}
    assert "moved" in by_chat[out["expected_moved"]]
    assert "deleted" in by_chat[out["expected_deleted"]]
    assert out["moved_row_hidden"] is True
    assert [out["expected_moved"], ["metadata", "messages", "keys", "moved"]] in out["team_page"]
    assert out["team_rows"] == [out["expected_moved"]]
    assert out["resets"] == [True, True, True, True]
    assert out["expired_reset"] is True and out["current_not_reset"] is False
    assert out["overview"] == {"chat": True, "saved_items": 1}
    assert out["team_overview"] == {"chat": None, "saved_items": None}
