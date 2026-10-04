-- Additive owner compatibility and indexes; no data removal or retention change.
CREATE EXTENSION IF NOT EXISTS pgcrypto;
-- Team chats are owned by hashed_team_id and may have no hashed_user_id.
ALTER TABLE chat_message_archive_segments ALTER COLUMN hashed_user_id DROP NOT NULL;
ALTER TABLE chat_message_archive_pages ALTER COLUMN hashed_user_id DROP NOT NULL;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chat_message_archive_segments_owner_ck') THEN
    ALTER TABLE chat_message_archive_segments ADD CONSTRAINT chat_message_archive_segments_owner_ck
      CHECK (hashed_user_id IS NOT NULL OR hashed_team_id IS NOT NULL) NOT VALID;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chat_message_archive_pages_owner_ck') THEN
    ALTER TABLE chat_message_archive_pages ADD CONSTRAINT chat_message_archive_pages_owner_ck
      CHECK (hashed_user_id IS NOT NULL OR hashed_team_id IS NOT NULL) NOT VALID;
  END IF;
END $$;
CREATE INDEX IF NOT EXISTS chat_message_archive_segments_team_owner_idx
  ON chat_message_archive_segments (hashed_team_id, id) WHERE hashed_team_id IS NOT NULL;
-- Earlier page metadata had only the creator hash. Recover its Team scope from
-- the segment before account deletion filters rely on the new owner column.
UPDATE chat_message_archive_pages AS page
SET hashed_team_id = segment.hashed_team_id
FROM chat_message_archive_segments AS segment
WHERE page.segment_id = segment.id
  AND page.hashed_team_id IS NULL
  AND segment.hashed_team_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS chat_message_archive_segments_checkpoint_uq
  ON chat_message_archive_segments (chat_id, checkpoint_id);
CREATE INDEX IF NOT EXISTS chat_message_archive_segments_state_idx
  ON chat_message_archive_segments (state, lease_until, id);
CREATE INDEX IF NOT EXISTS chat_message_archive_segments_prune_due_idx
  ON chat_message_archive_segments (source_copy_until, id) WHERE state = 'reader_active';
CREATE UNIQUE INDEX IF NOT EXISTS chat_message_archive_pages_number_uq
  ON chat_message_archive_pages (segment_id, page_number);
CREATE INDEX IF NOT EXISTS chat_message_archive_pages_window_idx
  ON chat_message_archive_pages (chat_id, last_timestamp DESC, last_message_id DESC)
  WHERE read_enabled;
CREATE INDEX IF NOT EXISTS chat_message_archive_pages_first_window_idx
  ON chat_message_archive_pages (chat_id, first_timestamp, first_message_id, id)
  WHERE read_enabled;
CREATE INDEX IF NOT EXISTS chat_message_archive_pages_position_missing_idx
  ON chat_message_archive_pages (chat_id, id)
  WHERE read_enabled AND message_positions IS NULL;
CREATE INDEX IF NOT EXISTS chat_message_archive_pages_owner_idx
  ON chat_message_archive_pages (hashed_user_id, id);
CREATE INDEX IF NOT EXISTS chat_message_archive_pages_team_owner_idx
  ON chat_message_archive_pages (hashed_team_id, id) WHERE hashed_team_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS chat_message_archive_pages_ids_idx
  ON chat_message_archive_pages USING gin ((message_ids::jsonb));
CREATE INDEX IF NOT EXISTS chat_message_archive_pages_reader_pending_idx
  ON chat_message_archive_pages (segment_id, page_number) WHERE NOT reader_verified;
CREATE INDEX IF NOT EXISTS chat_message_archive_pages_prune_pending_idx
  ON chat_message_archive_pages (segment_id, page_number) WHERE NOT pruned;
CREATE INDEX IF NOT EXISTS chat_compression_checkpoints_archive_pending_idx
  ON chat_compression_checkpoints (id)
  WHERE covered_message_ids IS NOT NULL AND compressed_up_to_message_id IS NOT NULL;

-- Serialize new Project links with account chat deletion fences. The target
-- hash is client supplied, so resolve it against a locked canonical chat row.
CREATE INDEX IF NOT EXISTS chats_storage_hashed_id_idx
  ON chats ((encode(digest(id::text, 'sha256'), 'hex')));
