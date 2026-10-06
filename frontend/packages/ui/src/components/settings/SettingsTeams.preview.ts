/** The default preview retains the account-free joined-team list state. */
import type { TeamBillingSummary, TeamStorageNotice, TeamStorageSummary, TeamViewModel } from '../../services/teamService';

const team: TeamViewModel = {
  team_id: 'preview-team', name: 'Example team', description: 'Shared encrypted team', role: 'owner', status: 'active',
  profileImageMetadata: {}, zeroBalance: 0, createdAt: 1_700_000_000, updatedAt: 1_700_000_000,
  encrypted: { team_id: 'preview-team' },
};
const billing: TeamBillingSummary = { balanceCredits: 12, version: 1, raw: { balance_credits: 12, version: 1 } };
const storage: TeamStorageSummary = {
  total_bytes: 1_610_612_736, legacy_upload_bytes: 0, logical_s3_bytes: 1_610_612_736,
  categories: { cold_chat_graphs: 1_610_612_736 }, measurement_at: 1_791_072_000,
  metering_source_version: 'logical-s3-v1', metering_policy_version: 'team-storage-1gb-3credits-week-v1',
  free_bytes: 1_073_741_824, credits_per_started_excess_gib_per_week: 3, billable_gib: 1,
  weekly_cost_credits: 3, billing_status: 'disabled_pending_validation',
  billing: { status: 'disabled_pending_validation', warning_count: 0, deadline_at: null,
    expiry_due: false, expiry_enabled: false, affected_units: [], has_more_affected_units: false },
};
const unit = { unit_id: 'a'.repeat(64), kind: 'cold_chat' as const, resource_id: 'chat-1',
  oldest_at: 1_700_000_000, bytes: 536_870_912, fingerprint: 'preview' };
const notice: TeamStorageNotice = { episode_id: 'episode-1', warning_count: 3,
  deadline_at: 1_791_936_000, manual_review: false, unit_selection_hash: 'preview',
  units: [unit], has_more: true, next_after_unit_id: unit.unit_id };

export default { activeSettingsView: 'teams' };
export const variants = {
  owner: { activeSettingsView: 'teams/preview-team', previewData: { team, billing, storage, notice: null } },
  viewer: { activeSettingsView: 'teams/preview-team', previewData: { team: { ...team, role: 'viewer' }, billing, storage, notice: null } },
  admin: { activeSettingsView: 'teams/preview-team', previewData: { team: { ...team, role: 'admin' }, billing, storage, notice: null } },
  notice: { activeSettingsView: 'teams/preview-team', previewData: { team, billing,
  storage: { ...storage, billing_status: 'unpaid', billing: { ...storage.billing, status: 'unpaid', warning_count: 3, deadline_at: notice.deadline_at } },
  notice } },
};
