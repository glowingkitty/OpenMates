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
    import type { AppMetadata, MemoryFieldMetadata } from '../../types/apps';
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import { appSettingsMemoriesStore, appSettingsMemoriesForApp } from '../../stores/appSettingsMemoriesStore';
    import type { Readable } from 'svelte/store';

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

    // Local loading state - tracks if we're currently loading entries for this component
    // This is separate from the global store loading state to avoid conflicts
    // We control this state locally to ensure it always clears after loading completes
    let isInitialLoad = $state(false);
    
    // Get entries for this app (grouped by settings_group)
    let appEntries: Readable<Record<string, unknown>> = appSettingsMemoriesForApp(appId);
    let groupedEntries = $appEntries;

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
     * Shows loading state while loading, then clears it when done.
     * This ensures loading only happens when clicking on the settings/memories entry,
     * and always clears even if there are 0 entries.
     */
    onMount(async () => {
        if (appId && isAuthenticated) {
            // Show loading state while we fetch entries
            isInitialLoad = true;
            try {
                // Load entries for this app (this handles encryption/decryption)
                await appSettingsMemoriesStore.loadEntriesForApp(appId);
            } catch (error) {
                // Log error but don't throw - we'll show empty state if load fails
                console.error('[AppSettingsMemoriesCategory] Error loading entries:', error);
            } finally {
                // CRITICAL: Always clear loading state after load completes
                // This prevents infinite loading screens
                // Whether we have 0 entries or many entries, loading should stop here
                isInitialLoad = false;
            }
        } else {
            // If not authenticated, no need to load
            isInitialLoad = false;
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
    
    /**
     * Navigate to create entry sub-settings menu for this specific category.
     * This opens a sub-settings menu for creating entries of this exact category type.
     */
    function handleAddEntry() {
        dispatch('openSettings', {
            settingsPath: `app_store/${appId}/settings_memories/${categoryId}/create`,
            direction: 'forward',
            icon: getIconName(app?.icon_image),
            title: $text('settings.app_settings_memories.add_entry.text')
        });
    }
    
    /**
     * Format date timestamp for display.
     */
    function formatDate(timestamp: number): string {
        const date = new Date(timestamp * 1000);
        return date.toLocaleDateString(undefined, {
            year: 'numeric',
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        });
    }
    
    /**
     * Format entry value for display.
     */
    function formatValue(value: unknown): string {
        if (value === null || value === undefined) {
            return 'null';
        }
        if (typeof value === 'boolean') {
            return value ? 'true' : 'false';
        }
        if (typeof value === 'object') {
            return JSON.stringify(value, null, 2);
        }
        return String(value);
    }
    
    /**
     * Get all entries flattened from all groups.
     * Since entries are grouped by settings_group, we need to flatten them for display.
     */
    let allEntries = $derived.by(() => {
        const entries: Array<{ id: string; item_key: string; item_value: unknown; updated_at: number; item_version: number; settings_group: string }> = [];
        for (const [groupName, groupEntries] of Object.entries(groupedEntries)) {
            if (Array.isArray(groupEntries)) {
                for (const entry of groupEntries) {
                    entries.push({
                        id: entry.id as string,
                        item_key: entry.item_key as string,
                        item_value: entry.item_value,
                        updated_at: entry.updated_at as number,
                        item_version: entry.item_version as number,
                        settings_group: groupName
                    });
                }
            }
        }
        // Sort by updated_at descending (newest first)
        return entries.sort((a, b) => b.updated_at - a.updated_at);
    });

</script>

<div class="app-settings-memories-category">
    {#if !app || !category}
        <div class="error">
            <p>{$text('settings.app_store.category_not_found.text')}</p>
            <button class="back-button" onclick={goBack}>← {$text('settings.app_store.back_to_app.text')}</button>
        </div>
    {:else}
        <!-- Category description at the top -->
        <div class="header">
            {#if categoryDescription}
                <p class="description">{categoryDescription}</p>
            {/if}
        </div>

        {#if isAuthenticated}
            <!-- Add entry button - temporarily commented out -->
            <!-- TODO: Commenting out add entry functionality - feature needs more testing and stability -->
            <!-- <div class="add-entry-section">
                <SettingsItem
                    type="submenu"
                    icon="create"
                    title={$text('settings.app_settings_memories.add_entry.text')}
                    onClick={handleAddEntry}
                />
            </div> -->

            <!-- Placeholder message for disabled functionality -->
            <div class="placeholder-section">
                <div class="placeholder-message">
                    <p>{$text('settings.app_settings_memories.placeholder.text')}</p>
                </div>
            </div>
            
            <!-- List of existing entries -->
            <div class="entries-section">
                {#if isInitialLoad}
                    <div class="loading">
                        <p>{$text('settings.app_settings_memories.loading.text')}</p>
                    </div>
                {:else if allEntries.length === 0}
                    <div class="empty">
                        <p>{$text('settings.app_settings_memories.no_settings.text')}</p>
                    </div>
                {:else}
                    <div class="entries-list">
                        {#each allEntries as entry (entry.id)}
                            <div class="entry-item">
                                <div class="entry-header">
                                    <span class="entry-key">{entry.item_key}</span>
                                    <span class="entry-meta">
                                        {entry.settings_group} • v{entry.item_version} • {formatDate(entry.updated_at)}
                                    </span>
                                </div>
                                <div class="entry-value">
                                    <code>{formatValue(entry.item_value)}</code>
                                </div>
                            </div>
                        {/each}
                    </div>
                {/if}
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
        padding: 14px;
        max-width: 1400px;
        margin: 0 auto;
    }
    
    .header {
        margin-bottom: 2rem;
        padding-left: 0;
    }
    
    .description {
        margin: 0;
        color: var(--color-grey-100);
        font-size: 1rem;
        line-height: 1.6;
        text-align: left;
    }
    
    .add-entry-section {
        margin-bottom: 2rem;
        padding-left: 0;
    }
    
    .entries-section {
        padding-left: 0;
    }
    
    .loading {
        padding: 2rem;
        text-align: center;
        color: var(--text-secondary, #666666);
    }
    
    .empty {
        padding: 2rem;
        text-align: center;
        color: var(--text-secondary, #666666);
    }
    
    .entries-list {
        display: flex;
        flex-direction: column;
        gap: 1rem;
    }
    
    .entry-item {
        padding: 1rem;
        background: var(--color-grey-10);
        border: 1px solid var(--color-grey-20);
        border-radius: 8px;
    }
    
    .entry-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 0.5rem;
        gap: 1rem;
        flex-wrap: wrap;
    }
    
    .entry-key {
        font-family: 'Courier New', monospace;
        font-size: 0.9rem;
        font-weight: 600;
        color: var(--text-primary);
        word-break: break-word;
    }
    
    .entry-meta {
        font-size: 0.75rem;
        color: var(--text-secondary);
        white-space: nowrap;
    }
    
    .entry-value {
        margin-top: 0.5rem;
    }
    
    code {
        display: block;
        padding: 0.75rem;
        background: var(--color-white);
        border: 1px solid var(--color-grey-20);
        border-radius: 4px;
        font-family: 'Courier New', monospace;
        font-size: 0.85rem;
        overflow-x: auto;
        color: var(--text-primary);
        word-break: break-word;
        white-space: pre-wrap;
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

    .placeholder-section {
        margin-bottom: 2rem;
        padding-left: 0;
    }

    .placeholder-message {
        padding: 2rem;
        text-align: center;
        background: var(--color-grey-10);
        border: 1px solid var(--color-grey-20);
        border-radius: 8px;
        color: var(--text-secondary, #666666);
        font-style: italic;
    }
</style>

