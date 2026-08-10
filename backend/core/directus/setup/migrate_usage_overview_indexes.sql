-- Usage overview rollup and summary hot-path indexes.
-- Idempotent for Directus setup reruns.
-- Raw usage credit fields are user-key encrypted, so this schema migration
-- repairs duplicate helper rows by merging existing summary totals/counts and
-- preserving archive metadata. Raw usage rows remain authoritative and intact.

WITH usage_summary_duplicate_groups AS (
    SELECT user_id_hash, chat_id, year_month,
           SUM(COALESCE(total_credits, 0)) AS total_credits,
           SUM(COALESCE(entry_count, 0)) AS entry_count,
           BOOL_OR(COALESCE(is_archived, false)) AS is_archived,
           MAX(archive_s3_key) FILTER (WHERE archive_s3_key IS NOT NULL AND archive_s3_key <> '') AS archive_s3_key,
           MAX(updated_at) AS updated_at
      FROM usage_monthly_chat_summaries
     WHERE chat_id IS NOT NULL AND chat_id <> ''
     GROUP BY user_id_hash, chat_id, year_month
    HAVING COUNT(*) > 1
), ranked AS (
    SELECT id, user_id_hash, chat_id, year_month,
           ROW_NUMBER() OVER (PARTITION BY user_id_hash, chat_id, year_month ORDER BY COALESCE(is_archived, false) DESC, updated_at DESC NULLS LAST, id) AS row_number
      FROM usage_monthly_chat_summaries
     WHERE chat_id IS NOT NULL AND chat_id <> ''
)
UPDATE usage_monthly_chat_summaries target
   SET total_credits = groups.total_credits,
       entry_count = groups.entry_count,
       is_archived = groups.is_archived,
       archive_s3_key = COALESCE(groups.archive_s3_key, target.archive_s3_key),
       updated_at = groups.updated_at
  FROM usage_summary_duplicate_groups groups
  JOIN ranked ON ranked.user_id_hash = groups.user_id_hash
             AND ranked.chat_id = groups.chat_id
             AND ranked.year_month = groups.year_month
             AND ranked.row_number = 1
 WHERE target.id = ranked.id;

WITH ranked AS (
    SELECT id,
           ROW_NUMBER() OVER (PARTITION BY user_id_hash, chat_id, year_month ORDER BY COALESCE(is_archived, false) DESC, updated_at DESC NULLS LAST, id) AS row_number
      FROM usage_monthly_chat_summaries
     WHERE chat_id IS NOT NULL AND chat_id <> ''
)
DELETE FROM usage_monthly_chat_summaries target
 USING ranked
 WHERE target.id = ranked.id
   AND ranked.row_number > 1;

WITH usage_summary_duplicate_groups AS (
    SELECT user_id_hash, app_id, year_month,
           SUM(COALESCE(total_credits, 0)) AS total_credits,
           SUM(COALESCE(entry_count, 0)) AS entry_count,
           BOOL_OR(COALESCE(is_archived, false)) AS is_archived,
           MAX(archive_s3_key) FILTER (WHERE archive_s3_key IS NOT NULL AND archive_s3_key <> '') AS archive_s3_key,
           MAX(updated_at) AS updated_at
      FROM usage_monthly_app_summaries
     WHERE app_id IS NOT NULL AND app_id <> ''
     GROUP BY user_id_hash, app_id, year_month
    HAVING COUNT(*) > 1
), ranked AS (
    SELECT id, user_id_hash, app_id, year_month,
           ROW_NUMBER() OVER (PARTITION BY user_id_hash, app_id, year_month ORDER BY COALESCE(is_archived, false) DESC, updated_at DESC NULLS LAST, id) AS row_number
      FROM usage_monthly_app_summaries
     WHERE app_id IS NOT NULL AND app_id <> ''
)
UPDATE usage_monthly_app_summaries target
   SET total_credits = groups.total_credits,
       entry_count = groups.entry_count,
       is_archived = groups.is_archived,
       archive_s3_key = COALESCE(groups.archive_s3_key, target.archive_s3_key),
       updated_at = groups.updated_at
  FROM usage_summary_duplicate_groups groups
  JOIN ranked ON ranked.user_id_hash = groups.user_id_hash
             AND ranked.app_id = groups.app_id
             AND ranked.year_month = groups.year_month
             AND ranked.row_number = 1
 WHERE target.id = ranked.id;

WITH ranked AS (
    SELECT id,
           ROW_NUMBER() OVER (PARTITION BY user_id_hash, app_id, year_month ORDER BY COALESCE(is_archived, false) DESC, updated_at DESC NULLS LAST, id) AS row_number
      FROM usage_monthly_app_summaries
     WHERE app_id IS NOT NULL AND app_id <> ''
)
DELETE FROM usage_monthly_app_summaries target
 USING ranked
 WHERE target.id = ranked.id
   AND ranked.row_number > 1;

