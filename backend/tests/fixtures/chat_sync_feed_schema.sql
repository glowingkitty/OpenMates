-- Minimal column-compatible subset of the Directus tables touched by
-- migrate_chat_sync_feed.sql (types match the dev database). Test-only.
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE TABLE directus_users (id uuid PRIMARY KEY, last_opened varchar(255), credits integer DEFAULT 0);
CREATE TABLE chats (
    id uuid PRIMARY KEY, hashed_user_id varchar(255), hashed_team_id varchar(255),
    encrypted_title text, messages_v integer, title_v integer, metadata_v integer,
    last_edited_overall_timestamp integer, unread_count integer, created_at integer, updated_at integer,
    encrypted_active_focus_id varchar(255), encrypted_chat_summary text, encrypted_chat_tags text,
    encrypted_follow_up_request_suggestions text, encrypted_chat_key varchar(255),
    encrypted_icon varchar(255), encrypted_category varchar(255),
    encrypted_top_recommended_apps_for_chat text, is_private boolean, is_shared boolean,
    pinned boolean, encrypted_quick_tip_slugs text, parent_id uuid, is_sub_chat boolean,
    budget_limit integer, budget_spent integer, encrypted_shared_short_url text,
    encrypted_share_cta_text text, storage_state varchar(255), encrypted_auto_speak_response varchar(255),
    encrypted_focus_phase_state text, archive_mutation_v integer, chat_visibility varchar(255),
    participant_user_hashes json, participant_key_envelopes json, encrypted_suggested_followup_message text
);
CREATE TABLE messages (id uuid PRIMARY KEY, chat_id varchar(255), hashed_user_id varchar(255), encrypted_content text);
CREATE TABLE drafts (id uuid PRIMARY KEY, chat_id varchar(255), hashed_user_id varchar(255), encrypted_content text, version integer);
CREATE TABLE chat_key_wrappers (
    id uuid PRIMARY KEY, hashed_chat_id varchar(255), hashed_user_id varchar(255), key_type varchar(255),
    hashed_project_id varchar(255), hashed_plan_id varchar(255), hashed_team_id varchar(255),
    team_key_epoch integer, encrypted_chat_key text, wrapper_version integer, expires_at integer, created_at integer
);
CREATE TABLE embeds (
    id uuid PRIMARY KEY, embed_id varchar(255), hashed_chat_id varchar(255), hashed_user_id varchar(255),
    hashed_team_id varchar(255), status varchar(255), encrypted_content text, encrypted_text_preview text,
    version_number integer
);
CREATE TABLE embed_keys (id uuid PRIMARY KEY, hashed_embed_id varchar(255), hashed_chat_id varchar(255),
    hashed_user_id varchar(255), hashed_team_id varchar(255));
CREATE TABLE chat_recovery_chat_deletion_fences (id uuid PRIMARY KEY, hashed_user_id varchar(255),
    hashed_team_id varchar(255), chat_id uuid);
CREATE TABLE reminders (id uuid PRIMARY KEY, hashed_user_id varchar(255), trigger_at integer,
    status varchar(255), target_type varchar(255), encrypted_target_chat_id varchar(255));
CREATE TABLE user_app_settings_and_memories (
    id uuid PRIMARY KEY, hashed_user_id varchar(255), hashed_team_id varchar(255), app_id varchar(255),
    item_key varchar(255), item_type varchar(255), encrypted_app_key text, encrypted_item_json text,
    created_at integer, updated_at integer, sequence_number integer, item_version integer
);
