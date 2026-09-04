-- Permanently remove obsolete AI-owned memories from active storage.
-- Other app memories share this table and must remain byte-for-byte untouched.
DELETE FROM public.user_app_settings_and_memories
WHERE app_id = 'ai';
