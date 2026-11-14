<!--
  PlanEmbedPreview.svelte
  Compact chat-embed card for a Plan: title, goal, status, approval state,
  Task progress, Checks summary and open assumptions. Props-driven; the parent
  supplies decrypted Plan data and the open callback.
-->
<script lang="ts">
  import { text } from '@repo/ui';
  import PlanStatusChip from './PlanStatusChip.svelte';
  import {
    countOpenAssumptions, derivePlanApproval, planStatusTone, summarizeChecks, summarizeProgress,
    type PlanEmbedData,
  } from './planEmbedModel';

  let { data, onOpen }: {
    data: PlanEmbedData;
    onOpen?: (planId: string) => void;
  } = $props();

  let approval = $derived(derivePlanApproval(data));
  let progress = $derived(summarizeProgress(data.tasks));
  let checks = $derived(summarizeChecks(data.checks));
  let openAssumptions = $derived(countOpenAssumptions(data.assumptions));
  let progressPercent = $derived(progress.total === 0 ? 0 : Math.round((progress.done / progress.total) * 100));
  let approvalLabel = $derived(approval.kind === 'approved' && approval.revisionNumber
    ? $text('plan_embeds.approval.approved', { values: { revision: approval.revisionNumber } })
    : $text(approval.kind === 'approved' ? 'plan_embeds.approval.approved_plain' : `plan_embeds.approval.${approval.kind}`));
</script>

<button type="button" class="plan-embed" data-testid="plan-embed-preview" data-plan-status={data.plan.status}
  data-approval-state={approval.kind} onclick={() => onOpen?.(data.plan.plan_id)}>
  <div class="head">
    <strong class="title" data-testid="plan-embed-title">{data.plan.title}</strong>
    <PlanStatusChip label={$text(`plan_embeds.status.plan.${data.plan.status}`)} tone={planStatusTone(data.plan.status)} testId="plan-embed-status" status={data.plan.status} />
  </div>
  {#if data.plan.goal}<p class="goal" data-testid="plan-embed-goal">{data.plan.goal}</p>{/if}
  <div class="progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow={progressPercent} aria-label={$text('plan_embeds.section.tasks')}>
    <span class="bar" style:width="{progressPercent}%"></span>
  </div>
  <div class="facts">
    <span data-testid="plan-embed-progress">{$text('plan_embeds.summary.tasks', { values: { done: progress.done, total: progress.total } })}</span>
    <span data-testid="plan-embed-checks">{$text('plan_embeds.summary.checks', { values: { green: checks.requiredGreen, required: checks.required } })}</span>
    {#if checks.waiting > 0}<span class="attention" data-testid="plan-embed-waiting">{$text('plan_embeds.summary.waiting', { values: { count: checks.waiting } })}</span>{/if}
    {#if openAssumptions > 0}
      <span data-testid="plan-embed-assumptions">{$text('plan_embeds.summary.assumptions_open', { values: { count: openAssumptions } })}</span>
    {/if}
  </div>
  <div class="foot"><PlanStatusChip label={approvalLabel} tone={approval.kind === 'approved' ? 'success' : approval.kind === 'changed' ? 'warning' : 'neutral'} testId="plan-embed-approval" status={approval.kind} /></div>
</button>

<style>
  .plan-embed { display: grid; align-content: start; justify-items: stretch; gap: var(--spacing-5); width: 100%; max-width: 420px; height: auto; min-height: 0; margin: 0; box-shadow: none; padding: var(--spacing-8); border: 1px solid var(--color-grey-20); border-radius: var(--radius-5, 24px); background: var(--color-grey-0); color: var(--color-font-primary); font: inherit; text-align: left; cursor: pointer; }
  .head { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--spacing-5); }
  .title { min-width: 0; overflow-wrap: anywhere; }
  .goal { margin: 0; color: var(--color-font-secondary); display: -webkit-box; line-clamp: 2; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
  .progress { height: 6px; border-radius: 999px; background: var(--color-grey-20); overflow: hidden; }
  .bar { display: block; height: 100%; background: var(--color-button-primary); }
  .facts { display: flex; flex-wrap: wrap; gap: var(--spacing-3) var(--spacing-6); font-size: var(--font-size-small, 0.875rem); color: var(--color-font-secondary); }
  .attention { color: var(--color-warning, var(--color-font-primary)); font-weight: 600; }
</style>
