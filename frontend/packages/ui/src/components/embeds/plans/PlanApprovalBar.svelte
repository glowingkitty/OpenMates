<!--
  PlanApprovalBar.svelte
  Shows the Plan revision number and approval state and approves the exact
  revision id shown. Disabled once that revision is approved.
-->
<script lang="ts">
  import { text } from '@repo/ui';
  import PlanStatusChip from './PlanStatusChip.svelte';
  import type { PlanApprovalSummary, PlanTone } from './planEmbedModel';

  let { approval, onApproveRevision, busy = false }: {
    approval: PlanApprovalSummary;
    onApproveRevision?: (revisionId: string) => void;
    busy?: boolean;
  } = $props();
  let stateLabel = $derived(approval.kind === 'approved'
    ? (approval.revisionNumber ? $text('plan_embeds.approval.approved', { values: { revision: approval.revisionNumber } }) : $text('plan_embeds.approval.approved_plain'))
    : $text(`plan_embeds.approval.${approval.kind}`));
  let tone = $derived<PlanTone>(approval.kind === 'approved' ? 'success' : approval.kind === 'changed' ? 'warning' : 'neutral');
</script>

<section class="approval-bar" data-testid="plan-approval-bar" data-approval-state={approval.kind} data-revision-id={approval.revisionId ?? ''}>
  <div class="approval-state">
    {#if approval.revisionNumber}
      <strong data-testid="plan-approval-revision">{$text('plan_embeds.approval.revision', { values: { revision: approval.revisionNumber } })}</strong>
    {:else if !approval.revisionId}
      <span data-testid="plan-approval-no-revision">{$text('plan_embeds.approval.no_revision')}</span>
    {/if}
    <PlanStatusChip label={stateLabel} {tone} testId="plan-approval-state" status={approval.kind} />
  </div>
  <button type="button" class="approve-button" data-testid="plan-approve-button" disabled={!approval.canApprove || busy}
    onclick={() => { if (approval.revisionId) onApproveRevision?.(approval.revisionId); }}>
    {approval.kind === 'approved' ? $text('plan_embeds.approval.already') : $text('plan_embeds.approval.approve')}
  </button>
</section>

<style>
  .approval-bar { display: flex; align-items: center; justify-content: space-between; gap: var(--spacing-5); padding: var(--spacing-6) var(--spacing-8); border: 1px solid var(--color-grey-20); border-radius: var(--radius-5, 24px); background: var(--color-grey-0); color: var(--color-font-primary); }
  .approval-state { display: flex; align-items: center; flex-wrap: wrap; gap: var(--spacing-4); }
  .approve-button { border: 0; border-radius: 999px; background: var(--color-button-primary); color: var(--color-font-button); padding: 11px 16px; font: inherit; cursor: pointer; }
  .approve-button:disabled { opacity: 0.55; cursor: not-allowed; }
  @media (max-width: 760px) { .approval-bar { flex-direction: column; align-items: stretch; } }
</style>
