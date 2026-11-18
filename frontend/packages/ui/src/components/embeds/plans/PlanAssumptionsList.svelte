<!--
  PlanAssumptionsList.svelte
  Read-only assumptions with status chip and a link to the checking chat.
-->
<script lang="ts">
  import { text } from '@repo/ui';
  import PlanStatusChip from './PlanStatusChip.svelte';
  import { assumptionStatusTone } from './planEmbedModel';
  import type { UserPlanAssumptionViewModel } from '../../../services/userPlanService';
  import './PlanSectionStyles.css';

  let { assumptions, onOpenChat }: {
    assumptions: UserPlanAssumptionViewModel[];
    onOpenChat?: (chatId: string) => void;
  } = $props();
</script>

<section class="plan-section" data-testid="plan-assumptions-list">
  <div class="plan-section-heading"><p>{$text('plan_embeds.section.assumptions')}</p><span class="plan-section-count">{assumptions.length}</span></div>
  {#if assumptions.length === 0}
    <p class="plan-empty">{$text('plan_embeds.empty.assumptions')}</p>
  {:else}
    <ul class="plan-rows">
      {#each assumptions as assumption (assumption.assumptionId)}
        <li class="plan-row" data-testid="plan-assumption-row" data-status={assumption.status}>
          <div class="plan-row-main">
            <strong>{assumption.correctedText || assumption.text}</strong>
            {#if assumption.evidenceSummary}<small>{assumption.evidenceSummary}</small>{/if}
            {#if assumption.linkedSubChatId}
              {@const chatId = assumption.linkedSubChatId}
              <button type="button" class="plan-link" data-testid="plan-assumption-open-chat" onclick={() => onOpenChat?.(chatId)}>{$text('plan_embeds.assumption.open_chat')}</button>
            {/if}
          </div>
          <PlanStatusChip label={$text(`plan_embeds.status.assumption.${assumption.status}`)} tone={assumptionStatusTone(assumption.status)} testId="plan-assumption-status" status={assumption.status} />
        </li>
      {/each}
    </ul>
  {/if}
</section>
