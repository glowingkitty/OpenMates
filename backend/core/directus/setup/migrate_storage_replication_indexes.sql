-- Required identities and bounded due-work scans for regional object storage.
-- Run after cms-setup creates replication jobs, tombstones, and health state.
-- PostgreSQL aborts if existing duplicate identities violate safety.
BEGIN;

CREATE UNIQUE INDEX IF NOT EXISTS storage_replication_jobs_identity_uq
  ON storage_replication_jobs (idempotency_key);
CREATE INDEX IF NOT EXISTS storage_replication_jobs_due_idx
  ON storage_replication_jobs (next_attempt_at, created_at)
  WHERE state IN ('pending', 'retry_scheduled');

CREATE UNIQUE INDEX IF NOT EXISTS storage_deletion_tombstones_identity_uq
  ON storage_deletion_tombstones (idempotency_key);
CREATE INDEX IF NOT EXISTS storage_deletion_tombstones_due_idx
  ON storage_deletion_tombstones (next_attempt_at, created_at)
  WHERE state IN ('pending', 'retry_scheduled');

CREATE UNIQUE INDEX IF NOT EXISTS storage_region_health_region_uq
  ON storage_region_health (region);

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE OR REPLACE FUNCTION enforce_chat_graph_storage_state()
RETURNS trigger AS $$
DECLARE
  target_chat_id text;
  root_chat_id uuid;
  root_storage_state text;
BEGIN
  target_chat_id := NEW.chat_id::text;
  WITH RECURSIVE lineage AS (
    SELECT id, parent_id, storage_state
    FROM chats
    WHERE id::text = target_chat_id
    UNION ALL
    SELECT parent.id, parent.parent_id, parent.storage_state
    FROM chats parent
    JOIN lineage child ON parent.id = child.parent_id
  )
  SELECT id INTO root_chat_id FROM lineage WHERE parent_id IS NULL LIMIT 1;
  SELECT storage_state INTO root_storage_state
  FROM chats WHERE id = root_chat_id FOR SHARE;
  IF root_storage_state IN ('archiving', 'cold', 'deleting') THEN
    RAISE EXCEPTION 'chat_graph_storage_transition';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_hashed_chat_graph_storage_state()
RETURNS trigger AS $$
DECLARE
  root_chat_id uuid;
  root_storage_state text;
BEGIN
  IF NEW.hashed_chat_id IS NULL THEN
    RETURN NEW;
  END IF;
  WITH RECURSIVE lineage AS (
    SELECT id, parent_id, storage_state
    FROM chats
    WHERE encode(digest(id::text, 'sha256'), 'hex') = NEW.hashed_chat_id
    UNION ALL
    SELECT parent.id, parent.parent_id, parent.storage_state
    FROM chats parent
    JOIN lineage child ON parent.id = child.parent_id
  )
  SELECT id INTO root_chat_id FROM lineage WHERE parent_id IS NULL LIMIT 1;
  SELECT storage_state INTO root_storage_state
  FROM chats WHERE id = root_chat_id FOR SHARE;
  IF root_storage_state IN ('archiving', 'cold', 'deleting') THEN
    RAISE EXCEPTION 'chat_graph_storage_transition';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_sub_chat_storage_state()
RETURNS trigger AS $$
DECLARE
  root_chat_id uuid;
  root_storage_state text;
BEGIN
  IF NEW.parent_id IS NULL THEN
    RETURN NEW;
  END IF;
  WITH RECURSIVE lineage AS (
    SELECT id, parent_id, storage_state FROM chats WHERE id = NEW.parent_id
    UNION ALL
    SELECT parent.id, parent.parent_id, parent.storage_state
    FROM chats parent
    JOIN lineage child ON parent.id = child.parent_id
  )
  SELECT id INTO root_chat_id FROM lineage WHERE parent_id IS NULL LIMIT 1;
  SELECT storage_state INTO root_storage_state
  FROM chats WHERE id = root_chat_id FOR SHARE;
  IF root_storage_state IN ('archiving', 'cold', 'deleting') THEN
    RAISE EXCEPTION 'chat_graph_storage_transition';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$
DECLARE
  table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'messages', 'drafts', 'chat_compression_checkpoints',
    'code_run_outputs', 'notebook_run_outputs', 'message_highlights'
  ] LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS %I ON %I', 'guard_chat_graph_storage_state', table_name);
    EXECUTE format(
      'CREATE TRIGGER %I BEFORE INSERT OR UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION enforce_chat_graph_storage_state()',
      'guard_chat_graph_storage_state',
      table_name
    );
  END LOOP;

  FOREACH table_name IN ARRAY ARRAY['embeds', 'embed_keys', 'chat_key_wrappers'] LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS %I ON %I', 'guard_hashed_chat_graph_storage_state', table_name);
    EXECUTE format(
      'CREATE TRIGGER %I BEFORE INSERT OR UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION enforce_hashed_chat_graph_storage_state()',
      'guard_hashed_chat_graph_storage_state',
      table_name
    );
  END LOOP;
END;
$$;

DROP TRIGGER IF EXISTS guard_sub_chat_storage_state ON chats;
CREATE TRIGGER guard_sub_chat_storage_state
  BEFORE INSERT OR UPDATE OF parent_id ON chats
  FOR EACH ROW EXECUTE FUNCTION enforce_sub_chat_storage_state();

COMMIT;
