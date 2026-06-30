<!--
  TaskBoard.svelte
  Shared Kanban board for central, project, and chat-scoped task surfaces.
  Supports pointer drag/drop and explicit move buttons for touch/accessibility.
-->

<script lang="ts">
  import TaskCard from './TaskCard.svelte';
  import type { UserTaskStatus, UserTaskViewModel } from '../../services/userTaskService';

  let {
    tasks,
    onMove,
    onStartAI,
  }: {
    tasks: UserTaskViewModel[];
    onMove: (task: UserTaskViewModel, status: UserTaskStatus) => void;
    onStartAI: (task: UserTaskViewModel) => void;
  } = $props();

  const columns: Array<{ status: UserTaskStatus; title: string; description: string }> = [
    { status: 'backlog', title: 'Backlog', description: 'Parked for later' },
    { status: 'todo', title: 'To do', description: 'Ready to start' },
    { status: 'in_progress', title: 'In progress', description: 'Active now' },
    { status: 'blocked', title: 'Blocked', description: 'Needs input' },
    { status: 'done', title: 'Done', description: 'Completed' },
  ];

  function tasksFor(status: UserTaskStatus): UserTaskViewModel[] {
    return tasks.filter((task) => task.status === status).sort((a, b) => a.position - b.position);
  }

  function handleDrop(event: DragEvent, status: UserTaskStatus): void {
    event.preventDefault();
    const taskId = event.dataTransfer?.getData('application/x-openmates-task-id') || event.dataTransfer?.getData('text/plain');
    const task = tasks.find((candidate) => candidate.task_id === taskId);
    if (task && task.status !== status) onMove(task, status);
  }
</script>

<div class="task-board" data-testid="task-board">
  {#each columns as column}
    <div
      class="task-column"
      data-testid={`task-column-${column.status}`}
      role="region"
      aria-label={`${column.title} task column`}
      ondragover={(event) => event.preventDefault()}
      ondrop={(event) => handleDrop(event, column.status)}
    >
      <header>
        <div>
          <h2>{column.title}</h2>
          <p>{column.description}</p>
        </div>
        <span>{tasksFor(column.status).length}</span>
      </header>

      <div class="task-column-list">
        {#each tasksFor(column.status) as task (task.task_id)}
          <TaskCard {task} {onMove} {onStartAI} />
        {:else}
          <div class="task-column-empty" data-testid="task-column-empty">
            No tasks here.
          </div>
        {/each}
      </div>
    </div>
  {/each}
</div>

<style>
  .task-board {
    display: grid;
    grid-template-columns: repeat(5, minmax(240px, 1fr));
    gap: 14px;
    align-items: start;
    min-width: min(100%, 1240px);
    overflow-x: auto;
    padding-bottom: 6px;
  }

  .task-column {
    display: flex;
    flex-direction: column;
    gap: 12px;
    min-height: 360px;
    border-radius: 30px;
    padding: 14px;
    background: var(--color-grey-10);
    border: 1px solid var(--color-grey-20);
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
    place-items: center;
    min-width: 28px;
    height: 28px;
    border-radius: 999px;
    background: var(--color-grey-0);
    color: var(--color-font-secondary);
    font-size: 0.8rem;
  }

  .task-column-list {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .task-column-empty {
    border: 1px dashed var(--color-grey-30);
    border-radius: 22px;
    padding: 22px 12px;
    text-align: center;
    color: var(--color-font-secondary);
    font-size: 0.85rem;
  }

  @media (max-width: 900px) {
    .task-board {
      grid-template-columns: minmax(260px, 1fr);
      overflow: visible;
    }

    .task-column {
      min-height: auto;
    }
  }
</style>
