<script lang="ts">
  import { onMount } from 'svelte';
  import { get } from 'svelte/store';
  import WorkspaceHomeShell from '../workspace/WorkspaceHomeShell.svelte';
  import { activeTeamContext } from '../../stores/teamStore';
  import type { TeamViewModel } from '../../services/teamService';

  let { surface = 'projects' }: { surface?: 'projects' | 'tasks' | 'workflows' } = $props();
  const previewTeam: TeamViewModel = {
    team_id: 'preview-team', name: 'Preview Team', description: '', role: 'member',
    status: 'active', zeroBalance: 0, createdAt: 0, updatedAt: 0,
    profileImageMetadata: { mode: 'generated', icon_name: 'team', icon_color: '#ffffff', background_color: '#4d73ff' },
    encrypted: { team_id: 'preview-team' },
  };
  onMount(() => {
    const previous = get(activeTeamContext);
    activeTeamContext.set({ team: previewTeam, teamId: previewTeam.team_id, epoch: previous.epoch + 1 });
    return () => activeTeamContext.set(previous);
  });
</script>

<WorkspaceHomeShell {surface} heading="Preview workspace" showComposer={false} />