CREATE INDEX IF NOT EXISTS project_items_chat_target_guard_idx
  ON project_items (target_id_hash, id)
  WHERE item_type = 'chat' AND deleted_target_state IS NULL;
CREATE INDEX IF NOT EXISTS upload_files_storage_hashed_id_idx
  ON upload_files ((encode(digest(id::text, 'sha256'), 'hex')));
CREATE INDEX IF NOT EXISTS upload_files_storage_hashed_embed_idx
  ON upload_files ((encode(digest(embed_id, 'sha256'), 'hex')))
  WHERE embed_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS project_items_upload_target_guard_idx
  ON project_items (target_id_hash, id)
  WHERE item_type = 'upload' AND deleted_target_state IS NULL;
CREATE INDEX IF NOT EXISTS embeds_storage_hashed_id_idx
  ON embeds ((encode(digest(embed_id, 'sha256'), 'hex')), id);
CREATE INDEX IF NOT EXISTS project_items_embed_target_guard_idx
  ON project_items (target_id_hash, id)
  WHERE item_type = 'embed' AND deleted_target_state IS NULL;
CREATE INDEX IF NOT EXISTS embed_keys_storage_reference_guard_idx
  ON embed_keys (hashed_embed_id, id);

CREATE OR REPLACE FUNCTION guard_project_item_chat_target_deletion()
RETURNS trigger AS $$
DECLARE target_state text;
BEGIN
  IF NEW.item_type <> 'chat' THEN
    RETURN NEW;
  END IF;
  IF TG_OP = 'UPDATE' THEN
    IF NEW.item_type IS NOT DISTINCT FROM OLD.item_type AND
       NEW.target_id_hash IS NOT DISTINCT FROM OLD.target_id_hash AND
       NEW.hashed_user_id IS NOT DISTINCT FROM OLD.hashed_user_id AND
       NEW.hashed_team_id IS NOT DISTINCT FROM OLD.hashed_team_id AND
       NEW.deleted_target_state IS NOT DISTINCT FROM OLD.deleted_target_state THEN
      RETURN NEW;
    END IF;
  END IF;
  SELECT storage_state INTO target_state FROM chats
  WHERE encode(digest(id::text, 'sha256'), 'hex') = NEW.target_id_hash
  FOR UPDATE;
  IF NOT FOUND OR target_state = 'deleting' THEN
    RAISE EXCEPTION 'project_chat_target_unavailable' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION guard_account_chat_deletion_project_refs()
RETURNS trigger AS $$
BEGIN
  IF NEW.storage_state = 'deleting' AND OLD.storage_state IS DISTINCT FROM 'deleting'
      AND NEW.hashed_team_id IS NULL AND EXISTS (
        SELECT 1 FROM project_items item
        WHERE item.item_type = 'chat'
          AND item.target_id_hash = encode(digest(NEW.id::text, 'sha256'), 'hex')
          AND item.deleted_target_state IS NULL
          AND (item.hashed_team_id IS NOT NULL
               OR item.hashed_user_id IS DISTINCT FROM NEW.hashed_user_id)
      ) THEN
    RAISE EXCEPTION 'account_chat_has_surviving_project_reference' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION guard_project_item_upload_target_deletion()
RETURNS trigger AS $$
DECLARE target_ids uuid[];
BEGIN
  IF NEW.item_type <> 'upload' THEN
    RETURN NEW;
  END IF;
  IF TG_OP = 'UPDATE' THEN
    IF NEW.item_type IS NOT DISTINCT FROM OLD.item_type AND
       NEW.target_id_hash IS NOT DISTINCT FROM OLD.target_id_hash AND
       NEW.hashed_user_id IS NOT DISTINCT FROM OLD.hashed_user_id AND
       NEW.hashed_team_id IS NOT DISTINCT FROM OLD.hashed_team_id AND
       NEW.deleted_target_state IS NOT DISTINCT FROM OLD.deleted_target_state THEN
      RETURN NEW;
    END IF;
  END IF;
  SELECT array_agg(id) INTO target_ids FROM (
    SELECT id FROM upload_files
    WHERE encode(digest(id::text, 'sha256'), 'hex') = NEW.target_id_hash
       OR encode(digest(embed_id, 'sha256'), 'hex') = NEW.target_id_hash
    FOR UPDATE
  ) AS matching_uploads;
  IF COALESCE(array_length(target_ids, 1), 0) <> 1 THEN
    RAISE EXCEPTION 'project_upload_target_unavailable' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION guard_account_upload_deletion_project_refs()
