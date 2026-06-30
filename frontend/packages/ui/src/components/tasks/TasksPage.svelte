<!--
  TasksPage.svelte
  Central Tasks V1 workspace. Loads encrypted user tasks, decrypts them on the
  client, and renders a reusable Kanban board for all task statuses.
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import TaskBoard from './TaskBoard.svelte';
  import { notificationStore } from '../../stores/notificationStore';
  import {
    createUserTask,
    listUserTasks,
    startUserTaskWithAI,
    updateUserTask,
    type ListUserTasksFilters,
    type UserTaskStatus,
    type UserTaskViewModel,
  } from '../../services/userTaskService';
  import {
    activateUserPlan,
    completeUserPlan,
    createUserPlan,
    listUserPlans,
    type UserPlanViewModel,
  } from '../../services/userPlanService';

  let {
    projectId = null,
    chatId = null,
    compact = false,
  }: {
    projectId?: string | null;
    chatId?: string | null;
    compact?: boolean;
  } = $props();

  let tasks = $state<UserTaskViewModel[]>([]);
  let plans = $state<UserPlanViewModel[]>([]);
  let isLoading = $state(true);
  let isLoadingPlans = $state(true);
  let isSaving = $state(false);
  let planActionId = $state<string | null>(null);
  let hasLoadError = $state(false);
  let title = $state('');
  let description = $state('');
  let planTitle = $state('');
  let planSummary = $state('');
  let assignToAI = $state(false);

  const totalCount = $derived(tasks.length);
  const activeCount = $derived(tasks.filter((task) => task.status === 'in_progress').length);
  const doneCount = $derived(tasks.filter((task) => task.status === 'done').length);
  const activePlans = $derived(plans.filter((plan) => !['completed', 'archived'].includes(plan.status)));

  function filters(): ListUserTasksFilters {
    return {
      projectId: projectId ?? undefined,
      chatId: chatId ?? undefined,
    };
  }

  function broadcastTasksChanged(): void {
    if (typeof window === 'undefined') return;
    window.dispatchEvent(new CustomEvent('openmates-user-tasks-changed', {
      detail: { chatId, projectId },
    }));
  }

  function broadcastPlansChanged(): void {
    if (typeof window === 'undefined') return;
    window.dispatchEvent(new CustomEvent('openmates-user-plans-changed', {
      detail: { chatId, projectId },
    }));
  }

  async function refreshTasks(): Promise<void> {
    isLoading = true;
    try {
      hasLoadError = false;
      tasks = await listUserTasks(filters());
    } catch (error) {
      hasLoadError = true;
      console.error('[TasksPage] Failed to load tasks:', error);
      notificationStore.error('Failed to load tasks');
    } finally {
      isLoading = false;
    }
  }

  async function refreshPlans(): Promise<void> {
    isLoadingPlans = true;
    try {
      plans = await listUserPlans({
        projectId: projectId ?? undefined,
        chatId: chatId ?? undefined,
        limit: compact ? 5 : 12,
      });
    } catch (error) {
      console.error('[TasksPage] Failed to load plans:', error);
    } finally {
      isLoadingPlans = false;
    }
  }

  async function handleCreateTask(): Promise<void> {
    const trimmedTitle = title.trim();
    if (!trimmedTitle || isSaving) return;
    isSaving = true;
    try {
      const assignedToAI = assignToAI;
      const task = await createUserTask({
        title: trimmedTitle,
        description: description.trim(),
        assigneeType: assignedToAI ? 'ai' : 'user',
        primaryChatId: chatId,
        linkedProjectIds: projectId ? [projectId] : [],
      });
      tasks = [task, ...tasks];
      broadcastTasksChanged();
      title = '';
      description = '';
      assignToAI = false;
      notificationStore.success(assignedToAI ? 'AI task started' : 'Task created');
    } catch (error) {
      console.error('[TasksPage] Failed to create task:', error);
      notificationStore.error('Failed to create task');
    } finally {
      isSaving = false;
    }
  }

  async function handleCreatePlan(): Promise<void> {
    const trimmedTitle = planTitle.trim();
    if (!trimmedTitle || isSaving) return;
    isSaving = true;
    try {
      const plan = await createUserPlan({
        title: trimmedTitle,
        summary: planSummary.trim(),
        status: 'draft',
        primaryChatId: chatId,
        linkedProjectIds: projectId ? [projectId] : [],
      });
      plans = [plan, ...plans];
      broadcastPlansChanged();
      planTitle = '';
      planSummary = '';
      notificationStore.success('Plan created');
    } catch (error) {
      console.error('[TasksPage] Failed to create plan:', error);
      notificationStore.error('Failed to create plan');
    } finally {
      isSaving = false;
    }
  }

  async function handleMove(task: UserTaskViewModel, status: UserTaskStatus): Promise<void> {
    const previous = tasks;
    tasks = tasks.map((candidate) => candidate.task_id === task.task_id ? { ...candidate, status } : candidate);
    try {
      const updated = await updateUserTask(task, { status });
      tasks = tasks.map((candidate) => candidate.task_id === updated.task_id ? updated : candidate);
      broadcastTasksChanged();
    } catch (error) {
      tasks = previous;
      console.error('[TasksPage] Failed to update task:', error);
      notificationStore.error('Failed to update task');
    }
  }

  async function handleStartAI(task: UserTaskViewModel): Promise<void> {
    try {
      const updated = await startUserTaskWithAI(task);
      tasks = tasks.map((candidate) => candidate.task_id === updated.task_id ? updated : candidate);
      broadcastTasksChanged();
      notificationStore.success('AI task queued');
    } catch (error) {
      console.error('[TasksPage] Failed to start AI task:', error);
      notificationStore.error('Failed to start AI task');
    }
  }

  async function handleActivatePlan(plan: UserPlanViewModel): Promise<void> {
    planActionId = plan.plan_id;
    try {
      const updated = await activateUserPlan(plan);
      plans = plans.map((candidate) => candidate.plan_id === updated.plan_id ? updated : candidate);
      broadcastPlansChanged();
      notificationStore.success('Plan activated');
    } catch (error) {
      console.error('[TasksPage] Failed to activate plan:', error);
      notificationStore.error('Failed to activate plan');
    } finally {
      planActionId = null;
    }
  }

  async function handleCompletePlan(plan: UserPlanViewModel): Promise<void> {
    planActionId = plan.plan_id;
    try {
      const updated = await completeUserPlan(plan);
      plans = plans.map((candidate) => candidate.plan_id === updated.plan_id ? updated : candidate);
      broadcastPlansChanged();
      notificationStore.success('Plan completed');
    } catch (error) {
      console.error('[TasksPage] Failed to complete plan:', error);
      notificationStore.error('Plan still has blockers');
    } finally {
      planActionId = null;
    }
  }

  onMount(() => {
    void refreshTasks();
    void refreshPlans();
  });
