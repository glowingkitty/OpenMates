<script lang="ts">
  import TeamAvatar from './TeamAvatar.svelte';
  import type { TeamViewModel } from '../../services/teamService';

  let { team = null, surface, avatarTestId, iconTestId }: {
    team?: TeamViewModel | null;
    surface: string;
    avatarTestId: string;
    iconTestId: string;
  } = $props();
</script>

<span class="workspace-identity" aria-hidden="true">
  {#if team}
    <span class="workspace-team-avatar" data-testid={avatarTestId}>
      <TeamAvatar {team} size="var(--workspace-avatar-size)" />
    </span>
  {/if}
  <span class="workspace-surface-icon" data-testid={iconTestId} data-surface={surface}></span>
</span>

<style>
  .workspace-identity {
    --workspace-avatar-size: clamp(76px, 11vw, 128px);
    position: absolute;
    left: 50%;
    top: 50%;
    z-index: -1;
    display: inline-flex;
    align-items: center;
    gap: 10px;
    transform: translate(-50%, -54%);
    pointer-events: none;
  }

  .workspace-team-avatar,
  .workspace-surface-icon {
    display: inline-flex;
    flex: none;
    width: var(--workspace-avatar-size);
    height: var(--workspace-avatar-size);
  }

  .workspace-team-avatar {
    border-radius: var(--radius-full);
    opacity: 0.3;
  }

  .workspace-surface-icon {
    background: var(--color-grey-30);
    -webkit-mask: url('@openmates/ui/static/icons/chat.svg') center / contain no-repeat;
    mask: url('@openmates/ui/static/icons/chat.svg') center / contain no-repeat;
  }

  .workspace-surface-icon[data-surface='apps'] {
    -webkit-mask-image: url('@openmates/ui/static/icons/app.svg');
    mask-image: url('@openmates/ui/static/icons/app.svg');
  }

  .workspace-surface-icon[data-surface='projects'] {
    -webkit-mask-image: url('@openmates/ui/static/icons/project.svg');
    mask-image: url('@openmates/ui/static/icons/project.svg');
  }

  .workspace-surface-icon[data-surface='plans'] {
    -webkit-mask-image: url('@openmates/ui/static/icons/task.svg');
    mask-image: url('@openmates/ui/static/icons/task.svg');
  }

  .workspace-surface-icon[data-surface='workflows'] {
    -webkit-mask-image: url('@openmates/ui/static/icons/workflow.svg');
    mask-image: url('@openmates/ui/static/icons/workflow.svg');
  }

  .workspace-surface-icon[data-surface='tasks'] {
    -webkit-mask-image: url('@openmates/ui/static/icons/projectmanagement.svg');
    mask-image: url('@openmates/ui/static/icons/projectmanagement.svg');
  }

  .workspace-surface-icon[data-surface='teams'] {
    -webkit-mask-image: url('@openmates/ui/static/icons/team.svg');
    mask-image: url('@openmates/ui/static/icons/team.svg');
  }
</style>
