<!--
  TaskDetailPage.svelte
  Canonical encrypted Task detail surface for stable nested routes.
  The task adapter retains client-side encryption and server metadata versions.
-->

<script lang="ts">
  import { onMount, untrack } from 'svelte';
  import WorkspaceReportIssueButton from '../workspace/WorkspaceReportIssueButton.svelte';
  import TaskDetailContent from './TaskDetailContent.svelte';
  import { taskDetailAdapter } from '../workspace/detailMetadataAdapters';
  import { getTaskAssignmentEligibility, isUserTaskDeleted, peekTaskAssignmentEligibility, peekUserTask, subscribeUserTasks, type UserTaskViewModel } from '../../services/userTaskService';
  import { text } from '@repo/ui';
  import { getWorkspaceCacheIdentity } from '../../services/workspaceQueryCache';
  import { userProfile } from '../../stores/userProfile';

  let { taskId }: { taskId: string } = $props();
  let task = $state<UserTaskViewModel | null>(null);
  let visibleTask = $derived(task?.task_id === taskId ? task : peekUserTask(taskId) ?? null);
  let hasError = $state(false);
  let canAssignCodex = $state(peekTaskAssignmentEligibility() ?? false);
  let loadGeneration = 0;
  let domainLabel = $derived($text('navigation.tasks'));
  onMount(() => {
    let displayedScope = getWorkspaceCacheIdentity();
    const unsubscribe = subscribeUserTasks(() => {
      const scope = getWorkspaceCacheIdentity();
      if (scope !== displayedScope) {
        displayedScope = scope;
        loadGeneration += 1;
        task = null;
        canAssignCodex = false;
        if (scope) void load(taskId);
      }
      const cached = peekUserTask(taskId);
      if (cached) task = cached;
      else if (isUserTaskDeleted(taskId)) { task = null; hasError = true; }
      canAssignCodex = peekTaskAssignmentEligibility() ?? false;
    });
    return unsubscribe;
  });
  $effect(() => {
    const requestedTaskId = taskId;
    const userId = $userProfile.user_id;
    if (!userId) { loadGeneration += 1; task = null; canAssignCodex = false; return; }
    untrack(() => void load(requestedTaskId));
  });
  async function load(requestedTaskId: string): Promise<void> {
    const generation = ++loadGeneration;
    const scope = getWorkspaceCacheIdentity();
    hasError = false;
    if (task?.task_id !== requestedTaskId) task = null;
    try {
      const loaded = await taskDetailAdapter.load(requestedTaskId);
      if (generation !== loadGeneration || taskId !== requestedTaskId || scope !== getWorkspaceCacheIdentity()) return;
      task = loaded;
      const eligibility = peekTaskAssignmentEligibility();
      if (eligibility !== undefined) canAssignCodex = eligibility;
      else void getTaskAssignmentEligibility().then((eligible) => {
        if (generation === loadGeneration && taskId === requestedTaskId && scope === getWorkspaceCacheIdentity()) canAssignCodex = eligible;
      }).catch((error) => console.error('[TaskDetailPage] Failed to load assignment eligibility:', error));
    } catch (value) {
      if (generation !== loadGeneration || taskId !== requestedTaskId || scope !== getWorkspaceCacheIdentity()) return;
      if (!visibleTask) hasError = true;
      console.error('[TaskDetailPage] Failed to load task:', value);
    }
  }
  function handleTaskChange(updated: UserTaskViewModel): void { task = updated; }
</script>

<section class="detail-page" data-testid="task-detail-page">
  <nav><a href="/#tasks">{domainLabel}</a><WorkspaceReportIssueButton /></nav>
  {#if visibleTask}
    {#key visibleTask.task_id}<TaskDetailContent task={visibleTask} {canAssignCodex} onTaskChange={handleTaskChange} />{/key}
  {:else if hasError}<div class="state" role="alert"><p>{$text('common.detail_load_error', { values: { item: domainLabel } })}</p><button type="button" onclick={() => void load(taskId)}>{$text('common.retry')}</button></div>
  {:else}<div class="state">{$text('common.detail_loading', { values: { item: domainLabel } })}</div>{/if}
</section>

<style>
  .detail-page { width: 100%; height: 100%; overflow: auto; background: var(--color-grey-0); color: var(--color-font-primary); }
  nav { display: flex; align-items: center; justify-content: space-between; padding: var(--spacing-5) var(--spacing-8); }
  nav a { color: var(--color-font-primary); }
  .state { display: grid; min-height: 240px; place-content: center; gap: var(--spacing-5); text-align: center; }
</style>
