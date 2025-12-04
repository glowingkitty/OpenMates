<!-- frontend/packages/ui/src/components/settings/AppSettingsMemoriesCategory.svelte
     Component for managing entries in a specific app settings/memories category.
     
     This component is used for the app_store/{app_id}/settings_memories/{category_id} nested route.
     
     **Backend Implementation**:
     - Data source: Static appsMetadata.ts (generated at build time) for category definition
     - Storage: IndexedDB (encrypted with app-specific keys)
     - Sync: Synced from server after Phase 3 chat sync completes
     - Types: frontend/packages/ui/src/types/apps.ts
     
     **Zero-Knowledge Architecture**:
     - All entries stored encrypted in IndexedDB
     - Decrypted on-demand for display
     - CRUD operations maintain encryption
     - Sync happens after all chats are synced (Phase 3)
-->

<script lang="ts">
    import { onMount } from 'svelte';
    import { appSkillsStore } from '../../stores/appSkillsStore';
    import { authStore } from '../../stores/authStore';
    import SettingsItem from '../SettingsItem.svelte';
    import AppSettingsMemoriesPanel from './appSettings/AppSettingsMemoriesPanel.svelte';
    import type { AppMetadata, MemoryFieldMetadata } from '../../types/apps';
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import { appSettingsMemoriesStore, appSettingsMemoriesLoading } from '../../stores/appSettingsMemoriesStore';

    // Create event dispatcher for navigation
    const dispatch = createEventDispatcher();

    // Check if user is authenticated - only authenticated users can manage settings and memories
    let isAuthenticated = $derived($authStore.isAuthenticated);

    interface Props {
        appId: string;
        categoryId: string;
    }

    let { appId, categoryId }: Props = $props();

    // Get store state reactively (Svelte 5)
    let storeState = $state(appSkillsStore.getState());

    // Get app metadata from store
    let app = $derived<AppMetadata | undefined>(storeState.apps[appId]);
    let category = $derived<MemoryFieldMetadata | undefined>(
        app?.settings_and_memories.find(c => c.id === categoryId)
    );

    let isLoading = $appSettingsMemoriesLoading;

    /**
     * Get the translated category name.
     */
    let categoryName = $derived(
        category?.name_translation_key
            ? $text(category.name_translation_key)
            : categoryId
    );

    /**
     * Get the translated category description.
     */
    let categoryDescription = $derived(
        category?.description_translation_key
            ? $text(category.description_translation_key)
            : ''
    );

    /**
     * Load entries for this category on mount.
     */
    onMount(async () => {
        if (appId) {
            await appSettingsMemoriesStore.loadEntriesForApp(appId);
        }
    });
    
    /**
     * Get icon name from icon_image filename.
     */
    function getIconName(iconImage: string | undefined): string {
        if (!iconImage) return appId;
        return iconImage.replace(/\.svg$/, '');
    }
    
    /**
     * Navigate back to app details.
     */
    function goBack() {
        dispatch('openSettings', {
            settingsPath: `app_store/${appId}`,
            direction: 'back',
            icon: getIconName(app?.icon_image),
            title: app?.name_translation_key ? $text(app.name_translation_key) : appId
        });
    }
    

</script>

<div class="app-settings-memories-category">
    {#if !app || !category}
        <div class="error">
            <p>{$text('settings.app_store.category_not_found.text')}</p>
            <button class="back-button" onclick={goBack}>← {$text('settings.app_store.back_to_app.text')}</button>
        </div>
    {:else}
        <!-- Header -->
        <div class="header">
            <h1>{categoryName}</h1>
            {#if categoryDescription}
                <p class="subtitle">{categoryDescription}</p>
            {/if}
        </div>

        {#if isAuthenticated}
            <!-- Full UI for managing settings and memories - only shown for authenticated users -->
            <div class="entries-container">
                <AppSettingsMemoriesPanel {appId} />
            </div>
        {:else}
            <!-- For non-authenticated users, only show the description -->
            <div class="description-only">
                {#if categoryDescription}
                    <p class="description-text">{categoryDescription}</p>
                {/if}
            </div>
        {/if}
    {/if}
</div>

<style>
    .app-settings-memories-category {
        padding: 2rem;
        max-width: 1400px;
        margin: 0 auto;
    }
    
    .header {
        margin-bottom: 2rem;
    }
    
    .header h1 {
        margin: 0 0 0.5rem 0;
        font-size: 2rem;
        font-weight: 600;
        color: var(--text-primary, #000000);
    }
    
    .subtitle {
        margin: 0;
        color: var(--text-secondary, #666666);
        font-size: 0.9rem;
    }
    
    .entries-container {
        padding: 1rem 0;
    }
    
    .error {
        padding: 3rem;
        text-align: center;
        color: var(--error-color, #dc3545);
    }
    
    .back-button {
        background: var(--button-background, #f0f0f0);
        border: 1px solid var(--border-color, #e0e0e0);
        border-radius: 6px;
        padding: 0.5rem 1rem;
        margin-top: 1rem;
        cursor: pointer;
        font-size: 0.9rem;
        color: var(--text-primary, #000000);
        transition: background 0.2s ease;
    }
    
    .back-button:hover {
        background: var(--button-hover-background, #e0e0e0);
    }
    
    .description-only {
        padding: 2rem;
        margin-top: 1rem;
    }
    
    .description-text {
        margin: 0;
        color: var(--text-secondary, #666666);
        font-size: 1rem;
        line-height: 1.6;
    }
</style>

