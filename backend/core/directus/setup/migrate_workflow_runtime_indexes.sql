-- Required idempotency and scheduler indexes for durable Workflow execution.
-- Run after cms-setup creates the Workflow collections.
BEGIN;

ALTER TABLE IF EXISTS workflow_versions
  ADD COLUMN IF NOT EXISTS restored_from_version_id text,
  ADD COLUMN IF NOT EXISTS pruned_at integer;
ALTER TABLE IF EXISTS workflow_runs
  ADD COLUMN IF NOT EXISTS cancellation_requested_at integer,
  ADD COLUMN IF NOT EXISTS cancelled_at integer,
  ADD COLUMN IF NOT EXISTS cancelled_by_hash text;

CREATE UNIQUE INDEX IF NOT EXISTS workflow_versions_version_id_uq
  ON workflow_versions (version_id);

-- Existing workflow records predate workflow_versions rows. Materialize each
-- current encrypted graph reference before manual acceptance requires a pin.
INSERT INTO workflow_versions (
  id,
  version_id,
  workflow_id,
  hashed_user_id,
  version_number,
  graph_json,
  graph_hash,
  encrypted_graph_secrets,
  created_by_client,
  created_at
)
SELECT
  gen_random_uuid(),
  workflow.current_version_id,
  workflow.workflow_id,
  workflow.hashed_user_id,
  COALESCE((current_version.value->>'version_number')::integer, workflow.version, 1),
  jsonb_build_object('encrypted_graph_ref', COALESCE(current_version.value->>'encrypted_graph_ref', workflow.record_json->>'encrypted_graph_ref')),
  COALESCE(current_version.value->>'encrypted_graph_checksum', workflow.record_json->>'encrypted_graph_checksum'),
  COALESCE(current_version.value->>'encrypted_graph_ref', workflow.record_json->>'encrypted_graph_ref'),
  COALESCE(current_version.value->>'created_by_client', workflow.source, 'system'),
  COALESCE((current_version.value->>'created_at')::integer, workflow.created_at, 0)
FROM workflows AS workflow
LEFT JOIN LATERAL jsonb_array_elements(COALESCE(workflow.record_json::jsonb->'versions', '[]'::jsonb)) AS current_version(value)
  ON current_version.value->>'id' = workflow.current_version_id
LEFT JOIN workflow_versions AS existing_version
  ON existing_version.version_id = workflow.current_version_id
WHERE existing_version.version_id IS NULL
  AND workflow.current_version_id IS NOT NULL
  AND COALESCE(current_version.value->>'encrypted_graph_ref', workflow.record_json->>'encrypted_graph_ref') IS NOT NULL
  AND COALESCE(current_version.value->>'encrypted_graph_checksum', workflow.record_json->>'encrypted_graph_checksum') IS NOT NULL
ON CONFLICT (version_id) DO NOTHING;

CREATE INDEX IF NOT EXISTS workflow_triggers_due_claim_idx
  ON workflow_triggers (next_run_at, trigger_id)
  WHERE enabled = true AND trigger_type = 'schedule';
CREATE INDEX IF NOT EXISTS workflow_triggers_due_owner_idx
  ON workflow_triggers (owner_user_id, next_run_at, trigger_id)
  WHERE enabled = true AND trigger_type = 'schedule' AND owner_user_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS workflow_triggers_event_routing_idx
  ON workflow_triggers (hashed_user_id, hashed_project_id, source, event_type, trigger_id)
  WHERE enabled = true AND trigger_type = 'event';
CREATE UNIQUE INDEX IF NOT EXISTS workflow_runs_acceptance_identity_uq
  ON workflow_runs (acceptance_idempotency_key);
CREATE UNIQUE INDEX IF NOT EXISTS workflow_event_receipts_trigger_event_uq
  ON workflow_event_receipts (trigger_id, event_id);
CREATE UNIQUE INDEX IF NOT EXISTS workflow_template_projections_workflow_uq
  ON workflow_template_projections (workflow_id);
CREATE UNIQUE INDEX IF NOT EXISTS workflow_input_events_session_event_uq
  ON workflow_input_events (session_id, event_id);
CREATE INDEX IF NOT EXISTS workflow_input_sessions_owner_updated_idx
  ON workflow_input_sessions (hashed_user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS workflow_input_mutations_session_created_idx
  ON workflow_input_mutations (session_id, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS workflow_assistant_proposals_proposal_id_uq
  ON workflow_assistant_proposals (proposal_id);
CREATE INDEX IF NOT EXISTS workflow_assistant_proposals_pending_expiry_idx
  ON workflow_assistant_proposals (expires_at, proposal_id)
  WHERE status = 'pending';

COMMIT;
