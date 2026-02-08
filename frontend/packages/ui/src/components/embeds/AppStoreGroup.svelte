<!--
  frontend/packages/ui/src/components/embeds/AppStoreGroup.svelte
  
  A horizontal scrollable container displaying AppStoreCard components
  for all available apps in the App Store.
  
  This component is rendered within demo chat messages when the
  [[app_store_group]] placeholder is encountered.
  
  Uses the same AppStoreCard design as the Settings App Store but scaled up
  to look more fitting in the chat message context.
  
  Clicking a card opens the App Store to that app's detail page.
-->

<script lang="ts">
  import AppStoreCard from '../settings/AppStoreCard.svelte';
  import { getAvailableApps } from '../../services/appSkillsService';
  import { settingsDeepLink } from '../../stores/settingsDeepLinkStore';
  
  /**
   * Get all available apps sorted alphabetically by name.
   * Uses the static appsMetadata (no API call, works offline).
   */
  let allApps = $derived((() => {
    const appsMap = getAvailableApps();
    const appsList = Object.values(appsMap);
    // Sort alphabetically by app name for consistent display
    return appsList.sort((a, b) => (a.name || a.id).localeCompare(b.name || b.id));
  })());
  
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

{#if allApps.length > 0}
  <div class="app-store-group-wrapper">
    <div class="app-store-group">
      {#each allApps as app (app.id)}
        <div class="app-card-scaled">
          <AppStoreCard {app} onSelect={handleAppSelect} />
        </div>
      {/each}
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
</style>
