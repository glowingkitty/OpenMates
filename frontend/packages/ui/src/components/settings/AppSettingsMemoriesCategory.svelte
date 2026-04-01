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
     
     **Display Features**:
     - Uses is_title and is_subtitle schema properties to show entry title/subtitle
     - Entries displayed as clickable menu items (SettingsItem components)
     - Clicking an entry navigates to its detail view for viewing/editing
-->

<script lang="ts">
    import { onMount, onDestroy } from 'svelte';
    import { appSkillsStore } from '../../stores/appSkillsStore';
    import { authStore } from '../../stores/authStore';
    import SettingsItem from '../SettingsItem.svelte';
    import { SettingsSectionHeading } from './elements';
    import type { AppMetadata, MemoryFieldMetadata } from '../../types/apps';
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import { appSettingsMemoriesStore, appSettingsMemoriesForApp } from '../../stores/appSettingsMemoriesStore';
    import { setAppStoreNavList, clearAppStoreNav } from '../../stores/appStoreNavigationStore';

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
    // CRITICAL: Use $derived to maintain reactivity with the store
    // Without $derived, the store value is only read once at initialization
    // and won't update when loadEntriesForApp completes
    let appEntries = $derived(appSettingsMemoriesForApp(appId));
    let groupedEntries = $derived($appEntries);

    /**
     * Get example translation keys from category metadata (defined in app.yml).
     * These are resolved via $text() and shown to non-authenticated users to illustrate what this category stores.
     */
    let exampleTranslationKeys = $derived(category?.example_translation_keys ?? []);

    // Get schema from category for title/subtitle field detection
    let schema = $derived(category?.schema_definition);
    
    /**
     * Find the field name marked as is_title in the schema.
     * Falls back to 'name' or 'title' if no explicit is_title is set.
     */
    let titleFieldName = $derived.by<string | null>(() => {
        if (!schema?.properties) return null;
        
        // First, look for explicit is_title
        for (const [fieldName, prop] of Object.entries(schema.properties)) {
            if (prop.is_title) return fieldName;
        }
        
        // Fallback: look for common title field names
        const commonTitleFields = ['name', 'title', 'label'];
        for (const field of commonTitleFields) {
            if (schema.properties[field]) return field;
        }
        
        return null;
    });
    
    /**
     * Find the field name marked as is_subtitle in the schema.
     * Falls back to 'proficiency', 'description', 'status' if no explicit is_subtitle is set.
     */
    let subtitleFieldName = $derived.by<string | null>(() => {
        if (!schema?.properties) return null;
        
        // First, look for explicit is_subtitle
        for (const [fieldName, prop] of Object.entries(schema.properties)) {
            if (prop.is_subtitle) return fieldName;
        }
        
        // Fallback: look for common subtitle field names
        const commonSubtitleFields = ['proficiency', 'description', 'status', 'type'];
        for (const field of commonSubtitleFields) {
            if (schema.properties[field]) return field;
        }
        
        return null;
    });

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
     * Get app icon name from icon_image filename.
     * Maps icon_image like "ai.svg" to icon name "ai" for the Icon component.
     */
    function getIconName(iconImage: string | undefined): string {
        if (!iconImage) return appId;
        let iconName = iconImage.replace(/\.svg$/, '');
        if (iconName === 'coding') iconName = 'code';
        if (iconName === 'heart') iconName = 'health';
        return iconName;
    }

    /**
     * Get the icon name for this category to display with the pink memory gradient.
     * Uses the category's own icon_image (e.g. "calendar.svg" -> "calendar") so each
     * category has a distinct icon instead of always showing the parent app icon.
     * Falls back to the category ID, then to the app ID.
     */
    function getCategoryIconName(categoryIconImage: string | undefined): string {
        if (!categoryIconImage) return category?.id ?? appId;
        return categoryIconImage.replace(/\.svg$/, '');
    }
    
    /**
     * Register sibling settings/memories categories for prev/next navigation in AppDetailsHeader.
     * Re-runs whenever app or categoryId changes (deep link changes the current category).
     * Clears the navigation state when this component is destroyed.
     */
    $effect(() => {
        const categories = app?.settings_and_memories ?? [];
        if (categories.length > 1) {
            setAppStoreNavList(
                categories.map(c => ({
                    id: c.id,
                    name: c.name_translation_key ? $text(c.name_translation_key) : c.id,
                })),
                categoryId,
                (targetCategoryId) => {
                    dispatch('openSettings', {
                        settingsPath: `app_store/${appId}/settings_memories/${targetCategoryId}`,
                        direction: 'forward',
                        icon: getIconName(app?.icon_image),
                        title: app?.name_translation_key ? $text(app.name_translation_key) : appId,
                    });
                },
            );
        } else {
            // Single category — no siblings to navigate to
            clearAppStoreNav();
        }
    });

    onDestroy(() => {
        clearAppStoreNav();
    });

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
            title: $text('common.add_entry')
        });
    }
    
    /**
     * Navigate to entry detail view (view mode).
     */
    function handleEntryClick(entryId: string, entryTitle: string) {
        dispatch('openSettings', {
            settingsPath: `app_store/${appId}/settings_memories/${categoryId}/entry/${entryId}`,
            direction: 'forward',
            icon: getIconName(app?.icon_image),
            title: entryTitle
        });
    }

    /**
     * Navigate directly to entry edit mode.
     * Used by the modify button so clicking edit goes straight to editing, not view mode.
     */
    function handleEntryEditClick(entryId: string, entryTitle: string) {
        dispatch('openSettings', {
            settingsPath: `app_store/${appId}/settings_memories/${categoryId}/entry/${entryId}/edit`,
            direction: 'forward',
            icon: getIconName(app?.icon_image),
            title: entryTitle
        });
    }

    /**
     * Navigate to a read-only example entry view.
     * Examples use the special entryId prefix "example_" so the detail component
     * knows to render in read-only mode without Modify/Delete buttons.
     */
    function handleExampleClick(index: number, exampleKey: string) {
        const title = $text(exampleKey);
        dispatch('openSettings', {
            settingsPath: `app_store/${appId}/settings_memories/${categoryId}/entry/example_${index}`,
            direction: 'forward',
            icon: getIconName(app?.icon_image),
            title
        });
    }
    
    /**
     * Get the title to display for an entry based on schema is_title field.
     */
    function getEntryTitle(itemValue: Record<string, unknown>): string {
        if (titleFieldName && itemValue[titleFieldName] !== undefined) {
            return String(itemValue[titleFieldName]);
        }
        // Fallback: use _original_item_key or first string value
        if (itemValue._original_item_key) {
            const key = String(itemValue._original_item_key);
            // Remove category prefix if present (e.g., "preferred_tech.Python" -> "Python")
            const parts = key.split('.');
            return parts.length > 1 ? parts.slice(1).join('.') : key;
        }
        // Last resort: use first non-internal string value
        for (const [key, value] of Object.entries(itemValue)) {
            if (!key.startsWith('_') && key !== 'settings_group' && typeof value === 'string') {
                return value;
            }
        }
        return 'Entry';
    }
    
    /**
     * Get the subtitle to display for an entry based on schema is_subtitle field.
     */
    function getEntrySubtitle(itemValue: Record<string, unknown>, updatedAt: number): string {
        const parts: string[] = [];
        
        // Add subtitle field value if available
        if (subtitleFieldName && itemValue[subtitleFieldName] !== undefined) {
            const value = itemValue[subtitleFieldName];
            if (typeof value === 'boolean') {
                parts.push(value ? 'Yes' : 'No');
            } else {
                parts.push(String(value));
            }
        }
        
        // Add relative time
        parts.push(formatRelativeTime(updatedAt));
        
        return parts.join(' • ');
    }
    
    /**
     * Format timestamp as relative time (e.g., "2 days ago", "Just now").
     */
    function formatRelativeTime(timestamp: number): string {
        const now = Math.floor(Date.now() / 1000);
        const diff = now - timestamp;
        
        if (diff < 60) return $text('common.just_now');
        if (diff < 3600) {
            const mins = Math.floor(diff / 60);
            return `${mins}m ago`;
        }
        if (diff < 86400) {
            const hours = Math.floor(diff / 3600);
            return `${hours}h ago`;
        }
        if (diff < 604800) {
            const days = Math.floor(diff / 86400);
            return `${days}d ago`;
        }
        
        // For older entries, show the actual date
        const date = new Date(timestamp * 1000);
        return date.toLocaleDateString(undefined, {
            month: 'short',
            day: 'numeric',
            year: date.getFullYear() !== new Date().getFullYear() ? 'numeric' : undefined
        });
    }
    
    /**
     * Get entries filtered to only the current category.
     * The categoryId corresponds to the settings_group field in entries.
     * Only entries matching the current category are displayed.
     */
    let allEntries = $derived.by(() => {
        const entries: Array<{ 
            id: string; 
            item_key: string; 
            item_value: Record<string, unknown>; 
            updated_at: number; 
            item_version: number; 
            settings_group: string 
        }> = [];
        
        // Only get entries for the specific categoryId (settings_group)
        // This ensures the page only shows entries for the selected category
        const categoryEntries = groupedEntries[categoryId];
        if (Array.isArray(categoryEntries)) {
            for (const entry of categoryEntries) {
                entries.push({
                    id: entry.id as string,
                    item_key: entry.item_key as string,
                    item_value: entry.item_value as Record<string, unknown>,
                    updated_at: entry.updated_at as number,
                    item_version: entry.item_version as number,
                    settings_group: categoryId
                });
            }
        }
        
        // Sort by updated_at descending (newest first)
        return entries.sort((a, b) => b.updated_at - a.updated_at);
    });

