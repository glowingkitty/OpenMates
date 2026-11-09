-- Chat sync feed (architecture.sync@2): durable per-scope change log.
--
-- Every committed change to a chat's metadata, transcript, keys, embeds,
-- drafts, deletion fences, the user's last opened chat or the due-soon inputs
-- appends one row (ids and kinds only, never content) under a per-scope clock.
-- The clock row stays locked until commit, so revisions become visible in
-- commit order without gaps; a reader that sees committed revision R may read
-- every row <= R. pg_notify delivers a content-free hint after commit only.
-- Scopes: personal:<sha256(user)>, team:<sha256(team)>, user:<sha256(user)>
-- (the user lane: drafts, last opened chat and due-soon inputs).
-- Kinds bitmask: 1 metadata, 2 messages, 4 content, 8 keys, 16 draft,
-- 32 deleted, 64 revoked, 128 moved, 256 last_opened, 512 due_soon.
-- Read path: backend/core/directus/extensions/chat-sync/src/operations.js.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS chat_sync_clocks (
    scope text PRIMARY KEY,
    revision bigint NOT NULL DEFAULT 0,
    epoch uuid NOT NULL DEFAULT gen_random_uuid()
);
CREATE TABLE IF NOT EXISTS chat_sync_changes (
    scope text NOT NULL,
    revision bigint NOT NULL,
    chat_id text,
    hashed_chat_id text,
    kinds smallint NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (scope, revision)
);
CREATE INDEX IF NOT EXISTS chat_sync_changes_retention_idx
    ON chat_sync_changes (created_at);
CREATE INDEX IF NOT EXISTS chats_storage_hashed_id_idx
    ON chats ((encode(digest(id::text, 'sha256'), 'hex')));

CREATE OR REPLACE FUNCTION chat_sync_scope(owner_hash text, team_hash text)
RETURNS text AS $$
    SELECT CASE
        WHEN NULLIF(team_hash, '') IS NOT NULL THEN 'team:' || team_hash
        WHEN NULLIF(owner_hash, '') IS NOT NULL THEN 'personal:' || owner_hash
        ELSE NULL END;
$$ LANGUAGE sql IMMUTABLE;

CREATE OR REPLACE FUNCTION chat_sync_is_uuid(value text)
RETURNS boolean AS $$
    SELECT value ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$';
$$ LANGUAGE sql IMMUTABLE;

CREATE OR REPLACE FUNCTION chat_sync_record(scope_key text, changed_chat_id text, changed_hash text, change_kinds integer)
RETURNS void AS $$
DECLARE next_revision bigint; dedupe_key text;
BEGIN
    IF scope_key IS NULL OR change_kinds IS NULL OR change_kinds = 0 THEN RETURN; END IF;
    -- Bulk statements (deleting a long transcript) repeat the same change; the
    -- transaction commits atomically, so one row describes all of them.
    dedupe_key := scope_key || '|' || COALESCE(changed_chat_id, changed_hash, '') || '|' || change_kinds;
    IF current_setting('openmates.chat_sync_last', true) = dedupe_key THEN RETURN; END IF;
    PERFORM set_config('openmates.chat_sync_last', dedupe_key, true);
    INSERT INTO chat_sync_clocks(scope, revision) VALUES (scope_key, 1)
    ON CONFLICT (scope) DO UPDATE SET revision = chat_sync_clocks.revision + 1
    RETURNING revision INTO next_revision;
    INSERT INTO chat_sync_changes(scope, revision, chat_id, hashed_chat_id, kinds)
    VALUES (scope_key, next_revision, changed_chat_id,
            COALESCE(changed_hash, CASE WHEN changed_chat_id IS NULL THEN NULL
                     ELSE encode(digest(changed_chat_id, 'sha256'), 'hex') END),
            change_kinds);
    PERFORM pg_notify('openmates_chat_sync', scope_key || '|' || next_revision);
END;
$$ LANGUAGE plpgsql;

