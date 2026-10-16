import type { TeamViewModel } from '../../services/teamService';

const team: TeamViewModel = {
  team_id: 'preview-team', name: 'Studio team', description: '', role: 'member', status: 'active',
  profileImageMetadata: { version: 1, mode: 'generated', icon_name: 'team', icon_color: '#ffffff', background_color: '#4d73ff' },
  zeroBalance: 0, createdAt: 1, updatedAt: 1, encrypted: { team_id: 'preview-team' },
};

const props = { team, activeSettingsView: 'teams/preview-team/members/member-preview' };
export default { ...props, memberName: 'Alex' };
export const variants = {
  coldMemberLink: { ...props, memberName: '[T:settings.teams.preview_team.members.member_preview]' },
  missingMemberTitle: { ...props, memberName: '' },
};
