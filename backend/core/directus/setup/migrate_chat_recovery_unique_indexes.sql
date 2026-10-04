-- Required composite identity constraints for chat completion recovery.
-- Run after the three recovery collections have been created by cms-setup.
-- PostgreSQL aborts this transaction if pre-existing duplicates violate safety.
BEGIN;

CREATE UNIQUE INDEX IF NOT EXISTS chat_turn_preflights_owner_chat_turn_uq
  ON chat_turn_preflights (hashed_user_id, chat_id, turn_id);
CREATE UNIQUE INDEX IF NOT EXISTS chat_turn_preflights_user_message_uq
  ON chat_turn_preflights (user_message_id);
CREATE UNIQUE INDEX IF NOT EXISTS chat_turn_preflights_task_uq
  ON chat_turn_preflights (inference_task_id) WHERE inference_task_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS chat_turn_preflights_billing_uq
  ON chat_turn_preflights (billing_identity) WHERE billing_identity IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS chat_inference_outbox_preflight_uq
  ON chat_inference_outbox (preflight_id);
CREATE UNIQUE INDEX IF NOT EXISTS chat_inference_outbox_task_uq
  ON chat_inference_outbox (inference_task_id);
CREATE UNIQUE INDEX IF NOT EXISTS chat_inference_outbox_billing_uq
  ON chat_inference_outbox (billing_identity);

CREATE UNIQUE INDEX IF NOT EXISTS chat_recovery_jobs_owner_chat_turn_uq
  ON chat_completion_recovery_jobs (hashed_user_id, chat_id, turn_id);
CREATE UNIQUE INDEX IF NOT EXISTS chat_recovery_jobs_preflight_uq
  ON chat_completion_recovery_jobs (preflight_id);
CREATE UNIQUE INDEX IF NOT EXISTS chat_recovery_jobs_task_uq
  ON chat_completion_recovery_jobs (inference_task_id);
CREATE UNIQUE INDEX IF NOT EXISTS chat_recovery_jobs_assistant_message_uq
  ON chat_completion_recovery_jobs (assistant_message_id);

-- The permanent deletion fence must be one row per owner/chat even if a
-- future writer uses a different primary-key derivation.
CREATE UNIQUE INDEX IF NOT EXISTS chat_recovery_chat_deletion_owner_chat_uq
  ON chat_recovery_chat_deletion_fences (hashed_user_id, chat_id);

-- A registered Celery task owns at most one immutable output per ordinal.
CREATE UNIQUE INDEX IF NOT EXISTS chat_recovery_output_producer_child_ordinal_uq
  ON chat_recovery_output_producer_children (producer_intent_id, ordinal);
CREATE UNIQUE INDEX IF NOT EXISTS chat_recovery_output_producer_child_subject_uq
  ON chat_recovery_output_producer_children
    (producer_intent_id, subject_id, output_kind, output_version);
CREATE UNIQUE INDEX IF NOT EXISTS chat_recovery_output_producer_output_ordinal_uq
  ON chat_recovery_outputs (producer_intent_id, producer_ordinal)
  WHERE producer_intent_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS chat_recovery_output_producer_preflight_idx
  ON chat_recovery_output_producers (preflight_id) WHERE state = 'PENDING';
CREATE INDEX IF NOT EXISTS chat_recovery_authorized_rerender_owner_chat_idx
  ON chat_recovery_authorized_rerenders (hashed_user_id, target_chat_id)
  WHERE state IN ('PENDING', 'RUNNING');
CREATE INDEX IF NOT EXISTS chat_recovery_authorized_direct_skill_owner_chat_idx
  ON chat_recovery_authorized_direct_skills (hashed_user_id, target_chat_id)
  WHERE state IN ('PENDING', 'RUNNING');
CREATE INDEX IF NOT EXISTS chat_recovery_authorized_direct_skill_embed_idx
  ON chat_recovery_authorized_direct_skills (hashed_user_id, primary_embed_id, target_chat_id)
  WHERE state IN ('PENDING', 'RUNNING');
CREATE INDEX IF NOT EXISTS chat_recovery_authorized_rerender_embed_idx
  ON chat_recovery_authorized_rerenders (hashed_user_id, primary_embed_id, target_chat_id, expected_embed_version)
  WHERE state IN ('PENDING', 'RUNNING');
CREATE INDEX IF NOT EXISTS chat_recovery_authorized_direct_skill_pending_idx
  ON chat_recovery_authorized_direct_skills (id) WHERE state = 'RUNNING';
CREATE INDEX IF NOT EXISTS chat_recovery_authorized_rerender_pending_idx
  ON chat_recovery_authorized_rerenders (id) WHERE state = 'RUNNING';
CREATE INDEX IF NOT EXISTS chat_recovery_legacy_producer_identity_idx
  ON chat_recovery_legacy_output_producers (legacy_task_identity, state);
CREATE INDEX IF NOT EXISTS chat_recovery_legacy_producer_owner_embed_idx
  ON chat_recovery_legacy_output_producers (hashed_user_id, primary_embed_id, target_chat_id)
  WHERE state IN ('PENDING', 'RUNNING');
CREATE UNIQUE INDEX IF NOT EXISTS chat_recovery_legacy_batch_task_uq
  ON chat_recovery_legacy_batch_claims (task_identity);
CREATE UNIQUE INDEX IF NOT EXISTS chat_recovery_legacy_broker_task_uq
  ON chat_recovery_legacy_batch_claims (broker_task_id)
  WHERE broker_task_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS chat_recovery_legacy_batch_active_idx
  ON chat_recovery_legacy_batch_claims (id)
  WHERE state IN ('PREPARED', 'CLAIMED');
CREATE INDEX IF NOT EXISTS chat_recovery_legacy_batch_owner_chat_idx
  ON chat_recovery_legacy_batch_claims (hashed_user_id, chat_id)
  WHERE state IN ('PREPARED', 'CLAIMED');

COMMIT;
