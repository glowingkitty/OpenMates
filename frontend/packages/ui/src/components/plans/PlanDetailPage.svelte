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
  import {
    addPlanVerificationEvidence,
    createPlanAssumption,
    createPlanCriterion,
    createPlanVerification,
    loadUserPlanDetailState,
    updatePlanAssumption,
    updatePlanCriterion,
    type UserPlanAssumptionViewModel,
    type UserPlanCriterionViewModel,
    type UserPlanDetailState,
    type UserPlanVerificationViewModel,
    type UserPlanViewModel,
  } from '../../services/userPlanService';
  import { text } from '@repo/ui';

  let { planId }: { planId: string } = $props();
  let plan = $state<UserPlanViewModel | null>(null);
  let detailState = $state<UserPlanDetailState>({ criteria: [], verifications: [], assumptions: [], referencePatterns: [] });
  let hasError = $state(false);
  let detailError = $state(false);
  let isDetailLoading = $state(false);
  let isSaving = $state(false);
  let assumptionText = $state('');
  let criterionText = $state('');
  let checkTitle = $state('');
  let checkCommand = $state('');
  let evidenceSummary = $state('');
  let selectedVerificationId = $state('');
  let domainLabel = $derived($text('navigation.plans'));
  let unresolvedAssumptions = $derived(detailState.assumptions.filter((item) => !['confirmed', 'waived'].includes(item.status)).length);
  let uncoveredCriteria = $derived(detailState.criteria.filter((item) => item.required && item.coverageStatus !== 'covered' && item.verificationIds.length === 0).length);
  let failedChecks = $derived(detailState.verifications.filter((item) => item.status === 'failed').length);
  onMount(() => { void load(); });
  async function load(): Promise<void> {
    hasError = false;
    try {
      plan = await planDetailAdapter.load(planId);
      await loadDetailState();
    } catch (value) {
      hasError = true;
      console.error('[PlanDetailPage] Failed to load plan:', value);
    }
  }

  async function loadDetailState(): Promise<void> {
    if (!plan) return;
    isDetailLoading = true;
    detailError = false;
    try {
      detailState = await loadUserPlanDetailState(plan);
      if (!selectedVerificationId && detailState.verifications.length > 0) {
        selectedVerificationId = detailState.verifications[0].verificationId;
      }
    } catch (value) {
      detailError = true;
      console.error('[PlanDetailPage] Failed to load plan detail state:', value);
    } finally {
      isDetailLoading = false;
    }
  }

  async function saveTitle(title: string): Promise<void> { if (plan) plan = await planDetailAdapter.saveTitle(plan, title); }
  async function saveDescription(summary: string): Promise<void> { if (plan) plan = await planDetailAdapter.saveDescription(plan, summary); }

  async function handleAddAssumption(): Promise<void> {
    if (!plan || !assumptionText.trim() || isSaving) return;
    isSaving = true;
    try {
      const assumption = await createPlanAssumption(plan, { text: assumptionText.trim(), requiredBefore: 'implementation' });
      detailState = { ...detailState, assumptions: [...detailState.assumptions, assumption] };
      assumptionText = '';
    } finally {
      isSaving = false;
    }
  }

  async function handleConfirmAssumption(assumption: UserPlanAssumptionViewModel): Promise<void> {
    if (!plan || isSaving) return;
    isSaving = true;
    try {
      const updated = await updatePlanAssumption(plan, assumption.assumptionId, { status: 'confirmed', evidenceSummary: 'Confirmed from plan review.' });
      detailState = { ...detailState, assumptions: detailState.assumptions.map((item) => item.assumptionId === updated.assumptionId ? updated : item) };
    } finally {
      isSaving = false;
    }
  }

  async function handleAddCriterion(): Promise<void> {
    if (!plan || !criterionText.trim() || isSaving) return;
    isSaving = true;
    try {
      const criterion = await createPlanCriterion(plan, { text: criterionText.trim(), type: 'acceptance', required: true });
      detailState = { ...detailState, criteria: [...detailState.criteria, criterion] };
      criterionText = '';
    } finally {
      isSaving = false;
    }
  }

  async function handleAddVerification(): Promise<void> {
    if (!plan || !checkTitle.trim() || isSaving) return;
    isSaving = true;
    try {
      const covers = detailState.criteria.map((criterion) => criterion.criterionId);
      const verification = await createPlanVerification(plan, {
        kind: checkCommand.trim() ? 'command' : 'manual',
        title: checkTitle.trim(),
        command: checkCommand.trim(),
        covers,
        requiredForDone: true,
      });
      const criteria = await Promise.all(detailState.criteria.map((criterion) => updatePlanCriterion(plan, criterion.criterionId, {
        verificationIds: [...new Set([...criterion.verificationIds, verification.verificationId])],
        coverageStatus: 'covered',
        verificationScope: checkTitle.trim(),
      })));
      detailState = {
        ...detailState,
        verifications: [...detailState.verifications, verification],
        criteria,
      };
      selectedVerificationId = verification.verificationId;
      checkTitle = '';
      checkCommand = '';
    } finally {
      isSaving = false;
    }
  }

  async function handleAddEvidence(): Promise<void> {
    if (!plan || !selectedVerificationId || !evidenceSummary.trim() || isSaving) return;
    isSaving = true;
    try {
      const updated = await addPlanVerificationEvidence(plan, selectedVerificationId, {
        status: 'passed',
        resultSummary: evidenceSummary.trim(),
      });
      detailState = { ...detailState, verifications: detailState.verifications.map((item) => item.verificationId === updated.verificationId ? updated : item) };
      evidenceSummary = '';
    } finally {
      isSaving = false;
    }
  }

  function verificationLabel(verification: UserPlanVerificationViewModel): string {
    return verification.description || verification.command || verification.kind;
  }

  function criterionLabel(criterion: UserPlanCriterionViewModel): string {
    return criterion.text || criterion.criterionId;
  }
