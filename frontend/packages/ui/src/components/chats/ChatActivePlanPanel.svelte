<!--
  ChatActivePlanPanel.svelte
  Chat settings view of the chat's active Plan body: approval, Tasks (to-dos),
  Checks and assumptions with their status, plus an "Open plan" action. The
  title/status row stays with the caller. Props-driven; the parent supplies
  decrypted details.
-->
<script lang="ts">
  import { text } from '@repo/ui';
  import PlanStatusChip from '../embeds/plans/PlanStatusChip.svelte';
  import {
    assumptionStatusTone, checkAggregateStatus, checkLabel, checkStatusTone, derivePlanApproval,
    summarizeChecks, summarizeProgress, taskStatusTone, type PlanEmbedData,
  } from '../embeds/plans/planEmbedModel';

  let { data, onOpenPlan }: {
    data: PlanEmbedData;
    onOpenPlan?: (planId: string) => void;
  } = $props();
  let approval = $derived(derivePlanApproval(data));
  let progress = $derived(summarizeProgress(data.tasks));
  let checks = $derived(summarizeChecks(data.checks));
  let approvalLabel = $derived(approval.kind === 'approved' && approval.revisionNumber
    ? $text('plan_embeds.approval.approved', { values: { revision: approval.revisionNumber } })
    : $text(approval.kind === 'approved' ? 'plan_embeds.approval.approved_plain' : `plan_embeds.approval.${approval.kind}`));
</script>

<div class="active-plan" data-testid="chat-active-plan-panel" data-plan-id={data.plan.plan_id} data-approval-state={approval.kind}>
  <div class="summary">
    <PlanStatusChip label={approvalLabel} tone={approval.kind === 'approved' ? 'success' : approval.kind === 'changed' ? 'warning' : 'neutral'} testId="chat-active-plan-approval" status={approval.kind} />
    <span data-testid="chat-active-plan-progress">{$text('plan_embeds.summary.tasks', { values: { done: progress.done, total: progress.total } })}</span>
    <span data-testid="chat-active-plan-checks">{$text('plan_embeds.summary.checks', { values: { green: checks.requiredGreen, required: checks.required } })}</span>
  </div>

  <section aria-label={$text('plan_embeds.section.tasks')} data-testid="chat-active-plan-tasks">
    <p class="heading">{$text('plan_embeds.section.tasks')}</p>
    {#if data.tasks.length === 0}<p class="empty">{$text('plan_embeds.empty.tasks')}</p>{/if}
    <ul>
      {#each data.tasks as task (task.taskId)}
        <li data-testid="chat-active-plan-task" data-status={task.status}>
          <span>{task.title}</span>
          <PlanStatusChip label={$text(`plan_embeds.status.task.${task.status}`)} tone={taskStatusTone(task.status)} testId="chat-active-plan-task-status" status={task.status} />
        </li>
      {/each}
    </ul>
  </section>

  <section aria-label={$text('plan_embeds.section.checks')} data-testid="chat-active-plan-checks-list">
    <p class="heading">{$text('plan_embeds.section.checks')}</p>
    {#if data.checks.length === 0}<p class="empty">{$text('plan_embeds.empty.checks')}</p>{/if}
    <ul>
      {#each data.checks as check (check.verificationId)}
        {@const status = checkAggregateStatus(check)}
        <li data-testid="chat-active-plan-check" data-status={status}>
          <span>{checkLabel(check)}</span>
          <PlanStatusChip label={$text(`plan_embeds.status.check.${status}`)} tone={checkStatusTone(status)} testId="chat-active-plan-check-status" status={status} />
        </li>
      {/each}
    </ul>
  </section>

  <section aria-label={$text('plan_embeds.section.assumptions')} data-testid="chat-active-plan-assumptions">
    <p class="heading">{$text('plan_embeds.section.assumptions')}</p>
    {#if data.assumptions.length === 0}<p class="empty">{$text('plan_embeds.empty.assumptions')}</p>{/if}
    <ul>
      {#each data.assumptions as assumption (assumption.assumptionId)}
        <li data-testid="chat-active-plan-assumption" data-status={assumption.status}>
          <span>{assumption.correctedText || assumption.text}</span>
          <PlanStatusChip label={$text(`plan_embeds.status.assumption.${assumption.status}`)} tone={assumptionStatusTone(assumption.status)} testId="chat-active-plan-assumption-status" status={assumption.status} />
        </li>
      {/each}
    </ul>
  </section>

  <button type="button" class="open-plan" data-testid="chat-active-plan-open" onclick={() => onOpenPlan?.(data.plan.plan_id)}>{$text('plan_embeds.plan.open')}</button>
</div>

<style>
  .active-plan { display: grid; gap: var(--spacing-6); margin-top: var(--spacing-5); color: var(--color-font-primary); }
  .summary { display: flex; flex-wrap: wrap; align-items: center; gap: var(--spacing-3) var(--spacing-6); color: var(--color-font-secondary); font-size: var(--font-size-small, 0.875rem); }
  .heading { margin: 0 0 var(--spacing-3); font-weight: 700; }
  .empty { margin: 0; color: var(--color-font-secondary); }
  ul { display: grid; gap: var(--spacing-3); margin: 0; padding: 0; list-style: none; }
  li { display: flex; align-items: center; justify-content: space-between; gap: var(--spacing-5); padding: var(--spacing-4) var(--spacing-5); border-radius: var(--radius-4, 18px); background: var(--color-grey-10); }
  li span:first-child { min-width: 0; overflow-wrap: anywhere; }
  .open-plan { justify-self: start; border: 0; border-radius: 999px; background: var(--color-button-primary); color: var(--color-font-button); padding: 11px 16px; font: inherit; cursor: pointer; }
</style>
