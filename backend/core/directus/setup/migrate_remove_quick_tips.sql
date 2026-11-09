-- Chat Recommendations replaced quick tips (docs/plans/chat-recommendations/plan.yml, D-11).
-- Drops the old quick tip columns and their Directus field metadata. Idempotent.
-- Must run after migrate_chat_sync_feed.sql: that migration recreates the chats
-- update trigger without encrypted_quick_tip_slugs in its UPDATE OF column list,
-- which PostgreSQL requires before the column can be dropped.
ALTER TABLE public.chats DROP COLUMN IF EXISTS encrypted_quick_tip_slugs;
ALTER TABLE public.directus_users DROP COLUMN IF EXISTS quick_tips_enabled;
DELETE FROM public.directus_fields
WHERE (collection = 'chats' AND field = 'encrypted_quick_tip_slugs')
   OR (collection = 'directus_users' AND field = 'quick_tips_enabled');
