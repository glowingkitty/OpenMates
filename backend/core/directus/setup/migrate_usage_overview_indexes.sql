-- Usage overview rollup and summary hot-path indexes.
-- Idempotent for Directus setup reruns.

CREATE UNIQUE INDEX IF NOT EXISTS usage_period_rollups_user_granularity_period_idx
    ON usage_period_rollups (user_id_hash, granularity, period_key);

CREATE INDEX IF NOT EXISTS usage_period_rollups_user_period_start_idx
    ON usage_period_rollups (user_id_hash, granularity, period_start DESC);

CREATE INDEX IF NOT EXISTS usage_user_created_idx
    ON usage (user_id_hash, created_at DESC);

CREATE INDEX IF NOT EXISTS usage_monthly_chat_user_month_idx
    ON usage_monthly_chat_summaries (user_id_hash, year_month);

CREATE INDEX IF NOT EXISTS usage_monthly_app_user_month_idx
    ON usage_monthly_app_summaries (user_id_hash, year_month);

CREATE INDEX IF NOT EXISTS usage_monthly_api_key_user_month_idx
    ON usage_monthly_api_key_summaries (user_id_hash, year_month);

CREATE INDEX IF NOT EXISTS usage_daily_chat_user_date_idx
    ON usage_daily_chat_summaries (user_id_hash, date);

CREATE INDEX IF NOT EXISTS usage_daily_app_user_date_idx
    ON usage_daily_app_summaries (user_id_hash, date);

CREATE INDEX IF NOT EXISTS usage_daily_api_key_user_date_idx
    ON usage_daily_api_key_summaries (user_id_hash, date);