-- Records a change for the chat identified by its hash (wrappers, embeds, keys).
CREATE OR REPLACE FUNCTION chat_sync_record_hashed(chat_hash text, change_kinds integer)
RETURNS void AS $$
DECLARE target record;
BEGIN
    IF chat_hash IS NULL OR chat_hash = '' THEN RETURN; END IF;
    SELECT id, hashed_user_id, hashed_team_id INTO target FROM chats
    WHERE encode(digest(id::text, 'sha256'), 'hex') = chat_hash LIMIT 1;
    -- A wrapper/embed written before its chat row is covered by the chat insert.
    IF NOT FOUND THEN RETURN; END IF;
    PERFORM chat_sync_record(chat_sync_scope(target.hashed_user_id, target.hashed_team_id),
                             target.id::text, chat_hash, change_kinds);
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION chat_sync_chat_changed()
RETURNS trigger AS $$
DECLARE old_scope text; new_scope text; change_kinds integer := 0;
BEGIN
    IF TG_OP = 'DELETE' THEN
        PERFORM chat_sync_record(chat_sync_scope(OLD.hashed_user_id, OLD.hashed_team_id), OLD.id::text, NULL, 32);
        RETURN OLD;
    END IF;
    new_scope := chat_sync_scope(NEW.hashed_user_id, NEW.hashed_team_id);
    IF TG_OP = 'INSERT' THEN
        PERFORM chat_sync_record(new_scope, NEW.id::text, NULL, 1);
        RETURN NEW;
    END IF;
    old_scope := chat_sync_scope(OLD.hashed_user_id, OLD.hashed_team_id);
    IF old_scope IS DISTINCT FROM new_scope THEN
        -- The former scope must learn about the removal even though the chat
        -- is no longer readable there; the new scope receives full metadata.
        PERFORM chat_sync_record(old_scope, OLD.id::text, NULL, 128);
        PERFORM chat_sync_record(new_scope, NEW.id::text, NULL, 1 | 2 | 8 | 128);
        RETURN NEW;
    END IF;
    IF NEW.messages_v IS DISTINCT FROM OLD.messages_v
        OR NEW.archive_mutation_v IS DISTINCT FROM OLD.archive_mutation_v THEN
        change_kinds := change_kinds | 2;
    END IF;
    IF NEW.encrypted_chat_key IS DISTINCT FROM OLD.encrypted_chat_key
        OR NEW.participant_key_envelopes::text IS DISTINCT FROM OLD.participant_key_envelopes::text THEN
        change_kinds := change_kinds | 8;
    END IF;
    IF NEW.title_v IS DISTINCT FROM OLD.title_v
        OR NEW.metadata_v IS DISTINCT FROM OLD.metadata_v
        OR NEW.last_edited_overall_timestamp IS DISTINCT FROM OLD.last_edited_overall_timestamp
        OR NEW.pinned IS DISTINCT FROM OLD.pinned
        OR NEW.unread_count IS DISTINCT FROM OLD.unread_count
        OR NEW.chat_visibility IS DISTINCT FROM OLD.chat_visibility
        OR NEW.participant_user_hashes::text IS DISTINCT FROM OLD.participant_user_hashes::text
        OR NEW.parent_id IS DISTINCT FROM OLD.parent_id
        OR NEW.is_sub_chat IS DISTINCT FROM OLD.is_sub_chat
        OR NEW.is_shared IS DISTINCT FROM OLD.is_shared
        OR NEW.is_private IS DISTINCT FROM OLD.is_private
        OR NEW.storage_state IS DISTINCT FROM OLD.storage_state
        OR NEW.budget_limit IS DISTINCT FROM OLD.budget_limit
        OR NEW.encrypted_title IS DISTINCT FROM OLD.encrypted_title
        OR NEW.encrypted_icon IS DISTINCT FROM OLD.encrypted_icon
        OR NEW.encrypted_category IS DISTINCT FROM OLD.encrypted_category
        OR NEW.encrypted_chat_summary IS DISTINCT FROM OLD.encrypted_chat_summary
        OR NEW.encrypted_chat_tags IS DISTINCT FROM OLD.encrypted_chat_tags
        OR NEW.encrypted_share_cta_text IS DISTINCT FROM OLD.encrypted_share_cta_text
        OR NEW.encrypted_shared_short_url IS DISTINCT FROM OLD.encrypted_shared_short_url
        OR NEW.encrypted_follow_up_request_suggestions IS DISTINCT FROM OLD.encrypted_follow_up_request_suggestions
        OR NEW.encrypted_suggested_followup_message IS DISTINCT FROM OLD.encrypted_suggested_followup_message
        OR NEW.encrypted_top_recommended_apps_for_chat IS DISTINCT FROM OLD.encrypted_top_recommended_apps_for_chat
        OR NEW.encrypted_recommendations IS DISTINCT FROM OLD.encrypted_recommendations
        OR NEW.encrypted_active_focus_id IS DISTINCT FROM OLD.encrypted_active_focus_id
        OR NEW.encrypted_focus_phase_state IS DISTINCT FROM OLD.encrypted_focus_phase_state
        OR NEW.encrypted_auto_speak_response IS DISTINCT FROM OLD.encrypted_auto_speak_response THEN
        change_kinds := change_kinds | 1;
    END IF;
    PERFORM chat_sync_record(new_scope, NEW.id::text, NULL, change_kinds);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS chat_sync_chat_trigger ON chats;
