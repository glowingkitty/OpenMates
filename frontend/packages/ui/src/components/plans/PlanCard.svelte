<!--
  PlanCard.svelte
  Reusable encrypted plan card for the central Plans workspace board. Receives
  only locally decrypted plan view models and exposes explicit status actions so
  touch/mobile users do not depend on drag-and-drop.
-->

<script lang="ts">
  import type { UserPlanViewModel } from '../../services/userPlanService';

  type PlanBoardColumn = 'backlog' | 'todo' | 'in_progress' | 'blocked' | 'done';

  let {
    plan,
    column,
    actionId,
    onMove,
    onArchive,
  }: {
    plan: UserPlanViewModel;
    column: PlanBoardColumn;
    actionId: string | null;
    onMove: (plan: UserPlanViewModel, column: PlanBoardColumn) => void;
    onArchive: (plan: UserPlanViewModel) => void;
  } = $props();

  const columns: Array<{ id: PlanBoardColumn; label: string; needsChat?: boolean }> = [
    { id: 'backlog', label: 'Backlog' },
    { id: 'todo', label: 'To do' },
    { id: 'in_progress', label: 'Start', needsChat: true },
    { id: 'blocked', label: 'Block', needsChat: true },
    { id: 'done', label: 'Done' },
  ];

  let isBusy = $derived(actionId === plan.plan_id);
  let summary = $derived(plan.summary || plan.goal || 'No summary yet.');

  function formatStatus(status: string): string {
    return status.replaceAll('_', ' ');
  }

  function actionDisabled(target: PlanBoardColumn, needsChat?: boolean): boolean {
    return isBusy || target === column || Boolean(needsChat && !plan.primaryChatId);
  }
</script>

<article
  class="plan-card"
  data-testid="plan-card"
  data-plan-id={plan.plan_id}
  data-plan-status={plan.status}
  data-plan-column={column}
>
  <div class="plan-card-main">
    <label class="done-toggle">
      <input
        type="checkbox"
        checked={column === 'done'}
        onchange={() => onMove(plan, column === 'done' ? 'todo' : 'done')}
        aria-label={`Mark ${plan.title || 'plan'} done`}
        disabled={isBusy}
        data-testid="plan-done-toggle"
      />
      <span></span>
    </label>
    <div class="plan-card-copy">
      <p class="plan-status">{formatStatus(plan.status)}</p>
      <h3 data-testid="plan-card-title">{plan.title || 'Untitled plan'}</h3>
      <p>{summary}</p>
    </div>
  </div>

  <footer class="plan-card-footer">
    <span>{plan.primaryChatId ? 'Linked chat' : 'No chat link'}</span>
    {#if plan.completedAt}
      <span>Completed {new Date(plan.completedAt * 1000).toLocaleDateString()}</span>
    {/if}
  </footer>

  <div class="plan-actions" aria-label="Manage plan">
    <a href={`/plans/${encodeURIComponent(plan.plan_id)}`} data-testid="plan-detail-link">Open</a>
    {#if plan.primaryChatId}
      <a href={`/#chat-id=${encodeURIComponent(plan.primaryChatId)}`} data-testid="plan-chat-link">Chat</a>
    {/if}
    {#each columns as target}
      {#if target.id !== column}
        <button
          type="button"
          disabled={actionDisabled(target.id, target.needsChat)}
          title={target.needsChat && !plan.primaryChatId ? 'Link this plan to a chat before execution actions.' : undefined}
          onclick={() => onMove(plan, target.id)}
          data-testid={`plan-move-${target.id}`}
        >{target.label}</button>
      {/if}
    {/each}
    <button class="danger-action" type="button" disabled={isBusy} onclick={() => onArchive(plan)} data-testid="plan-archive-button">Archive</button>
  </div>
</article>

<style>
  .plan-card {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 16px;
    border: 1px solid var(--color-grey-20);
    border-radius: 24px;
    background: var(--color-grey-0);
    box-shadow: 0 10px 28px rgba(0, 0, 0, 0.08);
    color: var(--color-font-primary);
  }

  .plan-card-main {
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
    width: 22px;
    height: 22px;
    border: 2px solid var(--color-grey-40);
    border-radius: var(--radius-full);
    background: var(--color-grey-0);
    place-items: center;
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

  .plan-card-copy {
    min-width: 0;
  }

  .plan-status,
  h3,
  p {
    margin: 0;
  }

  .plan-status {
    color: var(--color-font-secondary);
    font-size: var(--font-size-xxs);
    font-weight: 800;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }

  h3 {
    margin-top: 4px;
    font-size: 1rem;
    line-height: 1.25;
  }

  p:not(.plan-status) {
    margin-top: 6px;
    color: var(--color-font-secondary);
    font-size: 0.88rem;
    line-height: 1.4;
  }

  .plan-card-footer,
  .plan-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-items: center;
  }

  .plan-card-footer span {
    border-radius: var(--radius-full);
    padding: 4px 9px;
    background: var(--color-grey-10);
    color: var(--color-font-secondary);
    font-size: 0.75rem;
  }

  .plan-actions button,
  .plan-actions a {
    display: grid;
    min-width: 44px;
    min-height: 36px;
    place-items: center;
    border: 0;
    border-radius: var(--radius-full);
    background: var(--color-grey-10);
    color: var(--color-font-primary);
    padding: 6px 10px;
    font: inherit;
    font-size: var(--font-size-xs);
    cursor: pointer;
  }

  .plan-actions a {
    text-decoration: none;
  }

  .plan-actions button:disabled {
    opacity: 0.45;
    cursor: not-allowed;
  }

  .plan-actions .danger-action {
    background: var(--color-error, #c83a32);
    color: var(--color-grey-0);
  }
</style>
