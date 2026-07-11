<!--
  Plans route for the authenticated web app.
  Reuses the encrypted TasksPage workspace because Plans V1 keeps plans and
  verification tasks together while giving the header switcher a first-class
  Plans destination. The route shell mirrors Tasks so sidebar/settings behavior
  stays consistent across workspace sections.
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import { page } from '$app/state';
  import {
    Header,
    Notification,
    Settings,
    TasksPage,
    PlanDetailPage,
    authStore,
    featureAvailabilityStore,
    initialize,
    initializeFeatureAvailability,
    notificationStore,
    panelState,
  } from '@repo/ui';
  import { isWorkspaceFeatureAvailable } from '@repo/ui/config/workspaceFeatureGates';

  let featureAvailabilityLoaded = $derived($featureAvailabilityStore.initialized);
  let plansEnabled = $derived(isWorkspaceFeatureAvailable('platform:plans', $featureAvailabilityStore.disabledById));
  let routePlanId = $derived(page.params.plan_id ?? null);

  onMount(() => {
    initialize().catch((error) => {
      console.error('[PlansRoute] Failed to initialize auth:', error);
    });

    initializeFeatureAvailability().catch((error: unknown) => {
      console.warn('[PlansRoute] Failed to load feature availability:', error);
    });
  });
</script>

{#if !$authStore.isInitialized || !featureAvailabilityLoaded}
  <main class="plans-route-state" data-testid="plans-auth-loading">Loading plans...</main>
{:else if !plansEnabled}
  <Header context="webapp" isLoggedIn={$authStore.isAuthenticated} />
  <main class="plans-route-state" data-testid="plans-feature-disabled">
    <h1>Plans unavailable</h1>
    <p>Plans are disabled on this server.</p>
  </main>
{:else if $authStore.isAuthenticated}
  <div class="main-content" class:menu-closed={!$panelState.isActivityHistoryOpen}>
    <Header context="webapp" isLoggedIn={$authStore.isAuthenticated} />
    <div class="plans-container" class:menu-open={$panelState.isSettingsOpen}>
      <div class="plans-wrapper" id="main-plans" tabindex="-1">
        {#if routePlanId}<PlanDetailPage planId={routePlanId} />{:else}<TasksPage focus="plans" />{/if}
      </div>
      <div class="settings-wrapper">
        <Settings isLoggedIn={$authStore.isAuthenticated} />
      </div>
    </div>
  </div>
{:else}
  <Header context="webapp" isLoggedIn={$authStore.isAuthenticated} />
  <main class="plans-route-state" data-testid="plans-auth-required">
    <h1>Plans</h1>
    <p>Please log in to coordinate private plans for yourself and your AI mates.</p>
  </main>
{/if}

<div class="notification-container">
  {#each $notificationStore.notifications as notification (notification.id)}
    <Notification {notification} />
  {/each}
</div>

<style>
  .plans-route-state {
    min-height: calc(100vh - 90px);
    display: grid;
    place-content: center;
    gap: var(--spacing-8, 16px);
    padding: var(--spacing-20, 40px);
    text-align: center;
    color: var(--color-font-primary);
  }

  .main-content {
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

  .plans-container {
    display: flex;
    flex-direction: row;
    height: calc(100vh - 82px);
    height: calc(100dvh - 82px);
    gap: 0;
    padding: 10px 20px 10px 10px;
  }

  @media (min-width: 1100px) {
    .plans-container.menu-open {
      gap: 20px;
    }
  }

  .plans-wrapper {
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

    .plans-container {
      height: calc(100vh - 75px);
      height: calc(100dvh - 75px);
      padding-inline-end: 10px;
    }
  }

  .plans-route-state h1 {
    margin: 0;
    font-size: 2rem;
  }

  .plans-route-state p {
    margin: 0;
    color: var(--color-font-secondary);
  }

  .notification-container {
    position: fixed;
    top: 20px;
    right: 20px;
    z-index: 2000;
  }
</style>
