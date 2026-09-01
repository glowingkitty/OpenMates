<!--
  TaskDetailFullscreen.svelte
  Read-only Task fullscreen opened from the central Kanban board.
  Reuses UnifiedEmbedFullscreen for minimize/Escape behavior and delegates all
  task metadata rendering to TaskDetailContent for direct-route parity.
  Design reference: Figma Website node 5754:76027.
-->

<script lang="ts">
  import { onMount, tick } from 'svelte';
  import { focusTrap } from '../../actions/focusTrap';
  import UnifiedEmbedFullscreen from '../embeds/UnifiedEmbedFullscreen.svelte';
  import type { UserTaskDependencyViewModel, UserTaskViewModel } from '../../services/userTaskService';
  import { userProfile } from '../../stores/userProfile';
  import TaskDetailContent from './TaskDetailContent.svelte';

  interface TaskDetailRelatedData {
    projects: Array<{ id: string; title: string; description: string }>;
    plan: { id: string; title: string; description: string } | null;
    chat: { id: string; title: string } | null;
    dependencies: Array<UserTaskDependencyViewModel & { title: string }>;
  }

  let {
    task,
    related,
    onClose,
  }: {
    task: UserTaskViewModel;
    related?: TaskDetailRelatedData;
    onClose: () => void;
  } = $props();

  const priorityLabels = ['No priority', 'Low', 'Medium', 'High', 'Urgent'];
  let dialogElement = $state<HTMLElement | null>(null);
  let creatorName = $derived($userProfile.username.trim() || 'You');
  let statusLabel = $derived(task.status === 'todo' ? 'To do' : task.status.replace('_', ' ').replace(/^./, (value) => value.toUpperCase()));
  let priorityLabel = $derived(priorityLabels[Math.max(0, Math.min(priorityLabels.length - 1, task.priority))]);

  onMount(async () => {
    await tick();
    await new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
    dialogElement?.querySelector<HTMLElement>('[data-testid="task-detail-minimize"]')?.focus();
  });

  function formatDate(timestamp: number): string {
    return new Intl.DateTimeFormat('en-US', { year: 'numeric', month: 'short', day: 'numeric' }).format(new Date(timestamp * 1000));
  }

  function createdLabel(): string {
    const seconds = Math.max(0, Math.floor(Date.now() / 1000) - task.createdAt);
    if (seconds < 60) return 'Created seconds ago';
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `Created ${minutes} minute${minutes === 1 ? '' : 's'} ago`;
    return `Created ${formatDate(task.createdAt)}`;
  }
</script>

<div
  class="task-detail-dialog"
  role="dialog"
  aria-modal="true"
  aria-label={`Task details: ${task.title || 'Untitled task'}`}
  bind:this={dialogElement}
  use:focusTrap
>
  <UnifiedEmbedFullscreen
    testId="task-detail-fullscreen"
    closeTestId="task-detail-minimize"
    appId="tasks"
    skillId="task"
    skillIconName="task"
    embedHeaderTitle={task.title || 'Untitled task'}
    embedHeaderSubtitle={`${createdLabel()} by ${creatorName}`}
    showShare={false}
    {onClose}
  >
    {#snippet embedHeaderCta()}
      <div class="task-header-badges" aria-label="Task status and priority">
        <span class="priority" data-testid="task-detail-priority">{priorityLabel}</span>
        <span data-testid="task-detail-status">{statusLabel}</span>
      </div>
    {/snippet}
    {#snippet content()}
      <TaskDetailContent {task} {related} showTitle={false} />
    {/snippet}
  </UnifiedEmbedFullscreen>
</div>

<style>
  .task-detail-dialog { position: absolute; inset: 0; z-index: var(--z-index-dropdown); }
  .task-header-badges { display: flex; align-items: center; justify-content: center; gap: 8px; }
  .task-header-badges span { padding: 6px 11px; border-radius: var(--radius-full); background: color-mix(in srgb, var(--color-grey-0) 22%, transparent); color: var(--color-grey-0); font-size: var(--font-size-xs); font-weight: 700; }
  .task-header-badges .priority { background: var(--color-error); }
</style>
