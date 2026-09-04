-- Durable uniqueness and hot-path indexes for bounded sub-chat orchestration.
-- Run after orchestration collections have been created by cms-setup.
-- PostgreSQL aborts if existing rows violate an identity constraint.
BEGIN;

CREATE UNIQUE INDEX IF NOT EXISTS sub_chat_orchestrations_owner_root_turn_uq
  ON sub_chat_orchestrations (hashed_user_id, root_chat_id, root_turn_id);
CREATE INDEX IF NOT EXISTS sub_chat_orchestrations_owner_status_idx
  ON sub_chat_orchestrations (hashed_user_id, status, updated_at);
CREATE UNIQUE INDEX IF NOT EXISTS sub_chat_children_chat_uq
  ON sub_chat_orchestration_children (child_chat_id);
CREATE UNIQUE INDEX IF NOT EXISTS sub_chat_children_orchestration_token_uq
  ON sub_chat_orchestration_children (orchestration_id, dispatch_token_hash);
CREATE UNIQUE INDEX IF NOT EXISTS sub_chat_children_inference_task_uq
  ON sub_chat_orchestration_children (inference_task_id) WHERE inference_task_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS sub_chat_children_orchestration_state_idx
  ON sub_chat_orchestration_children (orchestration_id, state, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS sub_chat_batches_orchestration_parent_id_uq
  ON sub_chat_orchestration_batches (orchestration_id, parent_chat_id, id);
CREATE INDEX IF NOT EXISTS sub_chat_batches_orchestration_claim_idx
  ON sub_chat_orchestration_batches (orchestration_id, continuation_claimed, updated_at);
CREATE UNIQUE INDEX IF NOT EXISTS sub_chat_operations_identity_uq
  ON sub_chat_orchestration_operations (operation_id);
CREATE INDEX IF NOT EXISTS sub_chat_operations_orchestration_state_idx
  ON sub_chat_orchestration_operations (orchestration_id, state, created_at);
CREATE INDEX IF NOT EXISTS sub_chat_operations_charge_idx
  ON sub_chat_orchestration_operations (orchestration_id, charge_id, state);
CREATE UNIQUE INDEX IF NOT EXISTS usage_charge_id_uq
  ON usage (charge_id) WHERE charge_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS usage_user_root_created_idx
  ON usage (user_id_hash, root_chat_id, created_at) WHERE root_chat_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS usage_orchestration_created_idx
  ON usage (orchestration_id, created_at) WHERE orchestration_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS billing_charge_identities_charge_uq
  ON billing_charge_identities (charge_id);
CREATE INDEX IF NOT EXISTS billing_charge_identities_user_created_idx
  ON billing_charge_identities (hashed_user_id, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS billing_refund_identities_refund_uq
  ON billing_refund_identities (refund_id);
CREATE INDEX IF NOT EXISTS billing_settlement_outbox_due_idx
  ON billing_settlement_outbox (state, next_attempt_at, created_at)
  WHERE state IN ('pending', 'retry_scheduled');
CREATE UNIQUE INDEX IF NOT EXISTS team_credit_events_event_uq
  ON team_credit_events (event_id);
CREATE UNIQUE INDEX IF NOT EXISTS team_usage_events_event_uq
  ON team_usage_events (event_id);

COMMIT;
