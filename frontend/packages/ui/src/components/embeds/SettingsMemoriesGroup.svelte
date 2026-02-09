<!--
  frontend/packages/ui/src/components/embeds/SettingsMemoriesGroup.svelte
  
  A horizontal scrollable container displaying AppStoreCard components
  for available settings & memories categories across all apps (excluding AI app).
  
  This component is rendered within demo chat messages when the
  [[settings_memories_group]] placeholder is encountered.
  
  Features:
  - Excludes settings & memories from the AI app (always used, focus on other apps)
  - Limits display to first 10 items
  - Shows "+ N more" badge at the end when items are truncated
  - Supports custom sort order via sortOrder prop
  
  Uses the same AppStoreCard design as the Settings App Store but scaled up
  for the chat context.
  
  Clicking a card opens the App Store to that settings & memories category's detail page.
-->

<script lang="ts">
  import AppStoreCard from '../settings/AppStoreCard.svelte';
  import { getAvailableApps } from '../../services/appSkillsService';
  import { settingsDeepLink } from '../../stores/settingsDeepLinkStore';
  import { text } from '@repo/ui';
  import type { AppMetadata, MemoryFieldMetadata } from '../../types/apps';
  
  /** Maximum number of items to display before showing "+N more" */
  const MAX_DISPLAY_ITEMS = 10;
  
  /** App ID to exclude (AI app is always used, focus on other apps) */
  const EXCLUDED_APP_ID = 'ai';
  
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
   * Props interface for SettingsMemoriesGroup
   */
  interface Props {
    /**
     * Custom sort order for settings & memories. Array of "appId/categoryId" strings in desired display order.
     * Categories in this array appear first (in the specified order),
     * followed by any remaining categories sorted alphabetically.
     * If not provided, categories are sorted alphabetically by name translation key.
     */
    sortOrder?: string[];
  }
  
  let {
    sortOrder
  }: Props = $props();
  
  /**
   * Get all settings & memories categories across all apps (excluding AI app),
   * each wrapped with parent app context. Supports custom sort order.
   */
  let filteredCategories = $derived((() => {
    const appsMap = getAvailableApps();
    const categories: MemoryCategoryWithApp[] = [];
    
    for (const app of Object.values(appsMap)) {
      // Exclude AI app settings & memories
      if (app.id === EXCLUDED_APP_ID) continue;
      
      for (const category of app.settings_and_memories) {
        categories.push({
          category,
          appId: app.id,
          cardApp: {
            id: app.id,
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
    
    if (sortOrder && sortOrder.length > 0) {
      // Custom sort: categories in sortOrder come first, then remaining alphabetically
      const ordered: MemoryCategoryWithApp[] = [];
      const remaining: MemoryCategoryWithApp[] = [];
      
      for (const key of sortOrder) {
        const item = categories.find(c => `${c.appId}/${c.category.id}` === key);
        if (item) ordered.push(item);
      }
      
      for (const item of categories) {
        if (!sortOrder.includes(`${item.appId}/${item.category.id}`)) {
          remaining.push(item);
        }
      }
      
      remaining.sort((a, b) => 
        (a.category.name_translation_key || a.category.id).localeCompare(b.category.name_translation_key || b.category.id)
      );
      return [...ordered, ...remaining];
    }
    
    // Default: sort by category name translation key
    return categories.sort((a, b) => 
      (a.category.name_translation_key || a.category.id).localeCompare(b.category.name_translation_key || b.category.id)
    );
  })());
  
  /** Categories to display (limited to MAX_DISPLAY_ITEMS) */
  let displayCategories = $derived(filteredCategories.slice(0, MAX_DISPLAY_ITEMS));
  
  /** Count of remaining categories not shown */
  let remainingCount = $derived(Math.max(0, filteredCategories.length - MAX_DISPLAY_ITEMS));
  
  /**
   * Handle settings & memories category card click - open the App Store to the category's detail page.
   */
  async function handleCategorySelect(appId: string, categoryId: string) {
    console.debug('[SettingsMemoriesGroup] Category selected:', appId, categoryId);
    
    settingsDeepLink.set(`app_store/${appId}/settings_memories/${categoryId}`);
    
    const { panelState } = await import('../../stores/panelStateStore');
    panelState.openSettings();
  }
  
  /**
   * Handle "+N more" badge click - open the App Store overview
   */
  async function handleMoreClick() {
    settingsDeepLink.set('app_store');
    const { panelState } = await import('../../stores/panelStateStore');
    panelState.openSettings();
  }
</script>

{#if displayCategories.length > 0}
  <div class="settings-memories-group-wrapper">
    <div class="settings-memories-group">
      {#each displayCategories as { category, appId, cardApp } (`${appId}-${category.id}`)}
        <div class="memory-card-scaled">
          <AppStoreCard 
            app={cardApp} 
            onSelect={() => handleCategorySelect(appId, category.id)} 
          />
        </div>
      {/each}
      
      <!-- Show "+ N more" badge when there are more items than displayed -->
      {#if remainingCount > 0}
        <button
          class="more-badge"
          onclick={handleMoreClick}
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
