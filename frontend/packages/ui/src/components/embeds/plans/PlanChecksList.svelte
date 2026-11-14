<!--
  PlanChecksList.svelte
  Checks with aggregate status (incl. waiting_for_confirmation and stale) and
  required/supporting role.
-->
<script lang="ts">
  import { text } from '@repo/ui';
  import PlanStatusChip from './PlanStatusChip.svelte';
  import { checkAggregateStatus, checkLabel, checkStatusTone } from './planEmbedModel';
  import type { UserPlanVerificationViewModel } from '../../../services/userPlanService';
  import './PlanSectionStyles.css';

  let { checks, onOpenCheck }: {
    checks: UserPlanVerificationViewModel[];
    onOpenCheck?: (checkId: string) => void;
  } = $props();
</script>

<section class="plan-section" data-testid="plan-checks-list">
  <div class="plan-section-heading"><p>{$text('plan_embeds.section.checks')}</p><span class="plan-section-count">{checks.length}</span></div>
  {#if checks.length === 0}
    <p class="plan-empty">{$text('plan_embeds.empty.checks')}</p>
  {:else}
    <ul class="plan-rows">
      {#each checks as check (check.verificationId)}
        {@const status = checkAggregateStatus(check)}
        <li class="plan-row" data-testid="plan-check-row" data-status={status} data-required={check.requiredForDone}>
          <div class="plan-row-main">
            <button type="button" class="plan-link" data-testid="plan-check-open" aria-label={$text('plan_embeds.check.open')} onclick={() => onOpenCheck?.(check.verificationId)}>{checkLabel(check)}</button>
            {#if check.resultSummary}<small>{check.resultSummary}</small>{/if}
          </div>
          <div class="plan-row-meta">
            <small data-testid="plan-check-role">{check.requiredForDone ? $text('plan_embeds.check.required') : $text('plan_embeds.check.supporting')}</small>
            <PlanStatusChip label={$text(`plan_embeds.status.check.${status}`)} tone={checkStatusTone(status)} testId="plan-check-status" status={status} />
          </div>
        </li>
      {/each}
    </ul>
  {/if}
</section>
