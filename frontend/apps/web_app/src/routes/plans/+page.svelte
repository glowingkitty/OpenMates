<!--
  Plan detail route for root hashes and legacy /plans/:plan_id paths.
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { page } from '$app/state';
  import {
    Header,
    NotificationStack,
    Settings,
    PlanDetailPage,
    authStore,
    featureAvailabilityStore,
    initialize,
    initializeFeatureAvailability,
    panelState,
  } from '@repo/ui';
  import { isWorkspaceFeatureAvailable } from '@repo/ui/config/workspaceFeatureGates';

  let { planId = null }: { planId?: string | null } = $props();
  let featureAvailabilityLoaded = $derived($featureAvailabilityStore.initialized);
  let plansEnabled = $derived(
    isWorkspaceFeatureAvailable('platform:plans', $featureAvailabilityStore.disabledById),
  );
  let routePlanId = $derived(planId ?? page.params.plan_id ?? null);

  onMount(() => {
    if (page.url.pathname.startsWith('/plans')) {
      const legacyHashPlanId = new URLSearchParams(page.url.hash.replace(/^#\/?/, '')).get(
        'plan-id',
      );
      const legacyPlanId = page.params.plan_id ?? legacyHashPlanId;
      const target = legacyPlanId
        ? `/#plan-id=${encodeURIComponent(legacyPlanId)}`
        : '/#tasks';
      void goto(target, { replaceState: true });
      return;
    }

    initialize().catch((error) => {
      console.error('[PlanDetailRoute] Failed to initialize auth:', error);
    });

    initializeFeatureAvailability().catch((error: unknown) => {
      console.warn('[PlanDetailRoute] Failed to load feature availability:', error);
    });
  });
</script>

{#if !$authStore.isInitialized || !featureAvailabilityLoaded}
  <main class="plan-detail-route-state" data-testid="plan-detail-auth-loading">Loading plan...</main>
{:else if !plansEnabled}
  <Header context="webapp" isLoggedIn={$authStore.isAuthenticated} />
  <main class="plan-detail-route-state" data-testid="plan-detail-feature-disabled">
    <h1>Plan unavailable</h1>
    <p>Plans are disabled on this server.</p>
  </main>
{:else if $authStore.isAuthenticated}
  <div class="main-content" class:menu-closed={!$panelState.isActivityHistoryOpen}>
    <Header context="webapp" isLoggedIn={$authStore.isAuthenticated} />
    <div class="plan-detail-container" class:menu-open={$panelState.isSettingsOpen}>
      <div class="plan-detail-wrapper" id="main-plan-detail" tabindex="-1">
        {#if routePlanId}<PlanDetailPage planId={routePlanId} />{/if}
      </div>
      <div class="settings-wrapper">
        <Settings isLoggedIn={$authStore.isAuthenticated} />
      </div>
    </div>
  </div>
{:else}
  <Header context="webapp" isLoggedIn={$authStore.isAuthenticated} />
  <main class="plan-detail-route-state" data-testid="plan-detail-auth-required">
    <h1>Plan</h1>
    <p>Please log in to view this private plan.</p>
  </main>
{/if}

<NotificationStack />

<style>
  .plan-detail-route-state {
    min-height: calc(100vh - 90px);
    display: grid;
    place-content: center;
    gap: var(--spacing-8, 16px);
    padding: var(--spacing-20, 40px);
    text-align: center;
    color: var(--color-font-primary);
  }

  .main-content {
    container: main-content / inline-size;
    position: fixed;
    inset-inline-start: calc(var(--sidebar-width, 325px) + var(--sidebar-margin, 10px));
    inset-inline-end: 0;
    top: 0;
    bottom: 0;
    background: var(--color-grey-0);
    z-index: 10;
    transition:
      inset-inline-start 0.3s ease,
      transform 0.3s ease;
  }

  .main-content.menu-closed {
    inset-inline-start: var(--sidebar-margin, 10px);
  }

  .plan-detail-container {
    display: flex;
    flex-direction: row;
    height: calc(100vh - 82px);
    height: calc(100dvh - 82px);
    gap: 0;
    padding: 10px 20px 10px 10px;
  }

  @media (min-width: 1100px) {
    .plan-detail-container.menu-open {
      gap: 20px;
    }
  }

  .plan-detail-wrapper {
    flex: 1;
    display: flex;
    min-width: 0;
  }

  .settings-wrapper {
    display: flex;
    align-items: flex-start;
    min-width: fit-content;
  }

  @media (max-width: 600px) {
    .main-content {
      inset-inline-start: 0;
      inset-inline-end: 0;
      z-index: 20;
    }

    .main-content.menu-closed {
      inset-inline-start: 0;
    }

    .plan-detail-container {
      height: calc(100vh - 66px);
      height: calc(100dvh - 66px);
      padding-inline-end: 10px;
      box-sizing: border-box;
    }
  }

  .plan-detail-route-state h1 {
    margin: 0;
    font-size: 2rem;
  }

  .plan-detail-route-state p {
    margin: 0;
    color: var(--color-font-secondary);
  }

</style>
