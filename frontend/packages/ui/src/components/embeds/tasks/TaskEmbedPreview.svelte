<!--
  frontend/packages/ui/src/components/embeds/tasks/TaskEmbedPreview.svelte
  Snapshot child card for a task embed.
  The preview stays lightweight and does not load encrypted task detail data.
  Fullscreen handles live workspace loading and editing when possible.
-->

<script lang="ts">
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import { taskAssigneeLabel, taskStatusLabel } from './taskEmbedData';

  interface Props {
    id: string;
    taskId?: string;
    shortId?: string;
    title?: string;
    description?: string;
    status?: string;
    assignee?: string;
    isMobile?: boolean;
    onFullscreen: () => void;
  }

  let {
    id,
    taskId = '',
    shortId = '',
    title = '',
    description = '',
    status = 'todo',
    assignee = '',
    isMobile = false,
    onFullscreen,
  }: Props = $props();

  let displayTitle = $derived(title || 'Untitled task');
  let displayId = $derived(shortId || taskId);

  function handleStop() {
    // Task child cards are not cancellable.
  }
</script>

<UnifiedEmbedPreview
  {id}
  appId="tasks"
  skillId="task"
  skillIconName="task"
  status="finished"
  skillName="Task"
  {isMobile}
  {onFullscreen}
  onStop={handleStop}
  showStatus={false}
  showSkillIcon={false}
>
  {#snippet details()}
    <article class="task-card" data-testid="task-embed-card">
      <div class="icon-shell" aria-hidden="true"><span class="clickable-icon icon_task"></span></div>
      <div class="card-body">
        <div class="kicker">{displayId || taskStatusLabel(status)}</div>
        <h3>{displayTitle}</h3>
        {#if description}<p>{description}</p>{/if}
        <div class="meta-row">
          <span>{taskStatusLabel(status)}</span>
          <span>{taskAssigneeLabel(assignee)}</span>
        </div>
      </div>
    </article>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .task-card {
    display: flex;
    align-items: stretch;
    gap: var(--spacing-5);
    width: 100%;
    height: 100%;
    padding: var(--spacing-6);
  }

  .icon-shell {
    display: grid;
    flex: 0 0 56px;
    place-items: center;
    border-radius: 18px;
    background: linear-gradient(135deg, var(--color-app-tasks-start, var(--color-primary-start)), var(--color-app-tasks-end, var(--color-primary-end)));
  }

  .icon_task {
    width: 28px;
    height: 28px;
    background: var(--color-grey-0) !important;
  }

  .card-body {
    display: flex;
    min-width: 0;
    flex: 1 1 0;
    flex-direction: column;
    justify-content: center;
    gap: var(--spacing-3);
  }

  .kicker,
  .meta-row {
    color: var(--color-font-secondary);
    font-size: var(--font-size-xs);
    font-weight: 600;
  }

  h3,
  p {
    margin: 0;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  h3 {
    color: var(--color-font-primary);
    font-size: var(--font-size-sm);
    font-weight: 700;
    line-height: 1.25;
  }

  p {
    display: -webkit-box;
    color: var(--color-font-secondary);
    font-size: var(--font-size-xs);
    line-height: 1.35;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
  }

  .meta-row {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  .meta-row span {
    padding: 2px 7px;
    border-radius: var(--radius-full);
    background: var(--color-grey-10);
  }

  :global(.unified-embed-preview.mobile) .task-card {
    flex-direction: column;
  }
  :global(.unified-embed-preview.mobile) .icon-shell {
    flex: 0 0 48px;
  }
</style>
