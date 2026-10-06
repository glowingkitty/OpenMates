import type { TeamViewModel } from '../../services/teamService';

const generated: TeamViewModel = {
  team_id: 'preview-team', name: 'Preview Team', description: '', role: 'member', status: 'active',
  profileImageMetadata: { mode: 'generated', icon_name: 'team', icon_color: '#ffffff', background_color: '#4d73ff' },
  zeroBalance: 0, createdAt: 0, updatedAt: 0, encrypted: { team_id: 'preview-team' },
};

export default { team: generated, size: 48, testId: 'preview-team-avatar' };
export const variants = {
  uploaded: {
    team: {
      ...generated,
      profileImageMetadata: {
        mode: 'uploaded', team_id: 'preview-team', image_url: '/v1/teams/preview-team/profile-image',
        content_safety_status: 'accepted', updated_at: 1,
      },
    },
    size: 48,
    testId: 'preview-team-avatar',
  },
};
