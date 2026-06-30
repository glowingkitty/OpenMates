<!--
  ActiveChatTaskPreview.svelte
  Compact top-of-chat preview for the current task queue. It reads encrypted
  user tasks through userTaskService, decrypts locally, and never receives or
  emits plaintext task content to the backend.
-->

<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import {
    listUserTasks,
    updateUserTask,
    type UserTaskViewModel,
  } from '../../services/userTaskService';
  import { listUserPlans, type UserPlanViewModel } from '../../services/userPlanService';
  import { notificationStore } from '../../stores/notificationStore';

  let {
    chatId,
    onOpenDetails,
  }: {
    chatId: string | null;
    onOpenDetails: (tab?: 'tasks' | 'files' | 'usage' | 'share') => void;
  } = $props();

  let tasks = $state<UserTaskViewModel[]>([]);
  let plans = $state<UserPlanViewModel[]>([]);
  let isLoading = $state(false);

  const actionableTasks = $derived(tasks.filter((task) => task.status !== 'done'));
  const currentTask = $derived(
    actionableTasks.find((task) => task.status === 'in_progress')
      ?? actionableTasks.find((task) => task.status === 'blocked')
      ?? actionableTasks.find((task) => task.status === 'todo')
      ?? actionableTasks[0]
      ?? null,
  );
  const currentTaskIndex = $derived(currentTask ? tasks.findIndex((task) => task.task_id === currentTask.task_id) + 1 : 0);
  const doneCount = $derived(tasks.filter((task) => task.status === 'done').length);
  const progressPercent = $derived(tasks.length > 0 ? Math.round((doneCount / tasks.length) * 100) : 0);
  const currentPlan = $derived(
    plans.find((plan) => plan.status === 'executing')
      ?? plans.find((plan) => plan.status === 'active')
      ?? plans.find((plan) => plan.status === 'awaiting_confirmation')
      ?? plans.find((plan) => plan.status === 'draft')
      ?? null,
  );

  async function refreshTasks(): Promise<void> {
    if (!chatId) {
      tasks = [];
      plans = [];
      return;
    }
    isLoading = true;
    try {
      const [nextTasks, nextPlans] = await Promise.all([
        listUserTasks({ chatId }),
        listUserPlans({ chatId, limit: 3 }),
      ]);
      tasks = nextTasks;
      plans = nextPlans;
    } catch (error) {
      console.error('[ActiveChatTaskPreview] Failed to load tasks:', error);
    } finally {
      isLoading = false;
    }
  }

  async function toggleCurrentTask(event: Event): Promise<void> {
    event.stopPropagation();
    if (!currentTask) return;
    const nextStatus = currentTask.status === 'done' ? 'todo' : 'done';
    const previous = tasks;
    tasks = tasks.map((task) => task.task_id === currentTask.task_id ? { ...task, status: nextStatus } : task);
    try {
      const updated = await updateUserTask(currentTask, { status: nextStatus });
      tasks = tasks.map((task) => task.task_id === updated.task_id ? updated : task);
      window.dispatchEvent(new CustomEvent('openmates-user-tasks-changed', { detail: { chatId } }));
    } catch (error) {
      tasks = previous;
      console.error('[ActiveChatTaskPreview] Failed to update task:', error);
      notificationStore.error('Failed to update task');
    }
  }

  function handleTaskChange(event: Event): void {
    const detail = (event as CustomEvent<{ chatId?: string | null }>).detail;
    if (!detail?.chatId || detail.chatId === chatId) void refreshTasks();
  }

  function handlePlanChange(event: Event): void {
    const detail = (event as CustomEvent<{ chatId?: string | null }>).detail;
    if (!detail?.chatId || detail.chatId === chatId) void refreshTasks();
  }

  $effect(() => {
    void chatId;
    void refreshTasks();
  });

  onMount(() => {
    window.addEventListener('openmates-user-tasks-changed', handleTaskChange);
    window.addEventListener('openmates-user-plans-changed', handlePlanChange);
  });

  onDestroy(() => {
    window.removeEventListener('openmates-user-tasks-changed', handleTaskChange);
    window.removeEventListener('openmates-user-plans-changed', handlePlanChange);
  });
