import type { TeamViewModel } from '../../services/teamService';

const team: TeamViewModel = {
  team_id: 'preview-workspace-team',
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
  encrypted: { team_id: 'preview-workspace-team' },
};

export default { team, surface: 'workflows', avatarTestId: 'workflows-workspace-team-avatar', iconTestId: 'workflows-workspace-background-icon' };
export const variants = {
  workflows: { team, surface: 'workflows', avatarTestId: 'workflows-workspace-team-avatar', iconTestId: 'workflows-workspace-background-icon' },
  chats: { team, surface: 'chats', avatarTestId: 'chats-workspace-team-avatar', iconTestId: 'guest-workspace-icon' },
  projects: { team, surface: 'projects', avatarTestId: 'projects-workspace-team-avatar', iconTestId: 'projects-workspace-background-icon' },
  tasks: { team, surface: 'tasks', avatarTestId: 'tasks-workspace-team-avatar', iconTestId: 'tasks-workspace-background-icon' },
  personal: { team: null, surface: 'workflows', avatarTestId: 'workflows-workspace-team-avatar', iconTestId: 'workflows-workspace-background-icon' },
};
