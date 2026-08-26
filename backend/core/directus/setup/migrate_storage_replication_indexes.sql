-- Required identities and bounded due-work scans for regional object storage.
-- Run after cms-setup creates replication jobs, tombstones, and health state.
-- PostgreSQL aborts if existing duplicate identities violate safety.
BEGIN;

CREATE UNIQUE INDEX IF NOT EXISTS storage_replication_jobs_identity_uq
  ON storage_replication_jobs (idempotency_key);
CREATE INDEX IF NOT EXISTS storage_replication_jobs_due_idx
  ON storage_replication_jobs (next_attempt_at, created_at)
  WHERE state IN ('pending', 'retry_scheduled');

CREATE UNIQUE INDEX IF NOT EXISTS storage_deletion_tombstones_identity_uq
  ON storage_deletion_tombstones (idempotency_key);
CREATE INDEX IF NOT EXISTS storage_deletion_tombstones_due_idx
  ON storage_deletion_tombstones (next_attempt_at, created_at)
  WHERE state IN ('pending', 'retry_scheduled');

CREATE UNIQUE INDEX IF NOT EXISTS storage_region_health_region_uq
  ON storage_region_health (region);

COMMIT;
