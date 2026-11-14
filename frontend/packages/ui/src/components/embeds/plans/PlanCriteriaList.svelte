<!--
  PlanCriteriaList.svelte
  Success criteria with the Checks that cover each one.
-->
<script lang="ts">
  import { text } from '@repo/ui';
  import { checkLabel, checksCoveringCriterion } from './planEmbedModel';
  import type { UserPlanCriterionViewModel, UserPlanVerificationViewModel } from '../../../services/userPlanService';
  import './PlanSectionStyles.css';

  let { criteria, checks }: {
    criteria: UserPlanCriterionViewModel[];
    checks: UserPlanVerificationViewModel[];
  } = $props();
</script>

<section class="plan-section" data-testid="plan-criteria-list">
  <div class="plan-section-heading"><p>{$text('plan_embeds.section.criteria')}</p><span class="plan-section-count">{criteria.length}</span></div>
  {#if criteria.length === 0}
    <p class="plan-empty">{$text('plan_embeds.empty.criteria')}</p>
  {:else}
    <ul class="plan-rows">
      {#each criteria as criterion (criterion.criterionId)}
        {@const covering = checksCoveringCriterion(criterion, checks)}
        <li class="plan-row" data-testid="plan-criterion-row" data-covered={covering.length > 0}>
          <div class="plan-row-main">
            <strong>{criterion.text || criterion.criterionId}</strong>
            {#if covering.length > 0}
              <small data-testid="plan-criterion-covering">{covering.map(checkLabel).join(' · ')}</small>
            {:else}
              <small data-testid="plan-criterion-uncovered">{$text('plan_embeds.criterion.uncovered')}</small>
            {/if}
          </div>
          <small>{$text('plan_embeds.criterion.covered_by', { values: { count: covering.length } })}</small>
        </li>
      {/each}
    </ul>
  {/if}
</section>
