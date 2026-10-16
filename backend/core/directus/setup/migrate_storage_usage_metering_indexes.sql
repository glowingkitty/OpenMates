-- Additive metadata and bounded owner-scope lookup indexes for logical S3 quotes.
-- Existing archived versions without a measured size remain unbillable until
-- a verified, source-bound reconciliation supplies the exact byte count.
ALTER TABLE public.embed_diffs ADD COLUMN IF NOT EXISTS archive_size_bytes integer;
ALTER TABLE public.embed_diffs ADD COLUMN IF NOT EXISTS archive_owner_kind varchar(16);
ALTER TABLE public.embed_diffs ADD COLUMN IF NOT EXISTS archive_owner_hash varchar(64);
ALTER TABLE public.embed_diffs ADD COLUMN IF NOT EXISTS archive_hashed_chat_id varchar(64);

CREATE INDEX IF NOT EXISTS cold_archive_manifests_metering_resource_idx
  ON public.cold_archive_manifests (resource_id, state, archive_id);
CREATE INDEX IF NOT EXISTS chat_recovery_outputs_metering_root_idx
  ON public.chat_recovery_outputs (root_chat_id, id)
  WHERE state = 'PENDING' AND payload_storage = 's3' AND deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS embed_diffs_metering_archive_idx
  ON public.embed_diffs (embed_id, id)
  WHERE archive_state IN ('reader_active', 'pruned');
