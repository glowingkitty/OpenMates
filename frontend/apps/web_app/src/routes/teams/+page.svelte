<!--
  Teams route for the authenticated web app.
  Renders the Teams V1 workspace while preserving the same authenticated route
  shell, workspace header, settings side panel, and notifications used by Tasks
  and Plans. Feature availability plus the release gate both guard this route.
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import {
    Header,
    Notification,
    Settings,
    TeamsWorkspacePage,
    authStore,
    featureAvailabilityStore,
    initialize,
    initializeFeatureAvailability,
    notificationStore,
    panelState,
  } from '@repo/ui';
  import { isWorkspaceFeatureAvailable } from '@repo/ui/config/workspaceFeatureGates';

  let featureAvailabilityLoaded = $derived($featureAvailabilityStore.initialized);
  let teamsEnabled = $derived(isWorkspaceFeatureAvailable('platform:teams', $featureAvailabilityStore.disabledById));

  onMount(() => {
    initialize().catch((error) => {
      console.error('[TeamsRoute] Failed to initialize auth:', error);
    });

    initializeFeatureAvailability().catch((error: unknown) => {
      console.warn('[TeamsRoute] Failed to load feature availability:', error);
    });
  });
</script>

{#if !$authStore.isInitialized || !featureAvailabilityLoaded}
  <main class="teams-route-state" data-testid="teams-auth-loading">Loading teams...</main>
{:else if !teamsEnabled}
  <Header context="webapp" isLoggedIn={$authStore.isAuthenticated} />
  <main class="teams-route-state" data-testid="teams-feature-disabled">
    <h1>Teams unavailable</h1>
    <p>Teams are disabled on this server.</p>
  </main>
{:else if $authStore.isAuthenticated}
  <div class="main-content" class:menu-closed={!$panelState.isActivityHistoryOpen}>
    <Header context="webapp" isLoggedIn={$authStore.isAuthenticated} />
    <div class="teams-container" class:menu-open={$panelState.isSettingsOpen}>
      <div class="teams-wrapper" id="main-teams" tabindex="-1">
        <TeamsWorkspacePage />
      </div>
      <div class="settings-wrapper">
        <Settings isLoggedIn={$authStore.isAuthenticated} />
      </div>
    </div>
  </div>
{:else}
  <Header context="webapp" isLoggedIn={$authStore.isAuthenticated} />
  <main class="teams-route-state" data-testid="teams-auth-required">
    <h1>Teams</h1>
    <p>Please log in to collaborate in encrypted team workspaces.</p>
  </main>
{/if}

<div class="notification-container">
  {#each $notificationStore.notifications as notification (notification.id)}
    <Notification {notification} />
  {/each}
</div>

<style>
  .teams-route-state {
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

  .teams-container {
    display: flex;
    flex-direction: row;
    height: calc(100vh - 82px);
    height: calc(100dvh - 82px);
    gap: 0;
    padding: 10px 20px 10px 10px;
  }

  @media (min-width: 1100px) {
    .teams-container.menu-open {
      gap: 20px;
    }
  }

  .teams-wrapper {
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

    .teams-container {
      height: calc(100vh - 75px);
      height: calc(100dvh - 75px);
      padding-inline-end: 10px;
    }
  }

  .teams-route-state h1 {
    margin: 0;
    font-size: 2rem;
  }

  .teams-route-state p {
    margin: 0;
    color: var(--color-font-secondary);
  }

  .notification-container {
    position: fixed;
    top: 20px;
    right: 20px;
    z-index: 2000;
  }

  @media (max-width: 730px) {
    .notification-container {
      top: 10px;
      right: 10px;
      left: 10px;
    }
  }
</style>
