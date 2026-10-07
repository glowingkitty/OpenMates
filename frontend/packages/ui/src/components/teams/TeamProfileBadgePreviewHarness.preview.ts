import type { TeamViewModel } from '../../services/teamService';

const team: TeamViewModel = {
  team_id: 'preview-profile-team',
  name: 'Preview team',
  description: '',
  role: 'owner',
  status: 'active',
  profileImageMetadata: {
    version: 1, mode: 'generated', icon_name: 'team', icon_color: '#ffffff',
    background_color: '#4d73ff',
  },
  zeroBalance: 0,
  createdAt: 0,
  updatedAt: 0,
  encrypted: { team_id: 'preview-profile-team' },
};

export default { team };
