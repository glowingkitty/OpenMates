<!--
  Projects route for the authenticated web app.
  Renders the shared UI package ProjectsPage so project behavior stays reusable
  across route shells while preserving normal OpenMates header/navigation.
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import { Header, ProjectsPage, Notification, authStore, initialize, notificationStore, panelState } from '@repo/ui';

  onMount(() => {
    initialize().catch((error) => {
      console.error('[ProjectsRoute] Failed to initialize auth:', error);
    });
  });
</script>

<Header context="webapp" isLoggedIn={$authStore.isAuthenticated} />
{#if !$authStore.isInitialized}
  <main class="projects-route-state" data-testid="projects-auth-loading">Loading projects...</main>
{:else if $authStore.isAuthenticated}
  <div class="sidebar" class:closed={!$panelState.isActivityHistoryOpen}>
    {#if $panelState.isActivityHistoryOpen}
      <div class="sidebar-content">
        <ProjectsPage variant="sidebar" />
      </div>
    {/if}
  </div>
  <main class="projects-route-main" class:menu-closed={!$panelState.isActivityHistoryOpen}>
    <ProjectsPage />
  </main>
{:else}
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

  .projects-route-main {
    position: fixed;
    inset-inline-start: calc(var(--sidebar-width, 325px) + var(--sidebar-margin, 10px));
    inset-inline-end: 0;
    top: 82px;
    bottom: 0;
    overflow: auto;
    background: var(--color-grey-0);
    transition: inset-inline-start 0.3s ease;
  }

  .projects-route-main.menu-closed {
    inset-inline-start: var(--sidebar-margin, 10px);
  }

  @media (max-width: 600px) {
    .sidebar {
      width: 100%;
    }

    .projects-route-main {
      inset-inline-start: 0;
      inset-inline-end: 0;
      top: 75px;
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
