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

COMMIT;
