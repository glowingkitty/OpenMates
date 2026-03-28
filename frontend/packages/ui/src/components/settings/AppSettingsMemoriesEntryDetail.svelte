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
    import Icon from '../Icon.svelte';
    import { SettingsSectionHeading } from './elements';
    import { appSettingsMemoriesStore, appSettingsMemoriesForApp } from '../../stores/appSettingsMemoriesStore';
    import { updateEntryPrefillStore } from '../../stores/updateEntryPrefillStore';
    import { get } from 'svelte/store';
    import type { Readable } from 'svelte/store';
    import {
        MAX_LENGTH_SHORT,
        MAX_LENGTH_GENERIC_VALUE,
        MAX_LENGTH_GENERIC_KEY,
        getMaxLength,
        validateMaxLength
    } from '../../utils/inputValidation';

    // Create event dispatcher for navigation
    const dispatch = createEventDispatcher();

    // Check if user is authenticated
    let isAuthenticated = $derived($authStore.isAuthenticated);

    interface Props {
        appId: string;
        categoryId: string;
        entryId: string;
        readOnly?: boolean;
        startInEditMode?: boolean;
    }

    let { appId, categoryId, entryId, readOnly = false, startInEditMode = false }: Props = $props();

    // Detect example entries: entryId starts with "example_" (e.g. "example_0")
    // Example entries are shown read-only with translated text content from the category metadata.
    let isExample = $derived(entryId.startsWith('example_'));
    let exampleIndex = $derived(isExample ? parseInt(entryId.replace('example_', ''), 10) : -1);

    // Get store state reactively (Svelte 5)
    let storeState = $state(appSkillsStore.getState());

    // Get app metadata from store
    let app = $derived<AppMetadata | undefined>(storeState.apps[appId]);
    let category = $derived<MemoryFieldMetadata | undefined>(
        app?.settings_and_memories.find(c => c.id === categoryId)
    );

    // Get entries for this app (grouped by settings_group)
    let appEntries = $derived<Readable<Record<string, unknown>>>(appSettingsMemoriesForApp(appId));
    let groupedEntries = $derived($appEntries);

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

    // For example entries: resolve translated text from category metadata (legacy title-only)
    let exampleText = $derived.by(() => {
        if (!isExample || exampleIndex < 0) return '';
        const keys = category?.example_translation_keys ?? [];
        const key = keys[exampleIndex];
        return key ? $text(key) : '';
    });
    
    // For full example entries: get the complete example entry object with all fields
    let exampleEntry = $derived.by<Record<string, string | number | boolean> | undefined>(() => {
        if (!isExample || exampleIndex < 0) return undefined;
        const entries = category?.example_entries ?? [];
        return entries[exampleIndex];
    });
    
    /**
     * Resolve an example entry field value for display.
     * If the value looks like a translation key (contains dots), resolve it via $text().
     * Otherwise, display the raw value (enum, number, boolean).
     */
    function resolveExampleValue(value: string | number | boolean): string {
        if (typeof value === 'boolean') return value ? 'Yes' : 'No';
        if (typeof value === 'number') return String(value);
        // String values: check if it looks like a translation key
        if (typeof value === 'string' && value.includes('.') && !value.includes(' ') && !value.startsWith('http')) {
            const resolved = $text(value);
            // If $text() returns the key itself (not found), display the raw value
            return resolved !== value ? resolved : value;
        }
        return String(value);
    }

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
    // startInEditMode prop allows navigating directly to edit mode (e.g., from the list's edit button)
    // Use untrack() to read startInEditMode only once (initial value), not reactively.
    // This is intentional: mode is local state initialized from the prop, but not kept in sync.
    let mode = $state<'view' | 'edit'>(untrack(() => startInEditMode ? 'edit' : 'view'));
    
    // Form state for edit mode
    let formState = $state<Record<string, unknown>>({});
    let isSaving = $state(false);
    let isDeleting = $state(false);
    let saveError = $state('');
    
    // Track if form has been initialized
    let formInitialized = false;
    let lastEntryId: string | null = null;
    
    // Snapshot of form state at edit start, to detect if user made changes
    let initialFormSnapshot = '';
    
    // Detect whether the user has made changes compared to the initial state
    let hasFormChanges = $derived(JSON.stringify(formState) !== initialFormSnapshot);
    
    // Old values for diff display when the AI suggests updates via deep link.
    // Maps field name -> original value (before prefill was applied).
    // Only populated when the user arrives via an AI update deep link with prefill data.
    let oldValuesForDiff = $state<Record<string, unknown>>({});
    let hasPrefillDiff = $derived(Object.keys(oldValuesForDiff).length > 0);
    
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
                    initialFormSnapshot = JSON.stringify(initialState);
                } else {
                    const genericState = {
                        itemKey: entry.item_key,
                        itemValue: JSON.stringify(entry.item_value, null, 2),
                        settingsGroup: entry.settings_group
                    };
                    formState = genericState;
                    initialFormSnapshot = JSON.stringify(genericState);
                }
                // Apply prefill from AI-generated update deep link (if present)
                const prefill = get(updateEntryPrefillStore);
                if (prefill && prefill.entryId === currentEntryId && Object.keys(prefill.prefillFields).length > 0) {
                    const diffOldValues: Record<string, unknown> = {};
                    for (const [fieldName, newValue] of Object.entries(prefill.prefillFields)) {
                        if (fieldName in formState) {
                            // Record old value for diff display
                            diffOldValues[fieldName] = formState[fieldName];
                            // Apply prefilled new value
                            formState[fieldName] = newValue;
                        }
                    }
                    oldValuesForDiff = diffOldValues;
                    // initialFormSnapshot was already set above from entry.item_value,
                    // so hasFormChanges will correctly detect the prefilled fields as changes
                    updateEntryPrefillStore.set(null);
                    console.info('[AppSettingsMemoriesEntryDetail] Applied prefill from AI deep link:', Object.keys(prefill.prefillFields));
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
        // Handle special case: heart.svg -> health (since the app ID is "health" but icon file is heart.svg)
        if (iconName === 'heart') {
            iconName = 'health';
        }
        return iconName;
    }
    
    /**
     * Get the icon name for this category to use in field icon divs.
     * Uses the category's own icon_image (e.g. "travel.svg" -> "travel").
     * Falls back to categoryId, then to appId.
     */
    function getCategoryIconName(categoryIconImage: string | undefined): string {
        if (!categoryIconImage) return categoryId || appId;
        return categoryIconImage.replace(/\.svg$/, '');
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
        oldValuesForDiff = {}; // Clear any previous diff state
        mode = 'edit';
    }
    
    /**
     * Cancel edit and return to view mode.
     */
    function cancelEdit() {
        formInitialized = false;
        saveError = '';
        oldValuesForDiff = {}; // Clear diff state
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
     * Get display-friendly field label (title).
     * Returns the field name formatted as a human-readable title (e.g., "start_date" → "Start date").
     * The prop.description is used as placeholder text, NOT as the label title.
     */
    function getFieldLabel(fieldName: string): string {
        // Format the field key as a human-readable title:
        // "start_date" → "Start date", "destination" → "Destination"
        const words = fieldName.split('_');
        return words[0].charAt(0).toUpperCase() + words[0].slice(1).toLowerCase() +
            (words.length > 1 ? ' ' + words.slice(1).join(' ').toLowerCase() : '');
    }
    
    /**
     * Build an auto-generated title from other entry fields (e.g. for health appointments).
     * Used when schema has title with auto_generated: true.
     */
    function buildAutoTitleFromEntry(
        entryValue: Record<string, unknown>,
        schema: MemoryFieldMetadata['schema_definition']
    ): string {
        if (!schema?.properties) return 'Untitled';
        const parts: string[] = [];
        for (const [key, prop] of Object.entries(schema.properties)) {
            if (key === 'title' || prop.auto_generated) continue;
            const v = entryValue[key];
            if (v === undefined || v === null) continue;
            const s = String(v).trim();
            if (s === '') continue;
            parts.push(s.includes('_') && !s.includes(' ') ? s.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()) : s);
        }
        return parts.length > 0 ? parts.join(' - ') : 'Untitled';
    }
    
    /**
     * Validate form fields.
     * Checks required fields, numeric ranges, and string length limits.
     */
    function validateForm(): string | null {
        if (Object.keys(userInputProperties).length === 0) {
            const keyVal = String(formState.itemKey ?? '');
            if (!keyVal.trim()) {
                return 'Item key is required';
            }
            const keyLengthError = validateMaxLength(keyVal, MAX_LENGTH_GENERIC_KEY, 'Key');
            if (keyLengthError) return keyLengthError;

            const valueVal = String(formState.itemValue ?? '');
            const valueLengthError = validateMaxLength(valueVal, MAX_LENGTH_GENERIC_VALUE, 'Value');
            if (valueLengthError) return valueLengthError;

            return null;
        }
        
        const required = schema?.required || [];
        for (const fieldName of required) {
            if (schema?.properties?.[fieldName]?.auto_generated) {
                continue;
            }
            
            const value = formState[fieldName];
            if (value === undefined || value === null || String(value).trim() === '') {
                const fieldLabel = getFieldLabel(fieldName);
                return `${fieldLabel} is required`;
            }
        }

        // Type and length validation for user-input fields only
        for (const [fieldName, prop] of Object.entries(userInputProperties)) {
            const value = formState[fieldName];
            if (value === undefined || value === null || String(value).trim() === '') {
                continue; // Skip empty optional fields
            }

            if (prop.type === 'integer' || prop.type === 'number') {
                const numValue = Number(value);
                if (isNaN(numValue)) {
                    return `${getFieldLabel(fieldName)} must be a number`;
                }
                if (prop.minimum !== undefined && numValue < prop.minimum) {
                    return `${getFieldLabel(fieldName)} must be at least ${prop.minimum}`;
                }
                if (prop.maximum !== undefined && numValue > prop.maximum) {
                    return `${getFieldLabel(fieldName)} must be at most ${prop.maximum}`;
                }
            } else if (prop.type === 'string' || prop.type === undefined) {
                if (!prop.enum) {
                    const strVal = String(value);
                    const maxLen = getMaxLength(prop);
                    const lengthError = validateMaxLength(strVal, maxLen, getFieldLabel(fieldName));
                    if (lengthError) return lengthError;
                }
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
                
                // Re-generate auto_generated title when type/where/date etc. change
                for (const [key, prop] of Object.entries(schema.properties)) {
                    if (key === 'title' && prop.auto_generated) {
                        entryValue[key] = buildAutoTitleFromEntry(entryValue, schema);
                        break;
                    }
                }
                
                // Regenerate item key based on updated values
                const nameField = Object.keys(schema.properties).find(k => 
                    k.toLowerCase() === 'name' || k.toLowerCase() === 'title'
                );
                const titleIsAutoGenerated = nameField && schema.properties?.[nameField]?.auto_generated;
                const urlField = Object.keys(schema.properties).find(k => 
                    k.toLowerCase().includes('url')
                );
                
                if (urlField && formState[urlField]) {
                    itemKey = `${categoryId}.${String(formState[urlField]).trim()}`;
                } else if (nameField && (titleIsAutoGenerated ? entryValue[nameField] : formState[nameField])) {
                    const titleVal = titleIsAutoGenerated ? String(entryValue[nameField] || '').trim() : String(formState[nameField]).trim();
                    itemKey = `${categoryId}.${titleVal || entry.item_key}`;
                } else {
                    itemKey = entry.item_key;
                }
                
                // CRITICAL: Use categoryId (not categoryName) as settings_group
                // The filtering in AppSettingsMemoriesCategory.svelte uses categoryId to filter entries
                settingsGroup = categoryId;
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
        if (!confirm($text('settings.app_settings_memories.confirm_delete'))) {
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
            <button class="back-button" onclick={goBack}>← {$text('settings.app_store.back_to_app')}</button>
        </div>
    {:else if isExample}
        <!-- Example Entry View — read-only, shows all fields when example_entries data is available -->
        <div class="view-container">
            <div class="details-section">
                {#if exampleEntry && Object.keys(userInputProperties).length > 0}
                    <!-- Full example entry: render each schema field with its example value -->
                    {#each Object.keys(userInputProperties) as fieldName}
                        {#if exampleEntry[fieldName] !== undefined}
                            <div class="detail-row">
                                <SettingsSectionHeading title={getFieldLabel(fieldName)} icon={getCategoryIconName(category?.icon_image)} />
                                <span class="detail-value">
                                    {resolveExampleValue(exampleEntry[fieldName])}
                                </span>
                            </div>
                        {/if}
                    {/each}
                {:else}
                    <!-- Fallback: legacy title-only example text -->
                    <div class="detail-row">
                        <span class="detail-value example-text">{exampleText}</span>
                    </div>
                {/if}
            </div>
            <!-- No action buttons for examples -->
            <!-- Encrypted notice: entry data is zero-knowledge encrypted on-device -->
            <div class="encrypted-notice">
                <Icon name="lock" size="14px" />
                <span>{$text('settings.app_settings_memories.encrypted_notice')}</span>
            </div>
        </div>
    {:else if !isAuthenticated}
        <div class="error">
            <p>{$text('settings.app_settings_memories.authentication_required')}</p>
            <button class="back-button" onclick={goBack}>← {$text('settings.app_store.back_to_app')}</button>
        </div>
    {:else if !entry}
        <div class="error">
            <p>{$text('settings.app_settings_memories.entry_not_found')}</p>
            <button class="back-button" onclick={goBack}>← {$text('settings.app_settings_memories.back_to_category')}</button>
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
                            <SettingsSectionHeading title={getFieldLabel(fieldName)} icon={getCategoryIconName(category?.icon_image)} />
                            <span class="detail-value" class:not-set={entry.item_value[fieldName] === null || entry.item_value[fieldName] === undefined || entry.item_value[fieldName] === ''}>
                                {#if prop.type === 'boolean'}
                                    {entry.item_value[fieldName] ? 'Yes' : 'No'}
                                {:else if entry.item_value[fieldName] === null || entry.item_value[fieldName] === undefined || entry.item_value[fieldName] === ''}
                                    Not set
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
                
                <!-- Metadata — small, subtle timestamps -->
                <div class="metadata-section">
                    <span class="metadata-text">Last updated: {formatDate(entry.updated_at)}</span>
                    <span class="metadata-text">Created: {formatDate(entry.created_at)}</span>
                </div>
            </div>
            
            <!-- Action buttons — only for own (non-read-only) entries -->
            {#if !readOnly}
                <div class="action-buttons">
                    <button onclick={startEdit} disabled={isDeleting}>
                        {$text('settings.app_settings_memories.edit')}
                    </button>
                    <button class="delete-icon-btn" onclick={handleDelete} disabled={isDeleting} aria-label="Delete">
                        <div class="clickable-icon icon_delete"></div>
                    </button>
                </div>
            {/if}
            <!-- Encrypted notice: entry data is zero-knowledge encrypted on-device -->
            <div class="encrypted-notice">
                <Icon name="lock" size="14px" />
                <span>{$text('settings.app_settings_memories.encrypted_notice')}</span>
            </div>
        </div>
    {:else}
        <!-- Edit Mode -->
        <div class="edit-container">
            {#if Object.keys(userInputProperties).length > 0}
                <!-- Schema-based form -->
                {#each Object.entries(userInputProperties) as [fieldName, prop]}
                    <div class="form-group">
                        <SettingsSectionHeading title={getFieldLabel(fieldName)} icon={getCategoryIconName(category?.icon_image)} />
                        {#if prop.type === 'boolean'}
                            <div class="checkbox-group">
                                <input
                                    id={fieldName}
                                    type="checkbox"
                                    checked={Boolean(formState[fieldName])}
                                    onchange={(e) => formState[fieldName] = (e.target as HTMLInputElement).checked}
                                    disabled={isSaving}
                                />
                                <span class="checkbox-label">{getFieldLabel(fieldName)}</span>
                            </div>
                        {:else if prop.type === 'integer' || prop.type === 'number'}
                            <input
                                id={fieldName}
                                type="number"
                                bind:value={formState[fieldName]}
                                placeholder={prop.description || getFieldLabel(fieldName)}
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
                                <option value="">Select {getFieldLabel(fieldName)}</option>
                                {#each prop.enum as enumValue}
                                    <option value={enumValue}>{enumValue}</option>
                                {/each}
                            </select>
                        {:else if prop.multiline}
                            <textarea
                                id={fieldName}
                                bind:value={formState[fieldName]}
                                placeholder={prop.description || getFieldLabel(fieldName)}
                                rows="4"
                                maxlength={getMaxLength(prop)}
                                disabled={isSaving}
                            ></textarea>
                        {:else}
                            <input
                                id={fieldName}
                                type="text"
                                bind:value={formState[fieldName]}
                                placeholder={prop.description || getFieldLabel(fieldName)}
                                maxlength={getMaxLength(prop)}
                                disabled={isSaving}
                            />
                        {/if}
                        <!-- Diff hint: show old value when AI prefilled this field -->
                        {#if hasPrefillDiff && fieldName in oldValuesForDiff}
                            <div class="diff-hint">
                                <span class="diff-label">{$text("settings.app_settings_memories.diff_previous_value")}</span>
                                <span class="diff-old-value">
                                    {#if oldValuesForDiff[fieldName] === '' || oldValuesForDiff[fieldName] === null || oldValuesForDiff[fieldName] === undefined}
                                        <em class="not-set">{$text("settings.app_settings_memories.diff_not_set")}</em>
                                    {:else}
                                        {String(oldValuesForDiff[fieldName])}
                                    {/if}
                                </span>
                            </div>
                        {/if}
                    </div>
                {/each}
            {:else}
                <!-- Generic form -->
                <div class="form-group">
                    <SettingsSectionHeading title="Key" icon={getCategoryIconName(category?.icon_image)} />
                    <input
                        id="item-key"
                        type="text"
                        bind:value={formState.itemKey}
                        maxlength={MAX_LENGTH_GENERIC_KEY}
                        disabled={isSaving}
                    />
                </div>

                <div class="form-group">
                    <SettingsSectionHeading title="Group" icon={getCategoryIconName(category?.icon_image)} />
                    <input
                        id="settings-group"
                        type="text"
                        bind:value={formState.settingsGroup}
                        maxlength={MAX_LENGTH_SHORT}
                        disabled={isSaving}
                    />
                </div>

                <div class="form-group">
                    <SettingsSectionHeading title="Value" icon={getCategoryIconName(category?.icon_image)} />
                    <textarea
                        id="item-value"
                        bind:value={formState.itemValue}
                        rows="6"
                        maxlength={MAX_LENGTH_GENERIC_VALUE}
                        disabled={isSaving}
                    ></textarea>
                </div>
            {/if}

            {#if saveError}
                <div class="error-message">{saveError}</div>
            {/if}

            <div class="form-footer">
                {#if hasFormChanges}
                    <button
                        onclick={handleSave}
                        disabled={isSaving}
                    >
                        {isSaving 
                            ? $text('settings.app_settings_memories.saving')
                            : $text('common.save')
                        }
                    </button>
                {/if}
                <button class="cancel-link" onclick={cancelEdit} disabled={isSaving} type="button">
                    {$text('common.cancel')}
                </button>
            </div>
            <!-- Encrypted notice: entry data is zero-knowledge encrypted on-device -->
            <div class="encrypted-notice">
                <Icon name="lock" size="14px" />
                <span>{$text('settings.app_settings_memories.encrypted_notice')}</span>
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
    }
    
    .detail-row:first-child {
        padding-top: 0;
    }
    
    /* Metadata section — small, subtle date info */
    .metadata-section {
        display: flex;
        flex-direction: column;
        gap: 0.25rem;
        margin-top: 1.5rem;
        padding-top: 0.75rem;
    }
    
    .metadata-text {
        font-size: 0.75rem;
        color: var(--color-grey-30);
    }
    
    /* Field label — regular white text, like a menu title */
    .detail-label {
        font-size: 1rem;
        color: var(--text-primary);
        font-weight: 400;
    }
    
    .detail-value {
        font-size: 1rem;
        color: var(--text-primary);
        word-break: break-word;
    }
    
    /* "Not set" placeholder for null/empty values */
    .detail-value.not-set {
        color: var(--color-grey-30);
        font-style: italic;
    }

    .example-text {
        font-size: 1rem;
        color: var(--text-primary);
        line-height: 1.5;
        white-space: pre-wrap;
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
    
    /* Action buttons — Edit (standard <button>) + Delete (icon-only) */
    .action-buttons {
        display: flex;
        gap: 1rem;
        align-items: center;
        padding-top: 1rem;
    }
    
    /* Delete icon button — matches ChatContextMenu delete style */
    .delete-icon-btn {
        all: unset;
        display: flex;
        align-items: center;
        justify-content: center;
        width: 41px;
        height: 41px;
        cursor: pointer;
        border-radius: 20px;
        transition: opacity 0.15s ease-in-out;
    }
    
    .delete-icon-btn .clickable-icon {
        background: #E80000;
        width: 20px;
        height: 20px;
    }
    
    .delete-icon-btn:hover:not(:disabled) {
        opacity: 0.8;
    }
    
    .delete-icon-btn:disabled {
        opacity: 0.4;
        cursor: not-allowed;
    }
    
    /* Form styles (reused from create entry) */
    .form-group {
        margin-bottom: 1.5rem;
    }
    
    
    .form-group label {
        display: block;
        font-weight: 500;
        color: var(--text-primary);
    }
    
    .required {
        color: var(--error-color, #dc3545);
    }
    
    /* Shared input/textarea/select styles — consistent rounded design */
    input,
    textarea,
    select {
        width: 100%;
        padding: 0.75rem;
        border: 1px solid var(--color-grey-30);
        border-radius: 20px;
        font-family: inherit;
        font-size: 0.95rem;
        color: var(--text-primary);
        background: var(--color-grey-10);
        transition: border-color 0.2s ease;
        box-sizing: border-box;
    }
    
    /* Textarea keeps same style as input but with multiline-appropriate rounding */
    textarea {
        border-radius: 16px;
        resize: vertical;
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
    
    /* Form footer — Save button + Cancel text link below */
    .form-footer {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 0.75rem;
        margin-top: 2rem;
    }
    
    /* Cancel as clickable text link, not a button */
    .cancel-link {
        all: unset;
        cursor: pointer;
        color: var(--color-grey-30);
        font-size: 0.9rem;
        text-decoration: underline;
        transition: color 0.15s ease;
    }
    
    .cancel-link:hover:not(:disabled) {
        color: var(--text-primary);
    }
    
    .cancel-link:disabled {
        opacity: 0.5;
        cursor: not-allowed;
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

    /* Encrypted notice footer — lock icon + small privacy text */
    .encrypted-notice {
        display: flex;
        align-items: flex-start;
        gap: 6px;
        margin-top: 2rem;
        padding-top: 1rem;
        color: var(--color-grey-40);
        font-size: 0.75rem;
        line-height: 1.4;
    }

    .encrypted-notice :global(.icon) {
        flex-shrink: 0;
        margin-top: 1px;
        opacity: 0.7;
    }
    /* Diff hint styles — shown when AI suggests updates via deep link */
    .diff-hint {
        display: flex;
        align-items: baseline;
        gap: 6px;
        margin-top: 4px;
        padding: 4px 8px;
        border-radius: 4px;
        background-color: var(--color-surface-hover, rgba(0, 0, 0, 0.04));
        font-size: 0.8rem;
        color: var(--color-text-secondary, #666);
    }
    
    .diff-label {
        font-weight: 500;
        white-space: nowrap;
        color: var(--color-text-tertiary, #888);
    }
    
    .diff-old-value {
        word-break: break-word;
    }
    
    .diff-old-value .not-set {
        font-style: italic;
        opacity: 0.6;
    }
</style>
