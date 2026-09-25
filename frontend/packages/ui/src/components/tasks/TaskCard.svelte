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
  import { onMount } from 'svelte';

  let {
    task,
    onMove,
    onStartAI,
    onSkip,
    onDelete,
    onCancelWorkflowRun: _onCancelWorkflowRun,
    onSelect,
    linkedProjectName = null,
    assigneeAvatarUrl = null,
    wasRecentlyDropped = false,
  }: {
    task: TasksBoardItem;
    onMove: (task: TasksBoardItem, status: UserTaskStatus) => void;
    onStartAI: (task: TasksBoardItem) => void;
    onSkip: (task: TasksBoardItem) => void;
    onDelete: (task: TasksBoardItem) => void;
    onCancelWorkflowRun: (task: TasksBoardItem) => void;
    onSelect: (task: TasksBoardItem) => void;
    linkedProjectName?: string | null;
    assigneeAvatarUrl?: string | null;
    wasRecentlyDropped?: boolean;
  } = $props();

  const statuses: UserTaskStatus[] = ['backlog', 'todo', 'in_progress', 'blocked', 'done'];
  let workflowRun = $derived(isWorkflowRunTaskProjectionViewModel(task) ? task : null);
  let dragging = $state(false);
  let settling = $state(false);
  let isAssignedToAI = $derived(task.assigneeType === 'openmates' || task.assigneeType === 'external_ai');
  let isAssignedToUser = $derived(task.assigneeType === 'user');
  let linkedProjectLabel = $derived(task.linkedProjectIds.length > 0 ? linkedProjectName || 'Project' : null);

  onMount(() => {
    if (!wasRecentlyDropped) return;
    settling = true;
    let secondFrame = 0;
    const firstFrame = requestAnimationFrame(() => {
      secondFrame = requestAnimationFrame(() => { settling = false; });
    });
    return () => {
      cancelAnimationFrame(firstFrame);
      cancelAnimationFrame(secondFrame);
    };
  });

  function handleDragStart(event: DragEvent): void {
    dragging = true;
    event.dataTransfer?.setData('application/x-openmates-task-id', task.task_id);
    event.dataTransfer?.setData('text/plain', task.task_id);
    if (event.dataTransfer && event.currentTarget instanceof HTMLElement) {
      const dragImage = event.currentTarget.cloneNode(true) as HTMLElement;
      dragImage.classList.add('dragging');
      dragImage.removeAttribute('data-testid');
      dragImage.removeAttribute('data-task-id');
      dragImage.querySelectorAll('[data-testid]').forEach((element) => element.removeAttribute('data-testid'));
      dragImage.style.position = 'fixed';
      dragImage.style.inset = 'auto auto -1000px -1000px';
      dragImage.style.width = `${event.currentTarget.getBoundingClientRect().width}px`;
      dragImage.style.transition = 'none';
      dragImage.style.transform = 'translateY(-8px) rotate(10deg) scale(1.02)';
      dragImage.setAttribute('aria-hidden', 'true');
      document.body.append(dragImage);
      event.dataTransfer.setDragImage(dragImage, 12, 12);
      requestAnimationFrame(() => dragImage.remove());
    }
  }

  function handleDragEnd(): void {
    dragging = false;
  }

  function formatStatus(status: UserTaskStatus): string {
    return status.replace('_', ' ');
  }
</script>

