import type { TeamViewModel } from '../../services/teamService';

const teams: TeamViewModel[] = Array.from({ length: 7 }, (_, index) => ({
  team_id: `preview-team-${index + 1}`,
  name: `Preview Team ${index + 1}`,
  description: '',
  role: 'member',
  status: 'active',
  profileImageMetadata: {
    version: 1, mode: 'generated', icon_name: 'team', icon_color: '#ffffff',
    background_color: index % 2 ? '#5648b8' : '#4d73ff',
  },
  zeroBalance: 0,
  createdAt: 0,
  updatedAt: 0,
  encrypted: { team_id: `preview-team-${index + 1}` },
}));

export default { teams, activeTeamId: null, onTeamContextChange: () => {}, onCreateTeam: () => {} };
export const variants = {
  active: { teams, activeTeamId: 'preview-team-1', onTeamContextChange: () => {}, onCreateTeam: () => {} },
  compact: { teams, activeTeamId: 'preview-team-1', compact: true, onTeamContextChange: () => {}, onCreateTeam: () => {} },
};
