<!--
  PlanTaskCard.svelte
  Task-board presentation for a locally decrypted encrypted Plan. It preserves
  Plan lifecycle guards while matching the established Task card interaction.
-->

<script lang="ts">
  import type { UserPlanViewModel } from '../../services/userPlanService';
  import type { UserTaskStatus } from '../../services/userTaskService';

  let {
    plan,
    column,
    actionId,
    onMove,
    linkedProjectName = null,
    wasRecentlyDropped = false,
  }: {
    plan: UserPlanViewModel;
    column: UserTaskStatus;
    actionId: string | null;
    onMove: (plan: UserPlanViewModel, column: UserTaskStatus) => void;
    linkedProjectName?: string | null;
    wasRecentlyDropped?: boolean;
  } = $props();

  const columns: Array<{ id: UserTaskStatus; label: string; needsChat?: boolean }> = [
    { id: 'backlog', label: 'Backlog' },
    { id: 'todo', label: 'Todo' },
    { id: 'in_progress', label: 'In progress', needsChat: true },
    { id: 'blocked', label: 'Blocked', needsChat: true },
    { id: 'done', label: 'Done' },
  ];

  let dragging = $state(false);
  let settling = $state(false);
  let isBusy = $derived(actionId === plan.plan_id);
  let linkedProjectLabel = $derived(plan.linkedProjectIds.length > 0 ? linkedProjectName || 'Project' : null);

  $effect(() => {
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
    if (isBusy) {
      event.preventDefault();
      return;
    }
    dragging = true;
    event.dataTransfer?.setData('application/x-openmates-plan-id', plan.plan_id);
    event.dataTransfer?.setData('text/plain', plan.plan_id);
    if (event.dataTransfer && event.currentTarget instanceof HTMLElement) {
      const dragImage = event.currentTarget.cloneNode(true) as HTMLElement;
      dragImage.classList.add('dragging');
      dragImage.removeAttribute('data-testid');
      dragImage.removeAttribute('data-plan-id');
      dragImage.querySelectorAll('[data-testid]').forEach((element) => element.removeAttribute('data-testid'));
      dragImage.style.position = 'fixed';
      dragImage.style.inset = 'auto auto -1000px -1000px';
      dragImage.style.width = `${event.currentTarget.getBoundingClientRect().width}px`;
      dragImage.style.transition = 'none';
      document.body.append(dragImage);
      event.dataTransfer.setDragImage(dragImage, 12, 12);
      requestAnimationFrame(() => dragImage.remove());
    }
  }

  function actionDisabled(target: UserTaskStatus, needsChat?: boolean): boolean {
    return isBusy || target === column || Boolean(needsChat && !plan.primaryChatId);
  }
</script>

<article
  class="plan-task-card"
  class:dragging
  class:settling
  draggable={!isBusy}
  ondragstart={handleDragStart}
  ondragend={() => { dragging = false; }}
  data-testid="task-board-plan-card"
  data-plan-id={plan.plan_id}
  data-plan-status={plan.status}
  data-plan-column={column}
  data-drag-state={dragging ? 'picked-up' : 'settled'}
>
  <a
    class="card-open"
    href={`/#plan-id=${encodeURIComponent(plan.plan_id)}`}
    aria-label={`Open ${plan.title || 'plan'} details`}
    data-testid="task-board-plan-open"
  ></a>
  <div class="plan-card-main">
    <h3>{plan.title || 'Untitled plan'}</h3>
  </div>

  <div class="plan-card-metadata">
    {#if linkedProjectLabel}
      <span class="project-pill" data-testid="plan-project-pill"><span aria-hidden="true"></span>{linkedProjectLabel}</span>
    {/if}
  </div>
  <a class="open-plan-link" href={`/#plan-id=${encodeURIComponent(plan.plan_id)}`} data-testid="task-board-plan-link"><span aria-hidden="true"></span>Open plan</a>

  <div class="plan-actions" aria-label="Move plan">
    <details class="plan-action-menu">
      <summary data-testid="task-board-plan-actions" aria-label={`More actions for ${plan.title || 'plan'}`} title="More actions"><span aria-hidden="true">•••</span></summary>
      <div class="plan-action-menu-items">
        <a href={`/#plan-id=${encodeURIComponent(plan.plan_id)}`} data-testid="task-board-plan-detail-link">Open plan</a>
        {#if plan.primaryChatId}
          <a href={`/#chat-id=${encodeURIComponent(plan.primaryChatId)}`} data-testid="task-board-plan-chat-link">Open chat</a>
        {/if}
        {#each columns as target}
          {#if target.id !== column}
            <button
              type="button"
              disabled={actionDisabled(target.id, target.needsChat)}
              title={target.needsChat && !plan.primaryChatId ? 'Link this plan to a chat before execution actions.' : undefined}
              onclick={() => onMove(plan, target.id)}
              data-testid={`task-board-plan-move-${target.id}`}
            >{target.label}</button>
          {/if}
        {/each}
      </div>
    </details>
  </div>
</article>

<style>
  .plan-task-card {
    position: relative;
    box-sizing: border-box;
    display: flex;
    min-height: 4.25rem;
    flex-direction: column;
    gap: var(--spacing-2);
    border: 1px solid var(--color-grey-25);
    border-radius: var(--radius-5);
    padding: var(--spacing-5);
    background: var(--color-grey-0);
    box-shadow: var(--shadow-md);
    color: var(--color-font-primary);
    cursor: grab;
    transform: none;
    transform-origin: center;
    transition: transform 180ms ease, box-shadow 180ms ease;
    will-change: transform;
  }

  .plan-task-card.dragging {
    z-index: 8;
    cursor: grabbing;
    transform: translateY(-8px) rotate(10deg) scale(1.02);
    box-shadow: var(--shadow-xl);
  }

  .plan-task-card.settling {
    transform: translateY(-8px) rotate(10deg) scale(1.02);
    transition: none;
  }

  .card-open {
    position: absolute;
    z-index: 1;
    inset: 0;
    border-radius: inherit;
  }

  .card-open:focus-visible {
    outline: 3px solid var(--color-primary);
    outline-offset: 3px;
  }

  .plan-card-main,
  .plan-card-metadata,
  .plan-actions {
    position: relative;
    z-index: 2;
    pointer-events: none;
  }

  .plan-actions,
  .plan-actions a,
  .plan-actions button,
  .plan-action-menu,
  .open-plan-link {
    pointer-events: auto;
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

  .plan-card-metadata {
    display: flex;
    min-height: 1.25rem;
    flex-wrap: wrap;
    align-items: center;
    justify-content: flex-end;
    gap: var(--spacing-3);
  }

  .project-pill {
    border-radius: var(--radius-full);
    padding: 2px var(--spacing-3);
    font-size: var(--font-size-xxs);
    line-height: 1.25;
  }

  .project-pill {
    display: inline-flex;
    min-width: 0;
    max-width: 100%;
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

  .open-plan-link {
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

  .open-plan-link > span {
    width: 0.875rem;
    height: 0.875rem;
    background: currentColor;
    -webkit-mask: url('@openmates/ui/static/icons/planning.svg') center / contain no-repeat;
    mask: url('@openmates/ui/static/icons/planning.svg') center / contain no-repeat;
  }

  .open-plan-link:focus-visible {
    outline: 3px solid var(--color-primary);
    outline-offset: 3px;
  }

  .plan-actions {
    position: absolute;
    inset-block-start: var(--spacing-2);
    inset-inline-end: var(--spacing-2);
  }

  .plan-action-menu {
    position: relative;
    opacity: 0;
    transition: opacity 120ms ease;
  }

  .plan-task-card:hover .plan-action-menu,
  .plan-task-card:focus-within .plan-action-menu,
  .plan-action-menu[open] {
    opacity: 1;
  }

  .plan-action-menu summary {
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

  .plan-action-menu summary::-webkit-details-marker {
    display: none;
  }

  .plan-action-menu-items {
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

  .plan-action-menu-items button,
  .plan-action-menu-items a {
    box-sizing: border-box;
    display: grid;
    width: 100%;
    min-height: 1.5rem;
    place-items: center;
    border: 0;
    border-radius: var(--radius-full);
    padding: var(--spacing-1) var(--spacing-3);
    background: var(--color-grey-10);
    color: var(--color-font-primary);
    font: inherit;
    font-size: var(--font-size-xxs);
    text-align: center;
    text-decoration: none;
    cursor: pointer;
  }

  .plan-action-menu-items button:disabled {
    opacity: 0.45;
    cursor: not-allowed;
  }

  .plan-action-menu summary:focus-visible,
  .plan-action-menu-items button:focus-visible,
  .plan-action-menu-items a:focus-visible {
    outline: 2px solid var(--color-button-primary);
    outline-offset: 2px;
  }
</style>
