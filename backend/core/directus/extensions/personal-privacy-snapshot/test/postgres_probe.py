"""Runner-only disposable Postgres probe; never call against a shared database.

Executed by the isolated Playwright fixture inside its cms-setup image. Proves
row-lock serialization with a competing SQL writer and generation triggers for
SQL imports, updates, deletes, Team exclusion, settings and counter resets.
"""

import hashlib
import json
import threading
import time
import uuid

from setup_schemas import connect_database


def run(data):
    owner = data["user_id"]
    owner_hash = hashlib.sha256(owner.encode()).hexdigest()
    row_id = str(uuid.uuid4())
    finished = threading.Event()
    started = threading.Event()
    failure = []
    writer_pid = []
    reader = connect_database()
    writer = connect_database()
    inspector = connect_database()
    inspector.autocommit = True

    def generation(connection):
        return connection.execute(
            "SELECT epoch::text, generation FROM personal_privacy_generations WHERE owner_hash=%s",
            (owner_hash,),
        ).fetchone()

    try:
        before = generation(reader)
        assert before is not None
        reader.execute(
            "SELECT generation FROM personal_privacy_generations WHERE owner_hash=%s FOR SHARE",
            (owner_hash,),
        )

        def mutate():
            try:
                writer_pid.append(
                    writer.execute("SELECT pg_backend_pid()").fetchone()[0]
                )
                started.set()
                writer.execute(
                    "INSERT INTO user_app_settings_and_memories(id,hashed_user_id,hashed_team_id,app_id,item_type,item_key,encrypted_item_json,item_version) VALUES(%s,%s,NULL,'code','test',%s,'synthetic-opaque',1)",
                    (row_id, owner_hash, row_id),
                )
                writer.commit()
            except BaseException as error:
                failure.append(error)
            finally:
                finished.set()

        thread = threading.Thread(target=mutate, daemon=True)
        thread.start()
        assert started.wait(5)
        deadline = time.monotonic() + 5
        blocked = False
        while time.monotonic() < deadline and not finished.is_set():
            wait = inspector.execute(
                "SELECT wait_event_type FROM pg_stat_activity WHERE pid=%s",
                (writer_pid[0],),
            ).fetchone()
            if wait and wait[0] == "Lock":
                blocked = True
                break
            finished.wait(0.01)
        assert blocked, "Concurrent memory commit must wait for the snapshot clock lock"
        assert generation(reader) == before
        assert (
            reader.execute(
                "SELECT id FROM user_app_settings_and_memories WHERE id=%s", (row_id,)
            ).fetchone()
            is None
        )
        reader.commit()
        assert finished.wait(5)
        thread.join(1)
        if failure:
            raise failure[0]
        after_insert = generation(reader)
        assert after_insert[1] == before[1] + 1
        reader.execute(
            "UPDATE user_app_settings_and_memories SET encrypted_item_json='synthetic-updated' WHERE id=%s",
            (row_id,),
        )
        assert generation(reader)[1] == after_insert[1] + 1
        reader.execute(
            "DELETE FROM user_app_settings_and_memories WHERE id=%s", (row_id,)
        )
        assert generation(reader)[1] == after_insert[1] + 2
        # Team rows never change the Personal owner's clock.
        reader.execute(
            "INSERT INTO user_app_settings_and_memories(id,hashed_user_id,hashed_team_id,app_id,item_type,item_key,encrypted_item_json,item_version) VALUES(%s,%s,%s,'code','test',%s,'synthetic-team',1)",
            (row_id, owner_hash, "f" * 64, row_id),
        )
        assert generation(reader)[1] == after_insert[1] + 2
        reader.execute(
            "DELETE FROM user_app_settings_and_memories WHERE id=%s", (row_id,)
        )
        settings = reader.execute(
            "SELECT encrypted_settings FROM directus_users WHERE id=%s", (owner,)
        ).fetchone()[0]
        reader.execute(
            "UPDATE directus_users SET encrypted_settings='synthetic-opaque-settings' WHERE id=%s",
            (owner,),
        )
        assert generation(reader)[1] == after_insert[1] + 3
        reader.execute(
            "UPDATE directus_users SET encrypted_settings=%s WHERE id=%s",
            (settings, owner),
        )
        assert generation(reader)[1] == after_insert[1] + 4
        original = generation(reader)
        reader.execute(
            "UPDATE personal_privacy_generations SET generation=0 WHERE owner_hash=%s",
            (owner_hash,),
        )
        assert generation(reader)[0] != original[0]
        # Roll back temporary settings/team/reset probes; committed concurrent
        # import is removed in finally, preserving only correct generation bumps.
        reader.rollback()
        return {
            "concurrent_snapshot_commit_fence": True,
            "sql_import_update_delete": True,
            "team_excluded": True,
            "settings_write": True,
            "reset_epoch": True,
        }
    finally:
        reader.rollback()
        writer.rollback()
        reader.execute(
            "DELETE FROM user_app_settings_and_memories WHERE id=%s", (row_id,)
        )
        reader.commit()
        reader.close()
        writer.close()
        inspector.close()


if __name__ == "__main__":
    import sys

    print(json.dumps(run(json.load(sys.stdin))))
