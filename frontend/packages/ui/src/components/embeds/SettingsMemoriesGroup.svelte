<!--
  frontend/packages/ui/src/components/embeds/SettingsMemoriesGroup.svelte
  
  A horizontal scrollable container displaying AppStoreCard components
  for all available settings & memories categories across all apps.
  
  This component is rendered within demo chat messages when the
  [[settings_memories_group]] placeholder is encountered.
  
  Uses the same AppStoreCard design as the Settings App Store but scaled up
  for the chat context.
  
  Clicking a card opens the App Store to that settings & memories category's detail page.
-->

<script lang="ts">
  import AppStoreCard from '../settings/AppStoreCard.svelte';
  import { getAvailableApps } from '../../services/appSkillsService';
  import { settingsDeepLink } from '../../stores/settingsDeepLinkStore';
  import type { AppMetadata, MemoryFieldMetadata } from '../../types/apps';
  
  /**
   * Represents a settings & memories category with its parent app context,
   * needed to render AppStoreCard with correct gradient and icon.
   */
  interface MemoryCategoryWithApp {
    category: MemoryFieldMetadata;
    appId: string;
    /** AppMetadata-shaped object for the AppStoreCard component */
    cardApp: AppMetadata;
  }
  
  /**
   * Get all settings & memories categories across all apps, each wrapped with parent app context.
   * Sorted alphabetically by category name translation key for consistent display.
   */
  let allMemoryCategories = $derived((() => {
    const appsMap = getAvailableApps();
    const categories: MemoryCategoryWithApp[] = [];
    
    for (const app of Object.values(appsMap)) {
      for (const category of app.settings_and_memories) {
        categories.push({
          category,
          appId: app.id,
          cardApp: {
            id: app.id, // Use appId so gradient matches the app
            name_translation_key: category.name_translation_key,
            description_translation_key: category.description_translation_key,
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
    
    // Sort by category name translation key for consistent ordering
    return categories.sort((a, b) => 
      (a.category.name_translation_key || a.category.id).localeCompare(b.category.name_translation_key || b.category.id)
    );
  })());
  
  /**
   * Handle settings & memories category card click - open the App Store to the category's detail page.
   * Uses settingsDeepLink store + panelState.openSettings() to navigate.
   */
  async function handleCategorySelect(appId: string, categoryId: string) {
    console.debug('[SettingsMemoriesGroup] Category selected:', appId, categoryId);
    
    // Set the deep link to the category's detail page
    settingsDeepLink.set(`app_store/${appId}/settings_memories/${categoryId}`);
    
    // Open the settings panel (which will pick up the deep link)
    const { panelState } = await import('../../stores/panelStateStore');
    panelState.openSettings();
  }
</script>

{#if allMemoryCategories.length > 0}
  <div class="settings-memories-group-wrapper">
    <div class="settings-memories-group">
      {#each allMemoryCategories as { category, appId, cardApp } (`${appId}-${category.id}`)}
        <div class="memory-card-scaled">
          <AppStoreCard 
            app={cardApp} 
            onSelect={() => handleCategorySelect(appId, category.id)} 
          />
        </div>
      {/each}
    </div>
  </div>
{/if}

<style>
  .settings-memories-group-wrapper {
    width: 100%;
    margin: 16px 0;
    overflow: hidden;
  }
  
  .settings-memories-group {
    display: flex;
    gap: 12px;
    align-items: flex-start;
    overflow-x: auto;
    overflow-y: hidden;
    padding: 4px 0;
    scrollbar-width: thin;
    scrollbar-color: var(--color-grey-60) transparent;
  }
  
  .settings-memories-group::-webkit-scrollbar {
    height: 4px;
  }
  
  .settings-memories-group::-webkit-scrollbar-track {
    background: transparent;
  }
  
  .settings-memories-group::-webkit-scrollbar-thumb {
    background-color: var(--color-grey-60);
    border-radius: 2px;
  }
  
  /* Scale up the AppStoreCard for chat context.
     Original: 223x129px, scaled 1.15x: ~256x148px */
  .memory-card-scaled {
    flex-shrink: 0;
    transform: scale(1.15);
    transform-origin: top left;
    width: 256px;
    height: 148px;
  }
  
  .settings-memories-group > :global(*) {
    flex-shrink: 0;
  }
</style>
