-- Durable typed recovery discovery, ownership and retry identity.
BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE UNIQUE INDEX IF NOT EXISTS chat_recovery_outputs_identity_uq
  ON chat_recovery_outputs (hashed_user_id, turn_id, target_chat_id, subject_id, output_kind, output_version);
CREATE INDEX IF NOT EXISTS chat_recovery_outputs_owner_pending_idx
  ON chat_recovery_outputs (hashed_user_id, created_at, id)
  WHERE state = 'PENDING' AND deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS chat_recovery_outputs_root_state_idx
  ON chat_recovery_outputs (hashed_user_id, root_chat_id, state, created_at);
CREATE INDEX IF NOT EXISTS chat_recovery_outputs_target_state_idx
  ON chat_recovery_outputs (hashed_user_id, target_chat_id, state, created_at);
-- Warm admission tests pending recovery by chat identity without an owner hash.
CREATE INDEX IF NOT EXISTS chat_recovery_outputs_pending_target_chat_idx
  ON chat_recovery_outputs (target_chat_id)
  WHERE state = 'PENDING' AND deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS chat_recovery_outputs_pending_root_chat_idx
  ON chat_recovery_outputs (root_chat_id)
  WHERE state = 'PENDING' AND deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS chat_completion_recovery_jobs_pending_chat_idx
  ON chat_completion_recovery_jobs (chat_id)
  WHERE state IN ('AVAILABLE', 'LEASED');
CREATE INDEX IF NOT EXISTS chat_turn_preflights_active_chat_idx
  ON chat_turn_preflights (chat_id)
  WHERE state IN ('PREPARED', 'ENQUEUED', 'RUNNING');
CREATE INDEX IF NOT EXISTS chat_recovery_outputs_pending_target_hash_idx
  ON chat_recovery_outputs ((encode(digest(target_chat_id::text, 'sha256'), 'hex')))
  WHERE state = 'PENDING' AND deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS chat_recovery_outputs_pending_root_hash_idx
  ON chat_recovery_outputs ((encode(digest(root_chat_id::text, 'sha256'), 'hex')))
  WHERE state = 'PENDING' AND deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS chat_completion_recovery_jobs_pending_chat_hash_idx
  ON chat_completion_recovery_jobs ((encode(digest(chat_id::text, 'sha256'), 'hex')))
  WHERE state IN ('AVAILABLE', 'LEASED') AND invalidated_at IS NULL;
CREATE INDEX IF NOT EXISTS chat_turn_preflights_running_chat_hash_idx
  ON chat_turn_preflights ((encode(digest(chat_id::text, 'sha256'), 'hex')))
  WHERE state = 'RUNNING' AND deletion_invalidated_at IS NULL;
CREATE INDEX IF NOT EXISTS chat_recovery_outputs_s3_locator_idx
  ON chat_recovery_outputs (payload_s3_key)
  WHERE payload_s3_key IS NOT NULL;
-- PREPARING is a durable large-object writer intent and must fence readers,
-- archive admissions, and deletion until publication or settlement.
CREATE INDEX IF NOT EXISTS chat_recovery_outputs_owner_active_idx
  ON chat_recovery_outputs (hashed_user_id, state, created_at, id)
  WHERE state IN ('PREPARING', 'PENDING') AND deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS chat_recovery_jobs_owner_active_idx
  ON chat_completion_recovery_jobs (hashed_user_id, state, chat_id)
  WHERE state IN ('AVAILABLE', 'LEASED') AND invalidated_at IS NULL;
CREATE INDEX IF NOT EXISTS chat_recovery_preflights_owner_active_idx
  ON chat_turn_preflights (hashed_user_id, state, chat_id)
  WHERE state IN ('PREPARED', 'ENQUEUED', 'RUNNING') AND deletion_invalidated_at IS NULL;
CREATE INDEX IF NOT EXISTS chat_recovery_outputs_active_target_chat_idx
  ON chat_recovery_outputs (target_chat_id)
  WHERE state IN ('PREPARING', 'PENDING') AND deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS chat_recovery_outputs_active_root_chat_idx
  ON chat_recovery_outputs (root_chat_id)
  WHERE state IN ('PREPARING', 'PENDING') AND deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS chat_recovery_outputs_active_target_hash_idx
  ON chat_recovery_outputs ((encode(digest(target_chat_id::text, 'sha256'), 'hex')))
  WHERE state IN ('PREPARING', 'PENDING') AND deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS chat_recovery_outputs_active_root_hash_idx
  ON chat_recovery_outputs ((encode(digest(root_chat_id::text, 'sha256'), 'hex')))
  WHERE state IN ('PREPARING', 'PENDING') AND deleted_at IS NULL;

COMMIT;
