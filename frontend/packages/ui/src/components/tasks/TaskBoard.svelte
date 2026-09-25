<!--
  TaskBoard.svelte
  Shared Kanban board for central, project, and chat-scoped task surfaces.
  Supports pointer drag/drop and explicit move buttons for touch/accessibility.
-->

<script lang="ts">
  import TaskCard from './TaskCard.svelte';
  import PlanTaskCard from './PlanTaskCard.svelte';
  import type { UserPlanStatus, UserPlanViewModel } from '../../services/userPlanService';
  import type { TasksBoardItem, UserTaskStatus } from '../../services/userTaskService';

  let {
    tasks,
    plans = [],
    onMove,
    onMovePlan,
    onStartAI,
    onSkip,
    onDelete,
    onCancelWorkflowRun,
    onSelect,
    projectNames = {},
    assigneeAvatarUrl = null,
    planActionId = null,
  }: {
    tasks: TasksBoardItem[];
    plans?: UserPlanViewModel[];
    onMove: (task: TasksBoardItem, status: UserTaskStatus) => void;
    onMovePlan: (plan: UserPlanViewModel, status: UserTaskStatus) => void;
    onStartAI: (task: TasksBoardItem) => void;
    onSkip: (task: TasksBoardItem) => void;
    onDelete: (task: TasksBoardItem) => void;
    onCancelWorkflowRun: (task: TasksBoardItem) => void;
    onSelect: (task: TasksBoardItem) => void;
    projectNames?: Record<string, string>;
    assigneeAvatarUrl?: string | null;
    planActionId?: string | null;
  } = $props();

  const columns: Array<{ status: UserTaskStatus; title: string }> = [
    { status: 'backlog', title: 'Backlog' },
    { status: 'todo', title: 'Todo' },
    { status: 'in_progress', title: 'In progress' },
    { status: 'blocked', title: 'Blocked' },
    { status: 'done', title: 'Done' },
  ];
  let recentlyDroppedTaskId = $state<string | null>(null);
  let recentlyDroppedPlanId = $state<string | null>(null);
  let clearDropTimer: ReturnType<typeof setTimeout> | null = null;

  function tasksFor(status: UserTaskStatus): TasksBoardItem[] {
    return tasks.filter((task) => task.status === status).sort((a, b) => a.position - b.position);
  }

  function planColumn(status: UserPlanStatus): UserTaskStatus | null {
    if (status === 'archived') return null;
    if (status === 'completed') return 'done';
    if (status === 'blocked') return 'blocked';
    if (status === 'executing' || status === 'running_checks') return 'in_progress';
    if (status === 'checking_assumptions' || status === 'awaiting_confirmation' || status === 'active') return 'todo';
    return 'backlog';
  }

  function plansFor(status: UserTaskStatus): UserPlanViewModel[] {
    return plans
      .filter((plan) => planColumn(plan.status) === status)
      .sort((a, b) => b.updatedAt - a.updatedAt);
  }

  function itemCount(status: UserTaskStatus): number {
    return tasksFor(status).length + plansFor(status).length;
  }

  function handleDrop(event: DragEvent, status: UserTaskStatus): void {
    event.preventDefault();
    const planId = event.dataTransfer?.getData('application/x-openmates-plan-id');
    const taskId = event.dataTransfer?.getData('application/x-openmates-task-id') || (!planId ? event.dataTransfer?.getData('text/plain') : '');
    const plan = plans.find((candidate) => candidate.plan_id === planId);
    if (plan && planColumn(plan.status) !== status) {
      recentlyDroppedPlanId = plan.plan_id;
      if (clearDropTimer) clearTimeout(clearDropTimer);
      clearDropTimer = setTimeout(() => { recentlyDroppedPlanId = null; }, 1200);
      onMovePlan(plan, status);
      return;
    }
    const task = tasks.find((candidate) => candidate.task_id === taskId);
    if (task && task.status !== status) {
      recentlyDroppedTaskId = task.task_id;
      if (clearDropTimer) clearTimeout(clearDropTimer);
      clearDropTimer = setTimeout(() => { recentlyDroppedTaskId = null; }, 1200);
      onMove(task, status);
    }
  }
</script>

