<!--
  TaskDetailPage.svelte
  Canonical encrypted Task detail surface for stable nested routes.
  The task adapter retains client-side encryption and server metadata versions.
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import WorkspaceReportIssueButton from '../workspace/WorkspaceReportIssueButton.svelte';
  import TaskDetailContent from './TaskDetailContent.svelte';
  import { taskDetailAdapter } from '../workspace/detailMetadataAdapters';
  import { getTaskAssignmentEligibility, type UserTaskViewModel } from '../../services/userTaskService';
  import { text } from '@repo/ui';

  let { taskId }: { taskId: string } = $props();
  let task = $state<UserTaskViewModel | null>(null);
  let hasError = $state(false);
  let canAssignCodex = $state(false);
  let domainLabel = $derived($text('navigation.tasks'));
  onMount(() => { void load(); });
  async function load(): Promise<void> {
    hasError = false;
    canAssignCodex = false;
    try {
      const [loadedTask, eligible] = await Promise.all([taskDetailAdapter.load(taskId), getTaskAssignmentEligibility()]);
      task = loadedTask;
      canAssignCodex = eligible;
    } catch (value) { hasError = true; console.error('[TaskDetailPage] Failed to load task:', value); }
  }
  function handleTaskChange(updated: UserTaskViewModel): void { task = updated; }
</script>

<section class="detail-page" data-testid="task-detail-page">
  <nav><a href="/tasks">{domainLabel}</a><WorkspaceReportIssueButton /></nav>
  {#if task}
    <TaskDetailContent {task} {canAssignCodex} onTaskChange={handleTaskChange} />
  {:else if hasError}<div class="state" role="alert"><p>{$text('common.detail_load_error', { values: { item: domainLabel } })}</p><button type="button" onclick={() => void load()}>{$text('common.retry')}</button></div>
  {:else}<div class="state">{$text('common.detail_loading', { values: { item: domainLabel } })}</div>{/if}
</section>

<style>
  .detail-page { width: 100%; height: 100%; overflow: auto; background: var(--color-grey-0); color: var(--color-font-primary); }
  nav { display: flex; align-items: center; justify-content: space-between; padding: var(--spacing-5) var(--spacing-8); }
  nav a { color: var(--color-font-primary); }
  .state { display: grid; min-height: 240px; place-content: center; gap: var(--spacing-5); text-align: center; }
</style>