DROP TRIGGER IF EXISTS chat_sync_chat_update_trigger ON chats;
CREATE TRIGGER chat_sync_chat_trigger AFTER INSERT OR DELETE ON chats
FOR EACH ROW EXECUTE FUNCTION chat_sync_chat_changed();
-- Only versioned, key, scope, storage and synced encrypted-metadata columns;
-- budget accounting and orchestration timestamps never wake other devices.
CREATE TRIGGER chat_sync_chat_update_trigger AFTER UPDATE OF
    hashed_user_id, hashed_team_id, messages_v, archive_mutation_v, encrypted_chat_key,
    participant_key_envelopes, title_v, metadata_v, last_edited_overall_timestamp, pinned,
    unread_count, chat_visibility, participant_user_hashes, parent_id, is_sub_chat, is_shared,
    is_private, storage_state, budget_limit, encrypted_title, encrypted_icon, encrypted_category,
    encrypted_chat_summary, encrypted_chat_tags, encrypted_share_cta_text, encrypted_shared_short_url,
    encrypted_follow_up_request_suggestions, encrypted_suggested_followup_message,
    encrypted_top_recommended_apps_for_chat, encrypted_recommendations, encrypted_active_focus_id,
    encrypted_focus_phase_state, encrypted_auto_speak_response
ON chats FOR EACH ROW EXECUTE FUNCTION chat_sync_chat_changed();

CREATE OR REPLACE FUNCTION chat_sync_message_changed()
RETURNS trigger AS $$
DECLARE changed_chat text; target record;
BEGIN
    changed_chat := CASE WHEN TG_OP = 'DELETE' THEN OLD.chat_id ELSE NEW.chat_id END;
    IF changed_chat IS NOT NULL AND chat_sync_is_uuid(changed_chat) THEN
        SELECT id, hashed_user_id, hashed_team_id INTO target FROM chats WHERE id = changed_chat::uuid;
        IF FOUND THEN
            PERFORM chat_sync_record(chat_sync_scope(target.hashed_user_id, target.hashed_team_id),
                                     target.id::text, NULL, 2);
        END IF;
    END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS chat_sync_message_trigger ON messages;
DROP TRIGGER IF EXISTS chat_sync_message_update_trigger ON messages;
CREATE TRIGGER chat_sync_message_trigger AFTER INSERT OR DELETE ON messages
FOR EACH ROW EXECUTE FUNCTION chat_sync_message_changed();
CREATE TRIGGER chat_sync_message_update_trigger AFTER UPDATE OF encrypted_content ON messages
FOR EACH ROW WHEN (OLD.encrypted_content IS DISTINCT FROM NEW.encrypted_content)
EXECUTE FUNCTION chat_sync_message_changed();

CREATE OR REPLACE FUNCTION chat_sync_draft_changed()
RETURNS trigger AS $$
DECLARE draft_row drafts;
BEGIN
    draft_row := CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
    IF NULLIF(draft_row.hashed_user_id, '') IS NOT NULL AND draft_row.chat_id IS NOT NULL THEN
        PERFORM chat_sync_record('user:' || draft_row.hashed_user_id, draft_row.chat_id, NULL, 16);
    END IF;
    RETURN draft_row;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS chat_sync_draft_trigger ON drafts;
CREATE TRIGGER chat_sync_draft_trigger AFTER INSERT OR UPDATE OR DELETE ON drafts
FOR EACH ROW EXECUTE FUNCTION chat_sync_draft_changed();

CREATE OR REPLACE FUNCTION chat_sync_hashed_chat_changed()
RETURNS trigger AS $$
DECLARE change_kinds integer := TG_ARGV[0]::integer;
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        PERFORM chat_sync_record_hashed(OLD.hashed_chat_id, change_kinds);
    END IF;
    IF TG_OP IN ('INSERT', 'UPDATE') AND (TG_OP = 'INSERT' OR NEW.hashed_chat_id IS DISTINCT FROM OLD.hashed_chat_id) THEN
        PERFORM chat_sync_record_hashed(NEW.hashed_chat_id, change_kinds);
    END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS chat_sync_wrapper_trigger ON chat_key_wrappers;
