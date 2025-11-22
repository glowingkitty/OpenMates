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
    import { appSkillsStore } from '../../stores/appSkillsStore';
    import { authStore } from '../../stores/authStore';
    import SettingsItem from '../SettingsItem.svelte';
    import type { AppMetadata, MemoryFieldMetadata } from '../../types/apps';
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    
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
    
    /**
     * State for managing entries in this category.
     * TODO: Load from IndexedDB after sync completes
     * Structure: Array<{ id: string, data: any, approved: boolean, item_version: number }>
     */
    let entries = $state<any[]>([]);
    
    /**
     * State for showing add entry form
     */
    let showAddForm = $state(false);
    
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
     * Load entries for this category from IndexedDB.
     * TODO: Implement actual IndexedDB loading with decryption
     */
    async function loadEntries(): Promise<void> {
        console.log(`[AppSettingsMemoriesCategory] Loading entries for category: ${categoryId}`);
        // TODO: Implement IndexedDB loading
        // 1. Get app-specific encryption key
        // 2. Query IndexedDB for entries with this category
        // 3. Decrypt entries
        // 4. Update entries state
    }
    
    /**
     * Add a new entry to this category.
     * TODO: Implement actual IndexedDB storage with encryption
     */
    async function addEntry(entryData: any): Promise<void> {
        console.log(`[AppSettingsMemoriesCategory] Adding entry to category: ${categoryId}`, entryData);
        // TODO: Implement IndexedDB storage
        // 1. Generate entry_id (UUID)
        // 2. Encrypt entry data with app-specific key
        // 3. Store in IndexedDB with approved: false
        // 4. Update entries state
        // 5. Show entry in UI (pending approval)
    }
    
    /**
     * Delete an entry.
     * TODO: Implement actual IndexedDB deletion
     */
    async function deleteEntry(entryId: string): Promise<void> {
        console.log(`[AppSettingsMemoriesCategory] Deleting entry: ${entryId}`);
        // TODO: Implement IndexedDB deletion
        // 1. Delete from IndexedDB
        // 2. If approved, send deletion request to server
        // 3. Update entries state
    }
    
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
     * Initialize: Load entries for this category.
     * TODO: This should be called after sync completes
     */
    $effect(() => {
        if (category) {
            loadEntries();
        }
    });
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
            <!-- Entries list -->
            <div class="entries-container">
                {#if entries.length > 0}
                    {#each entries as entry (entry.id)}
                        <div class="entry-item">
                            <div class="entry-content">
                                <!-- TODO: Display decrypted entry data based on category schema -->
                                <p class="entry-preview">Entry ID: {entry.id}</p>
                                {#if !entry.approved}
                                    <span class="pending-badge">{$text('settings.app_store.settings_memories.pending.text')}</span>
                                {/if}
                            </div>
                            <button 
                                class="delete-button"
                                onclick={() => deleteEntry(entry.id)}
                                title={$text('settings.app_store.settings_memories.delete.text')}
                            >
                                {$text('settings.app_store.settings_memories.delete.text')}
                            </button>
                        </div>
                    {/each}
                {:else}
                    <div class="no-entries">
                        <p>{$text('settings.app_store.settings_memories.no_entries.text', { category: categoryName })}</p>
                    </div>
                {/if}
                
                <!-- Add entry button -->
                <button 
                    class="add-button"
                    onclick={() => showAddForm = true}
                >
                    + {$text('settings.app_store.settings_memories.add_entry.text')}
                </button>
            </div>
        {:else}
            <!-- For non-authenticated users, only show the description -->
            <!-- TODO: Add examples here later to help users understand what this category is for -->
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
    
    .entry-item {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 1rem;
        margin-bottom: 0.5rem;
        background: var(--color-grey-10);
        border-radius: 6px;
        border: 1px solid var(--color-grey-20);
    }
    
    .entry-content {
        flex: 1;
        display: flex;
        align-items: center;
        gap: 1rem;
    }
    
    .entry-preview {
        margin: 0;
        color: var(--text-primary, #000000);
    }
    
    .pending-badge {
        padding: 0.25rem 0.5rem;
        background: var(--color-warning, #ffc107);
        color: var(--text-primary, #000000);
        border-radius: 4px;
        font-size: 0.75rem;
        font-weight: 500;
    }
    
    .delete-button {
        background: var(--error-color, #dc3545);
        color: white;
        border: none;
        border-radius: 4px;
        padding: 0.5rem 1rem;
        cursor: pointer;
        font-size: 0.9rem;
        transition: background 0.2s ease;
    }
    
    .delete-button:hover {
        background: var(--error-color-dark, #c82333);
    }
    
    .add-button {
        background: var(--button-background, #f0f0f0);
        border: 1px solid var(--border-color, #e0e0e0);
        border-radius: 6px;
        padding: 0.75rem 1.5rem;
        margin-top: 1rem;
        cursor: pointer;
        font-size: 0.9rem;
        color: var(--text-primary, #000000);
        transition: background 0.2s ease;
    }
    
    .add-button:hover {
        background: var(--button-hover-background, #e0e0e0);
    }
    
    .no-entries {
        padding: 2rem;
        text-align: center;
        color: var(--text-secondary, #666666);
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

