<!--
  PlanBoard.svelte
  Plans V1 Kanban board for the central Plans workspace. It buckets persisted
  plan statuses into board columns without changing the underlying status model;
  completed plans remain visible in Done while archived plans stay hidden.
-->

<script lang="ts">
  import PlanCard from './PlanCard.svelte';
  import type { UserPlanStatus, UserPlanViewModel } from '../../services/userPlanService';

  type PlanBoardColumn = 'backlog' | 'todo' | 'in_progress' | 'blocked' | 'done';

  let {
    plans,
    actionId,
    onMove,
    onArchive,
  }: {
    plans: UserPlanViewModel[];
    actionId: string | null;
    onMove: (plan: UserPlanViewModel, column: PlanBoardColumn) => void;
    onArchive: (plan: UserPlanViewModel) => void;
  } = $props();

  const columns: Array<{ id: PlanBoardColumn; title: string; description: string }> = [
    { id: 'backlog', title: 'Backlog', description: 'Drafted for later' },
    { id: 'todo', title: 'To do', description: 'Ready for confirmation' },
    { id: 'in_progress', title: 'In progress', description: 'Executing or checking' },
    { id: 'blocked', title: 'Blocked', description: 'Needs input' },
    { id: 'done', title: 'Done', description: 'Completed plans' },
  ];

  function columnForStatus(status: UserPlanStatus): PlanBoardColumn | null {
    if (status === 'archived') return null;
    if (status === 'completed') return 'done';
    if (status === 'blocked') return 'blocked';
    if (status === 'executing' || status === 'running_checks') return 'in_progress';
    if (status === 'awaiting_confirmation' || status === 'checking_assumptions' || status === 'active') return 'todo';
    return 'backlog';
  }

  function plansFor(column: PlanBoardColumn): UserPlanViewModel[] {
    return plans
      .filter((plan) => columnForStatus(plan.status) === column)
      .sort((a, b) => b.updatedAt - a.updatedAt);
  }
</script>

<div class="plan-board" data-testid="plan-board" aria-label="Plans board">
  {#each columns as column}
    {@const columnPlans = plansFor(column.id)}
    <section class="plan-column" data-testid={`plan-column-${column.id}`} aria-label={`${column.title} plan column`}>
      <header>
        <div>
          <h2>{column.title}</h2>
          <p>{column.description}</p>
        </div>
        <span>{columnPlans.length}</span>
      </header>

      <div class="plan-column-list">
        {#each columnPlans as plan (plan.plan_id)}
          <PlanCard
            {plan}
            column={column.id}
            {actionId}
            {onMove}
            {onArchive}
          />
        {:else}
          <div class="plan-column-empty" data-testid="plan-column-empty">No plans here.</div>
        {/each}
      </div>
    </section>
  {/each}
</div>

<style>
  .plan-board {
    display: grid;
    grid-template-columns: repeat(5, minmax(260px, 280px));
    gap: 14px;
    align-items: start;
    width: 100%;
    min-width: 0;
    max-height: min(62vh, 720px);
    overflow: auto;
    padding: 0 0 8px;
    -webkit-overflow-scrolling: touch;
  }

  .plan-column {
    display: flex;
    min-height: 360px;
    flex-direction: column;
    gap: 12px;
    border: 1px solid var(--color-grey-20);
    border-radius: 30px;
    padding: 14px;
    background: var(--color-grey-10);
  }

  header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 10px;
  }

  h2,
  p {
    margin: 0;
  }

  h2 {
    font-size: 1rem;
  }

  p {
    margin-top: 3px;
    color: var(--color-font-secondary);
    font-size: 0.78rem;
  }

  header span {
    display: grid;
    min-width: 28px;
    height: 28px;
    border-radius: var(--radius-full);
    background: var(--color-grey-0);
    color: var(--color-font-secondary);
    font-size: 0.8rem;
    place-items: center;
  }

  .plan-column-list {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .plan-column-empty {
    border: 1px dashed var(--color-grey-30);
    border-radius: 22px;
    padding: 22px 12px;
    color: var(--color-font-secondary);
    font-size: 0.85rem;
    text-align: center;
  }

  @media (max-width: 730px) {
    .plan-board {
      grid-template-columns: repeat(5, minmax(252px, 270px));
      max-height: 58vh;
    }

    .plan-column {
      min-height: 300px;
    }
  }
</style>