</script>

<div class="app-settings-memories-category">
    {#if !app || !category}
        <div class="error">
            <p>{$text('settings.app_store.category_not_found')}</p>
            <button class="back-button" onclick={goBack}>← {$text('settings.app_store.back_to_app')}</button>
        </div>
    {:else}
        {#if isAuthenticated}
            <!-- "My / Settings & memories" section heading — 2-line style matching skill/provider headings -->
            <SettingsSectionHeading
                title={$text('settings.app_settings_memories.settings_and_memories')}
                icon="user"
            />

            <!-- List of owned entries -->
            {#if isInitialLoad}
                <div class="loading">
                    <p>{$text('settings.app_settings_memories.loading')}</p>
                </div>
            {:else if allEntries.length === 0}
                <div class="empty">
                    <p>{$text('settings.app_settings_memories.no_entries_yet')}</p>
                </div>
            {:else}
                <div class="entries-list">
                    {#each allEntries as entry (entry.id)}
                        {@const entryTitle = getEntryTitle(entry.item_value)}
                        {@const entrySubtitle = getEntrySubtitle(entry.item_value, entry.updated_at)}
                        <SettingsItem
                            type="submenu"
                            icon={getCategoryIconName(category?.icon_image)}
                            iconColor="var(--icon-memory-background)"
                            title={entryTitle}
                            subtitleBottom={entrySubtitle}
                            hasModifyButton={true}
                            onClick={() => handleEntryClick(entry.id, entryTitle)}
                            onModifyClick={() => handleEntryEditClick(entry.id, entryTitle)}
                        />
                    {/each}
                </div>
            {/if}

            <!-- Add entry link -->
            <div class="add-entry-section">
                <SettingsItem
                    type="submenu"
                    icon="create"
                    title={$text('common.add_entry')}
                    onClick={handleAddEntry}
                />
            </div>
        {/if}

        <!-- Examples section — only shown when user has no saved entries yet (or is not authenticated).
             This avoids cluttering the list when user already has their own entries. -->
        {#if exampleTranslationKeys.length > 0 && (!isAuthenticated || allEntries.length === 0)}
            <div class="examples-section">
                <!-- "Examples" section heading — uses task/checklist icon, matching skill heading style -->
                <SettingsSectionHeading
                    title={$text('settings.app_settings_memories.examples')}
                    icon="task"
                />
                <div class="examples-list">
                    {#each exampleTranslationKeys as exampleKey, index}
                        <SettingsItem
                            type="submenu"
                            icon={getCategoryIconName(category?.icon_image)}
                            iconColor="var(--icon-memory-background)"
                            title={$text(exampleKey)}
                            onClick={() => handleExampleClick(index, exampleKey)}
                        />
                    {/each}
                </div>
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

    .add-entry-section {
        margin-top: 0.25rem;
    }

    .loading {
        padding: 1rem 0.5rem;
        color: var(--text-secondary, #666666);
        font-size: 0.9rem;
    }

    .empty {
        padding: 0.75rem 0.5rem;
        color: var(--text-secondary, #666666);
        font-size: 0.9rem;
    }

    .entries-list {
        display: flex;
        flex-direction: column;
        gap: 0;
    }

    .examples-section {
        margin-top: 1rem;
    }

    .examples-list {
        display: flex;
        flex-direction: column;
        gap: 0;
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
</style>