</script>

<section class="tasks-page" class:compact data-testid={compact ? 'project-tasks-page' : 'tasks-page'}>
  {#if !compact}
    <header class="tasks-hero">
      <div>
        <p class="eyebrow">Tasks</p>
        <h1>Plan work for you and your AI mates.</h1>
        <p>Create private encrypted tasks, move them through a Kanban flow, and hand focused work to AI when it is ready.</p>
      </div>
      <div class="task-stats" aria-label="Task summary">
        <span><strong>{totalCount}</strong> total</span>
        <span><strong>{activeCount}</strong> active</span>
        <span><strong>{doneCount}</strong> done</span>
      </div>
    </header>
  {/if}

  <section class="plans-strip" data-testid="linked-plans-section" aria-label="Linked plans">
    <div class="plans-strip-heading">
      <div>
        <p class="eyebrow">Plans</p>
        <h2>{chatId ? 'Chat plan' : projectId ? 'Project plans' : 'Active plans'}</h2>
      </div>
      <span>{activePlans.length}</span>
    </div>
    <form class="plan-create-row" onsubmit={(event) => { event.preventDefault(); void handleCreatePlan(); }} data-testid="plan-create-form">
      <input bind:value={planTitle} placeholder={compact ? 'New project plan' : 'New plan'} data-testid="plan-title-input" />
      <input bind:value={planSummary} placeholder="Optional plan summary" data-testid="plan-summary-input" />
      <button type="submit" disabled={isSaving || !planTitle.trim()} data-testid="plan-create-button">
        {isSaving ? 'Creating...' : 'Create plan'}
      </button>
    </form>
    {#if isLoadingPlans}
      <div class="plans-loading" data-testid="plans-loading">Loading plans...</div>
    {:else if activePlans.length > 0}
      <div class="plan-card-list">
        {#each activePlans as plan (plan.plan_id)}
          <article class="plan-card" data-testid="linked-plan-card" data-plan-status={plan.status}>
            <div>
              <p class="plan-status">{plan.status.replaceAll('_', ' ')}</p>
              <h3>{plan.title || 'Untitled plan'}</h3>
              {#if plan.summary || plan.goal}
                <p>{plan.summary || plan.goal}</p>
              {/if}
            </div>
            <div class="plan-actions">
              {#if plan.status === 'draft' || plan.status === 'awaiting_confirmation'}
                <button type="button" disabled={planActionId === plan.plan_id} onclick={() => void handleActivatePlan(plan)} data-testid="plan-activate-button">
                  {planActionId === plan.plan_id ? 'Activating...' : 'Activate'}
                </button>
              {/if}
              <button type="button" disabled={planActionId === plan.plan_id} onclick={() => void handleCompletePlan(plan)} data-testid="plan-complete-button">
                {planActionId === plan.plan_id ? 'Saving...' : 'Complete'}
              </button>
            </div>
          </article>
        {/each}
      </div>
    {:else}
      <div class="plans-empty" data-testid="plans-empty">Create a plan above to coordinate tasks and verification.</div>
    {/if}
  </section>

  <form class="task-create-card" class:compact onsubmit={(event) => { event.preventDefault(); void handleCreateTask(); }} data-testid="task-create-form">
    <div>
      <label for={compact ? 'project-task-title' : 'task-title'}>New task</label>
      <input
        id={compact ? 'project-task-title' : 'task-title'}
        bind:value={title}
        placeholder={compact ? 'Add a project task' : 'What should happen next?'}
        data-testid="task-title-input"
      />
    </div>
    <div>
      <label for={compact ? 'project-task-description' : 'task-description'}>Details</label>
      <textarea
        id={compact ? 'project-task-description' : 'task-description'}
        bind:value={description}
        placeholder="Optional context or instructions"
        rows={compact ? 2 : 3}
        data-testid="task-description-input"
      ></textarea>
    </div>
    <label class="ai-toggle">
      <input type="checkbox" bind:checked={assignToAI} data-testid="task-assign-ai-toggle" />
      <span>Assign to AI now</span>
    </label>
    <button type="submit" disabled={isSaving || !title.trim()} data-testid="task-create-button">
      {isSaving ? 'Creating...' : 'Create task'}
    </button>
  </form>

  {#if isLoading}
    <div class="tasks-state" data-testid="tasks-loading">Loading tasks...</div>
  {:else if hasLoadError}
    <div class="tasks-state" data-testid="tasks-load-error">
      <p>Tasks could not be loaded.</p>
      <button type="button" onclick={() => void refreshTasks()}>Retry</button>
    </div>
  {:else if tasks.length === 0}
    <div class="tasks-state" data-testid="tasks-empty">
      <h2>No tasks yet</h2>
      <p>Create your first task above to start planning work.</p>
    </div>
  {:else}
    <TaskBoard {tasks} onMove={(task, status) => void handleMove(task, status)} onStartAI={(task) => void handleStartAI(task)} />
  {/if}
</section>

<style>
  .tasks-page {
    flex: 1;
    min-width: 0;
    height: 100%;
    overflow: auto;
    padding: clamp(18px, 3vw, 34px);
    background: var(--color-grey-0);
    color: var(--color-font-primary);
  }

  .tasks-page.compact {
    padding: 0;
    overflow: visible;
  }

  .tasks-hero,
  .plans-strip,
  .task-create-card,
  .tasks-state {
    border-radius: 32px;
    border: 1px solid var(--color-grey-20);
    background: linear-gradient(135deg, var(--color-grey-10), var(--color-grey-0));
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.08);
  }

  .tasks-hero {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 24px;
    padding: clamp(24px, 5vw, 54px);
    margin-bottom: 18px;
  }

  .plans-strip {
    display: flex;
    flex-direction: column;
    gap: 14px;
    padding: 16px;
    margin-bottom: 18px;
  }

  .tasks-page.compact .plans-strip {
    box-shadow: none;
    margin-bottom: 16px;
  }

  .plans-strip-heading {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
  }

  .plans-strip-heading span {
    display: grid;
    place-items: center;
    min-width: 30px;
    height: 30px;
    border-radius: 999px;
    background: var(--color-grey-0);
    color: var(--color-font-secondary);
    font-size: 0.82rem;
  }

  .plan-create-row {
    display: grid;
    grid-template-columns: minmax(180px, 1fr) minmax(220px, 1.4fr) auto;
    gap: 10px;
    align-items: center;
  }

  .tasks-page.compact .plan-create-row {
    grid-template-columns: 1fr;
  }

  .plans-loading,
  .plans-empty {
    border: 1px dashed var(--color-grey-30);
    border-radius: 20px;
    padding: 16px;
    color: var(--color-font-secondary);
    font-size: 0.88rem;
  }

  .plan-card-list {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
    gap: 12px;
  }

  .plan-card {
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    gap: 16px;
    border: 1px solid var(--color-grey-20);
    border-radius: 24px;
    padding: 14px;
    background: var(--color-grey-0);
  }

  .plan-card h3 {
    margin: 0;
    font-size: 1rem;
  }

  .plan-card p:not(.plan-status) {
    margin-top: 6px;
    color: var(--color-font-secondary);
    font-size: 0.86rem;
  }

  .plan-status {
    margin: 0 0 6px;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: var(--color-font-secondary);
    font-size: 0.68rem;
    font-weight: 700;
  }

  .plan-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }

  .eyebrow {
    margin: 0 0 8px;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    color: var(--color-font-secondary);
    font-size: 0.75rem;
    font-weight: 700;
  }

  h1,
  h2,
  h3,
  p {
    margin: 0;
  }

  h1 {
    max-width: 980px;
    font-size: clamp(2.6rem, 5.6vw, 5rem);
    line-height: 1.03;
    letter-spacing: -0.055em;
  }

  .tasks-hero p:not(.eyebrow),
  .tasks-state p {
    max-width: 650px;
    margin-top: 12px;
    color: var(--color-font-secondary);
  }

  .task-stats {
    display: flex;
    flex-wrap: wrap;
    justify-content: flex-end;
    gap: 10px;
  }

  .task-stats span {
    border-radius: 999px;
    padding: 8px 12px;
    background: var(--color-grey-0);
    color: var(--color-font-secondary);
    white-space: nowrap;
  }

  .task-stats strong {
    color: var(--color-font-primary);
  }

  .task-create-card {
    display: grid;
    grid-template-columns: minmax(180px, 1.2fr) minmax(220px, 2fr) auto auto;
    align-items: end;
    gap: 12px;
    padding: 16px;
    margin-bottom: 18px;
  }

  .task-create-card.compact {
    grid-template-columns: 1fr;
    box-shadow: none;
    margin-bottom: 16px;
  }

  label {
    display: flex;
    flex-direction: column;
    gap: 6px;
    color: var(--color-font-secondary);
    font-size: 0.8rem;
  }

  input,
  textarea {
    width: 100%;
    box-sizing: border-box;
    border: 1px solid var(--color-grey-30);
    border-radius: 18px;
    background: var(--color-grey-0);
    color: var(--color-font-primary);
    padding: 11px 13px;
    font: inherit;
  }

  textarea {
    resize: vertical;
  }

  .ai-toggle {
    flex-direction: row;
    align-items: center;
    color: var(--color-font-primary);
    white-space: nowrap;
  }

  button {
    border: 0;
    border-radius: 999px;
    background: var(--color-button-primary);
    color: var(--color-font-button);
    padding: 12px 16px;
    font: inherit;
    cursor: pointer;
  }

  button:disabled {
    opacity: 0.55;
    cursor: not-allowed;
  }

  .tasks-state {
    display: grid;
    place-items: center;
    gap: 10px;
    min-height: 260px;
    padding: 28px;
    text-align: center;
  }

  @media (max-width: 900px) {
    .tasks-hero,
    .task-create-card {
      grid-template-columns: 1fr;
      flex-direction: column;
    }

    .task-stats {
      justify-content: flex-start;
    }
  }
</style>