RETURNS trigger AS $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM project_items item
    WHERE item.item_type = 'upload'
      AND item.target_id_hash IN (
        encode(digest(OLD.id::text, 'sha256'), 'hex'),
        encode(digest(OLD.embed_id, 'sha256'), 'hex'))
      AND item.deleted_target_state IS NULL
      AND (item.hashed_team_id IS NOT NULL
           OR item.hashed_user_id IS DISTINCT FROM encode(digest(OLD.user_id, 'sha256'), 'hex'))
  ) THEN
    RAISE EXCEPTION 'account_upload_has_surviving_project_reference' USING ERRCODE = '23514';
  END IF;
  RETURN OLD;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION guard_project_item_embed_target_deletion()
RETURNS trigger AS $$
DECLARE target_ids uuid[];
BEGIN
  IF NEW.item_type <> 'embed' THEN
    RETURN NEW;
  END IF;
  IF TG_OP = 'UPDATE' THEN
    IF NEW.item_type IS NOT DISTINCT FROM OLD.item_type AND
       NEW.target_id_hash IS NOT DISTINCT FROM OLD.target_id_hash AND
       NEW.hashed_user_id IS NOT DISTINCT FROM OLD.hashed_user_id AND
       NEW.hashed_team_id IS NOT DISTINCT FROM OLD.hashed_team_id AND
       NEW.deleted_target_state IS NOT DISTINCT FROM OLD.deleted_target_state THEN
      RETURN NEW;
    END IF;
  END IF;
  SELECT array_agg(id) INTO target_ids FROM (
    SELECT id FROM embeds
    WHERE encode(digest(embed_id, 'sha256'), 'hex') = NEW.target_id_hash
    FOR UPDATE
  ) AS matching_embeds;
  IF COALESCE(array_length(target_ids, 1), 0) <> 1 THEN
    RAISE EXCEPTION 'project_embed_target_unavailable' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION guard_account_embed_deletion_project_refs()
RETURNS trigger AS $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM project_items item
    WHERE item.item_type = 'embed'
      AND item.target_id_hash = encode(digest(OLD.embed_id, 'sha256'), 'hex')
      AND item.deleted_target_state IS NULL
      AND (item.hashed_team_id IS NOT NULL
           OR item.hashed_user_id IS DISTINCT FROM OLD.hashed_user_id)
  ) OR EXISTS (
    SELECT 1 FROM project_items item
    WHERE item.item_type = 'embed'
      AND item.target_id_hash = encode(digest(OLD.embed_id, 'sha256'), 'hex')
      AND item.deleted_target_state IS NULL
      AND item.hashed_team_id IS NULL
      AND item.hashed_user_id = OLD.hashed_user_id
      AND NOT EXISTS (
        SELECT 1 FROM chat_recovery_account_fences account_fence
        WHERE account_fence.id = OLD.hashed_user_id
      )
  ) THEN
    RAISE EXCEPTION 'account_embed_has_surviving_project_reference' USING ERRCODE = '23514';
  END IF;
  IF EXISTS (
    SELECT 1 FROM embed_keys wrapper
    WHERE wrapper.hashed_embed_id = encode(digest(OLD.embed_id, 'sha256'), 'hex')
      AND (
        (wrapper.key_type = 'master' AND wrapper.hashed_user_id = OLD.hashed_user_id)
        OR (wrapper.key_type = 'chat' AND wrapper.hashed_team_id IS NULL
            AND wrapper.hashed_project_id IS NULL AND wrapper.hashed_plan_id IS NULL
            AND EXISTS (
              SELECT 1 FROM chats chat
              WHERE encode(digest(chat.id::text, 'sha256'), 'hex') = wrapper.hashed_chat_id
                AND chat.hashed_user_id = OLD.hashed_user_id
                AND chat.hashed_team_id IS NULL
            ))
        OR (wrapper.key_type = 'chat'
            AND wrapper.hashed_project_id IS NULL AND wrapper.hashed_plan_id IS NULL
            AND EXISTS (
              SELECT 1 FROM chats retiring_chat
              WHERE encode(digest(retiring_chat.id::text, 'sha256'), 'hex') = wrapper.hashed_chat_id
                AND retiring_chat.storage_state = 'deleting'
                AND (wrapper.hashed_team_id IS NULL
                     OR wrapper.hashed_team_id = retiring_chat.hashed_team_id)
            ))
      ) IS NOT TRUE
  ) THEN
    RAISE EXCEPTION 'account_embed_has_surviving_key_wrapper' USING ERRCODE = '23514';
  END IF;
  RETURN OLD;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION guard_embed_key_parent_deletion()
