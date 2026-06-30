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
  let isLoading = $state(true);
  let isSaving = $state(false);
  let hasLoadError = $state(false);
  let title = $state('');
  let description = $state('');
  let assignToAI = $state(false);

  const totalCount = $derived(tasks.length);
  const activeCount = $derived(tasks.filter((task) => task.status === 'in_progress').length);
  const doneCount = $derived(tasks.filter((task) => task.status === 'done').length);

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

  onMount(() => {
    void refreshTasks();
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
