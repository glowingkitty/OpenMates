-- Durable uniqueness and read indexes for encrypted per-user/chat AI model preferences.
CREATE UNIQUE INDEX IF NOT EXISTS user_chat_preferences_owner_chat_uq
    ON public.user_chat_preferences (hashed_user_id, chat_id);

CREATE INDEX IF NOT EXISTS user_chat_preferences_owner_updated_idx
    ON public.user_chat_preferences (hashed_user_id, updated_at DESC);
