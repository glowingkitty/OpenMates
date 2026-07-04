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
  let selectedTaskId = $state<string | null>(null);

  const actionableTasks = $derived(tasks.filter((task) => task.status !== 'done'));
  const defaultTask = $derived(
    actionableTasks.find((task) => task.task_id === selectedTaskId)
      ?? actionableTasks.find((task) => task.status === 'in_progress')
      ?? actionableTasks.find((task) => task.status === 'blocked')
      ?? actionableTasks.find((task) => task.status === 'todo')
      ?? actionableTasks[0]
      ?? null,
  );
  const currentTask = $derived(defaultTask);
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
      selectedTaskId = null;
      return;
    }
    try {
      const [nextTasks, nextPlans] = await Promise.all([
        listUserTasks({ chatId }),
        listUserPlans({ chatId, limit: 3 }),
      ]);
      tasks = nextTasks;
      plans = nextPlans;
      if (selectedTaskId && !nextTasks.some((task) => task.task_id === selectedTaskId && task.status !== 'done')) {
        selectedTaskId = null;
      }
    } catch (error) {
      console.error('[ActiveChatTaskPreview] Failed to load tasks:', error);
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

  function selectAdjacentTask(direction: -1 | 1, event: Event): void {
    event.stopPropagation();
    if (!currentTask || actionableTasks.length <= 1) return;
    const currentIndex = actionableTasks.findIndex((task) => task.task_id === currentTask.task_id);
    const nextIndex = (currentIndex + direction + actionableTasks.length) % actionableTasks.length;
    selectedTaskId = actionableTasks[nextIndex]?.task_id ?? null;
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
    <button class="preview-icon-tile" type="button" onclick={() => onOpenDetails('tasks')} aria-label="Open chat tasks">
      <span class="task-glyph" aria-hidden="true"></span>
    </button>
    <button class="task-count" type="button" onclick={() => onOpenDetails('tasks')}>
      <span>Task</span>
      <strong>{Math.max(currentTaskIndex, 1)}/{tasks.length}</strong>
      <span class="mini-progress" aria-label={`${progressPercent}% complete`}><span style={`width: ${progressPercent}%`}></span></span>
    </button>
    <button class="task-nav previous" type="button" onclick={(event) => selectAdjacentTask(-1, event)} aria-label="Previous task" disabled={actionableTasks.length <= 1}></button>
    <button class="task-check" type="button" onclick={toggleCurrentTask} aria-label="Complete current task" aria-pressed={currentTask.status === 'done'}>
      <span></span>
    </button>
    <button class="task-title" type="button" onclick={() => onOpenDetails('tasks')}>
      {currentTask.title || 'Untitled task'}
    </button>
    <button class="task-nav next" type="button" onclick={(event) => selectAdjacentTask(1, event)} aria-label="Next task" disabled={actionableTasks.length <= 1}></button>
  </div>
{:else if currentPlan}
  <button class="active-task-preview plan-preview" type="button" onclick={() => onOpenDetails('tasks')} data-testid="active-chat-plan-preview">
    <span class="preview-icon-tile" aria-hidden="true"><span class="task-glyph"></span></span>
    <span class="plan-copy">
      <span class="plan-label">Plan</span>
      <strong>{currentPlan.title || 'Untitled plan'}</strong>
      <small>{currentPlan.status.replaceAll('_', ' ')}</small>
    </span>
    <span class="task-nav next" aria-hidden="true"></span>
  </button>
{/if}

<style>
  .active-task-preview {
    position: relative;
    z-index: 2;
    display: flex;
    align-items: center;
    gap: 10px;
    width: fit-content;
    max-width: min(520px, calc(100% - 28px));
    min-height: 60px;
    margin: 34px auto 8px;
    padding: 10px 14px 10px 12px;
    border: 1px solid color-mix(in srgb, var(--color-grey-20) 70%, transparent);
    border-radius: 24px;
    background: color-mix(in srgb, var(--color-grey-0) 96%, transparent);
    color: var(--color-font-primary);
    box-shadow: 0 4px 8px rgba(0, 0, 0, 0.24);
    text-align: start;
    backdrop-filter: blur(12px);
  }

  .active-task-preview button {
    font: inherit;
  }

  .preview-icon-tile {
    position: relative;
    display: grid;
    place-items: center;
    flex: 0 0 auto;
    width: 48px;
    height: 48px;
    padding: 0;
    border: 0;
    border-radius: 12px;
    background: color-mix(in srgb, var(--color-button-primary) 86%, var(--color-grey-100));
    box-shadow: 0 4px 8px rgba(0, 0, 0, 0.24);
    cursor: pointer;
  }

  .task-glyph {
    position: relative;
    display: block;
    width: 22px;
    height: 26px;
    border: 3px solid var(--color-grey-0);
    border-radius: 5px;
  }

  .task-glyph::before,
  .task-glyph::after {
    position: absolute;
    top: 4px;
    bottom: 4px;
    width: 3px;
    border-radius: 999px;
    background: var(--color-grey-0);
    content: '';
  }

  .task-glyph::before {
    left: 5px;
  }

  .task-glyph::after {
    right: 5px;
  }

  .task-count {
    display: grid;
    grid-template-columns: max-content;
    gap: 0;
    min-width: 48px;
    padding: 0;
    border: 0;
    background: transparent;
    color: var(--color-font-secondary);
    text-align: start;
    cursor: pointer;
  }

  .task-count span:first-child,
  .plan-label,
  small {
    color: var(--color-font-secondary);
    font-size: 0.92rem;
    font-weight: 700;
    line-height: 1;
  }

  .task-count strong {
    color: var(--color-font-secondary);
    font-size: 1rem;
    line-height: 1.05;
  }

  .mini-progress {
    display: block;
    width: 42px;
    height: 5px;
    margin-top: 6px;
    overflow: hidden;
    border-radius: 999px;
    background: var(--color-grey-20);
  }

  .mini-progress span {
    display: block;
    height: 100%;
    border-radius: inherit;
    background: var(--color-success, var(--color-primary));
  }

  .task-nav {
    position: relative;
    flex: 0 0 auto;
    width: 28px;
    height: 36px;
    padding: 0;
    border: 0;
    background: transparent;
    cursor: pointer;
  }

  .task-nav::before {
    position: absolute;
    top: 50%;
    left: 50%;
    width: 18px;
    height: 18px;
    border-top: 4px solid var(--color-grey-40);
    border-right: 4px solid var(--color-grey-40);
    content: '';
  }

  .task-nav.previous::before {
    transform: translate(-35%, -50%) rotate(-135deg);
  }

  .task-nav.next::before {
    transform: translate(-65%, -50%) rotate(45deg);
  }

  .task-nav:disabled {
    opacity: 0.32;
    cursor: default;
  }

  .task-title {
    display: -webkit-box;
    max-width: min(360px, 42vw);
    min-width: 0;
    padding: 0;
    overflow: hidden;
    border: 0;
    background: transparent;
    color: var(--color-font-primary);
    cursor: pointer;
    font-size: 1.05rem;
    font-weight: 700;
    line-height: 1.15;
    text-align: start;
    text-overflow: ellipsis;
    white-space: normal;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
  }

  .plan-preview {
    cursor: pointer;
  }

  .plan-copy {
    display: grid;
    min-width: 0;
    max-width: min(360px, 52vw);
    gap: 3px;
  }

  .plan-copy strong {
    overflow: hidden;
    color: var(--color-font-primary);
    font-size: 1.05rem;
    line-height: 1.15;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .plan-copy small {
    overflow: hidden;
    text-overflow: ellipsis;
    text-transform: capitalize;
    white-space: nowrap;
  }

  .task-check {
    display: grid;
    place-items: center;
    flex: 0 0 auto;
    width: 32px;
    height: 32px;
    padding: 0;
    border: 0;
    background: transparent;
    cursor: pointer;
  }

  .task-check span {
    display: block;
    width: 28px;
    height: 28px;
    border: 2px solid var(--color-grey-30);
    border-radius: 7px;
    background: var(--color-grey-10);
  }

  @media (max-width: 700px) {
    .active-task-preview {
      gap: 8px;
      max-width: calc(100% - 20px);
      min-height: 54px;
      margin-top: 24px;
      padding: 8px 10px;
      border-radius: 22px;
    }

    .preview-icon-tile {
      width: 42px;
      height: 42px;
      border-radius: 11px;
    }

    .task-title,
    .plan-copy strong {
      max-width: 42vw;
      font-size: 0.95rem;
    }

    .task-nav {
      width: 22px;
    }
  }
</style>
