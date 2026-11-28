<!--
  PlanEmbedPreview.svelte
  Chat embed preview for a Plan (shared UnifiedEmbedPreview container): title, status, approval state,
  Task progress, Checks summary and open assumptions; the goal shows in fullscreen. Props-driven; the parent
  supplies decrypted Plan data and the required onFullscreen callback.
-->
<script lang="ts">
  import { text } from '@repo/ui';
  import UnifiedEmbedPreview from '../UnifiedEmbedPreview.svelte';
  import PlanStatusChip from './PlanStatusChip.svelte';
  import {
    countOpenAssumptions, derivePlanApproval, planStatusTone, summarizeChecks, summarizeProgress,
    type PlanEmbedData,
  } from './planEmbedModel';

  let { id, data, isMobile = false, onFullscreen }: {
    id: string;
    data: PlanEmbedData;
    isMobile?: boolean;
    onFullscreen: () => void;
  } = $props();

  let approval = $derived(derivePlanApproval(data));
  let progress = $derived(summarizeProgress(data.tasks));
  let checks = $derived(summarizeChecks(data.checks));
  let openAssumptions = $derived(countOpenAssumptions(data.assumptions));
  let progressPercent = $derived(progress.total === 0 ? 0 : Math.round((progress.done / progress.total) * 100));
  let approvalLabel = $derived(approval.kind === 'approved' && approval.revisionNumber
    ? $text('plan_embeds.approval.approved', { values: { revision: approval.revisionNumber } })
    : $text(approval.kind === 'approved' ? 'plan_embeds.approval.approved_plain' : `plan_embeds.approval.${approval.kind}`));
  let statusLabel = $derived($text(`plan_embeds.status.plan.${data.plan.status}`));
  // A draft Plan's approval chip would repeat the "Draft" status chip.
  let showApproval = $derived(approvalLabel !== statusLabel);
</script>

<UnifiedEmbedPreview
  {id}
  appId="plans"
  skillId="create"
  appIconName="planning"
  skillIconName="planning"
  status="finished"
  skillName={$text('plan_embeds.plan.fullscreen_label')}
  {isMobile}
  {onFullscreen}
  showStatus={false}
  showSkillIcon={false}
>
  {#snippet details()}
<article class="plan-embed" data-testid="plan-embed-preview" data-plan-status={data.plan.status} data-approval-state={approval.kind}>
  <div class="head">
    <strong class="title" data-testid="plan-embed-title" title={data.plan.title}>{data.plan.title}</strong>
    <PlanStatusChip label={statusLabel} tone={planStatusTone(data.plan.status)} testId="plan-embed-status" status={data.plan.status} />
  </div>
  <div class="approval-row">
    {#if showApproval}
      <PlanStatusChip label={approvalLabel} tone={approval.kind === 'approved' ? 'success' : approval.kind === 'changed' ? 'warning' : 'neutral'} testId="plan-embed-approval" status={approval.kind} />
    {/if}
    <div class="progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow={progressPercent} aria-label={$text('plan_embeds.section.tasks')}>
      <span class="bar" style:width="{progressPercent}%"></span>
    </div>
  </div>
  <div class="facts">
    <span data-testid="plan-embed-progress">{$text('plan_embeds.summary.tasks', { values: { done: progress.done, total: progress.total } })}</span>
    <span data-testid="plan-embed-checks">{$text('plan_embeds.summary.checks', { values: { green: checks.requiredGreen, required: checks.required } })}</span>
    {#if checks.waiting > 0}<span class="attention" data-testid="plan-embed-waiting">{$text('plan_embeds.summary.waiting', { values: { count: checks.waiting } })}</span>{/if}
    {#if openAssumptions > 0}<span data-testid="plan-embed-assumptions">{$text('plan_embeds.summary.assumptions_open', { values: { count: openAssumptions } })}</span>{/if}
  </div>
</article>
  {/snippet}
</UnifiedEmbedPreview>

<style>
  .plan-embed { display: grid; align-content: start; gap: var(--spacing-3); width: 100%; height: 100%; box-sizing: border-box; padding: var(--spacing-2) var(--spacing-6) 0; overflow: hidden; color: var(--color-font-primary); text-align: left; }
  .head { display: flex; align-items: center; gap: var(--spacing-3); min-width: 0; }
  .title { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .approval-row { display: flex; align-items: center; gap: var(--spacing-3); min-width: 0; }
  .progress { flex: 1; min-width: 32px; height: 6px; border-radius: 999px; background: var(--color-grey-20); overflow: hidden; }
  .bar { display: block; height: 100%; background: var(--color-button-primary); }
  .facts { display: flex; flex-direction: column; font-size: var(--font-size-small, 0.875rem); line-height: 1.25; color: var(--color-font-secondary); }
  .facts span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .attention { color: var(--color-warning, var(--color-font-primary)); font-weight: 600; }
</style>
