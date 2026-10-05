-- Owner debt scans and immutable weekly charge identities.
BEGIN;
CREATE INDEX IF NOT EXISTS storage_billing_periods_owner_debt_idx
  ON storage_billing_periods (hashed_user_id, state, period_start_at, id);
CREATE UNIQUE INDEX IF NOT EXISTS storage_billing_periods_charge_uq
  ON storage_billing_periods (charge_id);
CREATE INDEX IF NOT EXISTS storage_billing_owner_dunning_due_idx
  ON storage_billing_owner_state (id, last_warning_at)
  WHERE warning_count BETWEEN 1 AND 3
    AND closed_at IS NULL AND warning_manual_review_at IS NULL;
CREATE INDEX IF NOT EXISTS email_deliveries_storage_warning_retry_idx
  ON email_deliveries (processing_started_at, id)
  WHERE email_type = 'storage-billing-warning'
    AND storage_warning_acknowledged_at IS NULL
    AND status IN ('processing', 'failed', 'sent');
CREATE INDEX IF NOT EXISTS email_deliveries_storage_receipt_pending_idx
  ON email_deliveries (provider_receipt_checked_at, id)
  WHERE email_type = 'storage-billing-warning'
    AND status = 'sent'
    AND provider_delivery_state = 'accepted'
    AND storage_warning_acknowledged_at IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS storage_billing_warning_units_episode_unit_uq
  ON storage_billing_warning_units (episode_id, unit_id);
CREATE INDEX IF NOT EXISTS storage_billing_warning_units_owner_page_idx
  ON storage_billing_warning_units (hashed_user_id, episode_id, unit_id);
CREATE INDEX IF NOT EXISTS storage_billing_periods_waiver_episode_idx
  ON storage_billing_periods (hashed_user_id, waived_episode_id)
  WHERE waived_episode_id IS NOT NULL;
COMMIT;
