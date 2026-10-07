<script lang="ts">
  import TeamAvatar from './TeamAvatar.svelte';
  import type { TeamViewModel } from '../../services/teamService';

  let { team }: { team: TeamViewModel } = $props();
</script>

<span class="profile-team-badge" data-testid="profile-active-team-avatar" role="img" aria-label={`Active team: ${team.name}`}>
  <TeamAvatar {team} size={22} />
</span>

<style>
  .profile-team-badge {
    position: absolute;
    left: -0.125rem;
    bottom: -0.25rem;
    display: inline-flex;
    width: 1.5rem;
    height: 1.5rem;
    box-sizing: border-box;
    align-items: center;
    justify-content: center;
    border: 0.0625rem solid var(--color-grey-0);
    border-radius: var(--radius-full);
    box-shadow: var(--shadow-xs);
    pointer-events: none;
  }
</style>
