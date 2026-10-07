<script lang="ts">
  import TeamProfileBadge from './TeamProfileBadge.svelte';
  import type { TeamViewModel } from '../../services/teamService';

  let { team }: { team: TeamViewModel } = $props();
</script>

<span class="profile-avatar-preview-parent" data-testid="profile-avatar-preview-parent">
  <span class="profile-avatar-preview-icon" aria-hidden="true"></span>
  <TeamProfileBadge {team} />
</span>

<style>
  .profile-avatar-preview-parent {
    position: relative;
    display: inline-flex;
    width: 50px;
    height: 50px;
    align-items: center;
    justify-content: center;
    border-radius: var(--radius-full);
    background: var(--color-grey-20);
    box-shadow: var(--shadow-xs);
  }

  .profile-avatar-preview-icon {
    width: 25px;
    height: 25px;
    background: var(--color-grey-60);
    -webkit-mask: url('@openmates/ui/static/icons/user.svg') center / contain no-repeat;
    mask: url('@openmates/ui/static/icons/user.svg') center / contain no-repeat;
  }
</style>