RETURNS trigger AS $$
DECLARE target_ids uuid[];
BEGIN
  IF TG_OP = 'UPDATE' THEN
    IF NEW.hashed_embed_id IS NOT DISTINCT FROM OLD.hashed_embed_id AND
       NEW.key_type IS NOT DISTINCT FROM OLD.key_type AND
       NEW.hashed_user_id IS NOT DISTINCT FROM OLD.hashed_user_id AND
       NEW.hashed_chat_id IS NOT DISTINCT FROM OLD.hashed_chat_id AND
       NEW.hashed_team_id IS NOT DISTINCT FROM OLD.hashed_team_id AND
       NEW.hashed_project_id IS NOT DISTINCT FROM OLD.hashed_project_id AND
       NEW.hashed_plan_id IS NOT DISTINCT FROM OLD.hashed_plan_id THEN
      RETURN NEW;
    END IF;
  END IF;
  SELECT array_agg(id) INTO target_ids FROM (
    SELECT id FROM embeds
    WHERE encode(digest(embed_id, 'sha256'), 'hex') = NEW.hashed_embed_id
    FOR UPDATE
  ) AS matching_embeds;
  IF COALESCE(array_length(target_ids, 1), 0) <> 1 THEN
    RAISE EXCEPTION 'embed_key_parent_unavailable' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'project_items_chat_target_deletion_guard') THEN
    CREATE TRIGGER project_items_chat_target_deletion_guard
      BEFORE INSERT OR UPDATE ON project_items FOR EACH ROW
      EXECUTE FUNCTION guard_project_item_chat_target_deletion();
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'account_chat_deletion_project_ref_guard') THEN
    CREATE TRIGGER account_chat_deletion_project_ref_guard
      BEFORE UPDATE ON chats FOR EACH ROW
      EXECUTE FUNCTION guard_account_chat_deletion_project_refs();
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'project_items_upload_target_deletion_guard') THEN
    CREATE TRIGGER project_items_upload_target_deletion_guard
      BEFORE INSERT OR UPDATE ON project_items FOR EACH ROW
      EXECUTE FUNCTION guard_project_item_upload_target_deletion();
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'account_upload_deletion_project_ref_guard') THEN
    CREATE TRIGGER account_upload_deletion_project_ref_guard
      BEFORE DELETE ON upload_files FOR EACH ROW
      EXECUTE FUNCTION guard_account_upload_deletion_project_refs();
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'project_items_embed_target_deletion_guard') THEN
    CREATE TRIGGER project_items_embed_target_deletion_guard
      BEFORE INSERT OR UPDATE ON project_items FOR EACH ROW
      EXECUTE FUNCTION guard_project_item_embed_target_deletion();
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'account_embed_deletion_project_ref_guard') THEN
    CREATE TRIGGER account_embed_deletion_project_ref_guard
      BEFORE DELETE ON embeds FOR EACH ROW
      EXECUTE FUNCTION guard_account_embed_deletion_project_refs();
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'embed_keys_parent_deletion_guard') THEN
    CREATE TRIGGER embed_keys_parent_deletion_guard
      BEFORE INSERT OR UPDATE ON embed_keys FOR EACH ROW
      EXECUTE FUNCTION guard_embed_key_parent_deletion();
  END IF;
END $$;
