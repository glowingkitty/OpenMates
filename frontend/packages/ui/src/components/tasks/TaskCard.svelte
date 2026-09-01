<!--
  TaskCard.svelte
  Reusable encrypted task card for Tasks V1 boards. The card only receives
  decrypted view-model data from userTaskService; durable task content remains
  encrypted at rest and over the API.
-->

<script lang="ts">
  import {
    isWorkflowRunTaskProjectionViewModel,
    type TasksBoardItem,
    type UserTaskStatus,
  } from '../../services/userTaskService';

  let {
    task,
    onMove,
    onStartAI,
    onSkip,
    onDelete,
    onCancelWorkflowRun,
    onSelect,
  }: {
    task: TasksBoardItem;
    onMove: (task: TasksBoardItem, status: UserTaskStatus) => void;
    onStartAI: (task: TasksBoardItem) => void;
    onSkip: (task: TasksBoardItem) => void;
    onDelete: (task: TasksBoardItem) => void;
    onCancelWorkflowRun: (task: TasksBoardItem) => void;
    onSelect: (task: TasksBoardItem) => void;
  } = $props();

  const statuses: UserTaskStatus[] = ['backlog', 'todo', 'in_progress', 'blocked', 'done'];
  let workflowRun = $derived(isWorkflowRunTaskProjectionViewModel(task) ? task : null);

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
  draggable={!workflowRun}
  ondragstart={handleDragStart}
  data-testid="task-card"
  data-task-id={task.task_id}
>
  <button
    type="button"
    class="card-select"
    data-testid={workflowRun ? 'workflow-run-projection' : 'task-card-open'}
    data-workflow-run-id={workflowRun?.workflowRunId}
    data-status={workflowRun?.status}
    aria-label={workflowRun ? `Open ${workflowRun.title} run detail` : `Open ${task.title || 'task'} details`}
    onclick={() => onSelect(task)}
  ></button>
  <div class="task-card-main">
    {#if !workflowRun}<label class="done-toggle" data-testid="task-done-toggle">
      <input
        type="checkbox"
        checked={task.status === 'done'}
        onchange={() => onMove(task, task.status === 'done' ? 'todo' : 'done')}
        aria-label={`Mark ${task.title || 'task'} done`}
      />
      <span></span>
    </label>{/if}
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
    <span class="assignee" data-assignee={task.assigneeType}>{workflowRun ? 'Workflow run' : task.assigneeType === 'ai' ? 'AI task' : 'My task'}</span>
    {#if task.dueAt}
      <span class="due">Due {new Date(task.dueAt * 1000).toLocaleDateString()}</span>
    {/if}
  </footer>

  <div class="task-actions" aria-label="Move task">
    {#if workflowRun}
      <a href={`/workflows#workflow-id=${encodeURIComponent(workflowRun.workflowId)}&workflow-tab=details`} data-testid="workflow-open">Open workflow</a>
      {#if workflowRun.workflowRunId}
        <a href={`/workflows#workflow-id=${encodeURIComponent(workflowRun.workflowId)}&workflow-tab=runs&run-id=${encodeURIComponent(workflowRun.workflowRunId)}`} data-testid="workflow-run-open">Open workflow run</a>
      {/if}
      {#if workflowRun.canCancel}
        <button type="button" onclick={() => onCancelWorkflowRun(workflowRun)} data-testid="workflow-run-cancel">Cancel run</button>
      {/if}
      {#if workflowRun.canDelete}
        <button type="button" onclick={() => onDelete(workflowRun)} data-testid="workflow-next-run-skip">Skip next run</button>
      {/if}
    {:else}
      <a href={`/tasks/${encodeURIComponent(task.task_id)}`} data-testid="task-detail-link">Open</a>
      {#each statuses as status}
        {#if status !== task.status}
          <button type="button" onclick={() => onMove(task, status)} data-testid={`task-move-${status}`}>{formatStatus(status)}</button>
        {/if}
      {/each}
      {#if task.status !== 'blocked'}
        <button type="button" onclick={() => onMove(task, 'blocked')} data-testid="task-block-button">Block</button>
      {:else}
        <button type="button" onclick={() => onMove(task, 'todo')} data-testid="task-unblock-button">Unblock</button>
      {/if}
      {#if task.status !== 'backlog'}
        <button type="button" onclick={() => onSkip(task)} data-testid="task-skip-button">Skip</button>
      {/if}
      {#if task.assigneeType !== 'ai' || task.status !== 'in_progress'}
      <button class="ai-action" type="button" onclick={() => onStartAI(task)} data-testid="task-start-ai">Start with AI</button>
      {/if}
      <button class="danger-action" type="button" onclick={() => onDelete(task)} data-testid="task-delete-button">Delete</button>
    {/if}
  </div>
</article>

<style>
  .task-card {
    position: relative;
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

  .card-select { position: absolute; z-index: 1; inset: 0; border: 0; border-radius: inherit; background: transparent; cursor: pointer; }
  .card-select:focus-visible { outline: 3px solid var(--color-primary); outline-offset: 3px; }
  .task-card-main, .task-tags, .task-card-footer, .task-actions { position: relative; z-index: 2; pointer-events: none; }
  .done-toggle, .task-actions a, .task-actions button { pointer-events: auto; }

  .task-card-main {
    display: flex;
    align-items: flex-start;
    gap: 12px;
  }

  .done-toggle {
    position: relative;
    display: inline-grid;
    flex: 0 0 44px;
    place-items: center;
    width: 44px;
    height: 44px;
    cursor: pointer;
  }

  .done-toggle input {
    position: absolute;
    width: 1px;
    height: 1px;
    opacity: 0;
    pointer-events: none;
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

  .task-actions a {
    display: grid;
    min-width: 44px;
    min-height: 44px;
    place-items: center;
    border-radius: var(--radius-full);
    background: var(--color-grey-10);
    color: var(--color-font-primary);
    font-size: var(--font-size-xs);
  }

  .task-actions .ai-action {
    background: var(--color-button-primary);
    color: var(--color-font-button);
  }

  .task-actions .danger-action {
    background: var(--color-error, #c83a32);
    color: var(--color-grey-0);
  }
</style>
