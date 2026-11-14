<!--
  PlanTasksList.svelte
  Tasks linked to a Plan with status chips.
-->
<script lang="ts">
  import { text } from '@repo/ui';
  import PlanStatusChip from './PlanStatusChip.svelte';
  import { taskStatusTone, type PlanLinkedTask } from './planEmbedModel';
  import './PlanSectionStyles.css';

  let { tasks, onOpenTask }: {
    tasks: PlanLinkedTask[];
    onOpenTask?: (taskId: string) => void;
  } = $props();
</script>

<section class="plan-section" data-testid="plan-tasks-list">
  <div class="plan-section-heading"><p>{$text('plan_embeds.section.tasks')}</p><span class="plan-section-count">{tasks.length}</span></div>
  {#if tasks.length === 0}
    <p class="plan-empty">{$text('plan_embeds.empty.tasks')}</p>
  {:else}
    <ul class="plan-rows">
      {#each tasks as task (task.taskId)}
        <li class="plan-row" data-testid="plan-task-row" data-status={task.status}>
          <div class="plan-row-main">
            <button type="button" class="plan-link" data-testid="plan-task-open" aria-label={$text('plan_embeds.task.open')} onclick={() => onOpenTask?.(task.taskId)}>{task.title}</button>
          </div>
          <PlanStatusChip label={$text(`plan_embeds.status.task.${task.status}`)} tone={taskStatusTone(task.status)} testId="plan-task-status" status={task.status} />
        </li>
      {/each}
    </ul>
  {/if}
</section>