WITH usage_summary_duplicate_groups AS (
    SELECT user_id_hash, api_key_hash, year_month,
           SUM(COALESCE(total_credits, 0)) AS total_credits,
           SUM(COALESCE(entry_count, 0)) AS entry_count,
           BOOL_OR(COALESCE(is_archived, false)) AS is_archived,
           MAX(archive_s3_key) FILTER (WHERE archive_s3_key IS NOT NULL AND archive_s3_key <> '') AS archive_s3_key,
           MAX(updated_at) AS updated_at
      FROM usage_monthly_api_key_summaries
     WHERE api_key_hash IS NOT NULL AND api_key_hash <> ''
     GROUP BY user_id_hash, api_key_hash, year_month
    HAVING COUNT(*) > 1
), ranked AS (
    SELECT id, user_id_hash, api_key_hash, year_month,
           ROW_NUMBER() OVER (PARTITION BY user_id_hash, api_key_hash, year_month ORDER BY COALESCE(is_archived, false) DESC, updated_at DESC NULLS LAST, id) AS row_number
      FROM usage_monthly_api_key_summaries
     WHERE api_key_hash IS NOT NULL AND api_key_hash <> ''
)
UPDATE usage_monthly_api_key_summaries target
   SET total_credits = groups.total_credits,
       entry_count = groups.entry_count,
       is_archived = groups.is_archived,
       archive_s3_key = COALESCE(groups.archive_s3_key, target.archive_s3_key),
       updated_at = groups.updated_at
  FROM usage_summary_duplicate_groups groups
  JOIN ranked ON ranked.user_id_hash = groups.user_id_hash
             AND ranked.api_key_hash = groups.api_key_hash
             AND ranked.year_month = groups.year_month
             AND ranked.row_number = 1
 WHERE target.id = ranked.id;

WITH ranked AS (
    SELECT id,
           ROW_NUMBER() OVER (PARTITION BY user_id_hash, api_key_hash, year_month ORDER BY COALESCE(is_archived, false) DESC, updated_at DESC NULLS LAST, id) AS row_number
      FROM usage_monthly_api_key_summaries
     WHERE api_key_hash IS NOT NULL AND api_key_hash <> ''
)
DELETE FROM usage_monthly_api_key_summaries target
 USING ranked
 WHERE target.id = ranked.id
   AND ranked.row_number > 1;

WITH usage_summary_duplicate_groups AS (
    SELECT user_id_hash, chat_id, date,
           SUM(COALESCE(total_credits, 0)) AS total_credits,
           SUM(COALESCE(entry_count, 0)) AS entry_count,
           MAX(updated_at) AS updated_at
      FROM usage_daily_chat_summaries
     WHERE chat_id IS NOT NULL AND chat_id <> ''
     GROUP BY user_id_hash, chat_id, date
    HAVING COUNT(*) > 1
), ranked AS (
    SELECT id, user_id_hash, chat_id, date,
           ROW_NUMBER() OVER (PARTITION BY user_id_hash, chat_id, date ORDER BY updated_at DESC NULLS LAST, id) AS row_number
      FROM usage_daily_chat_summaries
     WHERE chat_id IS NOT NULL AND chat_id <> ''
)
UPDATE usage_daily_chat_summaries target
   SET total_credits = groups.total_credits,
       entry_count = groups.entry_count,
       updated_at = groups.updated_at
  FROM usage_summary_duplicate_groups groups
  JOIN ranked ON ranked.user_id_hash = groups.user_id_hash
             AND ranked.chat_id = groups.chat_id
             AND ranked.date = groups.date
             AND ranked.row_number = 1
 WHERE target.id = ranked.id;

WITH ranked AS (
    SELECT id,
           ROW_NUMBER() OVER (PARTITION BY user_id_hash, chat_id, date ORDER BY updated_at DESC NULLS LAST, id) AS row_number
      FROM usage_daily_chat_summaries
     WHERE chat_id IS NOT NULL AND chat_id <> ''
)
DELETE FROM usage_daily_chat_summaries target
 USING ranked
 WHERE target.id = ranked.id
   AND ranked.row_number > 1;

WITH usage_summary_duplicate_groups AS (
    SELECT user_id_hash, app_id, date,
           SUM(COALESCE(total_credits, 0)) AS total_credits,
           SUM(COALESCE(entry_count, 0)) AS entry_count,
           MAX(updated_at) AS updated_at
      FROM usage_daily_app_summaries
     WHERE app_id IS NOT NULL AND app_id <> ''
     GROUP BY user_id_hash, app_id, date
    HAVING COUNT(*) > 1
), ranked AS (
    SELECT id, user_id_hash, app_id, date,
           ROW_NUMBER() OVER (PARTITION BY user_id_hash, app_id, date ORDER BY updated_at DESC NULLS LAST, id) AS row_number
      FROM usage_daily_app_summaries
     WHERE app_id IS NOT NULL AND app_id <> ''
)
UPDATE usage_daily_app_summaries target
   SET total_credits = groups.total_credits,
       entry_count = groups.entry_count,
       updated_at = groups.updated_at
  FROM usage_summary_duplicate_groups groups
  JOIN ranked ON ranked.user_id_hash = groups.user_id_hash
             AND ranked.app_id = groups.app_id
             AND ranked.date = groups.date
             AND ranked.row_number = 1
 WHERE target.id = ranked.id;

