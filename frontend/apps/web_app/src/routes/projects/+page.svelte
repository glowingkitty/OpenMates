<!--
  Projects route for the authenticated web app.
  Renders the shared UI package ProjectsPage so project behavior stays reusable
  across route shells while preserving normal OpenMates header/navigation.
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import { Header, ProjectsPage, Settings, Notification, authStore, initialize, notificationStore, panelState, featureAvailabilityStore, initializeFeatureAvailability } from '@repo/ui';

  let featureAvailabilityLoaded = $derived($featureAvailabilityStore.initialized);
  let projectsEnabled = $derived($featureAvailabilityStore.featuresById?.['platform:projects']?.enabled === true);

  onMount(() => {
    initialize().catch((error) => {
      console.error('[ProjectsRoute] Failed to initialize auth:', error);
    });

    initializeFeatureAvailability().catch((error: unknown) => {
      console.warn('[ProjectsRoute] Failed to load feature availability:', error);
    });
  });
</script>

{#if !$authStore.isInitialized || !featureAvailabilityLoaded}
  <main class="projects-route-state" data-testid="projects-auth-loading">Loading projects...</main>
{:else if !projectsEnabled}
  <Header context="webapp" isLoggedIn={$authStore.isAuthenticated} />
  <main class="projects-route-state" data-testid="projects-feature-disabled">
    <h1>Projects unavailable</h1>
    <p>Projects are disabled on this server.</p>
  </main>
{:else if $authStore.isAuthenticated}
  <div class="sidebar" class:closed={!$panelState.isActivityHistoryOpen}>
    {#if $panelState.isActivityHistoryOpen}
      <div class="sidebar-content">
        <ProjectsPage variant="sidebar" />
      </div>
    {/if}
  </div>
  <div class="main-content" class:menu-closed={!$panelState.isActivityHistoryOpen}>
    <Header context="webapp" isLoggedIn={$authStore.isAuthenticated} />
    <div class="projects-container" class:menu-open={$panelState.isSettingsOpen}>
      <div class="projects-wrapper" id="main-projects" tabindex="-1">
        <ProjectsPage />
      </div>
      <div class="settings-wrapper">
        <Settings isLoggedIn={$authStore.isAuthenticated} />
      </div>
    </div>
  </div>
{:else}
  <Header context="webapp" isLoggedIn={$authStore.isAuthenticated} />
  <main class="projects-route-state" data-testid="projects-auth-required">
    <h1>Projects</h1>
    <p>Please log in to organize chats, embeds, and uploaded files into projects.</p>
  </main>
{/if}
<div class="notification-container">
  {#each $notificationStore.notifications as notification (notification.id)}
    <Notification {notification} />
  {/each}
</div>

<style>
  .projects-route-state {
    min-height: calc(100vh - 90px);
    display: grid;
    place-content: center;
    gap: var(--spacing-8, 16px);
    padding: var(--spacing-20, 40px);
    text-align: center;
    color: var(--color-font-primary);
  }

  .sidebar {
    position: fixed;
    inset-inline-start: 0;
    top: 0;
    bottom: 0;
    width: var(--sidebar-width, 325px);
    background-color: var(--color-grey-20);
    z-index: 10;
    overflow: hidden;
    box-shadow: inset -6px 0 12px -4px rgba(0, 0, 0, 0.25);
    transition:
      transform 0.3s ease,
      opacity 0.3s ease,
      visibility 0.3s ease;
    transform: translateX(0);
    opacity: 1;
    visibility: visible;
  }

  .sidebar.closed {
    transform: translateX(-100%);
    opacity: 0;
    visibility: hidden;
  }

  :global([dir='rtl']) .sidebar.closed {
    transform: translateX(100%);
  }

  :global([dir='rtl']) .sidebar {
    box-shadow: inset 6px 0 12px -4px rgba(0, 0, 0, 0.25);
  }

  .sidebar-content {
    height: 100%;
    width: 100%;
    overflow: hidden;
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

  .projects-container {
    display: flex;
    flex-direction: row;
    height: calc(100vh - 82px);
    height: calc(100dvh - 82px);
    gap: 0;
    padding: 10px 20px 10px 10px;
  }

  @media (min-width: 1100px) {
    .projects-container.menu-open {
      gap: 20px;
    }
  }

  .projects-wrapper {
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
    .sidebar {
      width: 100%;
    }

    .main-content {
      inset-inline-start: 0;
      inset-inline-end: 0;
      z-index: 20;
      transform: translateX(0);
    }

    .main-content:not(.menu-closed) {
      transform: translateX(100%);
    }

    :global([dir='rtl']) .main-content:not(.menu-closed) {
      transform: translateX(-100%);
    }

    .projects-container {
      height: calc(100vh - 75px);
      height: calc(100dvh - 75px);
      padding-inline-end: 10px;
    }
  }

  .projects-route-state h1 {
    margin: 0;
    font-size: 2rem;
  }

  .projects-route-state p {
    margin: 0;
    color: var(--color-font-secondary);
  }

  .notification-container {
    position: fixed;
    top: 0;
    inset-inline-start: 0;
    inset-inline-end: 0;
    z-index: 10000;
    pointer-events: none;
    display: flex;
    flex-direction: column;
    align-items: center;
    padding-top: 20px;
    gap: 10px;
  }

  .notification-container :global(.notification) {
    pointer-events: auto;
  }
</style>