</script>

{#if currentTask && tasks.length > 0}
  <div class="active-task-preview" data-testid="active-chat-task-preview">
    <button class="task-check" type="button" onclick={toggleCurrentTask} aria-label="Complete current task" aria-pressed={currentTask.status === 'done'}>
      <span class:checked={currentTask.status === 'done'}></span>
    </button>
    <button class="task-preview-copy" type="button" onclick={() => onOpenDetails('tasks')}>
      <div class="task-meta">
        <span>Task {Math.max(currentTaskIndex, 1)}/{tasks.length}</span>
        <span>{currentTask.status.replace('_', ' ')}</span>
      </div>
      <strong>{currentTask.title || 'Untitled task'}</strong>
      <div class="task-progress" aria-label={`${progressPercent}% complete`}>
        <span style={`width: ${progressPercent}%`}></span>
      </div>
    </button>
  </div>
{:else if currentPlan}
  <button class="active-task-preview plan-preview" type="button" onclick={() => onOpenDetails('tasks')} data-testid="active-chat-plan-preview">
    <div class="task-preview-copy">
      <div class="task-meta">
        <span>Plan</span>
        <span>{currentPlan.status.replaceAll('_', ' ')}</span>
      </div>
      <strong>{currentPlan.title || 'Untitled plan'}</strong>
      {#if currentPlan.summary || currentPlan.goal}
        <small>{currentPlan.summary || currentPlan.goal}</small>
      {/if}
    </div>
  </button>
{:else if isLoading}
  <div class="active-task-preview loading" data-testid="active-chat-task-preview-loading">Loading tasks...</div>
{/if}

<style>
  .active-task-preview {
    position: relative;
    z-index: 2;
    display: flex;
    align-items: center;
    gap: 12px;
    width: min(560px, calc(100% - 28px));
    margin: 70px auto 8px;
    padding: 12px 14px;
    border: 1px solid var(--color-grey-20);
    border-radius: 24px;
    background: color-mix(in srgb, var(--color-grey-0) 92%, transparent);
    color: var(--color-font-primary);
    box-shadow: 0 10px 28px rgba(0, 0, 0, 0.12);
    text-align: start;
    cursor: pointer;
    backdrop-filter: blur(16px);
  }

  .active-task-preview.loading {
    justify-content: center;
    color: var(--color-font-secondary);
    cursor: default;
  }

  .active-task-preview.plan-preview {
    border-color: color-mix(in srgb, var(--color-primary) 28%, var(--color-grey-20));
  }

  .task-check {
    display: grid;
    place-items: center;
    flex: 0 0 auto;
    width: 30px;
    height: 30px;
    padding: 0;
    border: 0;
    border-radius: 999px;
    background: transparent;
    cursor: pointer;
  }

  .task-check span {
    display: block;
    width: 22px;
    height: 22px;
    border: 2px solid var(--color-grey-40);
    border-radius: 999px;
    background: var(--color-grey-0);
  }

  .task-check span.checked {
    border-color: var(--color-button-primary);
    background: var(--color-button-primary);
  }

  .task-preview-copy {
    display: flex;
    flex: 1;
    min-width: 0;
    flex-direction: column;
    gap: 5px;
    padding: 0;
    border: 0;
    background: transparent;
    color: inherit;
    text-align: start;
    cursor: pointer;
  }

  .task-meta {
    display: flex;
    justify-content: space-between;
    gap: 10px;
    color: var(--color-font-secondary);
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
  }

  strong {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 0.95rem;
  }

  small {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--color-font-secondary);
    font-size: 0.8rem;
  }

  .task-progress {
    height: 5px;
    overflow: hidden;
    border-radius: 999px;
    background: var(--color-grey-20);
  }

  .task-progress span {
    display: block;
    height: 100%;
    border-radius: inherit;
    background: var(--color-primary);
  }

  @media (max-width: 700px) {
    .active-task-preview {
      margin-top: 58px;
    }
  }
</style>