CREATE TRIGGER chat_sync_wrapper_trigger AFTER INSERT OR UPDATE OR DELETE ON chat_key_wrappers
FOR EACH ROW EXECUTE FUNCTION chat_sync_hashed_chat_changed('8');
DROP TRIGGER IF EXISTS chat_sync_embed_trigger ON embeds;
DROP TRIGGER IF EXISTS chat_sync_embed_update_trigger ON embeds;
CREATE TRIGGER chat_sync_embed_trigger AFTER INSERT OR DELETE ON embeds
FOR EACH ROW EXECUTE FUNCTION chat_sync_hashed_chat_changed('4');
CREATE TRIGGER chat_sync_embed_update_trigger AFTER UPDATE OF status, encrypted_content, encrypted_text_preview, version_number, hashed_chat_id ON embeds
FOR EACH ROW EXECUTE FUNCTION chat_sync_hashed_chat_changed('4');
DROP TRIGGER IF EXISTS chat_sync_embed_key_trigger ON embed_keys;
CREATE TRIGGER chat_sync_embed_key_trigger AFTER INSERT OR DELETE ON embed_keys
FOR EACH ROW EXECUTE FUNCTION chat_sync_hashed_chat_changed('4');

CREATE OR REPLACE FUNCTION chat_sync_deletion_fence_changed()
RETURNS trigger AS $$
BEGIN
    PERFORM chat_sync_record(chat_sync_scope(NEW.hashed_user_id, NEW.hashed_team_id), NEW.chat_id::text, NULL, 32);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS chat_sync_deletion_fence_trigger ON chat_recovery_chat_deletion_fences;
CREATE TRIGGER chat_sync_deletion_fence_trigger AFTER INSERT ON chat_recovery_chat_deletion_fences
FOR EACH ROW EXECUTE FUNCTION chat_sync_deletion_fence_changed();

-- The user's single last opened chat (set_active_chat) orders every device's overview.
CREATE OR REPLACE FUNCTION chat_sync_last_opened_changed()
RETURNS trigger AS $$
DECLARE opened text;
BEGIN
    opened := regexp_replace(COALESCE(NEW.last_opened, ''), '^.*/', '');
    PERFORM chat_sync_record('user:' || encode(digest(NEW.id::text, 'sha256'), 'hex'),
                             CASE WHEN chat_sync_is_uuid(opened) THEN lower(opened) ELSE NULL END,
                             NULL, 256);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS chat_sync_last_opened_trigger ON directus_users;
CREATE TRIGGER chat_sync_last_opened_trigger AFTER UPDATE OF last_opened ON directus_users
FOR EACH ROW WHEN (OLD.last_opened IS DISTINCT FROM NEW.last_opened)
EXECUTE FUNCTION chat_sync_last_opened_changed();

-- Due-soon inputs: reminders and the saved-item memory categories used by the
-- welcome overview. Only a content-free user-lane marker is recorded.
CREATE OR REPLACE FUNCTION chat_sync_due_soon_changed()
RETURNS trigger AS $$
DECLARE source_row jsonb;
BEGIN
    source_row := CASE WHEN TG_OP = 'DELETE' THEN to_jsonb(OLD) ELSE to_jsonb(NEW) END;
    IF NULLIF(source_row->>'hashed_user_id', '') IS NULL THEN
        RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
    END IF;
    IF TG_TABLE_NAME = 'user_app_settings_and_memories' AND (
        NULLIF(source_row->>'hashed_team_id', '') IS NOT NULL
        OR (source_row->>'app_id', source_row->>'item_type') NOT IN (
            ('events', 'saved_events'), ('travel', 'saved_connections'), ('travel', 'saved_stays'),
            ('home', 'saved_listings'), ('health', 'appointments'))) THEN
        RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
    END IF;
    PERFORM chat_sync_record('user:' || (source_row->>'hashed_user_id'), NULL, NULL, 512);
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS chat_sync_reminder_trigger ON reminders;
DROP TRIGGER IF EXISTS chat_sync_reminder_update_trigger ON reminders;
CREATE TRIGGER chat_sync_reminder_trigger AFTER INSERT OR DELETE ON reminders
FOR EACH ROW EXECUTE FUNCTION chat_sync_due_soon_changed();
CREATE TRIGGER chat_sync_reminder_update_trigger AFTER UPDATE OF trigger_at, status, target_type, encrypted_target_chat_id ON reminders
FOR EACH ROW EXECUTE FUNCTION chat_sync_due_soon_changed();
DROP TRIGGER IF EXISTS chat_sync_saved_item_trigger ON user_app_settings_and_memories;
CREATE TRIGGER chat_sync_saved_item_trigger AFTER INSERT OR UPDATE OR DELETE ON user_app_settings_and_memories
FOR EACH ROW EXECUTE FUNCTION chat_sync_due_soon_changed();
