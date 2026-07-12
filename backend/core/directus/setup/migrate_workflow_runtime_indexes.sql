-- Required idempotency and scheduler indexes for durable Workflow execution.
-- Run after cms-setup creates the Workflow collections.
BEGIN;

CREATE INDEX IF NOT EXISTS workflow_triggers_due_claim_idx
  ON workflow_triggers (next_run_at, trigger_id)
  WHERE enabled = true AND trigger_type = 'schedule';
CREATE INDEX IF NOT EXISTS workflow_triggers_event_routing_idx
  ON workflow_triggers (hashed_user_id, hashed_project_id, source, event_type, trigger_id)
  WHERE enabled = true AND trigger_type = 'event';
CREATE UNIQUE INDEX IF NOT EXISTS workflow_runs_acceptance_identity_uq
  ON workflow_runs (acceptance_idempotency_key);
CREATE UNIQUE INDEX IF NOT EXISTS workflow_event_receipts_trigger_event_uq
  ON workflow_event_receipts (trigger_id, event_id);
CREATE UNIQUE INDEX IF NOT EXISTS workflow_template_projections_workflow_uq
  ON workflow_template_projections (workflow_id);

COMMIT;