</script>

<section class="detail-page" data-testid="plan-detail-page">
  <nav><a href="/plans">{domainLabel}</a><WorkspaceReportIssueButton /></nav>
  {#if plan}
    <WorkspaceDetailHeader title={plan.title || $text('common.detail_untitled', { values: { item: domainLabel } })} description={plan.summary || plan.goal || ''} category="productivity" icon="list-checks" writable={true} onSaveTitle={saveTitle} onSaveDescription={saveDescription} />
    <div class="plan-body">
      <section class="plan-overview" data-testid="plan-detail-overview">
        <article data-testid="plan-assumption-summary"><strong>{unresolvedAssumptions}</strong><span>open assumptions</span></article>
        <article data-testid="plan-criteria-summary"><strong>{uncoveredCriteria}</strong><span>uncovered criteria</span></article>
        <article data-testid="plan-check-summary"><strong>{failedChecks}</strong><span>failed checks</span></article>
      </section>

      {#if detailError}
        <div class="state" role="alert" data-testid="plan-detail-state-error"><p>Plan details could not be loaded.</p><button type="button" onclick={() => void loadDetailState()}>Retry</button></div>
      {:else if isDetailLoading}
        <div class="state" data-testid="plan-detail-state-loading">Loading plan details...</div>
      {:else}
        <section class="plan-section" data-testid="plan-assumptions-section">
          <div class="section-heading"><p>Assumptions</p><span>{detailState.assumptions.length}</span></div>
          <form class="inline-form" onsubmit={(event) => { event.preventDefault(); void handleAddAssumption(); }}>
            <input bind:value={assumptionText} placeholder="Add an assumption to verify before implementation" data-testid="plan-assumption-input" />
            <button type="submit" disabled={isSaving || !assumptionText.trim()} data-testid="plan-assumption-add-button">Add assumption</button>
          </form>
          <div class="item-list">
            {#each detailState.assumptions as assumption (assumption.assumptionId)}
              <article class="detail-item" data-testid="plan-assumption-item" data-plan-assumption-status={assumption.status}>
                <div><strong>{assumption.text}</strong><span>{assumption.status.replaceAll('_', ' ')} before {assumption.requiredBefore}</span>{#if assumption.evidenceSummary}<small>{assumption.evidenceSummary}</small>{/if}</div>
                {#if assumption.status !== 'confirmed'}<button type="button" disabled={isSaving} onclick={() => void handleConfirmAssumption(assumption)} data-testid="plan-assumption-confirm-button">Confirm</button>{/if}
              </article>
            {/each}
          </div>
        </section>

        <section class="plan-section" data-testid="plan-criteria-section">
          <div class="section-heading"><p>Acceptance Criteria</p><span>{detailState.criteria.length}</span></div>
          <form class="inline-form" onsubmit={(event) => { event.preventDefault(); void handleAddCriterion(); }}>
            <input bind:value={criterionText} placeholder="Add a required acceptance criterion" data-testid="plan-criterion-input" />
            <button type="submit" disabled={isSaving || !criterionText.trim()} data-testid="plan-criterion-add-button">Add criterion</button>
          </form>
          <div class="item-list">
            {#each detailState.criteria as criterion (criterion.criterionId)}
              <article class="detail-item" data-testid="plan-criterion-item" data-plan-criterion-status={criterion.status} data-plan-coverage-status={criterion.coverageStatus}>
                <div><strong>{criterionLabel(criterion)}</strong><span>{criterion.coverageStatus || 'uncovered'} · {criterion.verificationIds.length} checks</span>{#if criterion.evidence}<small>{criterion.evidence}</small>{/if}</div>
              </article>
            {/each}
          </div>
        </section>

        <section class="plan-section" data-testid="plan-checks-section">
          <div class="section-heading"><p>Checks</p><span>{detailState.verifications.length}</span></div>
          <form class="inline-form" onsubmit={(event) => { event.preventDefault(); void handleAddVerification(); }}>
            <input bind:value={checkTitle} placeholder="Check description" data-testid="plan-check-title-input" />
            <input bind:value={checkCommand} placeholder="Optional command" data-testid="plan-check-command-input" />
            <button type="submit" disabled={isSaving || !checkTitle.trim()} data-testid="plan-check-add-button">Add check</button>
          </form>
          <div class="item-list">
            {#each detailState.verifications as verification (verification.verificationId)}
              <article class="detail-item" data-testid="plan-check-item" data-plan-check-status={verification.status}>
                <div><strong>{verificationLabel(verification)}</strong><span>{verification.status} · covers {verification.covers.length} criteria</span>{#if verification.resultSummary}<small>{verification.resultSummary}</small>{/if}</div>
              </article>
            {/each}
          </div>
          {#if detailState.verifications.length > 0}
            <form class="inline-form evidence-form" onsubmit={(event) => { event.preventDefault(); void handleAddEvidence(); }}>
              <select bind:value={selectedVerificationId} data-testid="plan-evidence-check-select">
                {#each detailState.verifications as verification (verification.verificationId)}
                  <option value={verification.verificationId}>{verificationLabel(verification)}</option>
                {/each}
              </select>
              <input bind:value={evidenceSummary} placeholder="Evidence summary" data-testid="plan-evidence-summary-input" />
              <button type="submit" disabled={isSaving || !evidenceSummary.trim()} data-testid="plan-evidence-add-button">Mark passed</button>
            </form>
          {/if}
        </section>

        <section class="plan-section" data-testid="plan-reference-patterns-section">
          <div class="section-heading"><p>Reference Patterns</p><span>{detailState.referencePatterns.length}</span></div>
          <div class="item-list">
            {#each detailState.referencePatterns as pattern (pattern.patternId)}
              <article class="detail-item" data-testid="plan-reference-pattern-item" data-plan-reference-pattern-status={pattern.status}>
                <div><strong>{pattern.title}</strong><span>{pattern.status} · {pattern.sourceCount} sources</span>{#if pattern.evidenceSummary}<small>{pattern.evidenceSummary}</small>{/if}</div>
              </article>
            {/each}
          </div>
        </section>
      {/if}
    </div>
  {:else if hasError}<div class="state" role="alert"><p>{$text('common.detail_load_error', { values: { item: domainLabel } })}</p><button type="button" onclick={() => void load()}>{$text('common.retry')}</button></div>
  {:else}<div class="state">{$text('common.detail_loading', { values: { item: domainLabel } })}</div>{/if}
</section>

<style>
  .detail-page { width: 100%; height: 100%; overflow: auto; background: var(--color-grey-0); color: var(--color-font-primary); }
  nav { display: flex; align-items: center; justify-content: space-between; padding: var(--spacing-5) var(--spacing-8); }
  nav a { color: var(--color-font-primary); }
  .state { display: grid; min-height: 240px; place-content: center; gap: var(--spacing-5); text-align: center; }
  .plan-body { display: grid; gap: 16px; padding: 0 var(--spacing-8) var(--spacing-8); }
  .plan-overview { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }
  .plan-overview article,
  .plan-section { border: 1px solid var(--color-grey-20); border-radius: 24px; background: var(--color-grey-0); box-shadow: 0 8px 24px rgba(0, 0, 0, 0.06); }
  .plan-overview article { display: flex; flex-direction: column; gap: 4px; padding: 16px; }
  .plan-overview strong { font-size: 2rem; line-height: 1; }
  .plan-overview span,
  .section-heading span,
  .detail-item span,
  .detail-item small { color: var(--color-font-secondary); }
  .plan-section { display: grid; gap: 12px; padding: 16px; }
  .section-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
  .section-heading p { margin: 0; font-weight: 700; }
  .section-heading span { display: grid; min-width: 28px; height: 28px; place-items: center; border-radius: 999px; background: var(--color-grey-10); font-size: 0.8rem; }
  .inline-form { display: grid; grid-template-columns: minmax(180px, 1fr) auto; gap: 10px; }
  .inline-form:has(input + input) { grid-template-columns: minmax(160px, 1fr) minmax(160px, 1fr) auto; }
  .item-list { display: grid; gap: 8px; }
  .detail-item { display: flex; align-items: center; justify-content: space-between; gap: 12px; border-radius: 18px; padding: 12px; background: var(--color-grey-10); }
  .detail-item div { display: grid; gap: 4px; min-width: 0; }
  input,
  select { min-width: 0; border: 1px solid var(--color-grey-30); border-radius: 999px; background: var(--color-grey-0); color: var(--color-font-primary); padding: 11px 13px; font: inherit; }
  button { border: 0; border-radius: 999px; background: var(--color-button-primary); color: var(--color-font-button); padding: 11px 16px; font: inherit; cursor: pointer; }
  button:disabled { opacity: 0.55; cursor: not-allowed; }
  @media (max-width: 760px) { .inline-form, .inline-form:has(input + input), .evidence-form { grid-template-columns: 1fr; } .detail-item { align-items: stretch; flex-direction: column; } }
</style>
