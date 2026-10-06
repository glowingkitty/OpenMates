<script lang="ts">
  import TeamQuickAction from './TeamQuickAction.svelte';
  import type { TeamViewModel } from '../../services/teamService';

  const teams: TeamViewModel[] = [
    {
      team_id: 'preview-team', name: 'xHain', description: '', role: 'member', status: 'active',
      profileImageMetadata: { mode: 'generated', icon_name: 'team', icon_color: '#ffffff', background_color: '#358d50' },
      zeroBalance: 0, createdAt: 0, updatedAt: 0, encrypted: { team_id: 'preview-team' },
    },
    {
      team_id: 'preview-team-2', name: 'OpenMates', description: '', role: 'member', status: 'active',
      profileImageMetadata: { mode: 'generated', icon_name: 'user', icon_color: '#ffffff', background_color: '#4867cd' },
      zeroBalance: 0, createdAt: 0, updatedAt: 0, encrypted: { team_id: 'preview-team-2' },
    },
  ];
  let activeTeamId: string | null = $state(teams[0].team_id);
  let action = $state('');
</script>

<div class="preview-surface">
  <TeamQuickAction {teams} {activeTeamId} loading={false}
    onTeamContextChange={(contextId) => { activeTeamId = contextId === 'personal' ? null : contextId; action = 'context'; }}
    onTeamToggle={() => { activeTeamId = activeTeamId ? null : teams[0].team_id; action = 'toggle'; }}
    onCreateTeam={() => { action = 'create'; }}
    onOpenTeams={() => { action = 'open'; }} />
  <output class="preview-result" data-testid="team-quick-action-result" aria-live="polite">{action}</output>
</div>

<style>
  .preview-surface { width: 320px; min-height: 112px; padding: 8px; background: var(--color-grey-20); }
  .preview-result { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; }
</style>
