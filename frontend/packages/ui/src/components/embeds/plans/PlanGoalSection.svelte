<!--
  PlanGoalSection.svelte
  Goal section shared by the Plan fullscreen embed and the Plan detail page.
-->
<script lang="ts">
  import { text } from '@repo/ui';
  import './PlanSectionStyles.css';

  let { goal }: { goal: string } = $props();
</script>

<section class="plan-section" data-testid="plan-goal-section">
  <div class="plan-section-heading"><p>{$text('plan_embeds.section.goal')}</p></div>
  {#if goal}
    <p class="goal-text" data-testid="plan-goal-text">{goal}</p>
  {:else}
    <p class="plan-empty">{$text('plan_embeds.empty.goal')}</p>
  {/if}
</section>

<style>
  .goal-text { margin: 0; color: var(--color-font-primary); white-space: pre-wrap; }
</style>
