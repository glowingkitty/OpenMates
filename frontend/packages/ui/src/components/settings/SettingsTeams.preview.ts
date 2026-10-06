import type { TeamStorageNotice, TeamStorageSummary, TeamViewModel } from '../../services/teamService';

const team: TeamViewModel = {
  team_id: 'preview-team', name: 'Studio team', description: '', role: 'owner', status: 'active',
  profileImageMetadata: { version: 1, mode: 'generated', icon_name: 'design', icon_color: '#ffffff', background_color: '#4d73ff' },
  zeroBalance: 0, createdAt: 1, updatedAt: 1, encrypted: { team_id: 'preview-team' },
  securityPolicy: { restrict_email_domains: false, allowed_email_domains: [], require_invite_link_approval: true, require_strong_auth: false },
};

const previewData = {
  teams: [team],
  billing: { balanceCredits: 0, raw: {} },
  members: [
    { user_id: 'owner-preview', role: 'owner', status: 'active', profile: { display_name: 'Mira', avatar: { mode: 'generated', icon_name: 'mate', background_color: '#4d73ff' } } },
    { user_id: 'member-preview', role: 'member', status: 'active', profile: { display_name: 'Alex', avatar: { mode: 'generated', icon_name: 'mate', background_color: '#8b62c9' } } },
  ],
  invites: [{ invite_id: 'preview-invite', role: 'member', status: 'pending', kind: 'email', recipientEmail: 'alex@example.org' }],
};

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

/** Default preview is a valid first visit to Teams settings. */
export default { activeSettingsView: 'teams', previewData: { teams: [] } };

export const variants = {
  teamsListing: { activeSettingsView: 'teams', previewData: { teams: [team, { ...team, team_id: 'second-preview-team', name: 'Field team', role: 'admin' as const, createdAt: 2, updatedAt: 2 }] } },
  create: { activeSettingsView: 'teams/new', previewData: { teams: [] } },
  avatar: { activeSettingsView: 'teams/new/avatar', previewData: { teams: [] } },
  detail: { activeSettingsView: 'teams/preview-team', previewData },
  members: { activeSettingsView: 'teams/preview-team/members', previewData },
  uploadedAvatar: { activeSettingsView: 'teams/preview-team/avatar', previewData: { ...previewData, teams: [{ ...team, profileImageMetadata: { mode: 'uploaded', team_id: team.team_id, image_url: '/v1/teams/preview-team/profile-image', content_safety_status: 'accepted' } }] } },
  memberDetail: { activeSettingsView: 'teams/preview-team/members/member-preview', previewData },
  viewerMembers: { activeSettingsView: 'teams/preview-team/members', previewData: { ...previewData, teams: [{ ...team, role: 'viewer' as const }] } },
  viewerDetail: { activeSettingsView: 'teams/preview-team', previewData: { ...previewData, teams: [{ ...team, role: 'viewer' as const }] } },
  viewerMemberDetail: { activeSettingsView: 'teams/preview-team/members/member-preview', previewData: { ...previewData, teams: [{ ...team, role: 'viewer' as const }] } },
  restrictedMembers: { activeSettingsView: 'teams/preview-team/members', previewData: { ...previewData, teams: [{ ...team, securityPolicy: { ...team.securityPolicy!, restrict_email_domains: true, allowed_email_domains: ['example.org'] } }] } },
  security: { activeSettingsView: 'teams/preview-team/security', previewData },
  delete: { activeSettingsView: 'teams/preview-team/delete', previewData },
  owner: { activeSettingsView: 'teams/preview-team', previewData: { ...previewData, storage, notice: null } },
  viewer: { activeSettingsView: 'teams/preview-team', previewData: { ...previewData, teams: [{ ...team, role: 'viewer' as const }], storage, notice: null } },
  admin: { activeSettingsView: 'teams/preview-team', previewData: { ...previewData, teams: [{ ...team, role: 'admin' as const }], storage, notice: null } },
  notice: { activeSettingsView: 'teams/preview-team', previewData: { ...previewData,
    storage: { ...storage, billing_status: 'unpaid' as const,
      billing: { ...storage.billing, status: 'unpaid' as const, warning_count: 3, deadline_at: notice.deadline_at } },
    notice } },
};
