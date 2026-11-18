<!--
  PlanEmbedFullscreen.svelte
  Fullscreen Plan view: goal, assumptions (with checking chat), success
  criteria (with covering Checks), linked Tasks, Checks and the approval bar.
  Props-driven; all actions are callbacks the parent wires.
-->
<script lang="ts">
  import { text } from '@repo/ui';
  import PlanStatusChip from './PlanStatusChip.svelte';
  import PlanGoalSection from './PlanGoalSection.svelte';
  import PlanAssumptionsList from './PlanAssumptionsList.svelte';
  import PlanCriteriaList from './PlanCriteriaList.svelte';
  import PlanTasksList from './PlanTasksList.svelte';
  import PlanChecksList from './PlanChecksList.svelte';
  import PlanApprovalBar from './PlanApprovalBar.svelte';
  import { derivePlanApproval, planStatusTone, type PlanEmbedData } from './planEmbedModel';

  let { data, approving = false, onApproveRevision, onOpenChat, onOpenTask, onOpenCheck }: {
    data: PlanEmbedData;
    approving?: boolean;
    onApproveRevision?: (revisionId: string) => void;
    onOpenChat?: (chatId: string) => void;
    onOpenTask?: (taskId: string) => void;
    onOpenCheck?: (checkId: string) => void;
  } = $props();
  let approval = $derived(derivePlanApproval(data));
</script>

<article class="plan-fullscreen" data-testid="plan-embed-fullscreen" aria-label={$text('plan_embeds.plan.fullscreen_label')}>
  <header class="plan-header">
    <h1 data-testid="plan-fullscreen-title">{data.plan.title}</h1>
    <PlanStatusChip label={$text(`plan_embeds.status.plan.${data.plan.status}`)} tone={planStatusTone(data.plan.status)} testId="plan-fullscreen-status" status={data.plan.status} />
  </header>
  <PlanApprovalBar {approval} busy={approving} {onApproveRevision} />
  <PlanGoalSection goal={data.plan.goal} />
  <PlanAssumptionsList assumptions={data.assumptions} {onOpenChat} />
  <PlanCriteriaList criteria={data.criteria} checks={data.checks} />
  <PlanTasksList tasks={data.tasks} {onOpenTask} />
  <PlanChecksList checks={data.checks} {onOpenCheck} />
</article>

<style>
  .plan-fullscreen { display: grid; gap: var(--spacing-8); width: 100%; max-width: 860px; margin: 0 auto; padding: var(--spacing-8); box-sizing: border-box; color: var(--color-font-primary); }
  .plan-header { display: flex; align-items: center; flex-wrap: wrap; gap: var(--spacing-5); }
  h1 { margin: 0; font-size: var(--font-size-h2, 1.5rem); }
</style>