<div class="task-board" data-testid="task-board" data-board-state="mounted">
  {#each columns as column}
    <div
      class="task-column"
      data-status={column.status}
      data-testid={`task-column-${column.status}`}
      role="region"
      aria-label={`${column.title} task column`}
      ondragover={(event) => event.preventDefault()}
      ondrop={(event) => handleDrop(event, column.status)}
    >
      <header>
        <h2>{column.title}</h2>
        <span
          class="task-column-count"
          data-testid={`task-column-count-${column.status}`}
          aria-label={`${itemCount(column.status)} tasks and plans`}
        >({itemCount(column.status)})</span>
      </header>

      <div class="task-column-list">
        {#each tasksFor(column.status) as task (task.task_id)}
          <TaskCard
            {task}
            {onMove}
            {onStartAI}
            {onSkip}
            {onDelete}
            {onCancelWorkflowRun}
            {onSelect}
            linkedProjectName={projectNames[task.linkedProjectIds[0]] ?? null}
            {assigneeAvatarUrl}
            wasRecentlyDropped={recentlyDroppedTaskId === task.task_id}
          />
        {/each}
        {#each plansFor(column.status) as plan (plan.plan_id)}
          <PlanTaskCard
            {plan}
            column={column.status}
            actionId={planActionId}
            onMove={onMovePlan}
            linkedProjectName={projectNames[plan.linkedProjectIds[0]] ?? null}
            wasRecentlyDropped={recentlyDroppedPlanId === plan.plan_id}
          />
        {/each}
        {#if itemCount(column.status) === 0}
          <div class="task-column-empty" data-testid="task-column-empty">
            <span>No tasks or plans here.</span>
          </div>
        {/if}
      </div>
    </div>
  {/each}
</div>

<style>
  .task-board {
    display: grid;
    grid-template-columns: repeat(5, minmax(230px, 1fr));
    gap: clamp(var(--spacing-6), 1.5vw, var(--spacing-12));
    width: 100%;
    min-width: 0;
    min-height: 20rem;
    max-height: min(62vh, 720px);
    overflow: auto;
    padding: var(--spacing-2) var(--spacing-2) var(--spacing-8);
    scroll-snap-type: x proximity;
    scrollbar-color: var(--color-grey-30) transparent;
    -webkit-overflow-scrolling: touch;
  }

  .task-column {
    --status-accent: var(--color-primary);
    display: flex;
    flex-direction: column;
    gap: var(--spacing-8);
    min-width: 0;
    min-height: 21.25rem;
    border-radius: var(--radius-8);
    padding: var(--spacing-8) var(--spacing-6);
    background: transparent;
    scroll-snap-align: start;
  }

  .task-column[data-status='backlog'] { --status-accent: var(--color-chat-rainbow-purple); }
  .task-column[data-status='todo'] { --status-accent: var(--color-chat-rainbow-cyan); }
  .task-column[data-status='in_progress'] { --status-accent: var(--color-warning); }
  .task-column[data-status='blocked'] { --status-accent: var(--color-error); background: var(--color-grey-25); }
  .task-column[data-status='done'] { --status-accent: var(--color-chat-rainbow-green); }

  header {
    display: flex;
    justify-content: flex-start;
    align-items: center;
    gap: var(--spacing-3);
    min-height: 1.75rem;
    border-inline-start: 0.25rem solid var(--status-accent);
    padding-inline-start: var(--spacing-4);
  }

  h2 {
    margin: 0;
    color: var(--color-font-primary);
    font-size: var(--font-size-h3);
    font-weight: 700;
    line-height: 1.25;
    letter-spacing: -0.02em;
  }

  .task-column-count {
    color: var(--color-font-secondary);
    font-size: var(--font-size-xxs);
    font-weight: 500;
    line-height: 1;
  }

  .task-column-list { display: flex; flex-direction: column; gap: var(--spacing-6); }
  .task-column-empty {
    min-height: var(--spacing-8);
  }

  .task-column-empty span {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip: rect(0 0 0 0);
    clip-path: inset(50%);
    white-space: nowrap;
  }

  @media (max-width: 900px) {
    .task-board {
      grid-template-columns: repeat(5, minmax(15rem, 16rem));
      max-height: 58vh;
      padding-inline: 0;
      scroll-padding-inline: var(--spacing-4);
    }
    .task-column { min-height: 17.5rem; }
  }
</style>