<article
  class="task-card"
  class:dragging
  class:settling
  draggable={!workflowRun}
  ondragstart={handleDragStart}
  ondragend={handleDragEnd}
  data-testid="task-card"
  data-task-id={task.task_id}
  data-drag-state={dragging ? 'picked-up' : 'settled'}
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
    <div class="task-card-copy">
      <h3>{task.title || 'Untitled task'}</h3>
    </div>
  </div>

  {#if workflowRun}
    <a
      class="workflow-run-link"
      href={`/workflows#workflow-id=${encodeURIComponent(workflowRun.workflowId)}&workflow-tab=runs${workflowRun.workflowRunId ? `&run-id=${encodeURIComponent(workflowRun.workflowRunId)}` : ''}`}
      data-testid="workflow-run-open"
    ><span aria-hidden="true"></span>Open workflow run</a>
  {:else}
    <div class="task-card-metadata">
      {#if linkedProjectLabel}
        <span class="project-pill" data-testid="task-project-pill"><span aria-hidden="true"></span>{linkedProjectLabel}</span>
      {/if}
      {#if task.dueAt}
        <span class="due">Due {new Date(task.dueAt * 1000).toLocaleDateString()}</span>
      {/if}
      {#if isAssignedToUser && assigneeAvatarUrl}
        <img
          class="assignment-avatar"
          src={assigneeAvatarUrl}
          alt=""
          aria-label="Assigned to user"
          data-testid="task-assignment-user"
        />
      {:else if isAssignedToAI || isAssignedToUser}
        <span
          class="assignment-indicator"
          class:ai={isAssignedToAI}
          class:user={!isAssignedToAI}
          data-testid={isAssignedToAI ? 'task-assignment-ai' : 'task-assignment-user'}
          aria-label={isAssignedToAI ? 'Assigned to AI' : 'Assigned to user'}
        ></span>
      {/if}
    </div>
    {#if isAssignedToAI && task.primaryChatId}
      <a class="open-chat-link" href={`/#chat-id=${encodeURIComponent(task.primaryChatId)}`} data-testid="task-open-chat"><span aria-hidden="true"></span>Open chat</a>
    {/if}
  {/if}

  {#if !workflowRun}
  <div class="task-actions" aria-label="Move task">
      <details class="task-action-menu">
        <summary data-testid="task-actions-more" aria-label={`More actions for ${task.title || 'task'}`} title="More actions"><span aria-hidden="true">•••</span></summary>
        <div class="task-action-menu-items">
          <a href={`/tasks/${encodeURIComponent(task.task_id)}`} data-testid="task-detail-link">Open task</a>
          {#if !isAssignedToAI}
            <button class="ai-action" type="button" onclick={() => onStartAI(task)} data-testid="task-start-ai">Assign to AI</button>
          {/if}
          {#each statuses as status}
            {#if status !== task.status && status !== 'blocked'}
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
          <button class="danger-action" type="button" onclick={() => onDelete(task)} data-testid="task-delete-button">Delete</button>
        </div>
      </details>
  </div>
  {/if}
</article>

<style>
  .task-card {
    position: relative;
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
    gap: var(--spacing-2);
    min-height: 4.25rem;
    padding: var(--spacing-5);
    border-radius: var(--radius-5);
    background: var(--color-grey-0);
    border: 1px solid var(--color-grey-25);
    box-shadow: var(--shadow-md);
    color: var(--color-font-primary);
    cursor: grab;
    transform: none;
    transform-origin: center;
    transition: transform 180ms ease, box-shadow 180ms ease;
    will-change: transform;
  }

  .task-card.dragging {
    z-index: 8;
    cursor: grabbing;
    transform: translateY(-8px) rotate(10deg) scale(1.02);
    box-shadow: var(--shadow-xl);
  }

  .task-card.settling {
    transform: translateY(-8px) rotate(10deg) scale(1.02);
    transition: none;
  }

  .card-select { position: absolute; z-index: 1; inset: 0; border: 0; border-radius: inherit; background: transparent; cursor: pointer; }
  .card-select:focus-visible { outline: 3px solid var(--color-primary); outline-offset: 3px; }
  .task-card-main, .task-card-metadata, .task-actions { position: relative; z-index: 2; pointer-events: none; }
  .open-chat-link, .workflow-run-link, .task-actions a, .task-actions button, .task-action-menu { pointer-events: auto; }

  .task-card-main {
    display: flex;
    align-items: flex-start;
    gap: 0;
  }

  .task-card-copy {
    min-width: 0;
    width: 100%;
  }

  h3 { margin: 0; }

  h3 {
    display: -webkit-box;
    overflow: hidden;
    color: var(--color-grey-100);
    font-size: 1rem;
    font-weight: 700;
    line-height: 1.3;
    text-overflow: ellipsis;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 3;
  }

  .task-card-metadata,
  .task-actions {
    display: flex;
    flex-wrap: wrap;
    gap: var(--spacing-4);
    align-items: center;
  }

  .task-card-metadata {
    min-height: 1.25rem;
    justify-content: flex-end;
    gap: var(--spacing-3);
  }

  .project-pill,
  .due {
    border-radius: var(--radius-full);
    padding: 2px var(--spacing-3);
    font-size: var(--font-size-xxs);
    line-height: 1.25;
  }

  .project-pill {
    display: inline-flex;
    min-width: 0;
    max-width: calc(100% - 2rem);
    align-items: center;
    gap: var(--spacing-2);
    margin-inline-end: auto;
    overflow: hidden;
    background: var(--color-primary);
    color: var(--color-font-button);
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .project-pill > span {
    width: 0.75rem;
    height: 0.75rem;
    flex: 0 0 0.75rem;
    background: currentColor;
    -webkit-mask: url('@openmates/ui/static/icons/project.svg') center / contain no-repeat;
    mask: url('@openmates/ui/static/icons/project.svg') center / contain no-repeat;
  }

  .due {
    width: fit-content;
    background: var(--color-grey-10);
    color: var(--color-font-secondary);
  }

  .assignment-indicator {
    display: block;
    width: 1.25rem;
    height: 1.25rem;
    flex: 0 0 1.25rem;
    border-radius: var(--radius-full);
    background: var(--color-primary);
  }

  .assignment-avatar {
    display: block;
    width: 1.25rem;
    height: 1.25rem;
    flex: 0 0 1.25rem;
    border-radius: var(--radius-full);
    object-fit: cover;
  }

  .assignment-indicator::after {
    content: '';
    display: block;
    width: 100%;
    height: 100%;
    background: var(--color-font-button);
    -webkit-mask-position: center;
    mask-position: center;
    -webkit-mask-repeat: no-repeat;
    mask-repeat: no-repeat;
    -webkit-mask-size: 64%;
    mask-size: 64%;
  }

  .assignment-indicator.ai::after {
    -webkit-mask-image: url('@openmates/ui/static/icons/ai.svg');
    mask-image: url('@openmates/ui/static/icons/ai.svg');
  }

  .assignment-indicator.user::after {
    -webkit-mask-image: url('@openmates/ui/static/icons/user.svg');
    mask-image: url('@openmates/ui/static/icons/user.svg');
  }

  .open-chat-link,
  .workflow-run-link {
    position: relative;
    z-index: 2;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: var(--spacing-2);
    color: var(--color-font-secondary);
    font-size: var(--font-size-xs);
    font-weight: 400;
    line-height: normal;
    text-decoration: none;
  }

  .workflow-run-link {
    width: fit-content;
    margin: 0 auto;
  }

  .workflow-run-link > span {
    width: 0.875rem;
    height: 0.875rem;
    background: currentColor;
    -webkit-mask: url('@openmates/ui/static/icons/workflow.svg') center / contain no-repeat;
    mask: url('@openmates/ui/static/icons/workflow.svg') center / contain no-repeat;
  }

  .open-chat-link > span {
    width: 0.875rem;
    height: 0.875rem;
    background: currentColor;
    -webkit-mask: url('@openmates/ui/static/icons/chat.svg') center / contain no-repeat;
    mask: url('@openmates/ui/static/icons/chat.svg') center / contain no-repeat;
  }

  .task-actions {
    position: absolute;
    inset-block-start: var(--spacing-2);
    inset-inline-end: var(--spacing-2);
    display: flex;
    flex-wrap: nowrap;
    padding: 0;
    border: 0;
  }

  .task-actions button {
    border: 0;
    border-radius: 999px;
    background: var(--color-grey-10);
    color: var(--color-font-primary);
    min-height: 1.5rem;
    padding: var(--spacing-1) var(--spacing-3);
    font: inherit;
    font-size: var(--font-size-xxs);
    cursor: pointer;
  }

  .task-actions a {
    display: grid;
    min-width: 2.5rem;
    min-height: 1.5rem;
    place-items: center;
    border-radius: var(--radius-full);
    background: var(--color-grey-10);
    color: var(--color-font-primary);
    font-size: var(--font-size-xxs);
    text-align: center;
    text-decoration: none;
  }

  .task-actions .ai-action { color: var(--color-font-primary); }

  .task-actions .danger-action {
    background: var(--color-error);
    color: var(--color-font-button);
  }

  .task-action-menu {
    position: relative;
    opacity: 0;
    transition: opacity 120ms ease;
  }

  .task-card:hover .task-action-menu,
  .task-card:focus-within .task-action-menu,
  .task-action-menu[open] { opacity: 1; }

  .task-action-menu summary {
    display: grid;
    width: 1.75rem;
    min-height: 1.5rem;
    place-items: center;
    border-radius: var(--radius-full);
    padding: 0;
    background: transparent;
    color: var(--color-font-secondary);
    font-size: var(--font-size-xxs);
    line-height: 1rem;
    letter-spacing: 0.08em;
    list-style: none;
    cursor: pointer;
  }

  .task-action-menu summary::-webkit-details-marker { display: none; }

  .task-action-menu-items {
    position: absolute;
    z-index: 4;
    inset-block-start: calc(100% + var(--spacing-2));
    inset-inline-end: 0;
    display: grid;
    width: 8.5rem;
    gap: var(--spacing-2);
    border: 1px solid var(--color-grey-25);
    border-radius: var(--radius-5);
    padding: var(--spacing-4);
    background: var(--color-grey-0);
    box-shadow: var(--shadow-lg);
  }

  .task-action-menu-items button { width: 100%; }

  .task-action-menu-items a {
    width: 100%;
    box-sizing: border-box;
  }

  .task-actions a:hover,
  .task-actions button:hover {
    filter: brightness(0.96);
  }

  .task-actions a:focus-visible,
  .task-actions button:focus-visible,
  .task-action-menu summary:focus-visible,
  .open-chat-link:focus-visible {
    outline: 2px solid var(--color-button-primary);
    outline-offset: 2px;
  }
</style>
