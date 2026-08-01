<!--
  PlansWorkspacePage.svelte
  Central /plans workspace. It composes the shared workspace home shell with a
  plan-specific encrypted board, keeping completed plans visible in Done and
  hiding archived plans from the default board.
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import PlanBoard from './PlanBoard.svelte';
  import WorkspaceHomeShell from '../workspace/WorkspaceHomeShell.svelte';
  import WorkspacePromptComposer from '../workspace/WorkspacePromptComposer.svelte';
  import { featureAvailabilityStore, initializeFeatureAvailability } from '../../stores/appSkillsStore';
  import { notificationStore } from '../../stores/notificationStore';
  import { userProfile } from '../../stores/userProfile';
  import type { DailyInspiration } from '../../stores/dailyInspirationStore';
  import {
    activateUserPlan,
    completeUserPlan,
    createUserPlan,
    listUserPlans,
    updateUserPlan,
    type UserPlanStatus,
    type UserPlanViewModel,
  } from '../../services/userPlanService';

  type PlanBoardColumn = 'backlog' | 'todo' | 'in_progress' | 'blocked' | 'done';
  type ArchiveConfirmation = {
    plan: UserPlanViewModel;
    previousStatus: UserPlanStatus;
    request: string;
  };

  let plans = $state<UserPlanViewModel[]>([]);
  let isLoading = $state(true);
  let hasLoadError = $state(false);
  let isSaving = $state(false);
  let actionId = $state<string | null>(null);
  let promptValue = $state('');
  let searchTerm = $state('');
  let pendingArchive = $state<ArchiveConfirmation | null>(null);
  let lastArchiveUndo = $state<ArchiveConfirmation | null>(null);

  let featureAvailabilityReady = $derived($featureAvailabilityStore.initialized && $featureAvailabilityStore.disabledById !== null);
  let plansEnabled = $derived(featureAvailabilityReady && $featureAvailabilityStore.disabledById?.['platform:plans'] !== true);
  let greetingName = $derived(formatGreetingName($userProfile.username));
  let visiblePlans = $derived(filterPlans(plans, searchTerm));
  let activePlanCount = $derived(plans.filter((plan) => !['archived', 'completed'].includes(plan.status)).length);
  let donePlanCount = $derived(plans.filter((plan) => plan.status === 'completed').length);
  let filterChips = $derived(resolveFilterChips(plans));

  function formatGreetingName(username: string): string {
    const trimmed = username.trim();
    if (!trimmed) return 'there';
    return trimmed.split(/\s+/)[0];
  }

  function broadcastPlansChanged(): void {
    if (typeof window === 'undefined') return;
    window.dispatchEvent(new CustomEvent('openmates-user-plans-changed'));
  }

  async function refreshPlans(): Promise<void> {
    if (!plansEnabled) {
      plans = [];
      isLoading = false;
      return;
    }
    isLoading = true;
    try {
      hasLoadError = false;
      plans = await listUserPlans({ limit: 100 });
    } catch (error) {
      hasLoadError = true;
      console.error('[PlansWorkspacePage] Failed to load plans:', error);
      notificationStore.error('Failed to load plans');
    } finally {
      isLoading = false;
    }
  }

  function resolveFilterChips(items: UserPlanViewModel[]): string[] {
    const statuses = Array.from(new Set(items.filter((plan) => plan.status !== 'archived').map((plan) => plan.status.replaceAll('_', '-')))).slice(0, 3);
    return statuses.length > 0 ? statuses : ['draft', 'active', 'blocked'];
  }

  function filterPlans(items: UserPlanViewModel[], query: string): UserPlanViewModel[] {
    const normalized = query.trim().replace(/^#/, '').toLowerCase();
    const defaultPlans = items.filter((plan) => plan.status !== 'archived');
    if (!normalized) return defaultPlans;
    return defaultPlans.filter((plan) => [
      plan.title,
      plan.summary,
      plan.goal,
      plan.status,
      plan.risks,
    ].some((value) => value.toLowerCase().replaceAll('_', '-').includes(normalized)));
  }

  function findPlanMention(request: string): UserPlanViewModel | null {
    const normalized = request.toLowerCase();
    const matches = plans
      .filter((plan) => plan.status !== 'archived' && plan.title.trim())
      .filter((plan) => normalized.includes(plan.title.toLowerCase()))
      .sort((a, b) => b.title.length - a.title.length);
    return matches[0] ?? null;
  }

  function parseTargetColumn(request: string): PlanBoardColumn | null {
    const normalized = request.toLowerCase();
    if (/\b(done|complete|completed)\b/.test(normalized)) return 'done';
    if (/\b(block|blocked)\b/.test(normalized)) return 'blocked';
    if (/\b(in progress|start|execute|executing|running checks?)\b/.test(normalized)) return 'in_progress';
    if (/\b(to do|todo|confirm|active|resume)\b/.test(normalized)) return 'todo';
    if (/\b(backlog|draft|later)\b/.test(normalized)) return 'backlog';
    return null;
  }

  function looksLikeManagementRequest(request: string): boolean {
    return /\b(rename|retitle|edit|update|move|mark|delete|remove|archive|complete|block|start|resume)\b/i.test(request);
  }

  function parseRenameTitle(request: string): string | null {
    if (!/\b(rename|retitle)\b/i.test(request)) return null;
    const index = request.toLowerCase().lastIndexOf(' to ');
    if (index === -1) return null;
    return request.slice(index + 4).trim() || null;
  }

  function parseSummaryUpdate(request: string): string | null {
    const match = request.match(/\bsummary\s+(?:to|as)\s+(.+)$/i);
    return match?.[1]?.trim() || null;
  }

  function handleStartInspiration(inspiration: DailyInspiration): void {
    promptValue = inspiration.phrase;
  }

  async function handlePromptSubmit(value: string): Promise<void> {
    if (!plansEnabled || isSaving) return;
    const mentionedPlan = findPlanMention(value);
    const normalized = value.toLowerCase();
    if (/\b(delete|remove|archive)\b/.test(normalized)) {
      if (!mentionedPlan) {
        notificationStore.error('Name the plan to archive first.');
        return;
      }
      pendingArchive = { plan: mentionedPlan, previousStatus: mentionedPlan.status, request: value };
      promptValue = '';
      return;
    }

    if (mentionedPlan) {
      const renamedTitle = parseRenameTitle(value);
      const summary = parseSummaryUpdate(value);
      const targetColumn = parseTargetColumn(value);
      if (renamedTitle) {
        await updatePlan(mentionedPlan, { title: renamedTitle }, 'Plan renamed');
        promptValue = '';
        return;
      }
      if (summary) {
        await updatePlan(mentionedPlan, { summary }, 'Plan summary updated');
        promptValue = '';
        return;
      }
      if (targetColumn) {
        await movePlan(mentionedPlan, targetColumn);
        promptValue = '';
        return;
      }
    }

    if (looksLikeManagementRequest(value)) {
      notificationStore.error('I could not find a matching plan. Include the exact plan title.');
      return;
    }

    await createPlanFromPrompt(value);
    promptValue = '';
  }

  async function createPlanFromPrompt(value: string): Promise<void> {
    isSaving = true;
    try {
      const plan = await createUserPlan({
        title: value,
        summary: value.split(/\s+/).length > 8 ? value : '',
        goal: value,
        status: 'draft',
      });
      plans = [plan, ...plans];
      broadcastPlansChanged();
      notificationStore.success('Plan created');
    } catch (error) {
      console.error('[PlansWorkspacePage] Failed to create plan:', error);
      notificationStore.error('Failed to create plan');
    } finally {
      isSaving = false;
    }
  }

  async function updatePlan(plan: UserPlanViewModel, patch: Parameters<typeof updateUserPlan>[1], successMessage: string): Promise<void> {
    actionId = plan.plan_id;
    try {
      const updated = await updateUserPlan(plan, patch);
      plans = plans.map((candidate) => candidate.plan_id === updated.plan_id ? updated : candidate);
      broadcastPlansChanged();
      notificationStore.success(successMessage);
    } catch (error) {
      console.error('[PlansWorkspacePage] Failed to update plan:', error);
      notificationStore.error('Failed to update plan');
    } finally {
      actionId = null;
    }
  }

  async function movePlan(plan: UserPlanViewModel, column: PlanBoardColumn): Promise<void> {
    actionId = plan.plan_id;
    const previous = plans;
    try {
      let updated: UserPlanViewModel;
      if (column === 'done') {
        updated = await completeUserPlan(plan);
      } else if (column === 'todo') {
        updated = plan.primaryChatId ? await activateUserPlan(plan) : await updateUserPlan(plan, { status: 'awaiting_confirmation' });
      } else if (column === 'in_progress') {
        if (!plan.primaryChatId) throw new Error('Starting a plan requires a linked chat.');
        updated = await updateUserPlan(plan, { status: 'executing' });
      } else if (column === 'blocked') {
        if (!plan.primaryChatId) throw new Error('Blocking a plan requires a linked chat.');
        updated = await updateUserPlan(plan, { status: 'blocked' });
      } else {
        updated = await updateUserPlan(plan, { status: 'draft' });
      }
      plans = plans.map((candidate) => candidate.plan_id === updated.plan_id ? updated : candidate);
      broadcastPlansChanged();
      notificationStore.success(column === 'done' ? 'Plan completed' : 'Plan updated');
    } catch (error) {
      plans = previous;
      console.error('[PlansWorkspacePage] Failed to move plan:', error);
      notificationStore.error(column === 'done' ? 'Plan still has blockers before completion' : error instanceof Error ? error.message : 'Failed to update plan');
    } finally {
      actionId = null;
    }
  }

  function requestArchive(plan: UserPlanViewModel): void {
    pendingArchive = { plan, previousStatus: plan.status, request: `Archive ${plan.title}` };
  }

  async function confirmArchive(): Promise<void> {
    if (!pendingArchive) return;
    const confirmation = pendingArchive;
    pendingArchive = null;
    actionId = confirmation.plan.plan_id;
    try {
      const updated = await updateUserPlan(confirmation.plan, { status: 'archived' });
      plans = plans.map((candidate) => candidate.plan_id === updated.plan_id ? updated : candidate);
      lastArchiveUndo = confirmation;
      broadcastPlansChanged();
      notificationStore.success('Plan archived');
    } catch (error) {
      console.error('[PlansWorkspacePage] Failed to archive plan:', error);
      notificationStore.error('Failed to archive plan');
    } finally {
      actionId = null;
    }
  }

  async function undoArchive(): Promise<void> {
    if (!lastArchiveUndo) return;
    const undo = lastArchiveUndo;
    const archivedPlan = plans.find((plan) => plan.plan_id === undo.plan.plan_id) ?? undo.plan;
    actionId = archivedPlan.plan_id;
    try {
      const restored = await updateUserPlan(archivedPlan, { status: undo.previousStatus });
      plans = plans.map((candidate) => candidate.plan_id === restored.plan_id ? restored : candidate);
      lastArchiveUndo = null;
      broadcastPlansChanged();
      notificationStore.success('Plan archive undone');
    } catch (error) {
      console.error('[PlansWorkspacePage] Failed to undo archive:', error);
      notificationStore.error('Failed to undo archive');
    } finally {
      actionId = null;
    }
  }

  onMount(() => {
    void initializeFeatureAvailability();
  });

  $effect(() => {
    void plansEnabled;
    if (!$featureAvailabilityStore.initialized) return;
    void refreshPlans();
  });
</script>

{#if !plansEnabled}
  <section class="plans-workspace-page" data-testid="plans-feature-disabled">
    <div class="plans-state">
      <h2>Plans unavailable</h2>
      <p>Plans are disabled on this server.</p>
    </div>
  </section>
{:else}
  <section class="plans-workspace-page" data-testid="plans-page">
    <div class="plans-shell-frame">
      <WorkspaceHomeShell
        surface="plans"
        testId="plans-workspace-home"
        centerTestId="plan-greeting"
        heading={`Hey ${greetingName}!`}
        subtitle="What is your next plan?"
        showReportIssue
        onStartInspiration={handleStartInspiration}
      >
        <svelte:fragment slot="composer">
          <WorkspacePromptComposer
            surface="plans"
            bind:value={promptValue}
            placeholder="Click to add or update plans"
            submitLabel="Send"
            submittingLabel="Saving..."
            disabled={!plansEnabled || isSaving}
            submitting={isSaving}
            testId="plan-workspace-composer"
            inputTestId="plan-workspace-input"
            submitTestId="plan-workspace-submit"
            micTestId="plan-workspace-mic"
            onSubmit={handlePromptSubmit}
            onMicClick={() => { notificationStore.error('Voice plan input is not available yet'); }}
          />
          {#if pendingArchive}
            <div class="workspace-confirmation" data-testid="plan-archive-confirmation">
              <span>Archive "{pendingArchive.plan.title}"? It will be hidden from the default board.</span>
              <button type="button" onclick={() => void confirmArchive()} data-testid="plan-archive-confirm">Archive</button>
              <button type="button" onclick={() => { pendingArchive = null; }} data-testid="plan-archive-cancel">Cancel</button>
            </div>
          {/if}
          {#if lastArchiveUndo}
            <div class="workspace-confirmation undo" data-testid="plan-archive-undo">
              <span>Archived "{lastArchiveUndo.plan.title}".</span>
              <button type="button" onclick={() => void undoArchive()} data-testid="plan-archive-undo-button">Undo</button>
            </div>
          {/if}
        </svelte:fragment>
      </WorkspaceHomeShell>
    </div>

    <section class="plans-board-panel" data-testid="plans-board-workspace" aria-label="Plans workspace board">
      <div class="plans-toolbar">
        <div class="plans-summary">
          <p class="eyebrow">Plans</p>
          <h1>Plan board</h1>
          <p>{plans.length} total, {activePlanCount} active, {donePlanCount} done</p>
        </div>
        <div class="plans-actions">
          <label class="plans-search-field" for="plans-search">
            <span class="search-icon" aria-hidden="true"></span>
            <input id="plans-search" bind:value={searchTerm} placeholder="Search" data-testid="plan-search-input" />
          </label>
          <div class="plans-filter-chips" aria-label="Plan filters">
            {#each filterChips as chip}
              <button type="button" class:active={searchTerm.replace(/^#/, '') === chip} onclick={() => { searchTerm = searchTerm.replace(/^#/, '') === chip ? '' : chip; }}>#{chip}</button>
            {/each}
          </div>
        </div>
      </div>

      {#if isLoading}
        <div class="plans-state" data-testid="plans-loading">Loading plans...</div>
      {:else if hasLoadError}
        <div class="plans-state" data-testid="plans-load-error">
          <p>Plans could not be loaded.</p>
          <button type="button" onclick={() => void refreshPlans()}>Retry</button>
        </div>
      {:else}
        <PlanBoard
          plans={visiblePlans}
          {actionId}
          onMove={(plan, column) => void movePlan(plan, column)}
          onArchive={requestArchive}
        />
        {#if visiblePlans.length === 0 && searchTerm.trim()}
          <div class="plans-filter-empty" data-testid="plans-filter-empty">No plans match that filter.</div>
        {:else if visiblePlans.length === 0}
          <div class="plans-filter-empty" data-testid="plans-empty">Click above to add your first plan.</div>
        {/if}
      {/if}
    </section>
  </section>
{/if}

<style>
  .plans-workspace-page {
    display: flex;
    width: 100%;
    min-width: 0;
    height: 100%;
    min-height: 0;
    flex-direction: column;
    gap: 18px;
    overflow: auto;
    color: var(--color-font-primary);
  }

  .plans-shell-frame {
    min-height: clamp(330px, 42vh, 470px);
    flex-shrink: 0;
    position: relative;
    overflow: hidden;
    border-radius: 17px;
    background: var(--color-grey-0);
  }

  .plans-shell-frame :global(.daily-inspiration-banner) {
    --daily-inspiration-regular-height: clamp(112px, 14vh, 135px);
    min-height: 0;
  }

  .plans-shell-frame :global(.workspace-center-content.center-content) {
    top: calc(50% + 8vh);
  }

  .plans-shell-frame :global(.workspace-composer-slot) {
    bottom: 10px;
  }

  .plans-board-panel {
    display: flex;
    min-height: 0;
    flex: 1;
    flex-direction: column;
    gap: 14px;
    padding: 0 2px 14px;
  }

  .plans-toolbar {
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: 16px;
  }

  .plans-summary h1,
  .plans-summary p {
    margin: 0;
  }

  .plans-summary h1 {
    font-size: clamp(1.5rem, 3vw, 2.2rem);
  }

  .plans-summary p:not(.eyebrow) {
    color: var(--color-font-secondary);
    font-size: var(--font-size-small);
  }

  .eyebrow {
    margin: 0 0 4px;
    color: var(--color-font-secondary);
    font-size: var(--font-size-xxs);
    font-weight: 800;
    letter-spacing: 0.12em;
    text-transform: uppercase;
  }

  .plans-actions,
  .plans-filter-chips {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: flex-end;
    gap: 8px;
  }

  .plans-search-field {
    display: flex;
    min-width: min(260px, 100%);
    align-items: center;
    gap: 8px;
    border: 1px solid var(--color-grey-20);
    border-radius: var(--radius-full);
    padding: 8px 12px;
    background: var(--color-grey-10);
  }

  .plans-search-field input {
    min-width: 0;
    flex: 1;
    border: 0;
    outline: 0;
    background: transparent;
    color: var(--color-font-primary);
    font: inherit;
  }

  .search-icon {
    width: 16px;
    height: 16px;
    flex: 0 0 auto;
    background: var(--color-font-secondary);
    -webkit-mask: url('@openmates/ui/static/icons/search.svg') center / contain no-repeat;
    mask: url('@openmates/ui/static/icons/search.svg') center / contain no-repeat;
  }

  .plans-filter-chips button,
  .workspace-confirmation button,
  .plans-state button {
    border: 0;
    border-radius: var(--radius-full);
    background: var(--color-grey-10);
    color: var(--color-font-primary);
    padding: 8px 12px;
    font: inherit;
    font-size: var(--font-size-xs);
    cursor: pointer;
  }

  .plans-filter-chips button.active,
  .workspace-confirmation button:first-of-type {
    background: var(--color-button-primary);
    color: var(--color-font-button);
  }

  .workspace-confirmation {
    display: flex;
    max-width: min(620px, calc(100vw - 40px));
    flex-wrap: wrap;
    align-items: center;
    justify-content: center;
    gap: 8px;
    border: 1px solid var(--color-grey-20);
    border-radius: 18px;
    padding: 10px 12px;
    background: color-mix(in srgb, var(--color-grey-0) 92%, transparent);
    box-shadow: 0 10px 24px rgba(0, 0, 0, 0.08);
    color: var(--color-font-primary);
    font-size: var(--font-size-small);
  }

  .workspace-confirmation.undo button:first-of-type {
    background: var(--color-grey-80);
    color: var(--color-grey-0);
  }

  .plans-state,
  .plans-filter-empty {
    border: 1px dashed var(--color-grey-30);
    border-radius: 24px;
    padding: 28px;
    color: var(--color-font-secondary);
    text-align: center;
  }

  @media (max-width: 760px) {
    .plans-shell-frame {
      min-height: 360px;
    }

    .plans-toolbar {
      align-items: stretch;
      flex-direction: column;
    }

    .plans-actions,
    .plans-filter-chips {
      justify-content: flex-start;
    }
  }
</style>
