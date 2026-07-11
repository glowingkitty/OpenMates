<!--
  PlanDetailPage.svelte
  Canonical encrypted Plan detail surface for stable nested routes.
  Title and summary writes remain encrypted by userPlanService.
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import WorkspaceDetailHeader from '../workspace/WorkspaceDetailHeader.svelte';
  import WorkspaceReportIssueButton from '../workspace/WorkspaceReportIssueButton.svelte';
  import { planDetailAdapter } from '../workspace/detailMetadataAdapters';
  import type { UserPlanViewModel } from '../../services/userPlanService';
  import { text } from '@repo/ui';

  let { planId }: { planId: string } = $props();
  let plan = $state<UserPlanViewModel | null>(null);
  let hasError = $state(false);
  let domainLabel = $derived($text('navigation.plans'));
  onMount(() => { void load(); });
  async function load(): Promise<void> { hasError = false; try { plan = await planDetailAdapter.load(planId); } catch (value) { hasError = true; console.error('[PlanDetailPage] Failed to load plan:', value); } }
  async function saveTitle(title: string): Promise<void> { if (plan) plan = await planDetailAdapter.saveTitle(plan, title); }
  async function saveDescription(summary: string): Promise<void> { if (plan) plan = await planDetailAdapter.saveDescription(plan, summary); }
</script>

<section class="detail-page" data-testid="plan-detail-page">
  <nav><a href="/plans">{domainLabel}</a><WorkspaceReportIssueButton /></nav>
  {#if plan}
    <WorkspaceDetailHeader title={plan.title || $text('common.detail_untitled', { values: { item: domainLabel } })} description={plan.summary || plan.goal || ''} category="productivity" icon="list-checks" writable={true} onSaveTitle={saveTitle} onSaveDescription={saveDescription} />
  {:else if hasError}<div class="state" role="alert"><p>{$text('common.detail_load_error', { values: { item: domainLabel } })}</p><button type="button" onclick={() => void load()}>{$text('common.retry')}</button></div>
  {:else}<div class="state">{$text('common.detail_loading', { values: { item: domainLabel } })}</div>{/if}
</section>

<style>
  .detail-page { width: 100%; height: 100%; overflow: auto; background: var(--color-grey-0); color: var(--color-font-primary); }
  nav { display: flex; align-items: center; justify-content: space-between; padding: var(--spacing-5) var(--spacing-8); }
  nav a { color: var(--color-font-primary); }
  .state { display: grid; min-height: 240px; place-content: center; gap: var(--spacing-5); text-align: center; }
</style>
