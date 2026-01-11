<!-- frontend/packages/ui/src/components/settings/AppSettingsMemoriesEntryDetail.svelte
     Component for viewing and editing a specific app settings/memories entry.
     
     This component is used for the app_store/{app_id}/settings_memories/{category_id}/entry/{entry_id} nested route.
     
     **Features**:
     - View mode: Shows all entry details with option to edit or delete
     - Edit mode: Same form as create entry but prefilled with existing data
     
     **Zero-Knowledge Architecture**:
     - Entry is decrypted on-demand for display
     - Updates are re-encrypted before storage
-->
<script lang="ts">
    import { untrack } from 'svelte';
    import { appSkillsStore } from '../../stores/appSkillsStore';
    import { authStore } from '../../stores/authStore';
    import type { AppMetadata, MemoryFieldMetadata, SchemaPropertyDefinition } from '../../types/apps';
    import { createEventDispatcher } from 'svelte';
    import { text } from '@repo/ui';
    import { appSettingsMemoriesStore, appSettingsMemoriesForApp } from '../../stores/appSettingsMemoriesStore';
    import type { Readable } from 'svelte/store';

    // Create event dispatcher for navigation
    const dispatch = createEventDispatcher();

    // Check if user is authenticated
    let isAuthenticated = $derived($authStore.isAuthenticated);

    interface Props {
        appId: string;
        categoryId: string;
        entryId: string;
    }

    let { appId, categoryId, entryId }: Props = $props();

    // Get store state reactively (Svelte 5)
    let storeState = $state(appSkillsStore.getState());

    // Get app metadata from store
    let app = $derived<AppMetadata | undefined>(storeState.apps[appId]);
    let category = $derived<MemoryFieldMetadata | undefined>(
        app?.settings_and_memories.find(c => c.id === categoryId)
    );

    // Get entries for this app (grouped by settings_group)
    let appEntries: Readable<Record<string, unknown>> = appSettingsMemoriesForApp(appId);
    let groupedEntries = $appEntries;

    // Find the specific entry from the store
    let entry = $derived.by(() => {
        for (const [, entries] of Object.entries(groupedEntries)) {
            if (Array.isArray(entries)) {
                const found = entries.find((e: { id: string }) => e.id === entryId);
                if (found) return found as {
                    id: string;
                    item_key: string;
                    item_value: Record<string, unknown>;
                    updated_at: number;
                    created_at: number;
                    item_version: number;
                    settings_group: string;
                };
            }
        }
        return undefined;
    });

    /**
     * Get the translated category name.
     */
    let categoryName = $derived(
        category?.name_translation_key
            ? $text(category.name_translation_key)
            : categoryId
    );

    // Get schema from category metadata
    let schema = $derived(category?.schema_definition);
    
    // Filter out auto_generated fields
    let userInputProperties = $derived.by<Record<string, SchemaPropertyDefinition>>(() => {
        if (!schema?.properties) return {};
        const filtered: Record<string, SchemaPropertyDefinition> = {};
        for (const [key, prop] of Object.entries(schema.properties)) {
            if (!prop.auto_generated) {
                filtered[key] = prop;
            }
        }
        return filtered;
    });

    // Mode: 'view' or 'edit'
    let mode = $state<'view' | 'edit'>('view');
    
    // Form state for edit mode
    let formState = $state<Record<string, unknown>>({});
    let isSaving = $state(false);
    let isDeleting = $state(false);
    let saveError = $state('');
    
    // Track if form has been initialized
    let formInitialized = false;
    let lastEntryId: string | null = null;
    
    // Initialize form state when entry changes or mode switches to edit
    $effect(() => {
        const currentEntryId = entry?.id || null;
        
        if (mode === 'edit' && entry && (lastEntryId !== currentEntryId || !formInitialized)) {
            untrack(() => {
                if (Object.keys(userInputProperties).length > 0 && entry.item_value) {
                    const initialState: Record<string, unknown> = {};
                    for (const [key] of Object.entries(userInputProperties)) {
                        // Get value from entry's item_value, excluding internal metadata
                        if (key !== 'settings_group' && key !== '_original_item_key') {
                            initialState[key] = entry.item_value[key] ?? '';
                        }
                    }
                    formState = initialState;
                } else {
                    formState = {
                        itemKey: entry.item_key,
                        itemValue: JSON.stringify(entry.item_value, null, 2),
                        settingsGroup: entry.settings_group
                    };
                }
                formInitialized = true;
                lastEntryId = currentEntryId;
            });
        }
    });

    /**
     * Get icon name from icon_image filename.
     */
    function getIconName(iconImage: string | undefined): string {
        if (!iconImage) return appId;
        let iconName = iconImage.replace(/\.svg$/, '');
        if (iconName === 'coding') {
            iconName = 'code';
        }
        return iconName;
    }
    
    /**
     * Navigate back to category page.
     */
    function goBack() {
        dispatch('openSettings', {
            settingsPath: `app_store/${appId}/settings_memories/${categoryId}`,
            direction: 'back',
            icon: getIconName(app?.icon_image),
            title: category?.name_translation_key ? $text(category.name_translation_key) : categoryId
        });
    }
    
    /**
     * Switch to edit mode.
     */
    function startEdit() {
        formInitialized = false; // Force re-initialization
        mode = 'edit';
    }
    
    /**
     * Cancel edit and return to view mode.
     */
    function cancelEdit() {
        formInitialized = false;
        saveError = '';
        mode = 'view';
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
     * Get display-friendly field label.
     */
    function getFieldLabel(fieldName: string, prop: SchemaPropertyDefinition): string {
        return prop.description || fieldName.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
    }
    
    /**
     * Validate form fields.
     */
    function validateForm(): string | null {
        if (Object.keys(userInputProperties).length === 0) {
            if (!formState.itemKey || String(formState.itemKey).trim() === '') {
                return 'Item key is required';
            }
            return null;
        }
        
        const required = schema?.required || [];
        for (const fieldName of required) {
            if (schema?.properties?.[fieldName]?.auto_generated) {
                continue;
            }
            
            const value = formState[fieldName];
            if (value === undefined || value === null || String(value).trim() === '') {
                const prop = userInputProperties[fieldName];
                const fieldLabel = getFieldLabel(fieldName, prop);
                return `${fieldLabel} is required`;
            }
        }
        
        return null;
    }
    
    /**
     * Save the edited entry.
     */
    async function handleSave() {
        saveError = '';
        
        const validationError = validateForm();
        if (validationError) {
            saveError = validationError;
            return;
        }

        if (!entry) return;

        isSaving = true;
        try {
            let entryValue: Record<string, unknown>;
            let itemKey: string;
            let settingsGroup: string;
            
            if (schema?.properties && Object.keys(userInputProperties).length > 0) {
                // Build entry value from schema-based form
                entryValue = { ...entry.item_value }; // Preserve auto-generated fields
                
                for (const [key, prop] of Object.entries(userInputProperties)) {
                    const value = formState[key];
                    if (value !== undefined && value !== null && String(value).trim() !== '') {
                        if (prop.type === 'integer') {
                            entryValue[key] = parseInt(String(value), 10);
                        } else if (prop.type === 'number') {
                            entryValue[key] = parseFloat(String(value));
                        } else if (prop.type === 'boolean') {
                            entryValue[key] = Boolean(value);
                        } else {
                            entryValue[key] = String(value).trim();
                        }
                    }
                }
                
                // Regenerate item key based on updated values
                const nameField = Object.keys(schema.properties).find(k => 
                    k.toLowerCase() === 'name' || k.toLowerCase() === 'title'
                );
                const urlField = Object.keys(schema.properties).find(k => 
                    k.toLowerCase().includes('url')
                );
                
                if (urlField && formState[urlField]) {
                    itemKey = `${categoryId}.${String(formState[urlField]).trim()}`;
                } else if (nameField && formState[nameField]) {
                    itemKey = `${categoryId}.${String(formState[nameField]).trim()}`;
                } else {
                    itemKey = entry.item_key;
                }
                
                settingsGroup = categoryName;
            } else {
                // Generic form
                try {
                    entryValue = JSON.parse(String(formState.itemValue));
                } catch {
                    entryValue = { value: String(formState.itemValue).trim() };
                }
                itemKey = String(formState.itemKey).trim();
                settingsGroup = String(formState.settingsGroup || entry.settings_group).trim();
            }

            await appSettingsMemoriesStore.updateEntry(entryId, appId, {
                item_key: itemKey,
                item_value: entryValue,
                settings_group: settingsGroup
            });

            mode = 'view';
            formInitialized = false;
        } catch (error) {
            saveError = error instanceof Error ? error.message : 'Failed to save entry';
            console.error('[AppSettingsMemoriesEntryDetail] Error saving entry:', error);
        } finally {
            isSaving = false;
        }
    }
    
    /**
     * Delete the entry with confirmation.
     */
    async function handleDelete() {
        if (!confirm($text('settings.app_settings_memories.confirm_delete.text') || 'Are you sure you want to delete this entry?')) {
            return;
        }

        isDeleting = true;
        try {
            await appSettingsMemoriesStore.deleteEntry(entryId, appId);
            // Navigate back to category page after deletion
            goBack();
        } catch (error) {
            saveError = error instanceof Error ? error.message : 'Failed to delete entry';
            console.error('[AppSettingsMemoriesEntryDetail] Error deleting entry:', error);
        } finally {
            isDeleting = false;
        }
    }
    
    /**
     * Check if a field is required.
     */
    function isFieldRequired(fieldName: string): boolean {
        if (!schema?.required?.includes(fieldName)) return false;
        if (schema?.properties?.[fieldName]?.auto_generated) return false;
        return true;
    }
</script>

<div class="entry-detail">
    {#if !app || !category}
        <div class="error">
            <p>Error: {!app ? 'App not found' : 'Category not found'}</p>
            <button class="back-button" onclick={goBack}>← {$text('settings.app_store.back_to_app.text')}</button>
        </div>
    {:else if !isAuthenticated}
        <div class="error">
            <p>{$text('settings.app_settings_memories.authentication_required.text') || 'Authentication required'}</p>
            <button class="back-button" onclick={goBack}>← {$text('settings.app_store.back_to_app.text')}</button>
        </div>
    {:else if !entry}
        <div class="error">
            <p>{$text('settings.app_settings_memories.entry_not_found.text') || 'Entry not found'}</p>
            <button class="back-button" onclick={goBack}>← {$text('settings.app_settings_memories.back_to_category.text') || 'Back'}</button>
        </div>
    {:else if mode === 'view'}
        <!-- View Mode -->
        <div class="view-container">
            <!-- Entry details -->
            <div class="details-section">
                {#if Object.keys(userInputProperties).length > 0}
                    <!-- Schema-based display -->
                    {#each Object.entries(userInputProperties) as [fieldName, prop]}
                        <div class="detail-row">
                            <span class="detail-label">{getFieldLabel(fieldName, prop)}</span>
                            <span class="detail-value">
                                {#if prop.type === 'boolean'}
                                    {entry.item_value[fieldName] ? 'Yes' : 'No'}
                                {:else}
                                    {formatValue(entry.item_value[fieldName])}
                                {/if}
                            </span>
                        </div>
                    {/each}
                {:else}
                    <!-- Generic display -->
                    <div class="detail-row">
                        <span class="detail-label">Key</span>
                        <span class="detail-value">{entry.item_key}</span>
                    </div>
                    <div class="detail-row">
                        <span class="detail-label">Value</span>
                        <code class="detail-value-code">{formatValue(entry.item_value)}</code>
                    </div>
                {/if}
                
                <!-- Metadata -->
                <div class="metadata-section">
                    <div class="detail-row metadata">
                        <span class="detail-label">Version</span>
                        <span class="detail-value">v{entry.item_version}</span>
                    </div>
                    <div class="detail-row metadata">
                        <span class="detail-label">Last Updated</span>
                        <span class="detail-value">{formatDate(entry.updated_at)}</span>
                    </div>
                    <div class="detail-row metadata">
                        <span class="detail-label">Created</span>
                        <span class="detail-value">{formatDate(entry.created_at)}</span>
                    </div>
                </div>
            </div>
            
            <!-- Action buttons -->
            <div class="action-buttons">
                <button class="edit-btn" onclick={startEdit} disabled={isDeleting}>
                    {$text('settings.app_settings_memories.edit.text') || 'Edit'}
                </button>
                <button class="delete-btn" onclick={handleDelete} disabled={isDeleting}>
                    {isDeleting 
                        ? ($text('settings.app_settings_memories.deleting.text') || 'Deleting...')
                        : ($text('settings.app_settings_memories.delete.text') || 'Delete')
                    }
                </button>
            </div>
        </div>
    {:else}
        <!-- Edit Mode -->
        <div class="edit-container">
            {#if Object.keys(userInputProperties).length > 0}
                <!-- Schema-based form -->
                {#each Object.entries(userInputProperties) as [fieldName, prop]}
                    <div class="form-group">
                        <label for={fieldName}>
                            {getFieldLabel(fieldName, prop)}
                            {#if isFieldRequired(fieldName)}
                                <span class="required">*</span>
                            {/if}
                        </label>
                        {#if prop.type === 'boolean'}
                            <div class="checkbox-group">
                                <input
                                    id={fieldName}
                                    type="checkbox"
                                    checked={Boolean(formState[fieldName])}
                                    onchange={(e) => formState[fieldName] = (e.target as HTMLInputElement).checked}
                                    disabled={isSaving}
                                />
                                <span class="checkbox-label">{getFieldLabel(fieldName, prop)}</span>
                            </div>
                        {:else if prop.type === 'integer' || prop.type === 'number'}
                            <input
                                id={fieldName}
                                type="number"
                                bind:value={formState[fieldName]}
                                placeholder={getFieldLabel(fieldName, prop)}
                                min={prop.minimum}
                                max={prop.maximum}
                                step={prop.type === 'integer' ? 1 : undefined}
                                disabled={isSaving}
                            />
                        {:else if prop.enum}
                            <select
                                id={fieldName}
                                bind:value={formState[fieldName]}
                                disabled={isSaving}
                            >
                                <option value="">Select {getFieldLabel(fieldName, prop)}</option>
                                {#each prop.enum as enumValue}
                                    <option value={enumValue}>{enumValue}</option>
                                {/each}
                            </select>
                        {:else}
                            <input
                                id={fieldName}
                                type="text"
                                bind:value={formState[fieldName]}
                                placeholder={getFieldLabel(fieldName, prop)}
                                disabled={isSaving}
                            />
                        {/if}
                    </div>
                {/each}
            {:else}
                <!-- Generic form -->
                <div class="form-group">
                    <label for="item-key">
                        Key
                        <span class="required">*</span>
                    </label>
                    <input
                        id="item-key"
                        type="text"
                        bind:value={formState.itemKey}
                        disabled={isSaving}
                    />
                </div>

                <div class="form-group">
                    <label for="settings-group">Group</label>
                    <input
                        id="settings-group"
                        type="text"
                        bind:value={formState.settingsGroup}
                        disabled={isSaving}
                    />
                </div>

                <div class="form-group">
                    <label for="item-value">Value</label>
                    <textarea
                        id="item-value"
                        bind:value={formState.itemValue}
                        rows="6"
                        disabled={isSaving}
                    ></textarea>
                </div>
            {/if}

            {#if saveError}
                <div class="error-message">{saveError}</div>
            {/if}

            <div class="form-footer">
                <button class="cancel-btn" onclick={cancelEdit} disabled={isSaving}>
                    {$text('settings.app_settings_memories.cancel.text') || 'Cancel'}
                </button>
                <button
                    class="save-btn"
                    onclick={handleSave}
                    disabled={isSaving}
                >
                    {isSaving 
                        ? ($text('settings.app_settings_memories.saving.text') || 'Saving...')
                        : ($text('settings.app_settings_memories.save.text') || 'Save')
                    }
                </button>
            </div>
        </div>
    {/if}
</div>

<style>
    .entry-detail {
        padding: 14px;
        max-width: 1400px;
        margin: 0 auto;
    }
    
    .view-container,
    .edit-container {
        padding-left: 0;
    }
    
    .details-section {
        margin-bottom: 2rem;
    }
    
    .detail-row {
        display: flex;
        flex-direction: column;
        gap: 0.25rem;
        padding: 1rem 0;
        border-bottom: 1px solid var(--color-grey-20);
    }
    
    .detail-row:first-child {
        padding-top: 0;
    }
    
    .detail-row.metadata {
        flex-direction: row;
        justify-content: space-between;
        align-items: center;
        padding: 0.75rem 0;
    }
    
    .metadata-section {
        margin-top: 1.5rem;
        padding-top: 1rem;
        border-top: 2px solid var(--color-grey-30);
    }
    
    .detail-label {
        font-size: 0.85rem;
        color: var(--color-grey-60);
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    
    .detail-value {
        font-size: 1rem;
        color: var(--text-primary);
        word-break: break-word;
    }
    
    .detail-value-code {
        display: block;
        padding: 0.75rem;
        background: var(--color-grey-10);
        border: 1px solid var(--color-grey-20);
        border-radius: 6px;
        font-family: 'Courier New', monospace;
        font-size: 0.85rem;
        overflow-x: auto;
        white-space: pre-wrap;
        margin-top: 0.5rem;
    }
    
    .action-buttons {
        display: flex;
        gap: 1rem;
        padding-top: 1rem;
    }
    
    .edit-btn,
    .delete-btn,
    .cancel-btn,
    .save-btn {
        padding: 0.75rem 1.5rem;
        border-radius: 6px;
        border: none;
        cursor: pointer;
        font-size: 0.95rem;
        font-weight: 500;
        transition: background-color 0.2s ease;
    }
    
    .edit-btn {
        background: var(--color-primary);
        color: white;
        flex: 1;
    }
    
    .edit-btn:hover:not(:disabled) {
        background: var(--color-primary-dark, #005fa3);
    }
    
    .delete-btn {
        background: var(--color-grey-30);
        color: var(--color-error, #dc3545);
    }
    
    .delete-btn:hover:not(:disabled) {
        background: var(--color-error-light, #f8d7da);
    }
    
    .cancel-btn {
        background: var(--color-grey-30);
        color: var(--text-primary);
    }
    
    .cancel-btn:hover:not(:disabled) {
        background: var(--color-grey-40);
    }
    
    .save-btn {
        background: var(--color-primary);
        color: white;
    }
    
    .save-btn:hover:not(:disabled) {
        background: var(--color-primary-dark, #005fa3);
    }
    
    button:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }
    
    /* Form styles (reused from create entry) */
    .form-group {
        margin-bottom: 1.5rem;
    }
    
    .form-group label {
        display: block;
        margin-bottom: 0.5rem;
        font-weight: 500;
        color: var(--text-primary);
    }
    
    .required {
        color: var(--error-color, #dc3545);
    }
    
    input,
    textarea,
    select {
        width: 100%;
        padding: 0.75rem;
        border: 1px solid var(--color-grey-30);
        border-radius: 6px;
        font-family: inherit;
        font-size: 0.95rem;
        color: var(--text-primary);
        background: var(--color-white);
        transition: border-color 0.2s ease;
        box-sizing: border-box;
    }
    
    .checkbox-group {
        display: flex;
        align-items: center;
        gap: 0.5rem;
    }
    
    .checkbox-group input[type="checkbox"] {
        width: auto;
        margin: 0;
    }
    
    .checkbox-label {
        color: var(--text-primary);
        font-size: 0.95rem;
    }
    
    input:focus,
    textarea:focus,
    select:focus {
        outline: none;
        border-color: var(--color-primary);
        box-shadow: 0 0 0 3px rgba(0, 95, 163, 0.1);
    }
    
    input:disabled,
    textarea:disabled,
    select:disabled {
        background: var(--color-grey-15);
        cursor: not-allowed;
        opacity: 0.6;
    }
    
    .error-message {
        padding: 1rem;
        background: var(--color-error-light, #f8d7da);
        border: 1px solid var(--color-error, #f5c6cb);
        border-radius: 6px;
        color: var(--error-color, #721c24);
        margin-bottom: 1rem;
    }
    
    .form-footer {
        display: flex;
        gap: 1rem;
        justify-content: flex-end;
        margin-top: 2rem;
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
