<!--
  frontend/packages/ui/src/components/embeds/AppStoreGroup.svelte
  
  A horizontal scrollable container displaying AppStoreCard components
  for available apps in the App Store.
  
  This component is rendered within demo chat messages when the
  [[app_store_group]] placeholder is encountered.
  
  Features:
  - Excludes the AI app (always used, focus should be on other apps)
  - Limits display to first 10 items
  - Shows "+ N more" badge at the end when items are truncated
  - Supports custom sort order via sortOrder prop
  
  Uses the same AppStoreCard design as the Settings App Store but scaled up
  to look more fitting in the chat message context.
  
  Clicking a card opens the App Store to that app's detail page.
-->

<script lang="ts">
  import AppStoreCard from '../settings/AppStoreCard.svelte';
  import { getAvailableApps } from '../../services/appSkillsService';
  import { settingsDeepLink } from '../../stores/settingsDeepLinkStore';
  import { text } from '@repo/ui';
  
  /** Maximum number of items to display before showing "+N more" */
  const MAX_DISPLAY_ITEMS = 10;
  
  /** App ID to exclude (AI app is always used, focus on other apps) */
  const EXCLUDED_APP_ID = 'ai';
  
  /**
   * Props interface for AppStoreGroup
   */
  interface Props {
    /**
     * Custom sort order for apps. Array of app IDs in desired display order.
     * Apps in this array appear first (in the specified order),
     * followed by any remaining apps sorted alphabetically.
     * If not provided, apps are sorted alphabetically by name.
     */
    sortOrder?: string[];
  }
  
  let {
    sortOrder
  }: Props = $props();
  
  /**
   * Get all available apps excluding the AI app.
   * Supports custom sort order via sortOrder prop.
   * Limited to MAX_DISPLAY_ITEMS for display.
   */
  let filteredApps = $derived((() => {
    const appsMap = getAvailableApps();
    const appsList = Object.values(appsMap)
      .filter(app => app.id !== EXCLUDED_APP_ID);
    
    if (sortOrder && sortOrder.length > 0) {
      // Custom sort: apps in sortOrder come first (in that order), then remaining alphabetically
      const ordered = [];
      const remaining = [];
      
      for (const appId of sortOrder) {
        const app = appsList.find(a => a.id === appId);
        if (app) ordered.push(app);
      }
      
      for (const app of appsList) {
        if (!sortOrder.includes(app.id)) {
          remaining.push(app);
        }
      }
      
      remaining.sort((a, b) => (a.name || a.id).localeCompare(b.name || b.id));
      return [...ordered, ...remaining];
    }
    
    // Default: sort alphabetically by app name
    return appsList.sort((a, b) => (a.name || a.id).localeCompare(b.name || b.id));
  })());
  
  /** Apps to display (limited to MAX_DISPLAY_ITEMS) */
  let displayApps = $derived(filteredApps.slice(0, MAX_DISPLAY_ITEMS));
  
  /** Count of remaining apps not shown */
  let remainingCount = $derived(Math.max(0, filteredApps.length - MAX_DISPLAY_ITEMS));
  
  /**
   * Handle app card click - open the App Store to the specific app's detail page.
   * Uses settingsDeepLink store + panelState.openSettings() to navigate.
   */
  async function handleAppSelect(appId: string) {
    console.debug('[AppStoreGroup] App selected:', appId);
    
    // Set the deep link to the app's detail page in the App Store
    settingsDeepLink.set(`app_store/${appId}`);
    
    // Open the settings panel (which will pick up the deep link)
    const { panelState } = await import('../../stores/panelStateStore');
    panelState.openSettings();
  }
</script>

{#if displayApps.length > 0}
  <div class="app-store-group-wrapper">
    <div class="app-store-group">
      {#each displayApps as app (app.id)}
        <div class="app-card-scaled">
          <AppStoreCard {app} onSelect={handleAppSelect} />
        </div>
      {/each}
      
      <!-- Show "+ N more" badge when there are more items than displayed -->
      {#if remainingCount > 0}
        <button
          class="more-badge"
          onclick={() => handleAppSelect('')}
          type="button"
          aria-label={$text('app_store.plus_n_more.text', { values: { count: remainingCount } })}
        >
          <span class="more-text">+ {remainingCount}</span>
        </button>
      {/if}
    </div>
  </div>
{/if}

<style>
  .app-store-group-wrapper {
    /* Full width of the message content area */
    width: 100%;
    margin: 16px 0;
    /* Needed for proper overflow handling */
    overflow: hidden;
  }
  
  /* Match the standard embed group scroll container layout:
     - Smooth horizontal scrolling (no snap)
     - Same gap, padding, and scrollbar styling as ExampleChatsGroup */
  .app-store-group {
    display: flex;
    gap: 12px;
    align-items: flex-start;
    overflow-x: auto;
    overflow-y: hidden;
    padding: 4px 0;
    scrollbar-width: thin;
    scrollbar-color: var(--color-grey-60) transparent;
  }
  
  /* Custom scrollbar styling for WebKit browsers */
  .app-store-group::-webkit-scrollbar {
    height: 4px;
  }
  
  .app-store-group::-webkit-scrollbar-track {
    background: transparent;
  }
  
  .app-store-group::-webkit-scrollbar-thumb {
    background-color: var(--color-grey-60);
    border-radius: 2px;
  }
  
  /* Scale up the AppStoreCard to look more fitting in the chat context.
     Original card is 223x129px. Scaling by 1.15x makes it ~256x148px
     which looks better alongside the chat embed previews. */
  .app-card-scaled {
    flex-shrink: 0;
    transform: scale(1.15);
    transform-origin: top left;
    /* Account for the scaled size in the layout so scrolling works correctly.
       Original: 223x129, scaled: 223*1.15=256, 129*1.15=148 */
    width: 256px;
    height: 148px;
  }
  
  /* Ensure cards don't shrink */
  .app-store-group > :global(*) {
    flex-shrink: 0;
  }
  
  /* "+N more" badge at the end of the scrollable list */
  .more-badge {
    display: flex;
    align-items: center;
    justify-content: center;
    min-width: 80px;
    height: 148px;
    padding: 0 16px;
    background-color: var(--color-grey-30);
    border-radius: 12px;
    border: 1px solid var(--color-grey-40);
    cursor: pointer;
    flex-shrink: 0;
    transition: background-color 0.2s ease, transform 0.2s ease;
  }
  
  .more-badge:hover {
    background-color: var(--color-grey-35);
    transform: translateY(-2px);
  }
  
  .more-badge:active {
    transform: scale(0.96);
  }
  
  .more-text {
    font-size: 16px;
    font-weight: 600;
    color: var(--color-grey-70);
    white-space: nowrap;
  }
</style>
