<!--
  TaskCard.svelte
  Reusable encrypted task card for Tasks V1 boards. The card only receives
  decrypted view-model data from userTaskService; durable task content remains
  encrypted at rest and over the API.
-->

<script lang="ts">
  import type { UserTaskStatus, UserTaskViewModel } from '../../services/userTaskService';

  let {
    task,
    onMove,
    onStartAI,
  }: {
    task: UserTaskViewModel;
    onMove: (task: UserTaskViewModel, status: UserTaskStatus) => void;
    onStartAI: (task: UserTaskViewModel) => void;
  } = $props();

  const statuses: UserTaskStatus[] = ['backlog', 'todo', 'in_progress', 'blocked', 'done'];

  function handleDragStart(event: DragEvent): void {
    event.dataTransfer?.setData('application/x-openmates-task-id', task.task_id);
    event.dataTransfer?.setData('text/plain', task.task_id);
    event.dataTransfer?.setDragImage(event.currentTarget as Element, 12, 12);
  }

  function formatStatus(status: UserTaskStatus): string {
    return status.replace('_', ' ');
  }
</script>

<article
  class="task-card"
  draggable="true"
  ondragstart={handleDragStart}
  data-testid="task-card"
  data-task-id={task.task_id}
>
  <div class="task-card-main">
    <label class="done-toggle">
      <input
        type="checkbox"
        checked={task.status === 'done'}
        onchange={() => onMove(task, task.status === 'done' ? 'todo' : 'done')}
        aria-label={`Mark ${task.title || 'task'} done`}
        data-testid="task-done-toggle"
      />
      <span></span>
    </label>
    <div class="task-card-copy">
      <h3>{task.title || 'Untitled task'}</h3>
      {#if task.description}
        <p>{task.description}</p>
      {/if}
    </div>
  </div>

  {#if task.tags.length > 0}
    <div class="task-tags" aria-label="Task tags">
      {#each task.tags as tag}
        <span>{tag}</span>
      {/each}
    </div>
  {/if}

  <footer class="task-card-footer">
    <span class="assignee" data-assignee={task.assigneeType}>{task.assigneeType === 'ai' ? 'AI task' : 'My task'}</span>
    {#if task.dueAt}
      <span class="due">Due {new Date(task.dueAt * 1000).toLocaleDateString()}</span>
    {/if}
  </footer>

  <div class="task-actions" aria-label="Move task">
    {#each statuses as status}
      {#if status !== task.status}
        <button type="button" onclick={() => onMove(task, status)} data-testid={`task-move-${status}`}>{formatStatus(status)}</button>
      {/if}
    {/each}
    {#if task.assigneeType !== 'ai' || task.status !== 'in_progress'}
      <button class="ai-action" type="button" onclick={() => onStartAI(task)} data-testid="task-start-ai">Start with AI</button>
    {/if}
  </div>
</article>

<style>
  .task-card {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 16px;
    border-radius: 24px;
    background: var(--color-grey-0);
    border: 1px solid var(--color-grey-20);
    box-shadow: 0 10px 28px rgba(0, 0, 0, 0.08);
    color: var(--color-font-primary);
  }

  .task-card-main {
    display: flex;
    align-items: flex-start;
    gap: 12px;
  }

  .done-toggle input {
    position: absolute;
    opacity: 0;
  }

  .done-toggle span {
    display: grid;
    place-items: center;
    width: 22px;
    height: 22px;
    border-radius: 999px;
    border: 2px solid var(--color-grey-40);
    background: var(--color-grey-0);
  }

  .done-toggle input:checked + span {
    border-color: var(--color-button-primary);
    background: var(--color-button-primary);
  }

  .done-toggle input:checked + span::after {
    content: '';
    width: 8px;
    height: 4px;
    border-inline-start: 2px solid var(--color-font-button);
    border-bottom: 2px solid var(--color-font-button);
    transform: rotate(-45deg) translate(1px, -1px);
  }

  .task-card-copy {
    min-width: 0;
  }

  h3,
  p {
    margin: 0;
  }

  h3 {
    font-size: 1rem;
    line-height: 1.25;
  }

  p {
    margin-top: 6px;
    color: var(--color-font-secondary);
    font-size: 0.88rem;
    line-height: 1.4;
  }

  .task-tags,
  .task-card-footer,
  .task-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-items: center;
  }

  .task-tags span,
  .assignee,
  .due {
    border-radius: 999px;
    padding: 4px 9px;
    background: var(--color-grey-10);
    color: var(--color-font-secondary);
    font-size: 0.75rem;
  }

  .assignee[data-assignee='ai'] {
    color: var(--color-font-button);
    background: var(--color-button-primary);
  }

  .task-actions button {
    border: 0;
    border-radius: 999px;
    background: var(--color-grey-10);
    color: var(--color-font-primary);
    padding: 6px 10px;
    font: inherit;
    font-size: 0.75rem;
    cursor: pointer;
  }

  .task-actions .ai-action {
    background: var(--color-button-primary);
    color: var(--color-font-button);
  }
</style>
