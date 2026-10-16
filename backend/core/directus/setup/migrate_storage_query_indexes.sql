-- Cursor and aggregate access paths for bounded encrypted sync reads.
-- Apply after the chats, messages, embeds, embed_keys and embed_diffs schemas.
BEGIN;

CREATE INDEX IF NOT EXISTS messages_chat_created_client_id_idx
  ON public.messages (chat_id, created_at, client_message_id, id);

CREATE INDEX IF NOT EXISTS embeds_hashed_chat_created_cursor_idx
  ON public.embeds (hashed_chat_id, created_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS embed_keys_hashed_chat_type_embed_idx
  ON public.embed_keys (hashed_chat_id, key_type, hashed_embed_id, id);

CREATE INDEX IF NOT EXISTS embed_keys_user_type_embed_cursor_idx
  ON public.embed_keys (hashed_user_id, key_type, hashed_embed_id, id);

CREATE INDEX IF NOT EXISTS code_run_outputs_sync_cursor_idx
  ON public.code_run_outputs (chat_id, author_user_id, updated_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS notebook_run_outputs_sync_cursor_idx
  ON public.notebook_run_outputs (chat_id, author_user_id, updated_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS chat_key_wrappers_user_cursor_idx
  ON public.chat_key_wrappers (hashed_chat_id, hashed_user_id, id DESC);

CREATE INDEX IF NOT EXISTS chat_key_wrappers_team_cursor_idx
  ON public.chat_key_wrappers (hashed_chat_id, hashed_team_id, id DESC);

-- The warm policy ranks only hot main chats for one owner by recency.
CREATE INDEX IF NOT EXISTS chats_owner_main_hot_recency_idx
  ON public.chats (hashed_user_id, (COALESCE(last_edited_overall_timestamp, updated_at, 0)), id)
  WHERE parent_id IS NULL AND COALESCE(is_sub_chat, false) = false
    AND (storage_state IS NULL OR storage_state = 'hot');

COMMIT;
