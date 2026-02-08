<!--
  frontend/packages/ui/src/components/embeds/FocusModesGroup.svelte
  
  A horizontal scrollable container displaying AppStoreCard components
  for all available focus modes across all apps.
  
  This component is rendered within demo chat messages when the
  [[focus_modes_group]] placeholder is encountered.
  
  Uses the same AppStoreCard design as the Settings App Store but scaled up
  for the chat context.
  
  Clicking a card opens the App Store to that focus mode's detail page.
-->

<script lang="ts">
  import AppStoreCard from '../settings/AppStoreCard.svelte';
  import { getAvailableApps } from '../../services/appSkillsService';
  import { settingsDeepLink } from '../../stores/settingsDeepLinkStore';
  import type { AppMetadata, FocusModeMetadata } from '../../types/apps';
  
  /**
   * Represents a focus mode with its parent app context,
   * needed to render AppStoreCard with correct gradient and icon.
   */
  interface FocusModeWithApp {
    focusMode: FocusModeMetadata;
    appId: string;
    /** AppMetadata-shaped object for the AppStoreCard component */
    cardApp: AppMetadata;
  }
  
  /**
   * Get all focus modes across all apps, each wrapped with parent app context.
   * Sorted alphabetically by focus mode name translation key for consistent display.
   */
  let allFocusModes = $derived((() => {
    const appsMap = getAvailableApps();
    const focusModes: FocusModeWithApp[] = [];
    
    for (const app of Object.values(appsMap)) {
      for (const focusMode of app.focus_modes) {
        focusModes.push({
          focusMode,
          appId: app.id,
          cardApp: {
            id: app.id, // Use appId so gradient matches the app
            name_translation_key: focusMode.name_translation_key,
            description_translation_key: focusMode.description_translation_key,
            icon_image: app.icon_image,
            icon_colorgradient: app.icon_colorgradient,
            providers: [],
            skills: [],
            focus_modes: [],
            settings_and_memories: []
          }
        });
      }
    }
    
    // Sort by focus mode name translation key for consistent ordering
    return focusModes.sort((a, b) => 
      (a.focusMode.name_translation_key || a.focusMode.id).localeCompare(b.focusMode.name_translation_key || b.focusMode.id)
    );
  })());
  
  /**
   * Handle focus mode card click - open the App Store to the focus mode's detail page.
   * Uses settingsDeepLink store + panelState.openSettings() to navigate.
   */
  async function handleFocusModeSelect(appId: string, focusModeId: string) {
    console.debug('[FocusModesGroup] Focus mode selected:', appId, focusModeId);
    
    // Set the deep link to the focus mode's detail page
    settingsDeepLink.set(`app_store/${appId}/focus/${focusModeId}`);
    
    // Open the settings panel (which will pick up the deep link)
    const { panelState } = await import('../../stores/panelStateStore');
    panelState.openSettings();
  }
</script>

{#if allFocusModes.length > 0}
  <div class="focus-modes-group-wrapper">
    <div class="focus-modes-group">
      {#each allFocusModes as { focusMode, appId, cardApp } (`${appId}-${focusMode.id}`)}
        <div class="focus-mode-card-scaled">
          <AppStoreCard 
            app={cardApp} 
            onSelect={() => handleFocusModeSelect(appId, focusMode.id)} 
          />
        </div>
      {/each}
    </div>
  </div>
{/if}

<style>
  .focus-modes-group-wrapper {
    width: 100%;
    margin: 16px 0;
    overflow: hidden;
  }
  
  .focus-modes-group {
    display: flex;
    gap: 12px;
    align-items: flex-start;
    overflow-x: auto;
    overflow-y: hidden;
    padding: 4px 0;
    scrollbar-width: thin;
    scrollbar-color: var(--color-grey-60) transparent;
  }
  
  .focus-modes-group::-webkit-scrollbar {
    height: 4px;
  }
  
  .focus-modes-group::-webkit-scrollbar-track {
    background: transparent;
  }
  
  .focus-modes-group::-webkit-scrollbar-thumb {
    background-color: var(--color-grey-60);
    border-radius: 2px;
  }
  
  /* Scale up the AppStoreCard for chat context.
     Original: 223x129px, scaled 1.15x: ~256x148px */
  .focus-mode-card-scaled {
    flex-shrink: 0;
    transform: scale(1.15);
    transform-origin: top left;
    width: 256px;
    height: 148px;
  }
  
  .focus-modes-group > :global(*) {
    flex-shrink: 0;
  }
</style>
