<!--
  Projects route for the authenticated web app.
  Renders the shared UI package ProjectsPage so project behavior stays reusable
  across route shells while preserving normal OpenMates header/navigation.
-->

<script lang="ts">
  import { onMount } from 'svelte';
  import { Header, ProjectsPage, Notification, authStore, initialize, notificationStore } from '@repo/ui';

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
  <ProjectsPage />
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