WITH ranked AS (
    SELECT id,
           ROW_NUMBER() OVER (PARTITION BY user_id_hash, app_id, date ORDER BY updated_at DESC NULLS LAST, id) AS row_number
      FROM usage_daily_app_summaries
     WHERE app_id IS NOT NULL AND app_id <> ''
)
DELETE FROM usage_daily_app_summaries target
 USING ranked
 WHERE target.id = ranked.id
   AND ranked.row_number > 1;

WITH usage_summary_duplicate_groups AS (
    SELECT user_id_hash, api_key_hash, date,
           SUM(COALESCE(total_credits, 0)) AS total_credits,
           SUM(COALESCE(entry_count, 0)) AS entry_count,
           MAX(updated_at) AS updated_at
      FROM usage_daily_api_key_summaries
     WHERE api_key_hash IS NOT NULL AND api_key_hash <> ''
     GROUP BY user_id_hash, api_key_hash, date
    HAVING COUNT(*) > 1
), ranked AS (
    SELECT id, user_id_hash, api_key_hash, date,
           ROW_NUMBER() OVER (PARTITION BY user_id_hash, api_key_hash, date ORDER BY updated_at DESC NULLS LAST, id) AS row_number
      FROM usage_daily_api_key_summaries
     WHERE api_key_hash IS NOT NULL AND api_key_hash <> ''
)
UPDATE usage_daily_api_key_summaries target
   SET total_credits = groups.total_credits,
       entry_count = groups.entry_count,
       updated_at = groups.updated_at
  FROM usage_summary_duplicate_groups groups
  JOIN ranked ON ranked.user_id_hash = groups.user_id_hash
             AND ranked.api_key_hash = groups.api_key_hash
             AND ranked.date = groups.date
             AND ranked.row_number = 1
 WHERE target.id = ranked.id;

WITH ranked AS (
    SELECT id,
           ROW_NUMBER() OVER (PARTITION BY user_id_hash, api_key_hash, date ORDER BY updated_at DESC NULLS LAST, id) AS row_number
      FROM usage_daily_api_key_summaries
     WHERE api_key_hash IS NOT NULL AND api_key_hash <> ''
)
DELETE FROM usage_daily_api_key_summaries target
 USING ranked
 WHERE target.id = ranked.id
   AND ranked.row_number > 1;

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

CREATE UNIQUE INDEX IF NOT EXISTS usage_monthly_chat_user_chat_month_uq
    ON usage_monthly_chat_summaries (user_id_hash, chat_id, year_month)
    WHERE chat_id IS NOT NULL AND chat_id <> '' AND year_month IS NOT NULL AND year_month <> '';

CREATE UNIQUE INDEX IF NOT EXISTS usage_monthly_app_user_app_month_uq
    ON usage_monthly_app_summaries (user_id_hash, app_id, year_month)
    WHERE app_id IS NOT NULL AND app_id <> '' AND year_month IS NOT NULL AND year_month <> '';

CREATE UNIQUE INDEX IF NOT EXISTS usage_monthly_api_key_user_api_key_month_uq
    ON usage_monthly_api_key_summaries (user_id_hash, api_key_hash, year_month)
    WHERE api_key_hash IS NOT NULL AND api_key_hash <> '' AND year_month IS NOT NULL AND year_month <> '';

CREATE UNIQUE INDEX IF NOT EXISTS usage_daily_chat_user_chat_date_uq
    ON usage_daily_chat_summaries (user_id_hash, chat_id, date)
    WHERE chat_id IS NOT NULL AND chat_id <> '' AND date IS NOT NULL AND date <> '';

CREATE UNIQUE INDEX IF NOT EXISTS usage_daily_app_user_app_date_uq
    ON usage_daily_app_summaries (user_id_hash, app_id, date)
    WHERE app_id IS NOT NULL AND app_id <> '' AND date IS NOT NULL AND date <> '';

CREATE UNIQUE INDEX IF NOT EXISTS usage_daily_api_key_user_api_key_date_uq
    ON usage_daily_api_key_summaries (user_id_hash, api_key_hash, date)
    WHERE api_key_hash IS NOT NULL AND api_key_hash <> '' AND date IS NOT NULL AND date <> '';
